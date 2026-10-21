"""Foreground-only launcher. Never starts without a valid reservation.

No process termination, automatic takeover, detached work, or approval bypass.
The caller must run this launcher inside the normal approved execution tool.
"""
import json
from pathlib import Path
import shutil
import subprocess
import time

import psutil

from .processes import identity
from .store import CoordinationError, Store


def run(store: Store, request_id: str, owner: str, argv: list[str], *, cwd=None, lease_seconds=120) -> int:
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
