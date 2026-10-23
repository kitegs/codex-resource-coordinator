import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import psutil

from coordinator.board import Board
from coordinator.operations import Operations, recover
from coordinator.processes import identity, state
from coordinator.runner import run
from coordinator.store import CoordinationError, Store

ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "plugins/resource-coordinator/scripts/coordinate.py"
PAYLOAD = Path(__file__).with_name("job_payload.py")
RESOURCES = [{"key": "test:contained-output", "mode": "exclusive"}]
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="native Windows Job Object integration")


def until(predicate, seconds=8):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError("Bounded synthetic test condition not reached")


def command(store, request, *extra):
    # Avoid the venv REDIRECTOR shim when intentionally stopping the client.
    return [psutil.Process(os.getpid()).exe(), "-X", "utf8", "-B", str(ENTRY), "--db", str(store.path), *extra,
            "--request", request["id"], "--owner", "test"]


def launch(store, request, directory, mode="root", code=0):
    argv = command(store, request, "run") + ["--", sys.executable, "-B", str(PAYLOAD), mode, str(directory), str(code)]
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env())


def child_env():
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}


def cleanup(process, directory):
    (directory / "release").touch()
    if process is not None:
        process.communicate(timeout=12)


def terminate_owned(process):
    # Only the Popen-created SYNTHETIC monitor, freshly identity checked.
    captured = identity(process.pid)
    assert captured["pid"] == process.pid and state(captured) == "alive"
    process.terminate()
    process.wait(timeout=5)


def terminate_monitor(process, store, request):
    captured = json.loads(Operations(store).record(request["id"], "test")["monitor"])
    assert state(captured) == "alive"
    assert captured["pid"] in [p.pid for p in psutil.Process(process.pid).children(recursive=True)]
    psutil.Process(captured["pid"]).terminate()
    process.wait(timeout=8)


@WINDOWS
@pytest.mark.parametrize("mode,code", [("root", 0), ("root", 7), ("grandparent", 0)])
def test_parent_exit_does_not_release_live_children(tmp_path, mode, code):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "synthetic process tree", RESOURCES)
    process = launch(store, request, tmp_path, mode, code)
    try:
        until(lambda: (tmp_path / "started.json").exists())
        until(lambda: store.status(request["id"])["operation"]["root_exit"] == code)
        assert process.poll() is None
        following = store.request("other", "wait for all writers", RESOURCES)
        assert store.acquire(following["id"], "other")["state"] == "waiting"
        (tmp_path / "release").touch()
        out, err = process.communicate(timeout=10)
        assert process.returncode == code, (out, err)
        result = store.status(request["id"])
        assert result["state"] == ("completed" if code == 0 else "failed")
        assert result["operation"]["active_processes"] == 0
        assert store.acquire(following["id"], "other")["state"] == "leased"
    finally:
        cleanup(process, tmp_path)


@WINDOWS
def test_live_monitor_cannot_be_taken_over_even_after_lease_expiry(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "live monitor", RESOURCES)
    process = launch(store, request, tmp_path)
    try:
        until(lambda: (tmp_path / "started.json").exists())
        with store.connection() as db:
            db.execute("UPDATE requests SET deadline=0 WHERE id=?", (request["id"],))
        with pytest.raises(CoordinationError, match="alive or unverifiable"):
            recover(store, request["id"], "test")
        with pytest.raises(CoordinationError, match="Managed"):
            store.reconcile(request["id"], "test", True, "cannot bypass group evidence")
        assert process.poll() is None
    finally:
        cleanup(process, tmp_path)


@WINDOWS
def test_repeated_run_never_launches_duplicate_even_after_completion(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "no duplicate", RESOURCES)
    process = launch(store, request, tmp_path)
    try:
        until(lambda: (tmp_path / "started.json").exists())
        duplicate = launch(store, request, tmp_path)
        out, err = duplicate.communicate(timeout=8)
        assert duplicate.returncode == 4, (out, err)
        assert json.loads(out)["command_restarted"] is False
        with pytest.raises(CoordinationError, match="different command"):
            run(store, request["id"], "test", [sys.executable, "-c", "print('different')"])
        cleanup(process, tmp_path)
        duplicate = launch(store, request, tmp_path)
        duplicate.communicate(timeout=8)
        assert duplicate.returncode == 4
        assert (tmp_path / "launches.txt").read_text().splitlines() == ["launched"]
    finally:
        cleanup(process, tmp_path)


