"""A reminder only. No locks acquired, no disk changes, no command interception."""
import json
import sys

try:
    json.load(sys.stdin)
except (ValueError, OSError):
    pass
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Resource Coordinator is available. Before shared builds, editor restart, same-asset writes, or performance capture, inspect the queue and use the resource-coordination skill. Existing unregistered work remains unmanaged; never infer a free window from an empty queue. A reservation is not user permission. Do not restart or migrate active chats automatically."}}))
