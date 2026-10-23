"""Approved foreground launcher; Windows contained jobs are the v0.5 default.

No process termination, automatic command retry, detached supervisor or approval
bypass. On other platforms explicitly opt into the legacy observed-only mode.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

from .processes import identity
from .store import CoordinationError, Store


def run(store: Store, request_id: str, owner: str, argv: list[str], *, cwd=None, lease_seconds=120, tracking="contained", supervisor_worker=False) -> int:
    if tracking == "observed":
        return _observed(store, request_id, owner, argv, cwd=cwd, lease_seconds=lease_seconds)
    if tracking != "contained":
        raise CoordinationError("Unknown tracking mode")
    from .operations import Operations, fingerprint, supervise
    from .windows_job import Job, scope
    scope()  # unsupported platforms fail before acquiring anything
    if not argv or not shutil.which(argv[0]):
        raise CoordinationError("Executable missing; no command started")
    argv = [str(shutil.which(argv[0])), *argv[1:]]
    if Path(argv[0]).suffix.casefold() in (".bat", ".cmd"):
        raise CoordinationError("Use an explicit approved cmd.exe /d /s /c invocation for batch files; no implicit shell")
    cwd = str(Path(cwd or os.getcwd()).resolve())
    if not Path(cwd).is_dir():
        raise CoordinationError("Working directory missing; no command started")
    operations = Operations(store)
    previous = operations.record(request_id, owner)
    digest = fingerprint(argv, cwd)
    if previous:
        if previous["command_hash"] != digest:
            raise CoordinationError("Request already belongs to a different command; never reuse it")
        print(json.dumps({"request_id": request_id, "already_started": True, "command_restarted": False, "request": store.status(request_id)}), flush=True)
        return 4  # use watch/recover, never relaunch on resume
    if not supervisor_worker:
        # A normal child, NOT a detached service or an escape from the execution
        # host's job. Losing only this client does not discard the worker's job
        # handle. Host cancellation may still cancel BOTH; never restart either.
        entry = Path(__file__).resolve().parents[1] / "scripts/coordinate.py"
        command = [sys.executable, "-X", "utf8", "-B", str(entry), "--db", str(store.path),
                   "run", "--supervisor-worker", "--request", request_id, "--owner", owner,
                   "--cwd", cwd, "--lease-seconds", str(lease_seconds), "--", *argv]
        startup = subprocess.STARTUPINFO() if os.name == "nt" else None
        if startup:
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        worker = subprocess.Popen(command, shell=False, startupinfo=startup)
        try:
            return worker.wait()
        except KeyboardInterrupt:
            # Observe on resume with watch/recover; don't terminate/relaunch or
            # detach an already-running operation from the host's controls.
            return 130
    reservation = store.acquire(request_id, owner, lease_seconds)
    if reservation["state"] == "waiting":
        print(json.dumps(reservation), flush=True)
        return 3
    lease_token = reservation["lease_token"]
    store.start(request_id, owner, lease_token)
    token, row = operations.prepare(request_id, owner, lease_token, digest, identity(os.getpid()))
    job = process = None
    try:
        job = Job.create(row["job_name"])
        try:
            process = job.start(argv, cwd)
        except OSError:
            operations.checkpoint(request_id, owner, token, root_exit=-1, active=job.active(), error="launch_failed", lease_seconds=lease_seconds)
            operations.finish(request_id, owner, token, job)
            raise
        operations.checkpoint(request_id, owner, token, root=process.identity(), active=job.active(), lease_seconds=lease_seconds)
        # Ownership of the handles passes to supervise, including interrupt cleanup.
        watched_job, watched_process = job, process
        job = process = None
        result = supervise(operations, request_id, owner, token, watched_job, watched_process, lease_seconds)
        print(json.dumps({"request_id": request_id, "operation": result["operation"], "release_handoff": result["release_handoff"]}), flush=True)
        return result["observer_exit_code"]
    finally:
        if process:
            process.close()
        if job:
            job.close()


def _observed(store, request_id, owner, argv, *, cwd=None, lease_seconds=120):
    if not argv or not shutil.which(argv[0]):
        raise CoordinationError("Executable missing; no reservation acquired or command started")
    if cwd is not None and not Path(cwd).is_dir():
        raise CoordinationError("Working directory missing; no command started")
    reservation = store.acquire(request_id, owner, lease_seconds)
    if reservation["state"] == "waiting":
        print(json.dumps(reservation))
        return 3
    token = reservation["lease_token"]
    store.start(request_id, owner, token)
    startup = None
    if hasattr(subprocess, "STARTUPINFO"):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    try:
        child = subprocess.Popen(argv, cwd=cwd, shell=False, startupinfo=startup)
    except OSError:
        released = store.finish(request_id, owner, token, "failed")
        if released["release_handoff"]["pending_count"]:
            print(json.dumps({"request_id": request_id, "release_handoff": released["release_handoff"]}))
        raise
    observed = set()
    coordination_failed = False
    next_heartbeat = time.monotonic() + lease_seconds / 3
    while True:
        try:
            parent = psutil.Process(child.pid)
            processes = [parent] + parent.children(recursive=True)
            additions = []
            for process in processes:
                try:
                    item = identity(process.pid)
                    key = (item["pid"], item["created"])
                    if key not in observed:
                        additions.append(item)
                        observed.add(key)
                except psutil.NoSuchProcess:
                    pass
            if additions:
                store.bind_processes(request_id, owner, token, additions)
            if time.monotonic() >= next_heartbeat:
                store.heartbeat(request_id, owner, token, lease_seconds)
                next_heartbeat = time.monotonic() + lease_seconds / 3
        except psutil.NoSuchProcess:
            pass
        except Exception:
            # Keep waiting for our foreground child, but never silently release
            # a reservation whose monitoring failed. No kill-on-error policy.
            coordination_failed = True
        code = child.poll()
        if code is not None:
            child.wait()
            break
        time.sleep(0.25)
    if coordination_failed:
        raise CoordinationError("Monitoring failed; command ended but reservation retained for explicit reconciliation")
    released = store.finish(request_id, owner, token, "completed" if code == 0 else "failed")
    if released["release_handoff"]["pending_count"]:
        print(json.dumps({"request_id": request_id, "release_handoff": released["release_handoff"]}))
    return code
