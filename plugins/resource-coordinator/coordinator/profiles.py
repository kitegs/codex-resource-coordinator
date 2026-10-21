"""Optional UE resource names; scheduling itself is engine-independent."""
import hashlib
import os
from pathlib import Path
import subprocess

from .store import CoordinationError


def path_key(kind: str, path: Path | str) -> str:
    value = os.path.normcase(str(Path(path).resolve()))
    return f"{kind}:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def repository_key(project: Path | str) -> str:
    project = Path(project).resolve(strict=True)
    result = subprocess.run(["git", "-C", str(project), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, timeout=5)
    return path_key("repository", result.stdout.decode().strip() if result.returncode == 0 else project)


def ue_plan(project: Path | str, operation: str) -> dict:
    project = Path(project).resolve(strict=True)
    if not project.is_dir():
        raise CoordinationError("Project must be an existing directory")
    source = path_key("ue-source", project / "Source")
    output = path_key("ue-build", project / "Intermediate")
    runtime = path_key("ue-runtime", project)
    profiles = {
        "compile-only": [(source, "shared"), (output, "exclusive"), (runtime, "shared"), ("machine:heavy-job", "exclusive"), ("machine:load", "shared")],
        "cold-build": [(source, "shared"), (output, "exclusive"), (runtime, "exclusive"), ("machine:heavy-job", "exclusive"), ("machine:load", "shared")],
        "integrate": [(source, "exclusive"), (output, "exclusive"), (runtime, "exclusive")],
        "editor-test": [(runtime, "shared"), ("machine:load", "shared")],
        "performance": [(runtime, "shared"), ("machine:load", "exclusive")],
    }
    if operation not in profiles:
        raise CoordinationError("Unknown operation profile")
    return {"project": str(project), "repository": repository_key(project), "operation": operation,
            "resources": [{"key": key, "mode": mode} for key, mode in profiles[operation]],
            "warning": "Use the ACTUAL integration/build directory. This plan does not inspect UE state, stop processes, authorize restart, or launch commands."}
