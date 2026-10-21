"""MCP stdio entry. Dependencies must be installed explicitly; no startup downloads."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise SystemExit("Install this plugin's Python dependencies in the configured MCP interpreter first. See README; no automatic download performed.")
from coordinator.store import Store
from coordinator.profiles import ue_plan

server = FastMCP("resource-coordinator", instructions="Local cooperative scheduling only. All chats share one database. A reservation is not user authorization. Expired leases stay blocking. Never kill processes, alter Git, or claim unmanaged applications are locked. Use normal approved execution tools for commands; this server never runs arbitrary commands.")
store = Store()


@server.tool()
def queue_status(request_id: str | None = None, include_finished: bool = False) -> dict:
    """Read reservations. Tokens are redacted. An expired reservation still blocks."""
    return {"requests": store.status(request_id, include_finished=include_finished)}


@server.tool()
def request_resources(owner: str, purpose: str, resources: list[dict], idempotency_key: str | None = None) -> dict:
    """Queue exact resource keys/modes. Use a stable chat ID as owner; do not copy private prompts into purpose."""
    return store.request(owner, purpose, resources, idempotency_key)


@server.tool()
def acquire_resources(request_id: str, owner: str, lease_seconds: int = 120) -> dict:
    """Try once. Return waiting/blockers or a lease token. No command is started; do not claim permission to restart UE."""
    return store.acquire(request_id, owner, lease_seconds)


@server.tool()
def begin_operation(request_id: str, owner: str, lease_token: str) -> dict:
    """Mark a leased MANUAL operation running. For subprocesses prefer CLI run with a waiting request."""
    return store.start(request_id, owner, lease_token)


@server.tool()
def renew_lease(request_id: str, owner: str, lease_token: str, lease_seconds: int = 120) -> dict:
    """Renew an active reservation. Cannot revive expired/suspect reservations."""
    return store.heartbeat(request_id, owner, lease_token, lease_seconds)


@server.tool()
def complete_operation(request_id: str, owner: str, lease_token: str, outcome: str = "completed") -> dict:
    """Release only after operation ends; recorded processes must be gone. Never use completion to steal a window."""
    return store.finish(request_id, owner, lease_token, outcome)


@server.tool()
def cancel_waiting(request_id: str, owner: str) -> dict:
    """Remove only a waiting request. This never stops running work."""
    return store.cancel(request_id, owner)


@server.tool()
def reconcile_expired(request_id: str, owner: str, confirmed_stopped: bool, note: str) -> dict:
    """Manual recovery after explicit confirmation and process checks. Never infer confirmation from expiry or silence."""
    return store.reconcile(request_id, owner, confirmed_stopped, note)


@server.tool()
def plan_ue_resources(project: str, operation: str) -> dict:
    """Derive UE keys from actual integration path. Does not inspect editor/dirty state or authorize restart."""
    return ue_plan(project, operation)


if __name__ == "__main__":
    server.run(transport="stdio")