@WINDOWS
def test_dead_monitor_recovery_observes_children_without_restarting(tmp_path):
    from coordinator.windows_job import Job
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "recover monitor only", RESOURCES)
    process = launch(store, request, tmp_path)
    observer = witness = None
    try:
        until(lambda: (tmp_path / "started.json").exists())
        until(lambda: store.status(request["id"])["operation"]["root_exit"] == 0)
        row = Operations(store).record(request["id"], "test")
        witness = Job.open(row["job_name"], json.loads(row["scope"]))
        terminate_monitor(process, store, request)
        result = recover(store, request["id"], "test")
        assert result["state"] == "still_running" and result["command_restarted"] is False
        observer = subprocess.Popen(command(store, request, "watch"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env())
        until(lambda: json.loads(Operations(store).record(request["id"], "test")["monitor"])["pid"] == observer.pid)
        assert observer.poll() is None
        (tmp_path / "release").touch()
        out, err = observer.communicate(timeout=10)
        assert observer.returncode == 0, (out, err)
        result = json.loads(out)
        assert result["state"] == "completed" and result["command_restarted"] is False
        assert result["release_handoff"]["pending_count"] == 0
        assert (tmp_path / "launches.txt").read_text().splitlines() == ["launched"]
    finally:
        cleanup(observer, tmp_path)
        cleanup(process, tmp_path)
        if witness:
            witness.close()


@WINDOWS
def test_lost_exit_result_releases_but_never_unblocks_success_dependency(tmp_path):
    from coordinator.windows_job import Job
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "unknown outcome after crash", RESOURCES)
    process = launch(store, request, tmp_path, "root-waits")
    job = None
    try:
        until(lambda: (tmp_path / "started.json").exists())
        row = Operations(store).record(request["id"], "test")
        job = Job.open(row["job_name"], json.loads(row["scope"]))
        terminate_monitor(process, store, request)
        dependent = store.request("dependent", "requires proven success", RESOURCES, depends_on=[request["id"]])
        (tmp_path / "release").touch()
        until(lambda: job.active() == 0)
        result = recover(store, request["id"], "test")
        assert result["state"] == "failed" and result["operation"]["result"] == "unknown"
        assert result["observer_exit_code"] == 4 and result["command_restarted"] is False
        assert store.acquire(dependent["id"], "dependent")["dependency_blockers"]
        independent = store.request("independent", "does not require result", RESOURCES)
        assert store.acquire(independent["id"], "independent")["state"] == "leased"
    finally:
        if job:
            job.close()
        cleanup(process, tmp_path)


@WINDOWS
def test_monitor_can_reopen_still_alive_root_and_get_real_exit_code(tmp_path):
    from coordinator.windows_job import Job
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "reopen root by identity", RESOURCES)
    process = launch(store, request, tmp_path, "root-waits", 9)
    observer = witness = None
    try:
        until(lambda: (tmp_path / "started.json").exists())
        until(lambda: Operations(store).record(request["id"], "test")["root"] is not None)
        row = Operations(store).record(request["id"], "test")
        witness = Job.open(row["job_name"], json.loads(row["scope"]))
        terminate_monitor(process, store, request)
        observer = subprocess.Popen(command(store, request, "watch"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env())
        until(lambda: json.loads(Operations(store).record(request["id"], "test")["monitor"])["pid"] == observer.pid)
        time.sleep(.1)
        (tmp_path / "release").touch()
        out, err = observer.communicate(timeout=10)
        assert observer.returncode == 0, (out, err)
        result = json.loads(out)
        assert result["state"] == "failed" and result["operation"]["root_exit"] == 9
    finally:
        cleanup(observer, tmp_path)
        cleanup(process, tmp_path)
        if witness:
            witness.close()


@WINDOWS
def test_release_reuses_outbox_but_does_not_send_or_start_next(tmp_path):
    from coordinator.handoff import Handoffs
    store = Store(tmp_path / "state.sqlite3")
    board, handoffs = Board(store), Handoffs(store)
    for owner in ("test", "next"):
        board.register(owner, owner, "synthetic")
        handoffs.configure(owner, True, "synthetic test scope; no real messages")
    request = store.request("test", "first", RESOURCES)
    following = store.request("next", "next", RESOURCES)
    assert run(store, request["id"], "test", [sys.executable, "-c", "pass"]) == 0
    assert store.status(following["id"])["state"] == "waiting"
    assert handoffs.listing("test")["notices"][0]["state"] == "pending"
    assert recover(store, request["id"], "test")["state"] == "completed"


@WINDOWS
def test_launch_failure_releases_without_falling_back_to_uncontained(tmp_path, monkeypatch):
    from coordinator.windows_job import Job
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "start failure", RESOURCES)
    def fail(*_args, **_kwargs):
        raise OSError("synthetic CreateProcess rejection")
    monkeypatch.setattr(Job, "start", fail)
    with pytest.raises(OSError, match="synthetic"):
        run(store, request["id"], "test", [sys.executable, "-c", "pass"], supervisor_worker=True)
    assert store.status(request["id"])["state"] == "failed"


def test_unmanaged_requests_never_use_automatic_recovery(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "legacy", RESOURCES)
    with pytest.raises(CoordinationError, match="Legacy/unmanaged"):
        recover(store, request["id"], "test")
    assert store.status(request["id"])["state"] == "waiting"


