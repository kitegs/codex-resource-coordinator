import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .profiles import ue_plan
from .store import CoordinationError, Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cooperative resource queue; reservation is not execution permission.")
    parser.add_argument("--db", type=Path, help="Absolute LOCAL database path; all participants must use the same one")
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser("status")
    p.add_argument("--request")
    p.add_argument("--all", action="store_true")
    p = commands.add_parser("request")
    p.add_argument("--owner", required=True)
    p.add_argument("--purpose", required=True)
    p.add_argument("--resources", required=True, help='JSON list: [{"key":"build:project-a","mode":"exclusive"}]')
    p.add_argument("--idempotency-key")
    p.add_argument("--depends-on", default="[]", help="JSON list of prerequisite request IDs")
    p = commands.add_parser("board")
    p.add_argument("--project-key")
    p.add_argument("--stale-after", type=int, default=180)
    p = commands.add_parser("panel", help="Serve a read-only loopback panel; does not monitor native chats")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--stale-after", type=int, default=180)
    p.add_argument("--idle-timeout", type=int, default=1800)
    p = commands.add_parser("ingest-status")
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--observed-at", type=float, required=True)
    p = commands.add_parser("plan-ue")
    p.add_argument("--project", required=True)
    p.add_argument("--operation", required=True, choices=["compile-only", "cold-build", "integrate", "editor-test", "performance"])
    for name in ("cancel", "reconcile", "run"):
        p = commands.add_parser(name)
        p.add_argument("--request", required=True)
        p.add_argument("--owner", required=True)
        if name == "reconcile":
            p.add_argument("--confirmed-stopped", action="store_true")
            p.add_argument("--note", required=True)
        elif name == "run":
            p.add_argument("--cwd")
            p.add_argument("--lease-seconds", type=int, default=120)
            p.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan-ue":
            result = ue_plan(args.project, args.operation)
        elif args.action == "panel":
            from .dashboard import serve
            from .store import default_db
            return serve(args.db or default_db(), args.port, args.stale_after, args.idle_timeout)
        else:
            store = Store(args.db)
            if args.action in ("board", "ingest-status"):
                from .board import Board
                board = Board(store)
                result = board.view(args.project_key, args.stale_after) if args.action == "board" else board.ingest(json.loads(args.snapshot.read_text(encoding="utf-8")), args.observed_at)
            elif args.action == "status":
                result = store.status(args.request, include_finished=args.all)
            elif args.action == "request":
                result = store.request(args.owner, args.purpose, json.loads(args.resources), args.idempotency_key, json.loads(args.depends_on))
            elif args.action == "cancel":
                result = store.cancel(args.request, args.owner)
            elif args.action == "reconcile":
                result = store.reconcile(args.request, args.owner, args.confirmed_stopped, args.note)
            else:
                from .runner import run
                command = args.command[1:] if args.command[:1] == ["--"] else args.command
                return run(store, args.request, args.owner, command, cwd=args.cwd, lease_seconds=args.lease_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (CoordinationError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error), "command_started": False if args.action != "run" else "consult_request_status"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
