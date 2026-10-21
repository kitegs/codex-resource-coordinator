"""Prepare an independent local marketplace with a verified Python interpreter.

Does NOT edit Codex settings, enable hooks, start servers, or restart any client.
Run with --python pointing to the environment where this package is installed.
"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess


def prepare(interpreter: Path, target: Path) -> dict:
    interpreter = interpreter.resolve(strict=True)
    target = target.absolute()
    root = Path(__file__).resolve().parents[1]
    if target.exists() or target == root or target in root.parents:
        raise ValueError("Destination must be a new named directory; existing paths are never overwritten")
    subprocess.run([str(interpreter), "-B", "-c", "import mcp, psutil; from mcp.server.fastmcp import FastMCP"], check=True, capture_output=True)
    plugin = target / "plugins/resource-coordinator"
    shutil.copytree(root / "plugins/resource-coordinator", plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "*.sqlite*", "*.egg-info"))
    catalog = target / ".agents/plugins"
    catalog.mkdir(parents=True)
    shutil.copyfile(root / ".agents/plugins/marketplace.json", catalog / "marketplace.json")
    for name in (".mcp.json", "mcp.json"):
        path = plugin / name
        data = json.loads(path.read_text(encoding="utf-8"))
        data["mcpServers"]["coordinator"]["command"] = str(interpreter)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    hooks = plugin / "hooks/hooks.json"
    data = json.loads(hooks.read_text(encoding="utf-8"))
    command = [str(interpreter), "${PLUGIN_ROOT}/scripts/session_start.py"]
    data["hooks"]["SessionStart"][0]["hooks"][0]["command"] = subprocess.list2cmdline(command) if __import__("os").name == "nt" else shlex.join(command)
    hooks.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"marketplace": str(target), "interpreter": str(interpreter), "codex_settings_changed": False, "client_restarted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.python, args.target), indent=2))
