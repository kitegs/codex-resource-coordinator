import hashlib
import json
import sqlite3

import pytest

from coordinator.board import Board
from coordinator import __version__
from coordinator.store import CoordinationError, Store


RESOURCE = [{"key": "shared:output", "mode": "exclusive"}]


def test_v1_database_upgrade_preserves_existing_reservation_and_events(tmp_path):
    path = tmp_path / "v1.sqlite3"
    token = "synthetic-existing-lease"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE requests (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL, purpose TEXT NOT NULL,
                resources TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL,
                deadline REAL, token_hash TEXT, processes TEXT NOT NULL DEFAULT '[]',
                idempotency TEXT, result TEXT,
                UNIQUE(owner, idempotency)
            );
            CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL, at REAL NOT NULL, event TEXT NOT NULL
            );
            PRAGMA user_version=1;
        """)
        db.execute("INSERT INTO requests(id,owner,purpose,resources,state,created,updated,deadline,token_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                   ("existing", "a", "existing lease", json.dumps(RESOURCE), "leased", 10, 10, 200, hashlib.sha256(token.encode()).hexdigest()))
        db.execute("INSERT INTO events(request_id,at,event) VALUES(?,?,?)", ("existing", 10, "leased"))
    store = Store(path, clock=lambda: 100.0)
    board = Board(store)
    board.register("a", "A", "upgrade-test")
    existing = store.status("existing")
    assert existing["state"] == "leased" and existing["depends_on"] == []
    later = store.request("b", "wait for old lease", RESOURCE)
    assert store.acquire(later["id"], "b")["state"] == "waiting"
    store.finish("existing", "a", token)
    assert store.acquire(later["id"], "b")["state"] == "leased"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT event FROM events WHERE sequence=1").fetchone()[0] == "leased"
    assert Board(Store(path, clock=lambda: 100.0)).view()["chats"][0]["chat_id"] == "a"


def test_dependencies_do_not_deadlock_an_earlier_dependent(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    integration = store.request("integrator", "integrate after build", RESOURCE)
    build = store.request("builder", "prerequisite build", RESOURCE)
    store.set_dependencies(integration["id"], "integrator", [build["id"]])
    assert store.acquire(integration["id"], "integrator")["dependency_blockers"][0]["id"] == build["id"]
    active = store.acquire(build["id"], "builder")
    assert active["state"] == "leased"
    store.finish(active["id"], "builder", active["lease_token"])
    assert store.acquire(integration["id"], "integrator")["state"] == "leased"


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_failed_or_cancelled_dependency_is_not_success(tmp_path, outcome):
    store = Store(tmp_path / "state.sqlite3")
    first = store.request("a", "prerequisite", RESOURCE)
    later = store.request("b", "dependent", RESOURCE, depends_on=[first["id"]])
    if outcome == "cancelled":
        store.cancel(first["id"], "a")
    else:
        active = store.acquire(first["id"], "a")
        store.finish(first["id"], "a", active["lease_token"], "failed")
    result = store.acquire(later["id"], "b")
    assert result["state"] == "waiting"
    assert result["dependency_blockers"][0]["state"] == outcome


def test_cycle_rejected_and_previous_dependencies_preserved(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    a = store.request("a", "a", RESOURCE)
    b = store.request("b", "b", RESOURCE, depends_on=[a["id"]])
    with pytest.raises(CoordinationError, match="cycle"):
        store.set_dependencies(a["id"], "a", [b["id"]])
    assert store.status(a["id"])["depends_on"] == []
    assert store.status(b["id"])["depends_on"] == [a["id"]]


def test_unknown_dependency_rolls_back_new_request(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    with pytest.raises(CoordinationError, match="Unknown request"):
        store.request("a", "bad dependency", RESOURCE, depends_on=["missing"])
    assert store.status(include_finished=True) == []


def test_host_completed_never_marks_work_accepted_and_staleness_is_visible(tmp_path):
    now = [100.0]
    store = Store(tmp_path / "state.sqlite3", clock=lambda: now[0])
    board = Board(store)
    board.register("a", "Compiler", "demo")
    board.report("a", "a", "working", "runtime tests remain", 0)
    snapshot = {"polls": [{"thread": {"id": "a", "hostId": "local", "status": {"type": "idle", "activeFlags": []}}, "latestTurn": {"id": "t1", "status": "completed"}, "latestAssistantMessage": {"text": "Build ended"}}]}
    board.ingest(snapshot, 100.0)
    item = board.view()["chats"][0]
    assert item["turn_state"] == "completed" and item["work_state"] == "working"
    assert item["host_fresh"] and item["work_fresh"]
    now[0] = 400.0
    item = board.view()["chats"][0]
    assert not item["host_fresh"] and not item["work_fresh"]


def test_old_snapshot_cannot_overwrite_new_state_or_create_duplicate_notice(tmp_path):
    store = Store(tmp_path / "state.sqlite3", clock=lambda: 200.0)
    board = Board(store)
    board.register("a", "A", "demo")
    board.observe("a", "local", "active", "inProgress", "new", "new", 150, "codex.wait_threads")
    cursor = board.view()["latest_cursor"]
    ignored = board.observe("a", "local", "idle", "completed", "old", "old", 100, "codex.wait_threads")
    assert ignored["ignored"] == "older_or_duplicate_snapshot"
    assert board.view()["chats"][0]["turn_id"] == "new"
    assert board.view()["latest_cursor"] == cursor
    board.observe("a", "local", "active", "inProgress", "new", "new progress text", 160, "codex.wait_threads")
    assert board.view()["latest_cursor"] == cursor


def test_self_reports_use_revision_checks_and_keep_version_context(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "demo")
    evidence = {"base_commit": "abc", "dirty": True, "write_scope": ["Source/Example.cpp"], "evidence": [{"kind": "build", "status": "passed", "revision": "abc+local", "reference": "reports/build.log"}]}
    board.report("a", "a", "working", "build passed; runtime not verified", 0, worktree="isolated", commit_id="abc", provenance=evidence)
    with pytest.raises(CoordinationError, match="revision"):
        board.report("a", "a", "finished", "old report", 0)
    with pytest.raises(CoordinationError, match="own"):
        board.report("a", "b", "finished", "claim another chat finished", 1)
    board.report("a", "a", "ready_for_review", "review next", 1)
    item = board.view()["chats"][0]
    assert item["provenance"] == evidence
    assert item["commit_id"] == "abc" and item["worktree"] == "isolated"
    assert item["evidence_verified_by_plugin"] is False
    assert item["client_version"] == __version__ and item["adoption"] == "self_reported"


def test_change_ack_survives_client_restart_and_no_change_is_quiet(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "demo")
    changes = board.changes("a")
    board.acknowledge("a", changes["next_cursor"])
    resumed = Board(Store(store.path))
    assert resumed.changes("a")["changes"] == []
    resumed.report("a", "a", "needs_input", "permission decision needed", 0)
    notices = resumed.changes("a")["changes"]
    assert len(notices) == 1 and notices[0]["attention"] == 1


def test_board_suggests_runnable_prerequisite_and_preserves_cross_group_blocker(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "group-a")
    board.register("b", "B", "group-b")
    dependent = store.request("a", "dependent", RESOURCE)
    prerequisite = store.request("b", "prerequisite", RESOURCE)
    store.set_dependencies(dependent["id"], "a", [prerequisite["id"]])
    assert board.view()["ready_order"] == [prerequisite["id"]]
    group = board.view("group-a")
    assert group["ready_order"] == []
    assert group["queue"][0]["dependency_blockers"][0]["id"] == prerequisite["id"]


def test_import_rejects_unregistered_chat_and_does_not_store_transcripts(tmp_path):
    store = Store(tmp_path / "state.sqlite3", clock=lambda: 100.0)
    board = Board(store)
    raw = {"thread": {"id": "a", "hostId": "local", "status": {"type": "idle"}}, "turns": [{"id": "t", "status": "completed", "items": [{"text": "synthetic transcript must not be copied"}]}]}
    with pytest.raises(CoordinationError, match="not registered"):
        board.ingest(raw, 100.0)
    board.register("a", "A", "demo")
    board.ingest(raw, 100.0)
    with sqlite3.connect(store.path) as db:
        stored = str(db.execute("SELECT * FROM chats").fetchall())
    assert "synthetic transcript must not be copied" not in stored
    assert board.view()["chats"][0]["adoption"] == "observed_only"


def test_project_board_keeps_resource_blocker_from_another_group(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "one")
    board.register("b", "B", "two")
    first = store.request("b", "other group owns output", RESOURCE)
    store.acquire(first["id"], "b")
    waiting = store.request("a", "needs shared output", RESOURCE)
    view = board.view("one")
    assert len(view["queue"]) == 1 and view["queue"][0]["id"] == waiting["id"]
    assert view["queue"][0]["resource_blocker_details"] == [{"id": first["id"], "owner": "b", "purpose": "other group owns output", "state": "leased"}]
    assert view["ready_order"] == []


def test_unrelated_project_updates_are_filtered_but_cross_group_resource_release_is_visible(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "one")
    board.register("b", "B", "two")
    initial = board.changes("a")
    board.acknowledge("a", initial["next_cursor"])
    board.report("b", "b", "working", "unrelated coding", 0)
    quiet = board.changes("a")
    assert quiet["changes"] == []
    board.acknowledge("a", quiet["next_cursor"])
    active_request = store.request("b", "shared machine work", RESOURCE)
    active = store.acquire(active_request["id"], "b")
    store.request("a", "needs that output", RESOURCE)
    store.finish(active_request["id"], "b", active["lease_token"])
    relevant = board.changes("a")["changes"]
    assert len(relevant) == 1 and relevant[0]["subject"] == active_request["id"]
