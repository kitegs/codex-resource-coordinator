import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugins/resource-coordinator"


def result_data(result):
    assert not result.isError, result
    return result.structuredContent or json.loads(result.content[0].text)


def test_real_mcp_stdio_request_grant_wait_and_release(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-B", str(PLUGIN / "scripts/server.py")], env={"COORDINATOR_DB": str(tmp_path / "mcp.sqlite3")})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "resource-coordinator"
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert len(tools) == 21
                assert {"coordination_board", "import_codex_status_snapshot", "report_development_status", "set_request_dependencies"}.issubset(tools)
                assert not tools.intersection({"run", "execute", "shell", "kill_process"})
                for chat in ("chat-a", "chat-b"):
                    result_data(await session.call_tool("register_coordination_chat", {"chat_id":chat,"label":chat,"project_key":"protocol-test"}))
                    result_data(await session.call_tool("configure_release_notifications", {"chat_id":chat,"enabled":True,"authorization_reference":"synthetic explicit human scope"}))
                resources = [{"key": "asset:generic-test", "mode": "exclusive"}]
                a = result_data(await session.call_tool("request_resources", {"owner": "chat-a", "purpose": "smoke test", "resources": resources}))
                b = result_data(await session.call_tool("request_resources", {"owner": "chat-b", "purpose": "second smoke test", "resources": resources}))
                acquired = result_data(await session.call_tool("acquire_resources", {"request_id": a["id"], "owner": "chat-a"}))
                assert acquired["state"] == "leased"
                waiting = result_data(await session.call_tool("acquire_resources", {"request_id": b["id"], "owner": "chat-b"}))
                assert waiting["state"] == "waiting" and a["id"] in waiting["blocked_by"]
                invalid = await session.call_tool("complete_operation", {"request_id": a["id"], "owner": "chat-a", "lease_token": "not-the-token"})
                assert invalid.isError
                args = {"request_id": a["id"], "owner": "chat-a", "lease_token": acquired["lease_token"]}
                assert result_data(await session.call_tool("begin_operation", args))["state"] == "running"
                assert result_data(await session.call_tool("renew_lease", args))["state"] == "running"
                public = result_data(await session.call_tool("queue_status", {}))
                assert acquired["lease_token"] not in json.dumps(public)
                completed = result_data(await session.call_tool("complete_operation", args))
                assert completed["state"] == "completed" and completed["release_handoff"]["pending_count"] == 1
                outbox = result_data(await session.call_tool("release_notifications", {"actor":"chat-a"}))
                notice = outbox["notices"][0]
                claim = result_data(await session.call_tool("claim_release_notification", {"notice_id":notice["id"],"actor":"chat-a"}))
                assert claim["host_arguments"]["threadId"] == "chat-b" and claim["message_sent"] is False
                # Simulated host transport only. No real Codex chat is messaged.
                receipt = {"threadId":claim["host_arguments"]["threadId"]}
                ack = result_data(await session.call_tool("acknowledge_release_notification", {"notice_id":notice["id"],"actor":"chat-a","claim_token":claim["claim_token"],"outcome":"delivered","receipt_thread_id":receipt["threadId"]}))
                assert ack["state"] == "delivered" and ack["reservation_acquired"] is False
                assert result_data(await session.call_tool("release_notifications", {"actor":"chat-a"}))["notices"] == []
                assert result_data(await session.call_tool("acquire_resources", {"request_id": b["id"], "owner": "chat-b"}))["state"] == "leased"
                registered = result_data(await session.call_tool("register_coordination_chat", {"chat_id": "chat-a", "label": "A", "project_key": "protocol-test"}))
                assert registered["work_revision"] == 0
                result_data(await session.call_tool("report_development_status", {"chat_id": "chat-a", "reporter": "chat-a", "work_state": "working", "summary": "More checks remain", "expected_revision": 0}))
                view = result_data(await session.call_tool("coordination_board", {"project_key": "protocol-test"}))
                assert view["chats"][0]["work_state"] == "working"
                notices = result_data(await session.call_tool("coordination_changes", {"observer": "chat-a"}))
                result_data(await session.call_tool("acknowledge_coordination_changes", {"observer": "chat-a", "cursor": notices["next_cursor"]}))
                assert result_data(await session.call_tool("coordination_changes", {"observer": "chat-a"}))["changes"] == []

    asyncio.run(scenario())


def test_session_hook_is_reminder_only(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(PLUGIN / "scripts/session_start.py")], input='{"session_id":"synthetic","hook_event_name":"SessionStart"}', text=True, capture_output=True, check=True, cwd=tmp_path)
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "additionalContext" in output["hookSpecificOutput"]
    assert "permissionDecision" not in json.dumps(output)
    assert list(tmp_path.iterdir()) == []


def test_prepare_install_does_not_change_host_config_and_refuses_overwrite(tmp_path):
    spec = importlib.util.spec_from_file_location("prepare_plugin", ROOT / "scripts/prepare_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "prepared-marketplace"
    result = module.prepare(Path(sys.executable), target)
    assert result["codex_settings_changed"] is False
    assert result["client_restarted"] is False
    for name in ("index.html", "panel.css", "panel.js"):
        assert (target / "plugins/resource-coordinator/coordinator/panel" / name).is_file()
    assert not list((target / "plugins/resource-coordinator").glob("*.egg-info"))
    for name in (".mcp.json", "mcp.json"):
        configuration = json.loads((target / "plugins/resource-coordinator" / name).read_text())
        assert configuration["mcpServers"]["coordinator"]["command"] == str(Path(sys.executable).resolve())
    with pytest.raises(ValueError, match="never overwritten"):
        module.prepare(Path(sys.executable), target)


def test_manifest_links_resolve_inside_plugin():
    manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    for name in ("skills", "mcpServers", "hooks"):
        target = (PLUGIN / manifest[name]).resolve(strict=True)
        assert target.is_relative_to(PLUGIN.resolve())
    portable = json.loads((PLUGIN / "plugin.json").read_text())
    assert portable["name"] == manifest["name"]
    assert portable["version"] == manifest["version"]
    assert json.loads((PLUGIN / "mcp.json").read_text())["mcpServers"] == json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]


def test_install_smoke_refuses_existing_database(tmp_path):
    spec = importlib.util.spec_from_file_location("smoke_plugin", ROOT / "scripts/smoke_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"sentinel-do-not-overwrite")
    with pytest.raises(ValueError, match="never overwritten"):
        asyncio.run(module.smoke(PLUGIN, existing))
    assert existing.read_bytes() == b"sentinel-do-not-overwrite"
