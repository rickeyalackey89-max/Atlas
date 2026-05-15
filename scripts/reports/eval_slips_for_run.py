#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Atlas.runtime.slip_eval import write_eval_slips_for_run  # noqa: E402


def _resolve_run(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path.resolve()
    run_path = ROOT / "data" / "output" / "runs" / value
    if run_path.exists():
        return run_path.resolve()
    raise FileNotFoundError(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write eval_slips.csv/json for a run with eval_legs.csv.")
    parser.add_argument("run", help="Run folder path or run id under data/output/runs.")
    args = parser.parse_args()

    csv_path, json_path = write_eval_slips_for_run(_resolve_run(args.run))
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
