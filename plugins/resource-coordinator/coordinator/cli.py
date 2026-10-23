import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from .profiles import ue_plan
from .store import CoordinationError, Store


def read_object(path):
    """UTF-8 JSON file or stdin; PowerShell's UTF-8 BOM is accepted."""
    if str(path) == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8-sig")
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8-sig")
    def invalid_constant(_value):
        raise CoordinationError("JSON must not contain NaN or Infinity")
    result = json.loads(text.lstrip("\ufeff"), parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise CoordinationError("Input must be a JSON object")
    return result


def report_status(board, path):
    payload = read_object(path)
    required = {"chat_id", "reporter", "work_state", "summary", "expected_revision"}
    allowed = required | {"next_step", "blockers", "worktree", "commit_id", "provenance"}
    if not required <= payload.keys() or payload.keys() - allowed:
        raise CoordinationError("Report requires chat_id, reporter, work_state, summary, expected_revision; unknown fields rejected")
    if any(not isinstance(payload[k], str) for k in required - {"expected_revision"}):
        raise CoordinationError("Report identity, state and summary must be strings")
    revision = payload["expected_revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise CoordinationError("expected_revision must be a non-negative integer")
    return board.report(**payload)


def claim_to_file(store, handoffs, notice_id, actor, path):
    """Reserve a NEW private receipt before claiming. Never print send tokens."""
    path = path.absolute()
    # Exclusive creation also rejects existing symlinks. Windows uses inherited
    # ACLs: the caller must choose a private directory, not a shared/public one.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as receipt:
        result = handoffs.claim(notice_id, actor)
        envelope = {"format": "coordinator-claim-v1", "database": str(store.path.resolve()),
                    "actor": actor, "claim": result}
        try:
            json.dump(envelope, receipt, ensure_ascii=False, indent=2)
            receipt.flush()
            os.fsync(receipt.fileno())
        except (OSError, UnicodeError) as error:
            raise CoordinationError("Claim receipt persistence failed; no message sent. Do not claim again; inspect notice state and retain this file") from error
    return {**{k:v for k,v in result.items() if k != "claim_token"},
            "claim_file": str(path), "token_redacted": True}


def acknowledge_file(store, handoffs, args):
    envelope = read_object(args.claim_file)
    if envelope.get("format") != "coordinator-claim-v1" or not isinstance(envelope.get("database"), str):
        raise CoordinationError("Invalid claim receipt format")
    if Path(envelope["database"]).resolve() != store.path.resolve():
        raise CoordinationError("Claim receipt belongs to a different database")
    claim = envelope.get("claim")
    if not isinstance(claim, dict) or claim.get("state") != "sending" or not isinstance(claim.get("id"), str) or not isinstance(claim.get("claim_token"), str) or not isinstance(envelope.get("actor"), str):
        raise CoordinationError("Receipt does not contain a valid claimed notice")
    return handoffs.acknowledge(claim["id"], envelope["actor"], claim["claim_token"],
        args.outcome, args.receipt_thread_id, args.result_code)


def acquire_to_file(store, request_id, owner, path, lease_seconds=120):
    """Reserve a new receipt BEFORE acquiring; a failed write never releases work."""
    path = path.absolute()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    acquired = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as receipt:
            result = store.acquire(request_id, owner, lease_seconds)
            acquired = result["state"] == "leased"
            envelope = {"format": "coordinator-lease-v1", "database": str(store.path.resolve()),
                        "request_id": request_id, "owner": owner}
            if acquired:
                envelope["lease_token"] = result["lease_token"]
            json.dump(envelope, receipt, ensure_ascii=False, indent=2)
            receipt.flush()
            os.fsync(receipt.fileno())
    except (OSError, UnicodeError) as error:
        if acquired:
            raise CoordinationError("Lease receipt persistence failed after acquisition; do not start work or acquire again. Retain the file, inspect status, and reconcile only after verifying work stopped") from error
        raise
    return {**{k: v for k, v in result.items() if k != "lease_token"},
            "lease_file": str(path), "lease_usable": acquired, "token_redacted": True}


def manual_lease(store, path):
    """Receipts are capabilities, not current status; Store checks every action."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise CoordinationError("Lease receipt must be a regular file of at most 64 KiB")
    envelope = read_object(path)
    fields = {"format", "database", "request_id", "owner", "lease_token"}
    if (set(envelope) != fields or envelope.get("format") != "coordinator-lease-v1"
            or any(not isinstance(envelope.get(k), str) or not envelope[k].strip()
                   for k in fields)):
        raise CoordinationError("Receipt does not contain a valid acquired lease; waiting and notice receipts cannot be used")
    database = envelope["database"]
    if any(ord(char) < 32 for char in database) or not Path(database).is_absolute():
        raise CoordinationError("Lease receipt database must be an absolute local path")
    if Path(database).resolve() != store.path.resolve():
        raise CoordinationError("Lease receipt belongs to a different database")
    return envelope["request_id"], envelope["owner"], envelope["lease_token"]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
    p = commands.add_parser("acquire", help="Acquire for a manual GUI/asset operation; does not operate the application")
    p.add_argument("--request", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--lease-file", required=True, type=Path, help="NEW file in a private directory; never print or commit it")
    p.add_argument("--lease-seconds", type=int, default=120)
    for name in ("begin", "renew", "complete"):
        p = commands.add_parser(name, help="Manual operation lifecycle using a private lease receipt, not a raw token")
        p.add_argument("--lease-file", required=True, type=Path)
        if name == "renew":
            p.add_argument("--lease-seconds", type=int, default=120)
        elif name == "complete":
            p.add_argument("--outcome", choices=("completed", "failed", "cancelled"), default="completed",
                           help="Declare the scoped operation saved/finished; cannot complete a managed run")
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
    p = commands.add_parser("register-chat", help="Register only a participating chat; does not send or resume it")
    p.add_argument("--chat", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--project-key", required=True)
    p.add_argument("--host", default="local")
    p = commands.add_parser("report-status", help="Self-report with an expected revision; no peer acceptance claims")
    p.add_argument("--input", required=True, help="UTF-8 JSON file, or - for stdin; same fields as report_development_status")
    p = commands.add_parser("changes", help="Read relevant changes; an empty result means stay quiet")
    p.add_argument("--observer", required=True)
    p.add_argument("--after-cursor", type=int)
    p.add_argument("--limit", type=int, default=50)
    p = commands.add_parser("ack-changes")
    p.add_argument("--observer", required=True)
    p.add_argument("--cursor", required=True, type=int)
    p = commands.add_parser("set-dependencies")
    p.add_argument("--request", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--depends-on", required=True, help="JSON list of prerequisite request IDs")
    p = commands.add_parser("notifications", help="Durable outbox; NEVER sends a host message or wakes a chat itself")
    notices = p.add_subparsers(dest="notice_action", required=True)
    p = notices.add_parser("configure")
    p.add_argument("--chat", required=True)
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--enable", action="store_true")
    scope.add_argument("--disable", action="store_true")
    p.add_argument("--authorization-reference", default="")
    p = notices.add_parser("list")
    p.add_argument("--actor", required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=8)
    for name in ("claim", "retry", "archive"):
        p = notices.add_parser(name)
        p.add_argument("--notice", required=True)
        p.add_argument("--actor", required=True)
        if name == "claim":
            p.add_argument("--claim-file", required=True, type=Path, help="NEW file in a private directory; secret stays out of stdout/argv")
        elif name == "retry":
            p.add_argument("--confirmed-not-sent", action="store_true")
    p = notices.add_parser("ack", help="Record actual host result using the private claim file; does not send")
    p.add_argument("--claim-file", required=True, type=Path)
    p.add_argument("--outcome", required=True, choices=("delivered", "not_sent", "uncertain"))
    p.add_argument("--receipt-thread-id")
    p.add_argument("--result-code", default="", choices=("", "tool_unavailable", "approval_denied", "definitive_rejection", "transport_uncertain"))
    p = commands.add_parser("plan-ue")
    p.add_argument("--project", required=True)
    p.add_argument("--operation", required=True, choices=["compile-only", "cold-build", "integrate", "editor-test", "performance"])
    for name in ("cancel", "reconcile", "run", "recover", "watch"):
        p = commands.add_parser(name)
        p.add_argument("--request", required=True)
        p.add_argument("--owner", required=True)
        if name == "reconcile":
            p.add_argument("--confirmed-stopped", action="store_true")
            p.add_argument("--note", required=True)
        elif name == "run":
            p.add_argument("--cwd")
            p.add_argument("--supervisor-worker", action="store_true", help=argparse.SUPPRESS)
            p.add_argument("--lease-seconds", type=int, default=120)
            p.add_argument("--tracking", choices=("contained", "observed"), default="contained", help="Windows 10+ contained jobs; observed explicitly opts out of automatic recovery")
            p.add_argument("command", nargs=argparse.REMAINDER)
        elif name in ("watch", "recover"):
            p.add_argument("--lease-seconds", type=int, default=120)
    p = commands.add_parser("recover-reboot", help="Verify OS reboot evidence; never start a command or terminate a process")
    p.add_argument("--request", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--confirmed-reboot", action="store_true")
    p.add_argument("--confirmed-same-machine", action="store_true", help="Explicit legacy host-binding attestation, not a security credential")
    p.add_argument("--note", default="")
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
            if args.action in ("board", "ingest-status", "register-chat", "report-status", "changes", "ack-changes"):
                from .board import Board
                board = Board(store)
                if args.action == "board":
                    result = board.view(args.project_key, args.stale_after)
                elif args.action == "ingest-status":
                    result = board.ingest(read_object(args.snapshot), args.observed_at)
                elif args.action == "register-chat":
                    result = board.register(args.chat, args.label, args.project_key, args.host)
                elif args.action == "report-status":
                    result = report_status(board, args.input)
                elif args.action == "changes":
                    result = board.changes(args.observer, args.after_cursor, args.limit)
                else:
                    result = board.acknowledge(args.observer, args.cursor)
            elif args.action == "notifications":
                from .handoff import Handoffs
                handoffs = Handoffs(store)
                if args.notice_action == "configure":
                    result = handoffs.configure(args.chat, args.enable, args.authorization_reference)
                elif args.notice_action == "list":
                    result = handoffs.listing(args.actor, args.all, args.limit)
                elif args.notice_action == "claim":
                    result = claim_to_file(store, handoffs, args.notice, args.actor, args.claim_file)
                elif args.notice_action == "ack":
                    result = acknowledge_file(store, handoffs, args)
                elif args.notice_action == "retry":
                    result = handoffs.retry_failed(args.notice, args.actor, args.confirmed_not_sent)
                else:
                    result = handoffs.archive_obsolete(args.notice, args.actor)
            elif args.action == "status":
                result = store.status(args.request, include_finished=args.all)
            elif args.action == "request":
                result = store.request(args.owner, args.purpose, json.loads(args.resources), args.idempotency_key, json.loads(args.depends_on))
            elif args.action == "acquire":
                result = acquire_to_file(store, args.request, args.owner, args.lease_file, args.lease_seconds)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["lease_usable"] else 3
            elif args.action in ("begin", "renew", "complete"):
                lease = manual_lease(store, args.lease_file)
                if args.action == "begin":
                    result = store.start(*lease)
                elif args.action == "renew":
                    result = store.heartbeat(*lease, lease_seconds=args.lease_seconds)
                else:
                    result = store.finish(*lease, outcome=args.outcome)
            elif args.action == "cancel":
                result = store.cancel(args.request, args.owner)
            elif args.action == "set-dependencies":
                result = store.set_dependencies(args.request, args.owner, json.loads(args.depends_on))
            elif args.action == "reconcile":
                result = store.reconcile(args.request, args.owner, args.confirmed_stopped, args.note)
            elif args.action in ("recover", "watch"):
                from .operations import recover
                result = recover(store, args.request, args.owner, wait=args.action == "watch", lease_seconds=args.lease_seconds)
            elif args.action == "recover-reboot":
                from .reboot import recover_after_reboot
                result = recover_after_reboot(store, args.request, args.owner,
                    confirmed_reboot=args.confirmed_reboot, confirmed_same_machine=args.confirmed_same_machine,
                    note=args.note, check_only=args.check_only)
            else:
                from .runner import run
                command = args.command[1:] if args.command[:1] == ["--"] else args.command
                return run(store, args.request, args.owner, command, cwd=args.cwd, lease_seconds=args.lease_seconds, tracking=args.tracking, supervisor_worker=args.supervisor_worker)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (CoordinationError, OSError, sqlite3.Error, json.JSONDecodeError, UnicodeError) as error:
        print(json.dumps({"error": str(error), "command_started": False if args.action != "run" else "consult_request_status"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
