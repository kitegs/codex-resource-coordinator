"""Small cooperative progress board. Native runtime state and work claims differ.

No Codex database access, daemon, message sending, automatic turn continuation,
or assumption that an idle/completed turn means an accepted feature.
"""
import json
import math

from .store import CoordinationError, _text, conflicts
from . import __version__

WORK = {"unknown", "working", "waiting", "needs_input", "ready_for_review", "finished", "paused"}
HOST = {"unknown", "active", "idle", "notLoaded", "systemError"}
TURN = {"unknown", "inProgress", "completed", "interrupted", "failed"}


def short(value, limit=500):
    if not isinstance(value, str) or len(value) > limit:
        raise CoordinationError("Progress text too long or invalid")
    return " ".join(value.split())


class Board:
    def __init__(self, store, *, initialize=True):
        self.store = store
        if not initialize:
            return
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id TEXT PRIMARY KEY, host_id TEXT NOT NULL, project_key TEXT NOT NULL,
                    label TEXT NOT NULL, worktree TEXT NOT NULL DEFAULT '', commit_id TEXT NOT NULL DEFAULT '',
                    work_state TEXT NOT NULL DEFAULT 'unknown', summary TEXT NOT NULL DEFAULT '',
                    next_step TEXT NOT NULL DEFAULT '', blockers TEXT NOT NULL DEFAULT '[]',
                    work_updated REAL, work_revision INTEGER NOT NULL DEFAULT 0,
                    host_state TEXT NOT NULL DEFAULT 'unknown', active_flags TEXT NOT NULL DEFAULT '[]',
                    turn_state TEXT NOT NULL DEFAULT 'unknown', turn_id TEXT NOT NULL DEFAULT '',
                    host_summary TEXT NOT NULL DEFAULT '', host_observed REAL, host_source TEXT NOT NULL DEFAULT '',
                    seen_cursor INTEGER NOT NULL DEFAULT 0, provenance TEXT NOT NULL DEFAULT '{}',
                    client_version TEXT NOT NULL DEFAULT '', adoption TEXT NOT NULL DEFAULT 'observed_only'
                );
            """)
            if "provenance" not in {row[1] for row in db.execute("PRAGMA table_info(chats)")}:
                db.execute("ALTER TABLE chats ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'")
            columns = {row[1] for row in db.execute("PRAGMA table_info(chats)")}
            if "client_version" not in columns:
                db.execute("ALTER TABLE chats ADD COLUMN client_version TEXT NOT NULL DEFAULT ''")
            if "adoption" not in columns:
                db.execute("ALTER TABLE chats ADD COLUMN adoption TEXT NOT NULL DEFAULT 'observed_only'")

    def _row(self, db, chat_id):
        row = db.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
        if row is None:
            raise CoordinationError("Chat not registered; do not import unrelated conversations")
        return row

    def _change(self, db, subject, kind, attention=False):
        db.execute("INSERT INTO coordination_changes(at,subject,kind,attention) VALUES(?,?,?,?)", (self.store.clock(), subject, kind, attention))

    def register(self, chat_id, label, project_key, host_id="local"):
        for value, label_name, limit in [(chat_id, "chat ID", 200), (label, "chat label", 200), (project_key, "project key", 512), (host_id, "host ID", 100)]:
            _text(value, label_name, limit)
        with self.store.connection(write=True) as db:
            old = db.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
            if old:
                if old["host_id"] != host_id or old["project_key"] != project_key:
                    raise CoordinationError("Existing chat identity/group differs; do not silently move it")
            else:
                db.execute("INSERT INTO chats(chat_id,host_id,project_key,label) VALUES(?,?,?,?)", (chat_id, host_id, project_key, label))
                self._change(db, chat_id, "chat_registered")
            return dict(self._row(db, chat_id))

    def report(self, chat_id, reporter, work_state, summary, expected_revision, next_step="", blockers=None, worktree=None, commit_id=None, provenance=None):
        if reporter != chat_id:
            raise CoordinationError("Only a chat reports its own development/acceptance state")
        if work_state not in WORK:
            raise CoordinationError("Unknown work state")
        blockers = [] if blockers is None else blockers
        if not isinstance(blockers, list) or len(blockers) > 16:
            raise CoordinationError("At most 16 short blockers")
        blockers = [short(item, 200) for item in blockers]
        summary, next_step = short(summary), short(next_step)
        if worktree is not None:
            worktree = short(worktree, 1000)
        if commit_id is not None:
            commit_id = short(commit_id, 100)
        if provenance is not None:
            if not isinstance(provenance, dict) or set(provenance) - {"base_commit", "dirty", "write_scope", "evidence"}:
                raise CoordinationError("Unknown provenance field")
            if "base_commit" in provenance:
                short(provenance["base_commit"], 100)
            if "dirty" in provenance and provenance["dirty"] is not None and not isinstance(provenance["dirty"], bool):
                raise CoordinationError("Dirty state must be true, false, or unknown/null")
            scope = provenance.get("write_scope", [])
            if not isinstance(scope, list) or len(scope) > 32:
                raise CoordinationError("At most 32 responsibility paths")
            for path in scope:
                short(path, 500)
            evidence = provenance.get("evidence", [])
            if not isinstance(evidence, list) or len(evidence) > 12:
                raise CoordinationError("At most 12 evidence pointers")
            for item in evidence:
                if not isinstance(item, dict) or set(item) != {"kind", "status", "revision", "reference"} or item["kind"] not in ("build", "runtime", "test", "asset") or item["status"] not in ("passed", "failed", "not_run", "pending"):
                    raise CoordinationError("Evidence requires kind, status, revision and reference; acceptance is not inferred")
                short(item["revision"], 100)
                short(item["reference"], 1000)
        with self.store.connection(write=True) as db:
            old = self._row(db, chat_id)
            if old["work_revision"] != expected_revision:
                raise CoordinationError("Progress revision changed; read current board before retry")
            changed = old["work_state"] != work_state or json.loads(old["blockers"]) != blockers or old["next_step"] != next_step
            db.execute("UPDATE chats SET work_state=?,summary=?,next_step=?,blockers=?,worktree=?,commit_id=?,provenance=?,work_updated=?,client_version=?,adoption='self_reported',work_revision=work_revision+1 WHERE chat_id=?",
                       (work_state, summary, next_step, json.dumps(blockers), old["worktree"] if worktree is None else worktree, old["commit_id"] if commit_id is None else commit_id, old["provenance"] if provenance is None else json.dumps(provenance), self.store.clock(), __version__, chat_id))
            if changed:
                self._change(db, chat_id, "work_state_changed", work_state in ("needs_input", "ready_for_review"))
            return dict(self._row(db, chat_id))

    def observe(self, chat_id, host_id, host_state, turn_state, turn_id, host_summary, observed_at, source, active_flags=None):
        if host_state not in HOST or turn_state not in TURN or source not in ("codex.wait_threads", "codex.read_thread", "codex.app-server"):
            raise CoordinationError("Unknown native state/source")
        if not isinstance(observed_at, (int, float)) or not math.isfinite(observed_at) or observed_at > self.store.clock()+5 or observed_at < 0:
            raise CoordinationError("Snapshot needs an explicit valid capture time, not a future timestamp")
        flags = active_flags or []
        if not isinstance(flags, list) or len(flags) > 16:
            raise CoordinationError("Invalid active flags")
        flags = [short(flag, 100) for flag in flags]
        host_summary = short(host_summary, 500)
        turn_id = short(turn_id, 200)
        with self.store.connection(write=True) as db:
            old = self._row(db, chat_id)
            if old["host_id"] != host_id:
                raise CoordinationError("Native snapshot host mismatch")
            if old["host_observed"] is not None and observed_at <= old["host_observed"]:
                return {"chat_id": chat_id, "ignored": "older_or_duplicate_snapshot"}
            changed = (old["host_state"], old["turn_state"], old["turn_id"], json.loads(old["active_flags"])) != (host_state, turn_state, turn_id, flags)
            db.execute("UPDATE chats SET host_state=?,active_flags=?,turn_state=?,turn_id=?,host_summary=?,host_observed=?,host_source=? WHERE chat_id=?", (host_state, json.dumps(flags), turn_state, turn_id, host_summary, observed_at, source, chat_id))
            if changed:
                self._change(db, chat_id, "native_state_changed", host_state == "systemError" or turn_state == "failed" or any(flag in ("waitingOnApproval", "waitingOnUserInput") for flag in flags))
            return {"chat_id": chat_id, "host_state": host_state, "turn_state": turn_state, "work_state": old["work_state"], "observed_at": observed_at}

    def ingest(self, snapshot, observed_at):
        """Import a compact native-tool result; discard transcripts/tool contents."""
        if not isinstance(snapshot, dict):
            raise CoordinationError("Supply a decoded compact Codex snapshot")
        if "polls" in snapshot:
            polls, source = snapshot["polls"], "codex.wait_threads"
        elif "thread" in snapshot:
            turns = snapshot.get("turns") or []
            latest = turns[0] if turns else None
            polls, source = [{"thread": snapshot["thread"], "latestTurn": latest}], "codex.read_thread"
        else:
            raise CoordinationError("Expected wait_threads polls or read_thread thread")
        if not isinstance(polls, list) or len(polls) > 8:
            raise CoordinationError("At most 8 registered chats per snapshot")
        result = []
        for poll in polls:
            thread = poll.get("thread") or {}
            native = thread.get("status") or {}
            turn = poll.get("latestTurn") or {}
            message = poll.get("latestAssistantMessage") or {}
            result.append(self.observe(thread.get("id"), thread.get("hostId", "local"), native.get("type", "unknown"), turn.get("status", "unknown"), turn.get("id", ""), " ".join(str(message.get("text", "")).split())[:500], observed_at, source, native.get("activeFlags", [])))
        return result

    def view(self, project_key=None, stale_after=180):
        if not isinstance(stale_after, int) or not 10 <= stale_after <= 86400:
            raise CoordinationError("Freshness threshold must be 10..86400 seconds")
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM chats WHERE project_key=? ORDER BY label LIMIT 200", (project_key,)) if project_key else db.execute("SELECT * FROM chats ORDER BY label LIMIT 200")
            chats = []
            for row in rows:
                item = dict(row)
                item["blockers"], item["active_flags"] = json.loads(item["blockers"]), json.loads(item["active_flags"])
                item["provenance"] = json.loads(item["provenance"])
                item["evidence_verified_by_plugin"] = False
                for prefix, field in (("work", "work_updated"), ("host", "host_observed")):
                    item[prefix+"_fresh"] = item[field] is not None and 0 <= self.store.clock()-item[field] <= stale_after
                item["warning"] = "Turn completion/idle is not feature acceptance; stale data is unknown, not a free window."
                chats.append(item)
            queue = [self.store._public(row, db) for row in db.execute("SELECT * FROM requests WHERE state IN ('waiting','leased','running','suspect') ORDER BY sequence LIMIT 1000")]
            queue_truncated = db.execute("SELECT COUNT(*) FROM requests WHERE state IN ('waiting','leased','running','suspect')").fetchone()[0] > 1000
            for item in queue:
                blockers = [other["id"] for other in queue if other["id"] != item["id"] and (other["state"] in ("leased", "running", "suspect") or (other["state"] == "waiting" and other["sequence"] < item["sequence"] and not other["dependency_blockers"])) and conflicts(item["resources"], other["resources"])]
                item["resource_blockers"] = blockers
                item["resource_blocker_details"] = [{"id": other["id"], "owner": other["owner"], "purpose": other["purpose"], "state": other["state"]} for other in queue if other["id"] in blockers]
                item["eligible_by_queue_rules"] = not queue_truncated and item["state"] == "waiting" and not item["dependency_blockers"] and not blockers
            if project_key:
                owners = {item["chat_id"] for item in chats}
                queue = [item for item in queue if item["owner"] in owners]
            # Optional additive 0.4 tables: an older v2 database stays readable
            # without migration by the query-only panel. Never expose send tokens.
            notices = []
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='release_notices'").fetchone():
                where, args = ("WHERE project_key=?", (project_key,)) if project_key else ("", ())
                rows = db.execute(f"SELECT id,target_request,recipient,project_key,state,deadline,result_code,updated FROM release_notices {where} ORDER BY (state IN ('delivered','obsolete')),updated DESC,id LIMIT 201", args).fetchall()
                for row in rows[:200]:
                    item = dict(row)
                    if item["state"] == "sending" and item["deadline"] <= self.store.clock():
                        item["state"] = "uncertain"
                    notices.append(item)
                notices_truncated = len(rows) > 200
            else:
                notices_truncated = False
            cursor = db.execute("SELECT COALESCE(MAX(sequence),0) FROM coordination_changes").fetchone()[0]
            return {"chats": chats, "queue": queue, "queue_truncated": queue_truncated, "release_notices": notices, "notices_truncated": notices_truncated, "ready_order": [item["id"] for item in queue if item["eligible_by_queue_rules"]], "latest_cursor": cursor, "runtime_clearance": "Queue eligibility is not runtime clearance. Check unmanaged work, freshness, permissions and dirty assets separately.", "data_source": "cooperative self-reports + explicitly imported native snapshots; not a background live monitor"}

    def changes(self, observer, after_cursor=None, limit=50):
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise CoordinationError("Change limit must be 1..200")
        with self.store.connection() as db:
            chat = self._row(db, observer)
            after = chat["seen_cursor"] if after_cursor is None else after_cursor
            if not isinstance(after, int) or after < 0:
                raise CoordinationError("Invalid cursor")
            # Do not broadcast unrelated project progress. Cross-project resource
            # releases remain relevant when they conflict with this group's work.
            group_owners = {row[0] for row in db.execute("SELECT chat_id FROM chats WHERE project_key=?", (chat["project_key"],))}
            group_requests = [row for row in db.execute("SELECT * FROM requests WHERE state IN ('waiting','leased','running','suspect')") if row["owner"] in group_owners]
            dependency_ids = set()
            for request in group_requests:
                dependency_ids.update(row[0] for row in db.execute("""WITH RECURSIVE ancestors(id) AS (
                    SELECT prerequisite FROM request_dependencies WHERE request_id=?
                    UNION SELECT d.prerequisite FROM request_dependencies d JOIN ancestors a ON d.request_id=a.id
                ) SELECT id FROM ancestors""", (request["id"],)))
            events, scanned = [], after
            for row in db.execute("SELECT * FROM coordination_changes WHERE sequence>? ORDER BY sequence LIMIT 200", (after,)):
                scanned = row["sequence"]
                subject = row["subject"]
                relevant = subject in group_owners
                if not relevant:
                    request = db.execute("SELECT * FROM requests WHERE id=?", (subject,)).fetchone()
                    relevant = request is not None and (request["owner"] in group_owners or subject in dependency_ids or any(conflicts(json.loads(request["resources"]), json.loads(own["resources"])) for own in group_requests))
                if relevant:
                    events.append(dict(row))
                    if len(events) == limit:
                        break
            return {"changes": events, "next_cursor": scanned, "instruction": "No relevant change: stay quiet. Acknowledge next_cursor after processing, even when only unrelated events were scanned. Notify only actionable changes affecting your work; this does not authorize cross-chat messaging."}

    def acknowledge(self, observer, cursor):
        with self.store.connection(write=True) as db:
            chat = self._row(db, observer)
            maximum = db.execute("SELECT COALESCE(MAX(sequence),0) FROM coordination_changes").fetchone()[0]
            if not isinstance(cursor, int) or not 0 <= cursor <= maximum:
                raise CoordinationError("Invalid acknowledgment cursor")
            db.execute("UPDATE chats SET seen_cursor=? WHERE chat_id=?", (max(cursor, chat["seen_cursor"]), observer))
            return {"observer": observer, "seen_cursor": max(cursor, chat["seen_cursor"])}
