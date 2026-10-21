"""Exercise a prepared/installed plugin over real MCP using a NEW isolated database.

Does not update host settings, touch the default coordination database, start UE,
or claim that the current Codex chat has loaded the plugin. Output has no tokens.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def data(result):
    if result.isError:
        raise RuntimeError("MCP smoke call failed; inspect the isolated test run")
    return result.structuredContent or json.loads(result.content[0].text)


async def smoke(plugin, database, snapshot=None, observed_at=None):
    native_snapshot_supplied = snapshot is not None
    plugin = plugin.resolve(strict=True)
    database = database.absolute()
    if not database.is_absolute() or any(Path(str(database) + suffix).exists() for suffix in ("", "-wal", "-shm")):
        raise ValueError("Use a new isolated database; existing coordination data is never overwritten")
    configuration = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["coordinator"]
    # Resolve only the manifest placeholder; never interpret a shell command.
    params = StdioServerParameters(command=configuration["command"],
        args=[arg.replace("${PLUGIN_ROOT}", str(plugin)) for arg in configuration["args"]],
        env={**configuration.get("env", {}), "COORDINATOR_DB": str(database)})
    version = json.loads((plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert len(tools) == 16 and "coordination_board" in tools

            async def call(name, **arguments):
                return data(await session.call_tool(name, arguments))

            await call("register_coordination_chat", chat_id="smoke-observer", label="Smoke observer", project_key="install-smoke")
            await call("report_development_status", chat_id="smoke-observer", reporter="smoke-observer", work_state="working", summary="Protocol smoke only; host adoption remains unverified", expected_revision=0)
            resources = [{"key": "smoke:isolated-output", "mode": "exclusive"}]
            prerequisite = await call("request_resources", owner="smoke-observer", purpose="Prerequisite", resources=resources)
            dependent = await call("request_resources", owner="smoke-observer", purpose="Dependent", resources=resources, depends_on=[prerequisite["id"]])
            waiting = await call("acquire_resources", request_id=dependent["id"], owner="smoke-observer")
            assert waiting["state"] == "waiting" and waiting["dependency_blockers"][0]["id"] == prerequisite["id"]
            for request in (prerequisite, dependent):
                lease = await call("acquire_resources", request_id=request["id"], owner="smoke-observer")
                assert lease["state"] == "leased"
                args = {"request_id": request["id"], "owner": "smoke-observer", "lease_token": lease["lease_token"]}
                await call("begin_operation", **args)
                await call("complete_operation", **args)
            if snapshot is None:
                snapshot = {"polls": [{"thread": {"id": "smoke-observer", "hostId": "local", "status": {"type": "idle"}}, "latestTurn": {"id": "smoke-turn", "status": "completed"}}]}
                observed_at = time.time()
            else:
                if observed_at is None:
                    raise ValueError("A native snapshot requires its actual capture time")
                polls = snapshot.get("polls") or [{"thread": snapshot.get("thread", {})}]
                for poll in polls:
                    thread = poll["thread"]
                    await call("register_coordination_chat", chat_id=thread["id"], host_id=thread.get("hostId", "local"), label="Explicit native snapshot peer", project_key="install-smoke")
            imported = await call("import_codex_status_snapshot", snapshot=snapshot, observed_at=observed_at)
            assert len(imported["observations"]) >= 1
            board = await call("coordination_board", project_key="install-smoke")
            observer = next(chat for chat in board["chats"] if chat["chat_id"] == "smoke-observer")
            assert observer["work_state"] == "working" and observer["client_version"] == version
            for peer in board["chats"]:
                if peer["chat_id"] != "smoke-observer":
                    assert peer["work_state"] == "unknown" and peer["adoption"] == "observed_only"
            notices = await call("coordination_changes", observer="smoke-observer")
            await call("acknowledge_coordination_changes", observer="smoke-observer", cursor=notices["next_cursor"])
            assert (await call("coordination_changes", observer="smoke-observer"))["changes"] == []
            assert (await call("queue_status"))["requests"] == []
    return {"passed": True, "plugin_version": version, "tool_count": len(tools), "dependency_round_trip": True,
            "snapshot_import": True, "native_snapshot_supplied": native_snapshot_supplied,
            "all_test_reservations_released": True, "host_chat_adoption_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--observed-at", type=float)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else None
    print(json.dumps(asyncio.run(smoke(args.plugin, args.db, snapshot, args.observed_at)), indent=2))
