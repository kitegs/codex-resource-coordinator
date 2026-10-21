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
        else:
            store = Store(args.db)
            if args.action == "status":
                result = store.status(args.request, include_finished=args.all)
            elif args.action == "request":
                result = store.request(args.owner, args.purpose, json.loads(args.resources), args.idempotency_key)
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
