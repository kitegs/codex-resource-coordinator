"""Owned synthetic foreground jobs. Test outputs ONLY; never touches UE or host state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode, directory, exit_code = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
if mode in ("root", "root-waits", "grandparent"):
    with (directory / "launches.txt").open("a", encoding="utf-8") as stream:
        stream.write("launched\n")
    child_mode = "middle" if mode == "grandparent" else "child"
    subprocess.Popen([sys.executable, "-B", __file__, child_mode, str(directory), "0"])
    if mode == "root-waits":
        deadline = time.monotonic()+20
        while not (directory / "release").exists() and time.monotonic() < deadline:
            time.sleep(.025)
    raise SystemExit(exit_code)
if mode == "middle":
    subprocess.Popen([sys.executable, "-B", __file__, "child", str(directory), "0"])
    raise SystemExit(0)
(directory / "started.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
deadline = time.monotonic()+20
while not (directory / "release").exists() and time.monotonic() < deadline:
    time.sleep(.025)
(directory / "done").write_text("finished", encoding="utf-8")
raise SystemExit(exit_code)
