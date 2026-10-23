"""Synthetic boot records exercise release policy; native probe only READS this boot."""
import copy
import json
import os

import pytest

import coordinator.reboot as reboot
from coordinator.board import Board
from coordinator.cli import main
from coordinator.handoff import Handoffs
from coordinator.store import CoordinationError, Store


RESOURCE = [{"key": "test:reboot-resource", "mode": "exclusive"}]
SCOPE = {"machine": "synthetic-host", "session": 1, "boot": 2000}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3", clock=lambda: 3000, process_probe=lambda _: "gone")
    request = store.request("owner", "synthetic previous-boot job", RESOURCE)
    lease = store.acquire(request["id"], "owner")
    store.start(request["id"], "owner", lease["lease_token"])
    with store.connection(write=True) as db:
        db.execute("UPDATE requests SET created=1100,updated=1200 WHERE id=?", (request["id"],))
        db.execute("INSERT INTO managed_operations(request_id,operation_id,command_hash,job_name,scope,monitor,monitor_hash,phase,created,updated,root,active_processes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (request["id"], "synthetic-operation", "digest", "not-a-real-job",
                    json.dumps({**SCOPE, "boot": 1000}), json.dumps({"pid": 111, "created": 1100}),
                    "not-a-real-token", "monitoring", 1100, 1200,
                    json.dumps({"pid": 112, "created": 1101}), 5))
        db.execute("INSERT INTO managed_operation_hosts VALUES(?,?)", (request["id"], "synthetic-fingerprint"))
    evidence = {"scope": dict(SCOPE), "machine_hash": "synthetic-fingerprint", "os_boot": 2000,
                "events": [{"record_id": "10", "start": 1000, "start_utc": "old-boot"},
                           {"record_id": "20", "start": 2000, "start_utc": "new-boot"}]}
    monkeypatch.setattr(reboot, "collect_boot_evidence", lambda: copy.deepcopy(evidence))
    monkeypatch.setattr(reboot, "scope", lambda: dict(SCOPE))
    monkeypatch.setattr(reboot, "machine_fingerprint", lambda: "synthetic-fingerprint")
    return store, request, lease, evidence


def perform(store, request, **kwargs):
    return reboot.recover_after_reboot(store, request["id"], "owner", confirmed_reboot=True,
        confirmed_same_machine=True, note="Synthetic authorized recovery; no real processes", **kwargs)


def assert_blocking(store, request):
    assert store.status(request["id"])["state"] == "running"
    assert store.status(request["id"])["operation"]["result"] is None
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_reboot_recoveries").fetchone()[0] == 0


def test_verified_reboot_is_unknown_not_success_and_preserves_dependency(setup):
    store, request, lease, _ = setup
    dependent = store.request("dependent", "needs actual success", RESOURCE, depends_on=[request["id"]])
    independent = store.request("next", "independent work", RESOURCE)
    assert store.acquire(independent["id"], "next")["state"] == "waiting"
    result = perform(store, request)
    assert result["state"] == "failed" and result["result"] == "managed:unknown:verified_reboot"
    assert result["operation"]["result"] == "unknown"
    assert result["operation"]["error"] == "interrupted_by_verified_reboot"
    assert result["operation"]["active_processes"] == 0
    assert result["resources_released"] and not result["command_started"] and not result["command_restarted"]
    assert store.acquire(dependent["id"], "dependent")["dependency_blockers"]
    assert store.acquire(independent["id"], "next")["state"] == "leased"
    public = json.dumps(result)
    assert lease["lease_token"] not in public and "synthetic-fingerprint" not in public
    with pytest.raises(CoordinationError):
        store.finish(request["id"], "owner", lease["lease_token"])
    with pytest.raises(CoordinationError, match="no longer active"):
        perform(store, request)
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM managed_reboot_recoveries").fetchone()[0] == 1


