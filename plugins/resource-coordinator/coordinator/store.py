"""SQLite-backed all-or-nothing resource reservations with conservative expiry.

Every scheduling mutation is a short BEGIN IMMEDIATE transaction. Expired leases
remain blocking until explicitly reconciled; age alone never authorizes takeover.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from .processes import state as process_state


class CoordinationError(ValueError):
    pass


def default_db() -> Path:
    override = os.environ.get("COORDINATOR_DB")
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise CoordinationError("COORDINATOR_DB must be an absolute local path")
        return path
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / "CodexResourceCoordinator" / "state.sqlite3"


def normalize_resources(resources: list[dict]) -> list[dict]:
    if not isinstance(resources, list) or not 1 <= len(resources) <= 32:
        raise CoordinationError("Supply 1..32 resource objects")
    result = {}
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) != {"key", "mode"}:
            raise CoordinationError("Each resource needs exactly key and mode")
        key, mode = resource["key"], resource["mode"]
        if not isinstance(key, str) or not key.strip() or len(key) > 512 or any(ord(c) < 32 for c in key):
            raise CoordinationError("Invalid resource key")
        if key != key.strip() or mode not in ("shared", "exclusive"):
            raise CoordinationError("Invalid resource mode or whitespace in key")
        # Keys represent identities, not free-form display names.
        key = key.casefold()
        if key in result:
            raise CoordinationError("Duplicate resource key")
        result[key] = mode
    return [{"key": key, "mode": mode} for key, mode in sorted(result.items())]


def conflicts(first: list[dict], second: list[dict]) -> bool:
    modes = {r["key"]: r["mode"] for r in first}
    return any(r["key"] in modes and (r["mode"] == "exclusive" or modes[r["key"]] == "exclusive") for r in second)


def _text(value: str, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise CoordinationError(f"Invalid {label}")
    return value


class Store:
    def __init__(self, path: Path | str | None = None, *, clock=time.time, process_probe=process_state):
        self.path = Path(path) if path is not None else default_db()
        if not self.path.is_absolute() or str(self.path).startswith(("\\\\", "//")):
            raise CoordinationError("Database must be an absolute LOCAL-disk path; network shares are unsupported")
        if self.path.is_symlink():
            raise CoordinationError("Do not use a symlink as the database file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.process_probe = clock, process_probe
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise CoordinationError("Unsupported database version; do not overwrite it")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL, purpose TEXT NOT NULL,
                    resources TEXT NOT NULL, state TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    deadline REAL, token_hash TEXT, processes TEXT NOT NULL DEFAULT '[]',
                    idempotency TEXT, result TEXT,
                    UNIQUE(owner, idempotency)
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL, at REAL NOT NULL, event TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS requests_state_sequence ON requests(state, sequence);
                CREATE TABLE IF NOT EXISTS request_dependencies (
                    request_id TEXT NOT NULL, prerequisite TEXT NOT NULL,
                    PRIMARY KEY(request_id, prerequisite)
                );
                CREATE TABLE IF NOT EXISTS coordination_changes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    subject TEXT NOT NULL, kind TEXT NOT NULL, attention INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoff_routes (
                    chat_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
                    authorization_reference TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS release_notices (
                    id TEXT PRIMARY KEY, target_request TEXT NOT NULL,
                    released_request TEXT NOT NULL, source_owner TEXT NOT NULL,
                    recipient TEXT NOT NULL, project_key TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    dispatcher TEXT, claim_hash TEXT, deadline REAL,
                    receipt_thread_id TEXT, result_code TEXT,
                    UNIQUE(released_request, target_request)
                );
                CREATE INDEX IF NOT EXISTS notices_target_created ON release_notices(target_request,created);
                CREATE INDEX IF NOT EXISTS notices_project_state ON release_notices(project_key,state,created);
                CREATE TABLE IF NOT EXISTS managed_operations (
                    request_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                    command_hash TEXT NOT NULL, job_name TEXT NOT NULL, scope TEXT NOT NULL,
                    monitor TEXT NOT NULL, monitor_hash TEXT NOT NULL,
                    phase TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    root TEXT, root_exit INTEGER, active_processes INTEGER,
                    result TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS managed_operation_hosts (
                    request_id TEXT PRIMARY KEY, machine_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_reboot_recoveries (
                    request_id TEXT PRIMARY KEY, evidence TEXT NOT NULL, created REAL NOT NULL
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=5000")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.execute("COMMIT")
        except BaseException:
            if write and db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _event(self, db, request_id, event):
        db.execute("INSERT INTO events(request_id,at,event) VALUES(?,?,?)", (request_id, self.clock(), event))
        if event in ("completed", "failed", "cancelled_before_start", "explicitly_reconciled_no_process_termination", "lease_expired_manual_reconciliation_required"):
            db.execute("INSERT INTO coordination_changes(at,subject,kind,attention) VALUES(?,?,?,?)", (self.clock(), request_id, "resource_"+event, event != "completed"))

    def _expire(self, db):
        rows = db.execute("SELECT id FROM requests WHERE state IN ('leased','running') AND deadline <= ?", (self.clock(),)).fetchall()
        for row in rows:
            db.execute("UPDATE requests SET state='suspect',updated=? WHERE id=?", (self.clock(), row["id"]))
            self._event(db, row["id"], "lease_expired_manual_reconciliation_required")

    def _row(self, db, request_id):
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise CoordinationError("Unknown request")
        return row

    def _owned(self, row, owner, token=None):
        if row["owner"] != owner:
            raise CoordinationError("Owner does not match")
        if token is not None:
            digest = hashlib.sha256(token.encode()).hexdigest()
            if not row["token_hash"] or not hmac.compare_digest(digest, row["token_hash"]):
                raise CoordinationError("Invalid or stale lease token")

    def _public(self, row, db=None):
        item = dict(row)
        item.pop("token_hash")
        item["resources"] = json.loads(item["resources"])
        item["processes"] = json.loads(item["processes"])
        if item["state"] in ("leased", "running") and item["deadline"] <= self.clock():
            item["state"] = "suspect"
        if db is not None:
            item["depends_on"] = [r[0] for r in db.execute("SELECT prerequisite FROM request_dependencies WHERE request_id=? ORDER BY prerequisite", (item["id"],))]
            item["dependency_blockers"] = self._dependency_blockers(db, item["id"])
            if item["state"] == "waiting":
                _, blockers = self._waiting_blockers(db, row)
                ahead = [dict(r) for r in db.execute("SELECT id,owner,purpose,state FROM requests WHERE sequence<? AND state='waiting' ORDER BY sequence", (item["sequence"],)) if r["id"] in blockers]
                item["queue_progress"] = {"waiting_ahead": ahead, "waiting_ahead_count": len(ahead), "blocked_by": blockers,
                                          "eligible": not blockers and not item["dependency_blockers"], "eta_seconds": None}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_operations'").fetchone():
                operation = db.execute("SELECT operation_id,phase,updated,root_exit,active_processes,result,error FROM managed_operations WHERE request_id=?", (item["id"],)).fetchone()
                if operation:
                    item["operation"] = dict(operation)
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='managed_reboot_recoveries'").fetchone():
                        recovery = db.execute("SELECT created FROM managed_reboot_recoveries WHERE request_id=?", (item["id"],)).fetchone()
                        if recovery:
                            item["operation"]["recovery"] = {"kind": "verified_reboot", "recovered_at": recovery["created"]}
                    if item["state"] == "suspect" and item["operation"]["phase"] != "finished":
                        item["operation"]["phase"] = "needs_verification"
        return item

    def _dependency_blockers(self, db, request_id):
        return [{"id": r["id"], "state": r["state"], "owner": r["owner"]} for r in db.execute(
            "SELECT r.id,r.state,r.owner FROM request_dependencies d JOIN requests r ON r.id=d.prerequisite WHERE d.request_id=? AND r.state<>'completed' ORDER BY r.sequence", (request_id,))]

    def _set_dependencies(self, db, request_id, prerequisites):
        if not isinstance(prerequisites, list) or len(prerequisites) > 32 or any(not isinstance(p, str) for p in prerequisites):
            raise CoordinationError("Dependencies must be a list of at most 32 request IDs")
        if len(set(prerequisites)) != len(prerequisites):
            raise CoordinationError("Duplicate dependency")
        for prerequisite in prerequisites:
            self._row(db, prerequisite)
            if prerequisite == request_id:
                raise CoordinationError("Dependency cycle")
            found = db.execute("""WITH RECURSIVE ancestors(id) AS (
                SELECT prerequisite FROM request_dependencies WHERE request_id=?
                UNION SELECT d.prerequisite FROM request_dependencies d JOIN ancestors a ON d.request_id=a.id
            ) SELECT 1 FROM ancestors WHERE id=? LIMIT 1""", (prerequisite, request_id)).fetchone()
            if found:
                raise CoordinationError("Dependency cycle")
        db.execute("DELETE FROM request_dependencies WHERE request_id=?", (request_id,))
        db.executemany("INSERT INTO request_dependencies(request_id,prerequisite) VALUES(?,?)", [(request_id, p) for p in prerequisites])

    def set_dependencies(self, request_id, owner, prerequisites):
        with self.connection(write=True) as db:
            row = self._row(db, request_id)
            self._owned(row, owner)
            if row["state"] != "waiting":
                raise CoordinationError("Only waiting requests can change dependencies")
            self._set_dependencies(db, request_id, prerequisites)
            self._event(db, request_id, "dependencies_updated")
            return self._public(self._row(db, request_id), db)

    def status(self, request_id=None, *, include_finished=False, limit=100):
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise CoordinationError("Limit must be 1..1000")
        with self.connection() as db:
            if request_id:
                return self._public(self._row(db, request_id), db)
            clause = "" if include_finished else "WHERE state IN ('waiting','leased','running','suspect')"
            return [self._public(row, db) for row in db.execute(f"SELECT * FROM requests {clause} ORDER BY sequence LIMIT ?", (limit,))]

    def request(self, owner, purpose, resources, idempotency_key=None, depends_on=None):
        owner, purpose = _text(owner, "owner", 200), _text(purpose, "purpose", 500)
        resources = normalize_resources(resources)
        if idempotency_key is not None:
            _text(idempotency_key, "idempotency key", 200)
        prerequisites = depends_on if depends_on is not None else []
        with self.connection(write=True) as db:
            if idempotency_key is not None:
                old = db.execute("SELECT * FROM requests WHERE owner=? AND idempotency=?", (owner, idempotency_key)).fetchone()
                if old:
                    if old["purpose"] != purpose or json.loads(old["resources"]) != resources or sorted(prerequisites) != self._public(old, db)["depends_on"]:
                        raise CoordinationError("Idempotency key reused with different request data")
                    return self._public(old, db)
            request_id, now = str(uuid.uuid4()), self.clock()
            db.execute("INSERT INTO requests(id,owner,purpose,resources,state,created,updated,idempotency) VALUES(?,?,?,?,?,?,?,?)",
                       (request_id, owner, purpose, json.dumps(resources), "waiting", now, now, idempotency_key))
            self._event(db, request_id, "requested")
            self._set_dependencies(db, request_id, prerequisites)
            return self._public(self._row(db, request_id), db)

    @staticmethod
    def _ttl(seconds):
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 10 <= seconds <= 3600:
            raise CoordinationError("Lease seconds must be an integer in 10..3600")
        return seconds

    def acquire(self, request_id, owner, lease_seconds=120):
        self._ttl(lease_seconds)
        with self.connection(write=True) as db:
            self._expire(db)
            row = self._row(db, request_id)
            self._owned(row, owner)
            if row["state"] != "waiting":
                raise CoordinationError("Only a waiting request can acquire; do not mint replacement tokens")
            dependencies, blockers = self._waiting_blockers(db, row)
            if dependencies:
                return {"id": request_id, "state": "waiting", "blocked_by": [], "dependency_blockers": dependencies}
            if blockers:
                return {"id": request_id, "state": "waiting", "blocked_by": blockers}
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE requests SET state='leased',updated=?,deadline=?,token_hash=? WHERE id=?",
                       (self.clock(), self.clock()+lease_seconds, hashlib.sha256(token.encode()).hexdigest(), request_id))
            self._event(db, request_id, "acquired")
            return {**self._public(self._row(db, request_id), db), "lease_token": token}

    def _waiting_blockers(self, db, row):
        dependencies = self._dependency_blockers(db, row["id"])
        resources = json.loads(row["resources"])
        others = db.execute("SELECT * FROM requests WHERE id<>? AND (state IN ('leased','running','suspect') OR (state='waiting' AND sequence<?)) ORDER BY sequence", (row["id"], row["sequence"]))
        blockers = [other["id"] for other in others if
            (other["state"] != "waiting" or not self._dependency_blockers(db, other["id"])) and conflicts(resources, json.loads(other["resources"]))]
        return dependencies, blockers

    def _active(self, db, request_id, owner, token):
        self._expire(db)
        row = self._row(db, request_id)
        self._owned(row, owner, _text(token, "lease token", 200))
        if row["state"] not in ("leased", "running"):
            raise CoordinationError("Lease is not active; expired/suspect reservations require reconciliation")
        return row

    def start(self, request_id, owner, token):
        with self.connection(write=True) as db:
            row = self._active(db, request_id, owner, token)
            if row["state"] != "leased":
                raise CoordinationError("Request already started")
            db.execute("UPDATE requests SET state='running',updated=? WHERE id=?", (self.clock(), request_id))
            self._event(db, request_id, "started")
            return self._public(self._row(db, request_id), db)

    def bind_processes(self, request_id, owner, token, processes):
        if not isinstance(processes, list) or not 1 <= len(processes) <= 128:
            raise CoordinationError("Supply 1..128 process identities")
        for item in processes:
            if set(item) != {"pid", "created", "executable"} or not isinstance(item["pid"], int) or item["pid"] <= 0 or not isinstance(item["created"], (int, float)) or not isinstance(item["executable"], str):
                raise CoordinationError("Invalid process identity")
        with self.connection(write=True) as db:
            row = self._active(db, request_id, owner, token)
            if row["state"] != "running":
                raise CoordinationError("Only a running request can bind process identities")
            # Keep all observed identities, including children that outlive a launcher.
            identities = {(p["pid"], p["created"]): p for p in json.loads(row["processes"])}
            identities.update({(p["pid"], p["created"]): p for p in processes})
            if len(identities) > 512:
                # Large foreground builds may launch hundreds of sequential
                # compilers. Retain alive/unknown identities, not reaped history.
                identities = {key: item for key, item in identities.items() if self.process_probe(item) != "gone"}
                if len(identities) > 512:
                    raise CoordinationError("Live/unverifiable process tracking budget exceeded; retain lease for manual review")
            db.execute("UPDATE requests SET processes=?,updated=? WHERE id=?", (json.dumps(list(identities.values())), self.clock(), request_id))

    def heartbeat(self, request_id, owner, token, lease_seconds=120):
        self._ttl(lease_seconds)
        with self.connection(write=True) as db:
            self._active(db, request_id, owner, token)
            db.execute("UPDATE requests SET deadline=?,updated=? WHERE id=?", (self.clock()+lease_seconds, self.clock(), request_id))
            return self._public(self._row(db, request_id), db)

    def _confirm_processes_gone(self, row):
        for item in json.loads(row["processes"]):
            if self.process_probe(item) != "gone":
                raise CoordinationError("A recorded process is alive or unverifiable; reservation remains blocking")

    def finish(self, request_id, owner, token, outcome="completed"):
        if outcome not in ("completed", "failed", "cancelled"):
            raise CoordinationError("Outcome must be completed, failed, or cancelled")
        with self.connection(write=True) as db:
            row = self._active(db, request_id, owner, token)
            self._reject_managed_completion(db, request_id)
            self._confirm_processes_gone(row)
            db.execute("UPDATE requests SET state=?,result=?,token_hash=NULL,updated=? WHERE id=?", (outcome, outcome, self.clock(), request_id))
            self._event(db, request_id, outcome)
            from .handoff import Handoffs
            handoff = Handoffs(self).enqueue_after_release(db, row)
            return {**self._public(self._row(db, request_id), db), "release_handoff": handoff}

    def cancel(self, request_id, owner):
        with self.connection(write=True) as db:
            row = self._row(db, request_id)
            self._owned(row, owner)
            if row["state"] != "waiting":
                raise CoordinationError("Cancel only removes waiting requests; it never terminates work")
            db.execute("UPDATE requests SET state='cancelled',updated=? WHERE id=?", (self.clock(), request_id))
            self._event(db, request_id, "cancelled_before_start")
            return self._public(self._row(db, request_id), db)

    def reconcile(self, request_id, owner, confirmed_stopped=False, note=""):
        if confirmed_stopped is not True:
            raise CoordinationError("Explicit confirmation that work has stopped is required")
        _text(note, "reconciliation note", 500)
        with self.connection(write=True) as db:
            self._expire(db)
            row = self._row(db, request_id)
            self._owned(row, owner)
            self._reject_managed_completion(db, request_id)
            if row["state"] != "suspect":
                raise CoordinationError("Reconcile only suspect reservations")
            self._confirm_processes_gone(row)
            db.execute("UPDATE requests SET state='failed',result=?,token_hash=NULL,updated=? WHERE id=?", (note, self.clock(), request_id))
            self._event(db, request_id, "explicitly_reconciled_no_process_termination")
            from .handoff import Handoffs
            handoff = Handoffs(self).enqueue_after_release(db, row)
            return {**self._public(self._row(db, request_id), db), "release_handoff": handoff}

    @staticmethod
    def _reject_managed_completion(db, request_id):
        if db.execute("SELECT 1 FROM managed_operations WHERE request_id=?", (request_id,)).fetchone():
            raise CoordinationError("Managed operation: use watch/recover; recorded PIDs alone cannot prove the job drained")
