import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

import pandas as pd

from Atlas.model.share_matrix_builder_v2 import emit_share_matrix_csv, generate_share_matrix_v2
from Atlas.model.share_matrix_contract import require_valid_share_matrix

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LOGS_PATH = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
DEFAULT_OUT_PATH  = PROJECT_ROOT / "data" / "model" / "share_matrix.csv"


def main() -> None:
    p = argparse.ArgumentParser(description="Build share_matrix.csv from nba_gamelogs.csv")
    p.add_argument("--logs", type=str, default=str(DEFAULT_LOGS_PATH))
    p.add_argument("--out", type=str, default=str(DEFAULT_OUT_PATH))

    # Edge knobs (current roster/usage focus)
    p.add_argument("--recent-days", type=int, default=140)
    p.add_argument("--min-rotation-games", type=int, default=6)
    p.add_argument("--min-rotation-avg-min", type=float, default=8.0)

    # Cleanup knobs
    p.add_argument("--min-pattern-games", type=int, default=3)
    p.add_argument("--keep-zero-weights", action="store_true", default=False)
    args = p.parse_args()

    snapshot_dir = os.environ.get("ATLAS_IAEL_SNAPSHOT_DIR")
    has_run_snapshot = bool(snapshot_dir) or bool(os.environ.get("ATLAS_IAEL_INVALIDATIONS_PATH"))
    if not has_run_snapshot:
        # Standalone fallback: keep the old freshness hook, but avoid touching
        # the live source when the caller already supplied a frozen run snapshot.
        refresh_path = PROJECT_ROOT / "tools" / "refresh_iael_today.py"
        if refresh_path.exists():
            print(f"[IAEL] Preflight refresh via {refresh_path}")
            subprocess.run([sys.executable, str(refresh_path)], check=False)
        else:
            print(f"[IAEL] Preflight refresh missing: {refresh_path}")

    logs_path = Path(args.logs)
    out_path = Path(args.out)

    logs = pd.read_csv(logs_path)

    mat = generate_share_matrix_v2(
        logs,
        iael_df=None,
        recent_days=int(args.recent_days),
        min_rotation_games=int(args.min_rotation_games),
        min_rotation_avg_min=float(args.min_rotation_avg_min),
        min_pattern_games=int(args.min_pattern_games),
        keep_zero_weights=bool(args.keep_zero_weights),
    )

    if mat.empty:
        raise RuntimeError("share matrix generation produced no rows")

    require_valid_share_matrix(mat)

    emit_share_matrix_csv(mat, out_path)
    print(f"OK wrote {out_path} rows={len(mat)} (after cleanup)")


if __name__ == "__main__":
    main()