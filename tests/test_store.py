from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from pathlib import Path
import sys

import pytest

from coordinator.store import CoordinationError, Store


def resource(key="build:demo", mode="exclusive"):
    return [{"key": key, "mode": mode}]


def lease(store, owner="first", resources=None):
    request = store.request(owner, "test operation", resources or resource())
    return store.acquire(request["id"], owner)


def contend(args):
    path, request_id, owner = args
    store = Store(path)
    result = store.acquire(request_id, owner)
    return result["state"]


def test_conflicting_requests_fifo_and_cancel(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    first = store.request("first", "first build", resource())
    second = store.request("second", "second build", resource())
    assert store.acquire(second["id"], "second")["blocked_by"] == [first["id"]]
    store.cancel(first["id"], "first")
    assert store.acquire(second["id"], "second")["state"] == "leased"


def test_shared_readers_and_performance_writer_fairness(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    a = lease(store, "a", resource("machine:load", "shared"))
    b = lease(store, "b", resource("machine:load", "shared"))
    perf = store.request("perf", "capture", resource("machine:load"))
    late = store.request("late", "later build", resource("machine:load", "shared"))
    assert store.acquire(perf["id"], "perf")["state"] == "waiting"
    assert perf["id"] in store.acquire(late["id"], "late")["blocked_by"]
    store.finish(a["id"], "a", a["lease_token"])
    store.finish(b["id"], "b", b["lease_token"])
    assert store.acquire(perf["id"], "perf")["state"] == "leased"


def test_atomic_multi_resource_and_unrelated_work(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    a = lease(store, "a", resource("asset:a"))
    both = store.request("both", "needs two assets", resource("asset:a") + resource("asset:b"))
    assert store.acquire(both["id"], "both")["state"] == "waiting"
    assert store.status(both["id"])["state"] == "waiting"
    unrelated = lease(store, "other", resource("browser:independent"))
    assert unrelated["state"] == "leased"
    store.finish(a["id"], "a", a["lease_token"])
    assert store.acquire(both["id"], "both")["state"] == "leased"


def test_expiry_is_not_takeover_and_stale_token_cannot_release(tmp_path):
    now = [100.0]
    store = Store(tmp_path / "queue.sqlite3", clock=lambda: now[0])
    old = lease(store)
    following = store.request("next", "next build", resource())
    now[0] += 121
    assert store.status(old["id"])["state"] == "suspect"
    assert store.acquire(following["id"], "next")["state"] == "waiting"
    with pytest.raises(CoordinationError, match="not active"):
        store.heartbeat(old["id"], "first", old["lease_token"])
    with pytest.raises(CoordinationError, match="confirmation"):
        store.reconcile(old["id"], "first", False, "not confirmed")
    store.reconcile(old["id"], "first", True, "operator verified foreground work has stopped")
    active = store.acquire(following["id"], "next")
    with pytest.raises(CoordinationError):
        store.finish(active["id"], "next", old["lease_token"])
    assert store.status(active["id"])["state"] == "leased"


@pytest.mark.parametrize("state", ["alive", "unknown"])
def test_live_or_unverifiable_process_prevents_release_and_recovery(tmp_path, state):
    now = [100.0]
    store = Store(tmp_path / "queue.sqlite3", clock=lambda: now[0], process_probe=lambda _: state)
    active = lease(store)
    store.start(active["id"], "first", active["lease_token"])
    store.bind_processes(active["id"], "first", active["lease_token"], [{"pid": 123, "created": 1.0, "executable": "test-only.exe"}])
    with pytest.raises(CoordinationError, match="alive or unverifiable"):
        store.finish(active["id"], "first", active["lease_token"])
    now[0] += 121
    with pytest.raises(CoordinationError, match="alive or unverifiable"):
        store.reconcile(active["id"], "first", True, "attempted recovery")


def test_persistent_db_and_token_redaction(tmp_path):
    path = tmp_path / "queue.sqlite3"
    active = lease(Store(path))
    second_client = Store(path)
    assert second_client.status(active["id"])["state"] == "leased"
    assert active["lease_token"] not in json.dumps(second_client.status(include_finished=True))
    assert "token_hash" not in second_client.status(active["id"])


def test_idempotency_and_owner_checks(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    first = store.request("owner", "operation", resource(), "stable-key")
    assert first == store.request("owner", "operation", resource(), "stable-key")
    with pytest.raises(CoordinationError, match="different"):
        store.request("owner", "different operation", resource(), "stable-key")
    with pytest.raises(CoordinationError, match="Owner"):
        store.cancel(first["id"], "other")


@pytest.mark.parametrize("resources", [[], [{"key": "x", "mode": "wrong"}], [{"key": "x", "mode": "shared"}, {"key": "X", "mode": "exclusive"}], [{"key": "x\n", "mode": "shared"}]])
def test_invalid_resources_rejected(tmp_path, resources):
    with pytest.raises(CoordinationError):
        Store(tmp_path / "queue.sqlite3").request("owner", "operation", resources)


def test_four_real_processes_never_double_grant(tmp_path):
    path = tmp_path / "queue.sqlite3"
    store = Store(path)
    requests = [store.request(str(i), "same build", resource()) for i in range(4)]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        states = list(pool.map(contend, [(path, r["id"], str(i)) for i, r in enumerate(requests)]))
    assert states.count("leased") == 1
    assert states.count("waiting") == 3


def test_generic_non_ue_database_migration_scenario(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    migration = lease(store, "backend", resource("database:staging-schema"))
    test = store.request("integration-tests", "test schema", resource("database:staging-schema", "shared"))
    assert store.acquire(test["id"], "integration-tests")["state"] == "waiting"
    store.finish(migration["id"], "backend", migration["lease_token"])
    assert store.acquire(test["id"], "integration-tests")["state"] == "leased"


def test_runner_does_not_start_queued_command(tmp_path):
    from coordinator.runner import run
    store = Store(tmp_path / "queue.sqlite3")
    lease(store)
    queued = store.request("queued", "blocked command", resource())
    marker = tmp_path / "must-not-exist.txt"
    result = run(store, queued["id"], "queued", [sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).touch()", str(marker)])
    assert result == 3
    assert not marker.exists()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_runner_foreground_completion_and_failure(tmp_path, exit_code):
    from coordinator.runner import run
    store = Store(tmp_path / "queue.sqlite3")
    queued = store.request("runner", "small owned command", resource())
    assert run(store, queued["id"], "runner", [sys.executable, "-c", f"raise SystemExit({exit_code})"]) == exit_code
    assert store.status(queued["id"])["state"] == ("completed" if exit_code == 0 else "failed")


def test_cli_no_database_does_not_start_payload(tmp_path):
    import subprocess
    entry = Path(__file__).parents[1] / "plugins/resource-coordinator/scripts/coordinate.py"
    marker = tmp_path / "must-not-exist.txt"
    # A directory is not a SQLite database. The subprocess cannot reach its payload.
    result = subprocess.run([sys.executable, "-B", str(entry), "--db", str(tmp_path), "run", "--request", "unknown", "--owner", "test", "--", sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).touch()", str(marker)], capture_output=True)
    assert result.returncode == 1
    assert not marker.exists()


def test_long_build_retires_only_confirmed_gone_process_identities(tmp_path):
    store = Store(tmp_path / "queue.sqlite3", process_probe=lambda _: "gone")
    active = lease(store)
    store.start(active["id"], "first", active["lease_token"])
    for batch in range(6):
        identities = [{"pid": batch*100+i+1, "created": 1.0, "executable": "synthetic-compiler"} for i in range(100)]
        store.bind_processes(active["id"], "first", active["lease_token"], identities)
    store.finish(active["id"], "first", active["lease_token"])
    assert store.status(active["id"])["state"] == "completed"


def test_real_client_exits_without_release_and_needs_explicit_recovery(tmp_path):
    import subprocess
    import time
    path = tmp_path / "crash.sqlite3"
    store = Store(path)
    request = store.request("crasher", "synthetic crash", resource())
    script = """
import os,sys
sys.path.insert(0,sys.argv[1])
from coordinator.store import Store
from coordinator.processes import identity
s=Store(sys.argv[2])
a=s.acquire(sys.argv[3],'crasher',10)
s.start(a['id'],'crasher',a['lease_token'])
s.bind_processes(a['id'],'crasher',a['lease_token'],[identity(os.getpid())])
os._exit(23)
"""
    source = str(Path(__file__).parents[1] / "plugins/resource-coordinator")
    exited = subprocess.run([sys.executable, "-B", "-c", script, source, str(path), request["id"]], capture_output=True)
    assert exited.returncode == 23
    later = Store(path, clock=lambda: time.time()+11)
    queued = later.request("next", "next operation", resource())
    assert later.acquire(queued["id"], "next")["state"] == "waiting"
    later.reconcile(request["id"], "crasher", True, "verified owned synthetic client exited, no children")
    assert later.acquire(queued["id"], "next")["state"] == "leased"
