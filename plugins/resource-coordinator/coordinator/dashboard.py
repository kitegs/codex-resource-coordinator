"""Read-only local panel. No host API access, database initialization or mutations."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from . import __version__
from .board import Board
from .store import CoordinationError, Store

ASSETS = Path(__file__).resolve().parent / "panel"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/panel.css": ("panel.css", "text/css; charset=utf-8"), "/panel.js": ("panel.js", "text/javascript; charset=utf-8")}


class ReadOnlyStore(Store):
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute() or str(self.path).startswith(("\\\\", "//")) or self.path.is_symlink():
            raise CoordinationError("Panel database must be an absolute local non-symlink path")
        self.clock = time.time

    @contextmanager
    def connection(self, *, write=False):
        if write:
            raise CoordinationError("Panel database is read-only")
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            yield db
        finally:
            db.close()


class SnapshotReader:
    def __init__(self, path, stale_after=180):
        if not isinstance(stale_after, int) or not 10 <= stale_after <= 86400:
            raise CoordinationError("Freshness threshold must be 10..86400 seconds")
        self.store, self.stale_after = ReadOnlyStore(path), stale_after

    def snapshot(self):
        base = {"version": __version__, "captured_at": time.time(), "read_only": True, "native_monitor": False, "stale_after": self.stale_after}
        if not self.store.path.exists():
            return {**base, "available": False, "reason": "not_initialized"}
        try:
            with self.store.connection() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version != 2 or not {"chats", "requests", "request_dependencies", "coordination_changes"}.issubset(tables):
                return {**base, "available": False, "reason": "requires_coordinator_initialization"}
            return {**base, "available": True, **Board(self.store, initialize=False).view(stale_after=self.stale_after)}
        except (sqlite3.Error, OSError):
            return {**base, "available": False, "reason": "database_unavailable"}


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path, port=0, stale_after=180):
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise CoordinationError("Invalid loopback port")
        self.reader = SnapshotReader(path, stale_after)
        self.token = secrets.token_urlsafe(32)
        self.last_access = time.monotonic()
        self.access_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), PanelHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def local_url(self):
        return self.origin + "/#key=" + self.token


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log access tokens, private paths, or chat summaries.

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def _send(self, status, body, content_type="application/json; charset=utf-8", head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _dispatch(self, head=False):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://") or self.headers.get("Origin") not in (None, self.server.origin):
            return self._send(403, b'{"error":"origin_rejected"}', head=head)
        path = urlsplit(self.path).path
        if path in STATIC:
            name, mime = STATIC[path]
            return self._send(200, (ASSETS / name).read_bytes(), mime, head)
        if path == "/healthz":
            return self._send(200, b'{"ok":true,"read_only":true}', head=head)
        if path == "/api/board":
            token = self.headers.get("X-Coord-Token", "")
            if not secrets.compare_digest(token.encode(), self.server.token.encode()):
                return self._send(403, b'{"error":"token_required"}', head=head)
            with self.server.access_lock:
                self.server.last_access = time.monotonic()
            result = self.server.reader.snapshot()
            return self._send(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"), head=head)
        self._send(404, b'{"error":"not_found"}', head=head)

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch(True)

    def do_POST(self):
        self._send(405, b'{"error":"read_only"}')

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_POST


def serve(path, port=0, stale_after=180, idle_timeout=1800):
    if not isinstance(idle_timeout, int) or not 60 <= idle_timeout <= 86400:
        raise CoordinationError("Panel idle timeout must be 60..86400 seconds")
    with PanelServer(path, port, stale_after) as server:
        server.timeout = 1
        print(json.dumps({"local_url": server.local_url, "read_only": True, "native_monitor": False, "idle_timeout": idle_timeout}), flush=True)
        try:
            while time.monotonic() - server.last_access < idle_timeout:
                server.handle_request()
        except KeyboardInterrupt:
            pass
    return 0
