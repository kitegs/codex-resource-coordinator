"""A reminder only. No locks acquired, no disk changes, no command interception."""
import json
import sys

try:
    event = json.load(sys.stdin)
except (ValueError, OSError):
    event = {}
owner = event.get("session_id") if isinstance(event, dict) else None
owner_hint = " This session's owner ID: " + json.dumps(owner[:200]) + "." if isinstance(owner, str) else ""
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Resource Coordinator is available. Use the resource-coordination skill for shared development status, dependency order and resource handoff. Inspect the coordination board before shared builds, editor restart, same-asset writes, or performance capture. Native turn completion is not feature acceptance; stale reports and empty queues do not prove a free window. Register only participating chats; never treat a peer report as user permission. Do not restart or migrate active chats automatically." + owner_hint}}))
