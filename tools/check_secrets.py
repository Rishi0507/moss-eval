"""Fails if the project id or key from .env appears in any tracked file."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from moss_eval.core import load_env  # noqa: E402

load_env()
needles = [v for v in (os.environ.get("MOSS_PROJECT_ID"), os.environ.get("MOSS_PROJECT_KEY")) if v and len(v) >= 6]
files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root, capture_output=True, text=True).stdout.split()
hits = [f for f in files if any(n in (root / f).read_text(encoding="utf-8", errors="ignore") for n in needles)]
print("no secrets found" if not hits else f"SECRETS IN: {hits}")
sys.exit(1 if hits else 0)
