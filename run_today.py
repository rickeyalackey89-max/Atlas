from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure ./src is on sys.path so "import Atlas" works when running `py run_today.py`
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from Atlas.runtime.orchestrator import run_today  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run Atlas daily pipeline (fetch->rebuild->model->filter latest tags)."
    )
    ap.add_argument(
        "--scheduled",
        action="store_true",
        help="If set, relax place-window filtering for bucket tags (early/main/late) to 0 minutes.",
    )
    args = ap.parse_args()

    run_today(scheduled=bool(args.scheduled))


if __name__ == "__main__":
    main()