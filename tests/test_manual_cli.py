"""Manual CLI lifecycle: real SQLite/receipts, no application control or messages."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coordinator.board import Board
from coordinator.cli import main
from coordinator.handoff import Handoffs
from coordinator.operations import Operations
from coordinator.store import Store

ENTRY = Path(__file__).parents[1] / "plugins/resource-coordinator/scripts/coordinate.py"
RESOURCE = [{"key": "manual-test:asset", "mode": "exclusive"}]


@pytest.fixture
def cli(tmp_path, capsys):
    database = tmp_path / "state.sqlite3"

    def call(*args, code=0):
        actual = main(["--db", str(database), *map(str, args)])
        output = capsys.readouterr()
        assert actual == code, (actual, output)
        assert not (output.err if code in (0, 3) else output.out)
        text = output.out if code in (0, 3) else output.err
        assert "Traceback" not in text
        return json.loads(text)

    return database, call


def acquire(store, call, tmp_path, owner="a", resources=RESOURCE):
    request = store.request(owner, "manual asset operation", resources)
    receipt = tmp_path / (owner + ".lease.json")
    result = call("acquire", "--request", request["id"], "--owner", owner, "--lease-file", receipt)
    return request, receipt, result


def test_manual_lifecycle_queue_dependencies_redaction_and_handoff(cli, tmp_path):
    database, call = cli
    store = Store(database)
    for actor in ("a", "b"):
        Board(store).register(actor, actor, "test")
        Handoffs(store).configure(actor, True, "synthetic test authorization")
    first, receipt, acquired = acquire(store, call, tmp_path)
    token = json.loads(receipt.read_text(encoding="utf-8"))["lease_token"]
    original = receipt.read_bytes()
    assert acquired["state"] == "leased" and acquired["lease_usable"] and acquired["token_redacted"]
    if os.name != "nt":
        assert receipt.stat().st_mode & 0o777 == 0o600
    second = store.request("b", "dependent next operation", RESOURCE, depends_on=[first["id"]])
    waiting_file = tmp_path / "waiting.lease.json"
    waiting = call("acquire", "--request", second["id"], "--owner", "b", "--lease-file", waiting_file, code=3)
    assert waiting["state"] == "waiting" and not waiting["lease_usable"]
    assert "lease_token" not in json.loads(waiting_file.read_text())
    call("begin", "--lease-file", waiting_file, code=1)
    started = call("begin", "--lease-file", receipt)
    assert started["state"] == "running"
    call("begin", "--lease-file", receipt, code=1)
    renewed = call("renew", "--lease-file", receipt, "--lease-seconds", 600)
    assert renewed["deadline"] > acquired["deadline"]
    completed = call("complete", "--lease-file", receipt)
    assert completed["state"] == "completed" and completed["release_handoff"]["pending_count"] == 1
    assert receipt.read_bytes() == original  # renewal needs no secret-file rewrite
    for result in (acquired, waiting, started, renewed, completed, call("status", "--all"), call("board")):
        assert token not in json.dumps(result)
    assert Handoffs(store).listing("a")["notices"][0]["state"] == "pending"
    for command in ("complete", "renew", "begin"):
        error = call(command, "--lease-file", receipt, code=1)
        assert token not in json.dumps(error)
    assert len(Handoffs(store).listing("a")["notices"]) == 1
    following = tmp_path / "b.lease.json"
    assert call("acquire", "--request", second["id"], "--owner", "b", "--lease-file", following)["state"] == "leased"
    call("complete", "--lease-file", following)  # cancelling/finishing an unused reservation remains supported


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_all_completion_outcomes_and_dependency_policy(cli, tmp_path, outcome):
    database, call = cli
    store = Store(database)
    request, receipt, _ = acquire(store, call, tmp_path)
    second = store.request("b", "requires success", RESOURCE, depends_on=[request["id"]])
    call("begin", "--lease-file", receipt)
    assert call("complete", "--lease-file", receipt, "--outcome", outcome)["state"] == outcome
    state = store.status(second["id"])
    assert bool(state["dependency_blockers"]) is (outcome != "completed")


@pytest.mark.parametrize("target_kind", ["existing", "directory", "missing-parent"])
def test_receipt_creation_failure_prevents_acquisition(cli, tmp_path, target_kind):
    database, call = cli
    store = Store(database)
    request = store.request("a", "do not acquire without receipt", RESOURCE)
    path = tmp_path / "protected.lease.json"
    if target_kind == "existing":
        path.write_text("preserve me")
    elif target_kind == "directory":
        path.mkdir()
    else:
        path = tmp_path / "absent" / "receipt.lease.json"
    call("acquire", "--request", request["id"], "--owner", "a", "--lease-file", path, code=1)
    assert store.status(request["id"])["state"] == "waiting"
    if target_kind == "existing":
        assert path.read_text() == "preserve me"


@pytest.mark.parametrize("ttl", [9, 3601])
def test_lease_bounds_preserve_state(cli, tmp_path, ttl):
    database, call = cli
    store = Store(database)
    request = store.request("a", "bounds", RESOURCE)
    call("acquire", "--request", request["id"], "--owner", "a", "--lease-file", tmp_path / "bad.lease.json", "--lease-seconds", ttl, code=1)
    assert store.status(request["id"])["state"] == "waiting"
    receipt = tmp_path / "valid.lease.json"
    call("acquire", "--request", request["id"], "--owner", "a", "--lease-file", receipt)
    before = store.status(request["id"])["deadline"]
    call("renew", "--lease-file", receipt, "--lease-seconds", ttl, code=1)
    assert store.status(request["id"])["deadline"] == before


def test_receipt_fsync_failure_retains_lease_and_never_starts(cli, tmp_path, monkeypatch):
    database, call = cli
    store = Store(database)
    request = store.request("a", "disk failure", RESOURCE)
    def fail(_fd):
        raise OSError("synthetic disk error")
    monkeypatch.setattr("coordinator.cli.os.fsync", fail)
    result = call("acquire", "--request", request["id"], "--owner", "a", "--lease-file", tmp_path / "failed.lease.json", code=1)
    assert "do not start work or acquire again" in result["error"]
    assert store.status(request["id"])["state"] == "leased"
    next_request = store.request("b", "must remain blocked", RESOURCE)
    assert store.acquire(next_request["id"], "b")["state"] == "waiting"


@pytest.mark.parametrize("change", [
    {"owner": "other"}, {"request_id": "missing"}, {"lease_token": "incorrect"},
    {"format": "coordinator-claim-v1"}, {"owner": []}, {"lease_token": ""}, {"extra": "unknown"},
    {"database": "relative.sqlite3"}, {"database": "bad\u0000path"},
])
def test_tampered_receipts_do_not_start_or_release(cli, tmp_path, change):
    database, call = cli
    store = Store(database)
    request, receipt, _ = acquire(store, call, tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload.update(change)
    receipt.write_text(json.dumps(payload), encoding="utf-8-sig")
    for command in ("begin", "renew", "complete"):
        call(command, "--lease-file", receipt, code=1)
    assert store.status(request["id"])["state"] == "leased"


def test_wrong_database_receipt_rejected(cli, tmp_path):
    database, call = cli
    store = Store(database)
    request, receipt, _ = acquire(store, call, tmp_path)
    payload = json.loads(receipt.read_text())
    payload["database"] = str(tmp_path / "different.sqlite3")
    receipt.write_text(json.dumps(payload))
    assert "different database" in call("begin", "--lease-file", receipt, code=1)["error"]
    assert store.status(request["id"])["state"] == "leased"


@pytest.mark.parametrize("contents", ["[]", "{bad", '{"format": NaN}', "x" * 65537],
                         ids=["non-object", "broken-json", "nan", "oversized"])
def test_invalid_receipt_is_structured_error(cli, tmp_path, contents):
    _, call = cli
    path = tmp_path / "invalid.lease.json"
    path.write_text(contents)
    assert call("begin", "--lease-file", path, code=1)["command_started"] is False


def test_expired_manual_lease_requires_explicit_reconciliation(cli, tmp_path, monkeypatch):
    database, call = cli
    now = [1000.0]
    store = Store(database, clock=lambda: now[0])
    monkeypatch.setattr("coordinator.cli.Store", lambda _path: store)
    request, receipt, _ = acquire(store, call, tmp_path)
    now[0] += 121
    for command in ("begin", "renew", "complete"):
        call(command, "--lease-file", receipt, code=1)
    assert store.status(request["id"])["state"] == "suspect"
    next_request = store.request("b", "wait for verification", RESOURCE)
    assert store.acquire(next_request["id"], "b")["state"] == "waiting"
    result = call("reconcile", "--request", request["id"], "--owner", "a", "--confirmed-stopped", "--note", "synthetic manual operation verified stopped")
    assert result["state"] == "failed"


@pytest.mark.parametrize("process_state", ["alive", "unknown"])
def test_bound_live_or_unknown_process_prevents_manual_release(cli, tmp_path, monkeypatch, process_state):
    database, call = cli
    store = Store(database, process_probe=lambda _process: process_state)
    monkeypatch.setattr("coordinator.cli.Store", lambda _path: store)
    request, receipt, _ = acquire(store, call, tmp_path)
    call("begin", "--lease-file", receipt)
    token = json.loads(receipt.read_text())["lease_token"]
    store.bind_processes(request["id"], "a", token, [{"pid": 12345, "created": 100, "executable": "synthetic"}])
    call("complete", "--lease-file", receipt, code=1)
    assert store.status(request["id"])["state"] == "running"


def test_manual_complete_cannot_bypass_managed_journal(cli, tmp_path, monkeypatch):
    database, call = cli
    store = Store(database)
    request, receipt, _ = acquire(store, call, tmp_path)
    call("begin", "--lease-file", receipt)
    token = json.loads(receipt.read_text())["lease_token"]
    monkeypatch.setattr("coordinator.operations.scope", lambda: {"synthetic": True})
    # This is a journal-policy test, not native Windows identity acquisition.
    # Stub both OS inputs so Linux exercises the same refusal assertions.
    monkeypatch.setattr("coordinator.reboot.machine_fingerprint", lambda: "synthetic-machine-hash")
    Operations(store).prepare(request["id"], "a", token, "synthetic-hash", {"pid": 12345, "created": 100, "executable": "synthetic"})
    with store.connection() as db:
        assert db.execute("SELECT machine_hash FROM managed_operation_hosts WHERE request_id=?", (request["id"],)).fetchone()[0] == "synthetic-machine-hash"
    for outcome in ("completed", "failed", "cancelled"):
        assert "Managed operation" in call("complete", "--lease-file", receipt, "--outcome", outcome, code=1)["error"]
    assert store.status(request["id"])["state"] == "running"


def test_independent_cli_processes_compete_without_duplicate_token_or_start(tmp_path):
    database = tmp_path / "separate-processes.sqlite3"
    store = Store(database)
    request = store.request("a", "one manual owner", RESOURCE)
    def call(path):
        return subprocess.run([sys.executable, "-B", str(ENTRY), "--db", str(database), "acquire", "--request", request["id"], "--owner", "a", "--lease-file", str(path)],
                              capture_output=True, encoding="utf-8", timeout=15)
    paths = [tmp_path / (str(i) + ".lease.json") for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, paths))
    assert sorted(result.returncode for result in results) == [0, 1]
    winner = next(path for path, result in zip(paths, results) if result.returncode == 0)
    token = json.loads(winner.read_text())["lease_token"]
    assert all(token not in result.stdout + result.stderr for result in results)
    for command in ("begin", "renew", "complete"):
        result = subprocess.run([sys.executable, "-B", str(ENTRY), "--db", str(database), command, "--lease-file", str(winner)],
                                capture_output=True, encoding="utf-8", timeout=15)
        assert result.returncode == 0, result.stderr
        assert token not in result.stdout + result.stderr
    assert store.status(request["id"])["state"] == "completed"
