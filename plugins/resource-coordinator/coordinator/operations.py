"""Durable operation journal. Recovery observes existing work; NEVER relaunches.

The request remains the single resource owner. A separate, hashed monitor claim
allows a verified-dead monitor to be replaced, not an expired-but-alive one.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

from .processes import identity
from .store import CoordinationError
from .windows_job import Job, Process, scope


def fingerprint(argv, cwd):
    return hashlib.sha256(json.dumps([argv, cwd], ensure_ascii=True).encode()).hexdigest()


class Operations:
    def __init__(self, store):
        self.store = store

    def record(self, request_id, owner):
        with self.store.connection() as db:
            self.store._owned(self.store._row(db, request_id), owner)
            row = db.execute("SELECT * FROM managed_operations WHERE request_id=?", (request_id,)).fetchone()
            return dict(row) if row else None

    def prepare(self, request_id, owner, lease_token, digest, monitor):
        location = scope()  # fail before creating any child
        from .reboot import machine_fingerprint
        machine_hash = machine_fingerprint()
        token, opid = secrets.token_urlsafe(32), str(uuid.uuid4())
        with self.store.connection(write=True) as db:
            row = self.store._active(db, request_id, owner, lease_token)
            if row["state"] != "running":
                raise CoordinationError("Start the reserved operation first")
            if db.execute("SELECT 1 FROM managed_operations WHERE request_id=?", (request_id,)).fetchone():
                raise CoordinationError("Operation already journaled; never launch twice")
            now = self.store.clock()
            db.execute("INSERT INTO managed_operations(request_id,operation_id,command_hash,job_name,scope,monitor,monitor_hash,phase,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (request_id, opid, digest, "Local\\CodexCoord-v05-"+opid, json.dumps(location),
                        json.dumps(monitor), hashlib.sha256(token.encode()).hexdigest(), "launching", now, now))
            db.execute("INSERT INTO managed_operation_hosts(request_id,machine_hash) VALUES(?,?)", (request_id, machine_hash))
            # Also protects against older cooperative clients completing while
            # this monitor is alive. Old clients MUST NOT reconcile v0.5 jobs.
            db.execute("UPDATE requests SET processes=? WHERE id=?", (json.dumps([monitor]), request_id))
            self.store._event(db, request_id, "managed_operation_prepared")
        return token, self.record(request_id, owner)

    def _claimed(self, db, request_id, owner, token):
        request = self.store._row(db, request_id)
        self.store._owned(request, owner)
        row = db.execute("SELECT * FROM managed_operations WHERE request_id=?", (request_id,)).fetchone()
        if row is None or not hmac.compare_digest(row["monitor_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise CoordinationError("Invalid/stale operation monitor claim")
        if row["phase"] == "finished" or request["state"] not in ("leased", "running", "suspect"):
            raise CoordinationError("Operation no longer active")
        return row, request

    def checkpoint(self, request_id, owner, token, *, root=None, root_exit=None, active=None, phase="monitoring", error=None, lease_seconds=120):
        self.store._ttl(lease_seconds)
        with self.store.connection(write=True) as db:
            row, _ = self._claimed(db, request_id, owner, token)
            db.execute("UPDATE managed_operations SET root=COALESCE(?,root),root_exit=COALESCE(?,root_exit),active_processes=?,phase=?,error=?,updated=? WHERE request_id=?",
                       (json.dumps(root) if root else None, root_exit, active, phase, error, self.store.clock(), request_id))
            # Monitor authority, not elapsed time, permits renewing its OWN job.
            db.execute("UPDATE requests SET state='running',deadline=?,updated=?,processes=? WHERE id=?",
                       (self.store.clock()+lease_seconds, self.store.clock(), json.dumps([json.loads(row["monitor"])]), request_id))

    def claim_recovery(self, request_id, owner, monitor):
        token = secrets.token_urlsafe(32)
        with self.store.connection(write=True) as db:
            request = self.store._row(db, request_id)
            self.store._owned(request, owner)
            row = db.execute("SELECT * FROM managed_operations WHERE request_id=?", (request_id,)).fetchone()
            if row is None:
                raise CoordinationError("Legacy/unmanaged request: explicit reconciliation still required")
            if row["phase"] == "finished":
                return None
            if self.store.process_probe(json.loads(row["monitor"])) != "gone":
                raise CoordinationError("Monitor is alive or unverifiable; never take over because of age")
            db.execute("UPDATE managed_operations SET monitor=?,monitor_hash=?,updated=? WHERE request_id=?",
                       (json.dumps(monitor), hashlib.sha256(token.encode()).hexdigest(), self.store.clock(), request_id))
            self.store._event(db, request_id, "managed_monitor_recovered_no_relaunch")
        return token

    def finish(self, request_id, owner, token, job):
        # The open group handle must remain verifiable across the transaction.
        # A missing NAME is NOT a drain proof after all keeper handles close.
        with self.store.connection(write=True) as db:
            row, request = self._claimed(db, request_id, owner, token)
            # Verify the journal's actual group, not just a supplied handle or
            # the historical PID list. Access failures cannot become 'gone'.
            verified = Job.open(row["job_name"], json.loads(row["scope"]))
            if verified is None:
                raise CoordinationError("Group name unavailable and no durable drain proof; retain resources for verification")
            try:
                if verified is not None and verified.active() != 0:
                    raise CoordinationError("Associated processes still active; retain resources")
            finally:
                if verified:
                    verified.close()
            code = row["root_exit"]
            outcome = "completed" if code == 0 else "failed"
            result = "succeeded" if code == 0 else "failed" if code is not None else "unknown"
            # Unknown is deliberately NOT success, and never unblocks success dependencies.
            db.execute("UPDATE requests SET state=?,result=?,token_hash=NULL,updated=? WHERE id=?",
                       (outcome, "managed:"+result, self.store.clock(), request_id))
            db.execute("UPDATE managed_operations SET phase='finished',result=?,active_processes=0,updated=? WHERE request_id=?",
                       (result, self.store.clock(), request_id))
            self.store._event(db, request_id, outcome)
            from .handoff import Handoffs
            handoff = Handoffs(self.store).enqueue_after_release(db, request)
            return {**self.store._public(self.store._row(db, request_id), db), "release_handoff": handoff}


def supervise(operations, request_id, owner, token, job, process=None, lease_seconds=120):
    """Foreground observer; returns only after the whole contained group drains."""
    row = operations.record(request_id, owner)
    code = row["root_exit"]
    next_checkpoint = 0
    try:
        while True:
            active = job.active() if job else 0
            if code is None and process:
                code = process.poll()
            now = time.monotonic()
            if now >= next_checkpoint or active == 0:
                operations.checkpoint(request_id, owner, token, root_exit=code, active=active, lease_seconds=lease_seconds)
                next_checkpoint = now + min(2, lease_seconds / 3)
            if active == 0:
                result = operations.finish(request_id, owner, token, job)
                return {**result, "observer_exit_code": code if code is not None else 4}
            time.sleep(.25)
    except BaseException:
        # No killing, automatic command retry, success fabrication, or detaching
        # from the host job. The existing job survives only if the host allows it.
        try:
            operations.checkpoint(request_id, owner, token, root_exit=code, phase="needs_verification", error="monitor_interrupted_or_failed", lease_seconds=lease_seconds)
        except Exception:
            pass
        raise
    finally:
        if process:
            process.close()
        if job:
            job.close()


def recover(store, request_id, owner, *, wait=False, lease_seconds=120):
    """Inspect/recover only this owner's journaled operation. Does not execute argv."""
    store._ttl(lease_seconds)
    operations = Operations(store)
    row = operations.record(request_id, owner)
    if row is None:
        raise CoordinationError("Legacy/unmanaged request: no safe automatic recovery")
    if row["phase"] == "finished":
        return store.status(request_id)
    # Open before claiming; access denied, different session, missing group and
    # unknown monitor all remain blocking. Never use name absence as exit proof.
    job = Job.open(row["job_name"], json.loads(row["scope"]))
    if job is None:
        raise CoordinationError("Group name unavailable and no durable drain proof; manual verification required")
    process = None
    try:
        if store.process_probe(json.loads(row["monitor"])) != "gone":
            raise CoordinationError("Monitor is alive or unverifiable; no takeover")
        if not wait and job is not None and job.active():
            return {"id": request_id, "state": "still_running", "active_processes": job.active(), "command_restarted": False}
        token = operations.claim_recovery(request_id, owner, identity(os.getpid()))
        if token is None:
            return store.status(request_id)
        # Re-read AFTER the claim: the previous monitor may have persisted the
        # root exit code between our initial read and its actual termination.
        row = operations.record(request_id, owner)
        if job and row["root_exit"] is None:
            process = Process.reopen(json.loads(row["root"]) if row["root"] else None, job)
        result = supervise(operations, request_id, owner, token, job, process, lease_seconds)
        job = process = None  # supervise already closed them
        return {**result, "command_restarted": False}
    finally:
        if process:
            process.close()
        if job:
            job.close()
