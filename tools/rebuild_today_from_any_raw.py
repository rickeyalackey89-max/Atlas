from __future__ import annotations

import runpy
import sys
from pathlib import Path
from Atlas.stages.common.paths import find_repo_root

"""
Wrapper to preserve run_today.py wiring.

run_today.py shells out to:
  tools/rebuild_today_from_any_raw.py

The implementation lives in:
  src/Atlas/rebuild_today_from_any_raw.py

This wrapper now:
  - resolves repo root
  - ensures ./src is on sys.path
  - forwards ALL CLI args to the real script
"""

def main() -> None:
    repo_root = find_repo_root(Path(__file__))
    target = repo_root / "src" / "Atlas" / "rebuild_today_from_any_raw.py"

    if not target.exists():
        raise FileNotFoundError(f"Expected implementation not found: {target}")

    # Allow imports from src/ (so `import Atlas...` works)
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    # Forward args to the real script by making it "argv[0]"
    # This lets the underlying argparse see whatever flags we pass to THIS wrapper.
    sys.argv = [str(target)] + sys.argv[1:]

    # Execute the real script as if it were run directly
    runpy.run_path(str(target), run_name="__main__")

if __name__ == "__main__":
    main()
