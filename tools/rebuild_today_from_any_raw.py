from __future__ import annotations

import runpy
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
import sys

"""
Wrapper to preserve run_today.py wiring.

run_today.py shells out to:
  tools/rebuild_today_from_any_raw.py

The implementation lives in:
  src/Atlas/rebuild_today_from_any_raw.py
"""

def main() -> None:
    repo_root = find_repo_root(Path(__file__))
    target = repo_root / "src" / "Atlas" / "rebuild_today_from_any_raw.py"

    if not target.exists():
        raise FileNotFoundError(f"Expected implementation not found: {target}")

    # Allow imports from src/ (so `import Atlas...` works if needed)
    sys.path.insert(0, str(repo_root / "src"))

    # Execute the real script as if it were run directly
    runpy.run_path(str(target), run_name="__main__")

if __name__ == "__main__":
    main()