def test_dry_run_makes_no_recovery_or_release(setup):
    store, request, _, _ = setup
    result = reboot.recover_after_reboot(store, request["id"], "owner", check_only=True)
    assert result["eligible"] and result["check_only"] and not result["resources_released"]
    assert_blocking(store, request)


@pytest.mark.parametrize("flags", [{}, {"confirmed_reboot": True}, {"confirmed_same_machine": True},
                                  {"confirmed_reboot": 1, "confirmed_same_machine": True}])
def test_explicit_confirmations_required(setup, flags):
    store, request, _, _ = setup
    with pytest.raises(CoordinationError, match="confirmations"):
        reboot.recover_after_reboot(store, request["id"], "owner", note="synthetic", **flags)
    assert_blocking(store, request)


def test_wrong_owner_does_not_even_query_boot(setup, monkeypatch):
    store, request, _, _ = setup
    monkeypatch.setattr(reboot, "collect_boot_evidence", lambda: pytest.fail("owner must be checked first"))
    with pytest.raises(CoordinationError, match="Owner"):
        reboot.recover_after_reboot(store, request["id"], "other", check_only=True)
    assert_blocking(store, request)


@pytest.mark.parametrize("change", ["same_boot", "session_only", "other_machine", "other_fingerprint",
    "clock_jump", "missing_old_event", "missing_new_event", "reverse_records"])
def test_incomplete_or_conflicting_boot_evidence_stays_blocked(setup, change):
    store, request, _, evidence = setup
    if change in ("same_boot", "session_only"):
        evidence["scope"]["boot"] = evidence["os_boot"] = 1000
        if change == "session_only":
            evidence["scope"]["session"] = 2
    elif change == "other_machine":
        evidence["scope"]["machine"] = "different"
    elif change == "other_fingerprint":
        evidence["machine_hash"] = "different"
    elif change == "clock_jump":
        evidence["scope"]["boot"] = 2005
    elif change == "missing_old_event":
        evidence["events"].pop(0)
    elif change == "missing_new_event":
        evidence["events"].pop()
    else:
        evidence["events"][1]["record_id"] = "9"
    with pytest.raises(CoordinationError):
        perform(store, request)
    assert_blocking(store, request)


@pytest.mark.parametrize("state", ["alive", "unknown"])
def test_live_or_access_denied_identity_cannot_be_recovered(setup, state):
    store, request, _, _ = setup
    store.process_probe = lambda _: state
    with pytest.raises(CoordinationError, match="alive or unverifiable"):
        perform(store, request)
    assert_blocking(store, request)


@pytest.mark.parametrize("timestamp", [2001, 1999, 900, float("nan"), True])
def test_operation_must_be_inside_old_boot(setup, timestamp):
    store, request, _, _ = setup
    with store.connection(write=True) as db:
        db.execute("UPDATE managed_operations SET root=? WHERE request_id=?",
                   (json.dumps({"pid": 112, "created": timestamp}), request["id"]))
    with pytest.raises(CoordinationError, match="wholly before"):
        perform(store, request)
    assert_blocking(store, request)


def test_pre_052_operation_needs_explicit_same_machine_attestation(setup):
    store, request, _, _ = setup
    with store.connection(write=True) as db:
        db.execute("DELETE FROM managed_operation_hosts WHERE request_id=?", (request["id"],))
    result = reboot.recover_after_reboot(store, request["id"], "owner", check_only=True)
    assert result["proof"]["legacy_host_binding"]
    assert perform(store, request)["state"] == "failed"
    with store.connection() as db:
        audit = json.loads(db.execute("SELECT evidence FROM managed_reboot_recoveries").fetchone()[0])
    assert audit["legacy_host_binding"] and audit["owner"] == "owner"