def test_queue_progress_counts_only_conflicting_runnable_waiters_no_eta(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    first = store.request("a", "first", RESOURCES)
    unrelated = store.request("b", "other output", [{"key": "other", "mode": "exclusive"}])
    dependent = store.request("d", "blocked by dependency", RESOURCES, depends_on=[unrelated["id"]])
    last = store.request("c", "last", RESOURCES)
    progress = store.status(last["id"])["queue_progress"]
    assert progress["waiting_ahead_count"] == 1
    assert progress["waiting_ahead"][0]["id"] == first["id"]
    assert progress["eta_seconds"] is None and not progress["eligible"]
    store.cancel(first["id"], "a")
    assert store.status(last["id"])["queue_progress"]["eligible"]


def test_pid_reuse_is_gone_but_access_denied_is_unknown(monkeypatch):
    import coordinator.processes as processes
    class Reused:
        def create_time(self):
            return 200
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: Reused())
    assert state({"pid": 123, "created": 1}) == "gone"
    def denied(pid):
        raise processes.psutil.AccessDenied(pid)
    monkeypatch.setattr(processes.psutil, "Process", denied)
    assert state({"pid": 123, "created": 1}) == "unknown"


@WINDOWS
@pytest.mark.parametrize("probe", ["alive", "unknown"])
def test_recovery_never_steals_alive_or_unverifiable_monitor(tmp_path, probe):
    store = Store(tmp_path / "state.sqlite3", process_probe=lambda _: probe)
    request = store.request("test", "claim guard", RESOURCES)
    lease = store.acquire(request["id"], "test")
    store.start(request["id"], "test", lease["lease_token"])
    operations = Operations(store)
    token, _ = operations.prepare(request["id"], "test", lease["lease_token"], "synthetic", identity(os.getpid()))
    with pytest.raises(CoordinationError, match="alive or unverifiable"):
        operations.claim_recovery(request["id"], "test", identity(os.getpid()))
    with pytest.raises(CoordinationError, match="Managed"):
        store.finish(request["id"], "test", lease["lease_token"])
    public = json.dumps(store.status(request["id"]))
    assert token not in public and lease["lease_token"] not in public and "monitor_hash" not in public and "job_name" not in public


@WINDOWS
def test_changed_session_or_scope_must_not_be_misread_as_missing_job(tmp_path):
    from coordinator.windows_job import Job, scope
    current = scope()
    with pytest.raises(OSError, match="unverifiable"):
        Job.open("Local\\CodexCoord-nonexistent", {**current, "session": current["session"]+1})


@WINDOWS
def test_group_query_error_keeps_reservation_blocking(tmp_path, monkeypatch):
    from coordinator.windows_job import Job
    store = Store(tmp_path / "state.sqlite3", process_probe=lambda _: "gone")
    request = store.request("test", "unknown group", RESOURCES)
    lease = store.acquire(request["id"], "test")
    store.start(request["id"], "test", lease["lease_token"])
    Operations(store).prepare(request["id"], "test", lease["lease_token"], "test", identity(os.getpid()))
    def denied(*args):
        raise OSError("synthetic group access denied")
    monkeypatch.setattr(Job, "open", denied)
    with pytest.raises(OSError, match="access denied"):
        recover(store, request["id"], "test")
    assert store.status(request["id"])["state"] == "running"


@WINDOWS
def test_client_interruption_does_not_discard_operation_monitor(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "client ended; authorized worker remains", RESOURCES)
    process = launch(store, request, tmp_path)
    try:
        until(lambda: (tmp_path / "started.json").exists())
        monitor = json.loads(Operations(store).record(request["id"], "test")["monitor"])
        assert monitor["pid"] != process.pid
        terminate_owned(process)
        assert state(monitor) == "alive"
        assert store.status(request["id"])["state"] == "running"
        following = store.request("next", "next work", RESOURCES)
        assert store.acquire(following["id"], "next")["state"] == "waiting"
        (tmp_path / "release").touch()
        until(lambda: store.status(request["id"])["state"] == "completed")
        assert store.acquire(following["id"], "next")["state"] == "leased"
        assert (tmp_path / "launches.txt").read_text().splitlines() == ["launched"]
    finally:
        cleanup(process, tmp_path)


@WINDOWS
def test_lost_group_name_never_means_drained_even_after_known_root_exit(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "missing proof must block", RESOURCES)
    process = launch(store, request, tmp_path)
    try:
        until(lambda: (tmp_path / "started.json").exists())
        until(lambda: store.status(request["id"])["operation"]["root_exit"] == 0)
        terminate_monitor(process, store, request)
        # No witness handle kept: this reproduces the false-release bug found
        # during initial native tests. It MUST NOT infer exit from a missing name.
        with pytest.raises(CoordinationError, match="no durable drain proof"):
            recover(store, request["id"], "test")
        following = store.request("next", "blocked until verified", RESOURCES)
        assert store.acquire(following["id"], "next")["state"] == "waiting"
        assert not (tmp_path / "done").exists()
    finally:
        cleanup(process, tmp_path)


@WINDOWS
def test_legacy_observed_mode_still_available_but_never_auto_recovered(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    request = store.request("test", "explicit legacy", RESOURCES)
    assert run(store, request["id"], "test", [sys.executable, "-c", "pass"], tracking="observed") == 0
    assert "operation" not in store.status(request["id"])
    with pytest.raises(CoordinationError, match="Legacy"):
        recover(store, request["id"], "test")
