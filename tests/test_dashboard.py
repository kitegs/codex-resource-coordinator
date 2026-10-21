import http.client
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from coordinator.board import Board
from coordinator.handoff import Handoffs
from coordinator.dashboard import ASSETS, PanelServer, ReadOnlyStore, SnapshotReader
from coordinator.store import CoordinationError, Store


def test_missing_database_is_not_created_by_panel(tmp_path):
    path = tmp_path / "missing-directory" / "state.sqlite3"
    snapshot = SnapshotReader(path).snapshot()
    assert snapshot["available"] is False and snapshot["reason"] == "not_initialized"
    assert not path.parent.exists()


def test_panel_never_migrates_older_database(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE sentinel(value TEXT); PRAGMA user_version=1;")
    assert SnapshotReader(path).snapshot()["reason"] == "requires_coordinator_initialization"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("sentinel",)]


def test_read_only_connection_rejects_writes(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    readonly = ReadOnlyStore(store.path)
    with pytest.raises(CoordinationError, match="read-only"):
        with readonly.connection(write=True):
            pass
    with readonly.connection() as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM requests")


def test_panel_snapshot_preserves_reservations_and_reads_updated_work(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    board = Board(store)
    board.register("a", "A", "test")
    request = store.request("a", "preserve reservation", [{"key": "generic:output", "mode": "exclusive"}])
    lease = store.acquire(request["id"], "a")
    before = store.status(request["id"])
    reader = SnapshotReader(store.path)
    first = reader.snapshot()
    assert first["available"] and first["read_only"] and first["native_monitor"] is False
    assert first["queue"][0]["state"] == "leased" and first["chats"][0]["work_state"] == "unknown"
    board.report("a", "a", "working", "new milestone", 0)
    assert reader.snapshot()["chats"][0]["summary"] == "new milestone"
    assert store.status(request["id"]) == before
    assert lease["lease_token"] not in json.dumps(first)


def test_panel_shows_delivery_uncertainty_without_mutating_or_exposing_tokens(tmp_path):
    now = [100.0]
    store = Store(tmp_path / "notices.sqlite3", clock=lambda: now[0])
    board, handoffs = Board(store), Handoffs(store)
    for chat in ("a", "b"):
        board.register(chat, chat, "test")
        handoffs.configure(chat, True, "synthetic explicit scope")
    resources = [{"key":"test:output","mode":"exclusive"}]
    first = store.request("a", "first", resources)
    target = store.request("b", "next", resources)
    lease = store.acquire(first["id"], "a")
    store.finish(first["id"], "a", lease["lease_token"])
    notice = handoffs.listing("a")["notices"][0]
    claim = handoffs.claim(notice["id"], "a")
    reader = SnapshotReader(store.path)
    reader.store.clock = lambda: 250.0
    snapshot = reader.snapshot()
    shown = snapshot["release_notices"][0]
    assert shown["recipient"] == "b" and shown["state"] == "uncertain"
    assert target["id"] == shown["target_request"]
    assert claim["claim_token"] not in json.dumps(snapshot) and "claim_hash" not in json.dumps(snapshot)
    with store.connection() as db:
        assert db.execute("SELECT state FROM release_notices").fetchone()[0] == "sending"
    assert store.status(target["id"])["state"] == "waiting"


def test_panel_reads_v03_database_without_creating_optional_notice_tables(tmp_path):
    store = Store(tmp_path / "old-v2.sqlite3")
    Board(store)
    with store.connection() as db:
        db.execute("DROP TABLE release_notices")
        db.execute("DROP TABLE handoff_routes")
    snapshot = SnapshotReader(store.path).snapshot()
    assert snapshot["available"] and snapshot["release_notices"] == []
    with store.connection() as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='release_notices'").fetchone() is None


@pytest.fixture
def panel(tmp_path):
    store = Store(tmp_path / "panel.sqlite3")
    Board(store).register("a", "<img src=x onerror=alert(1)>", "test")
    server = PanelServer(store.path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()


def request(server, path="/api/board", method="GET", headers=None):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        client.request(method, path, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_real_http_panel_requires_token_and_rejects_foreign_origin(panel):
    assert panel.server_address[0] == "127.0.0.1"
    assert request(panel)[0] == 403
    headers = {"X-Coord-Token": panel.token}
    status, response_headers, body = request(panel, headers=headers)
    assert status == 200 and json.loads(body)["chats"][0]["label"].startswith("<img")
    assert panel.token.encode() not in body and "no-store" in response_headers["Cache-Control"]
    assert "Access-Control-Allow-Origin" not in response_headers
    assert request(panel, headers={**headers, "Origin": "https://untrusted.example"})[0] == 403
    assert request(panel, headers={**headers, "Host": "untrusted.example"})[0] == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_panel_has_no_mutation_routes(panel, method):
    assert request(panel, method=method, headers={"X-Coord-Token": panel.token})[0] == 405


def test_panel_static_assets_csp_and_no_file_serving(panel):
    for path in ("/", "/panel.js", "/panel.css"):
        status, headers, body = request(panel, path)
        assert status == 200 and body
        assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert request(panel, "/../coordinator/store.py")[0] == 404
    assert request(panel, "/api/board?token=" + panel.token)[0] == 403
    assert request(panel, "/healthz")[0] == 200
    javascript = (ASSETS / "panel.js").read_text(encoding="utf-8")
    assert "innerHTML" not in javascript and "textContent" in javascript
