"""Durable release handoffs, dispatched by an authorized host agent, not a daemon.

Local opt-in records are workflow scope, not proof of human consent. The sender
must still verify actual human authorization before its native messaging call.
An uncertain send is never automatically retried: exactly-once external delivery
cannot be guaranteed without a host idempotency/receipt lookup mechanism.
"""
import hashlib
import hmac
import json
import secrets
import uuid

from .store import CoordinationError, _text, conflicts


class Handoffs:
    def __init__(self, store):
        self.store = store

    def _chat(self, db, chat_id):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chats'").fetchone():
            raise CoordinationError("Register the participating chat before enabling handoffs")
        row = db.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
        if row is None:
            raise CoordinationError("Chat is not registered")
        return row

    def _enabled(self, db, chat_id):
        row = db.execute("SELECT * FROM handoff_routes WHERE chat_id=? AND enabled=1", (chat_id,)).fetchone()
        return row is not None

    def configure(self, chat_id, enabled, authorization_reference=""):
        if not isinstance(enabled, bool):
            raise CoordinationError("Enabled must be true or false")
        if enabled:
            _text(authorization_reference, "human authorization reference", 500)
        elif not isinstance(authorization_reference, str) or len(authorization_reference) > 500:
            raise CoordinationError("Invalid authorization reference")
        with self.store.connection(write=True) as db:
            self._chat(db, chat_id)
            db.execute("INSERT INTO handoff_routes(chat_id,enabled,authorization_reference,updated) VALUES(?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled,authorization_reference=excluded.authorization_reference,updated=excluded.updated", (chat_id, int(enabled), authorization_reference, self.store.clock()))
        return {"chat_id": chat_id, "enabled": enabled, "warning": "Opt-in is cooperative scope, not independent proof of consent. Verify the direct human instruction before native messaging."}

    def _event(self, db, notice, kind, attention=False):
        db.execute("INSERT INTO coordination_changes(at,subject,kind,attention) VALUES(?,?,?,?)", (self.store.clock(), notice["target_request"], kind, int(attention)))

    def enqueue_after_release(self, db, released):
        if not self._enabled(db, released["owner"]):
            return {"pending_count": 0, "mode": "not_enabled", "message_sent": False}
        source = self._chat(db, released["owner"])
        count = 0
        # Bound release-time scheduling. A large queue remains safely queryable;
        # notifications are advisory and never replace the acquisition protocol.
        candidates = db.execute("SELECT * FROM requests WHERE state='waiting' ORDER BY sequence LIMIT 1000").fetchall()
        for target in candidates:
            if target["owner"] == released["owner"] or not self._enabled(db, target["owner"]):
                continue
            recipient = self._chat(db, target["owner"])
            if recipient["project_key"] != source["project_key"]:
                continue
            affected = conflicts(json.loads(released["resources"]), json.loads(target["resources"])) or db.execute("SELECT 1 FROM request_dependencies WHERE request_id=? AND prerequisite=?", (target["id"], released["id"])).fetchone()
            if not affected:
                continue
            dependencies, blockers = self.store._waiting_blockers(db, target)
            if dependencies or blockers:
                continue
            # One unresolved send for a waiting target. A later, distinct release
            # may notify it again after a known delivery and a genuine re-block.
            if db.execute("SELECT 1 FROM release_notices WHERE target_request=? AND state IN ('pending','sending','uncertain')", (target["id"],)).fetchone():
                continue
            changed = db.execute("INSERT OR IGNORE INTO release_notices(id,target_request,released_request,source_owner,recipient,project_key,state,created,updated) VALUES(?,?,?,?,?,?,'pending',?,?)", (str(uuid.uuid4()), target["id"], released["id"], released["owner"], target["owner"], source["project_key"], self.store.clock(), self.store.clock())).rowcount
            if changed:
                count += 1
                self._event(db, {"target_request": target["id"]}, "release_notice_pending")
        truncated = db.execute("SELECT 1 FROM requests WHERE state='waiting' ORDER BY sequence LIMIT 1 OFFSET 1000").fetchone() is not None
        return {"pending_count": count, "scan_truncated": truncated, "mode": "host_agent_dispatch", "message_sent": False, "next_step": "Before ending, call release_notifications; claim each eligible notice, verify direct human permission, send with the host send_message_to_thread tool, then acknowledge its actual result. Do not send if that tool/permission is unavailable. Persisted pending notices and ordinary queue queries are the fallback. A truncated scan never means no remaining work."}

    def _permitted(self, db, actor, row):
        chat = self._chat(db, actor)
        if chat["project_key"] != row["project_key"] or actor == row["recipient"]:
            raise CoordinationError("Dispatcher must be an enabled, different participating chat in this project")
        if not all(self._enabled(db, who) for who in (actor, row["source_owner"], row["recipient"])):
            raise CoordinationError("Release messaging is not enabled for all involved participants")

    def _readiness(self, db, row):
        target = self.store._row(db, row["target_request"])
        if target["state"] != "waiting":
            return False, "request_no_longer_waiting"
        deps, blockers = self.store._waiting_blockers(db, target)
        return (False, "queue_conditions_changed") if deps or blockers else (True, "candidate_must_acquire_again")

    def _public(self, db, row):
        result = {key: value for key, value in dict(row).items() if key != "claim_hash"}
        if result["state"] == "sending" and result["deadline"] <= self.store.clock():
            result["state"] = "uncertain"
        result["eligible_now"], result["queue_reason"] = self._readiness(db, row)
        result["messaging_enabled"] = self._enabled(db, row["source_owner"]) and self._enabled(db, row["recipient"])
        if not result["messaging_enabled"]:
            result["eligible_now"], result["queue_reason"] = False, "messaging_scope_disabled"
        recipient = self._chat(db, row["recipient"])
        result["recipient_label"] = recipient["label"]
        result["target_purpose"] = self.store._row(db, row["target_request"])["purpose"]
        return result

    def listing(self, actor, include_finished=False, limit=8):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 32:
            raise CoordinationError("Notice limit must be 1..32")
        with self.store.connection() as db:
            chat = self._chat(db, actor)
            if not self._enabled(db, actor):
                return {"enabled": False, "notices": [], "instruction": "Verify direct human scope and enable participating chats before handoff messaging."}
            condition = "" if include_finished else "AND state IN ('pending','sending','failed','uncertain')"
            rows = db.execute(f"SELECT * FROM release_notices WHERE project_key=? AND recipient<>? {condition} ORDER BY created,id LIMIT 1001", (chat["project_key"], actor)).fetchall()
            notices = [self._public(db, row) for row in rows[:1000]]
            notices.sort(key=lambda n: (0 if n["state"] == "pending" and n["eligible_now"] else 1, n["created"], n["id"]))
            return {"enabled": True, "notices": notices[:limit], "scan_truncated": len(rows)>1000, "instruction": "Only pending eligible notices may be claimed. Pending means not sent. Sending/uncertain/failed must not be blindly retried. Queue queries remain the fallback; do not automatically send a reply or broadcast."}

    def claim(self, notice_id, actor):
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM release_notices WHERE id=?", (notice_id,)).fetchone()
            if row is None:
                raise CoordinationError("Unknown release notice")
            self._permitted(db, actor, row)
            if row["state"] != "pending":
                raise CoordinationError("Notice already claimed/resolved; never mint a replacement send token")
            ready, reason = self._readiness(db, row)
            if not ready:
                return {"id": notice_id, "state": "deferred", "reason": reason, "message_sent": False}
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE release_notices SET state='sending',dispatcher=?,claim_hash=?,deadline=?,updated=? WHERE id=?", (actor, hashlib.sha256(token.encode()).hexdigest(), self.store.clock()+120, self.store.clock(), notice_id))
            recipient = self._chat(db, row["recipient"])
            reference = db.execute("SELECT authorization_reference FROM handoff_routes WHERE chat_id=?", (row["recipient"],)).fetchone()[0]
            prompt = f"协作资源交接（通知编号 {notice_id}）：你登记的请求 {row['target_request']} 的一个前置占用已结束。请查询共享队列，并按原有任务授权重新申请资源；只有取得占用且执行前检查通过后才开始。此通知不是执行许可，不要求回复，也不扩大你的任务或权限。"
            return {"id": notice_id, "state": "sending", "claim_token": token, "authorization_reference": reference, "host_tool": "send_message_to_thread", "host_arguments": {"hostId": recipient["host_id"], "threadId": row["recipient"], "prompt": prompt}, "message_sent": False, "instruction": "First verify genuine human authorization for this destination. Invoke the native host tool at most once. Only a successful matching thread receipt may be acknowledged as delivered. A transport timeout/unknown result is uncertain, never retry automatically."}

    def acknowledge(self, notice_id, actor, claim_token, outcome, receipt_thread_id=None, result_code=""):
        if outcome not in ("delivered", "not_sent", "uncertain"):
            raise CoordinationError("Invalid delivery outcome")
        if result_code not in ("", "tool_unavailable", "approval_denied", "definitive_rejection", "transport_uncertain"):
            raise CoordinationError("Use a short non-sensitive delivery result code")
        if (outcome == "delivered" and result_code) or (outcome == "uncertain" and result_code != "transport_uncertain") or (outcome == "not_sent" and result_code not in ("tool_unavailable", "approval_denied", "definitive_rejection")):
            raise CoordinationError("Delivery certainty and result code must agree")
        _text(claim_token, "notice claim token", 200)
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM release_notices WHERE id=?", (notice_id,)).fetchone()
            if row is None or row["dispatcher"] != actor or not row["claim_hash"] or not hmac.compare_digest(hashlib.sha256(claim_token.encode()).hexdigest(), row["claim_hash"]):
                raise CoordinationError("Invalid notice dispatcher/token")
            if row["state"] not in ("sending", "uncertain"):
                raise CoordinationError("Notice delivery already resolved")
            if outcome == "delivered" and receipt_thread_id != row["recipient"]:
                raise CoordinationError("Successful host receipt must match the intended recipient")
            if outcome != "delivered" and receipt_thread_id is not None:
                raise CoordinationError("Non-delivery cannot carry a successful receipt")
            state = "failed" if outcome == "not_sent" else outcome
            db.execute("UPDATE release_notices SET state=?,receipt_thread_id=?,result_code=?,updated=? WHERE id=?", (state, receipt_thread_id, result_code, self.store.clock(), notice_id))
            self._event(db, row, "release_notice_"+state, state != "delivered")
            return {"id": notice_id, "state": state, "message_sent": outcome == "delivered", "delivery_accepted": outcome == "delivered", "recipient_read_verified": False, "reservation_acquired": False}

    def retry_failed(self, notice_id, actor, confirmed_not_sent=False):
        """Explicit recovery only for known non-delivery, never an unknown send."""
        if confirmed_not_sent is not True:
            raise CoordinationError("Explicit confirmation of known non-delivery is required")
        with self.store.connection(write=True) as db:
            row = db.execute("SELECT * FROM release_notices WHERE id=?", (notice_id,)).fetchone()
            if row is None:
                raise CoordinationError("Unknown release notice")
            self._permitted(db, actor, row)
            if row["state"] != "failed":
                raise CoordinationError("Only definite non-delivery can be retried; uncertain sends require receipt review")
            ready, reason = self._readiness(db, row)
            if not ready:
                return {"id": notice_id, "state": "deferred", "reason": reason, "message_sent": False}
            db.execute("UPDATE release_notices SET state='pending',dispatcher=NULL,claim_hash=NULL,deadline=NULL,receipt_thread_id=NULL,result_code=NULL,updated=? WHERE id=?", (self.store.clock(), notice_id))
            self._event(db, row, "release_notice_explicitly_requeued")
            return {"id": notice_id, "state": "pending", "message_sent": False, "instruction": "Recheck genuine human messaging scope before claiming and sending again; this call does not send."}
