"""CLI entry usable from an installed plugin without modifying PYTHONPATH."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.cli import main

raise SystemExit(main())