def test_monitor_checkpoint_during_probe_refuses_stale_snapshot(setup, monkeypatch):
    store, request, _, evidence = setup
    def raced():
        with store.connection(write=True) as db:
            db.execute("UPDATE managed_operations SET updated=1201 WHERE request_id=?", (request["id"],))
        return evidence
    monkeypatch.setattr(reboot, "collect_boot_evidence", raced)
    with pytest.raises(CoordinationError, match="changed during"):
        perform(store, request)
    assert_blocking(store, request)


def test_transaction_rolls_back_release_and_audit_on_failure(setup, monkeypatch):
    store, request, _, _ = setup
    def fail(*_args):
        raise OSError("synthetic outbox write error")
    monkeypatch.setattr(Handoffs, "enqueue_after_release", fail)
    with pytest.raises(OSError, match="outbox"):
        perform(store, request)
    assert_blocking(store, request)


def test_release_uses_existing_outbox_without_starting_waiter(setup):
    store, request, _, _ = setup
    board, handoffs = Board(store), Handoffs(store)
    for name in ("owner", "next"):
        board.register(name, name, "synthetic")
        handoffs.configure(name, True, "synthetic authorization; never send")
    following = store.request("next", "next work", RESOURCE)
    assert perform(store, request)["release_handoff"]["pending_count"] == 1
    assert store.status(following["id"])["state"] == "waiting"
    assert handoffs.listing("owner")["notices"][0]["state"] == "pending"


def test_cli_check_and_confirmation_gate(setup, capsys):
    store, request, _, _ = setup
    base = ["--db", str(store.path), "recover-reboot", "--request", request["id"], "--owner", "owner"]
    assert main(base + ["--check-only"]) == 0
    assert json.loads(capsys.readouterr().out)["check_only"]
    assert main(base) == 1
    assert json.loads(capsys.readouterr().err)["command_started"] is False
    assert_blocking(store, request)


def test_os_probe_failure_keeps_the_reservation(setup, monkeypatch):
    store, request, _, _ = setup
    def denied():
        raise CoordinationError("Cannot verify Windows boot history; retain resources")
    monkeypatch.setattr(reboot, "collect_boot_evidence", denied)
    with pytest.raises(CoordinationError, match="boot history"):
        perform(store, request)
    assert_blocking(store, request)


def test_root_exit_zero_does_not_prove_children_succeeded(setup):
    store, request, _, _ = setup
    with store.connection(write=True) as db:
        db.execute("UPDATE managed_operations SET root_exit=0 WHERE request_id=?", (request["id"],))
    result = perform(store, request)
    assert result["operation"]["root_exit"] == 0
    assert result["operation"]["result"] == "unknown" and result["state"] == "failed"


def test_scope_change_during_transaction_refuses_release(setup, monkeypatch):
    store, request, _, _ = setup
    monkeypatch.setattr(reboot, "scope", lambda: {**SCOPE, "session": 9})
    with pytest.raises(CoordinationError, match="scope changed"):
        perform(store, request)
    assert_blocking(store, request)


def test_bad_note_and_unmanaged_job_never_use_this_route(setup):
    store, request, _, _ = setup
    with pytest.raises(CoordinationError, match="note"):
        reboot.recover_after_reboot(store, request["id"], "owner", confirmed_reboot=True,
                                   confirmed_same_machine=True, note="bad\nnote")
    unmanaged = store.request("owner", "not a contained job", RESOURCE)
    with pytest.raises(CoordinationError, match="unmanaged"):
        perform(store, unmanaged)
    assert_blocking(store, request)


@pytest.mark.skipif(os.name != "nt", reason="read-only Windows evidence probe")
def test_native_boot_probe_is_structured_and_contains_no_raw_machine_guid():
    evidence = reboot.collect_boot_evidence()
    assert len(evidence["machine_hash"]) == 64
    assert abs(evidence["scope"]["boot"] - evidence["os_boot"]) <= 2
    assert any(abs(e["start"] - evidence["os_boot"]) <= 2 for e in evidence["events"])
    assert all(e["record_id"].isdigit() for e in evidence["events"])
