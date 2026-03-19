import argparse
from pathlib import Path
import sys
import subprocess

import pandas as pd

from Atlas.model.team_share_reallocator import build_removed_share_matrix

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
    
    # --- IAEL preflight: ensure normalized/latest.json is republished to newest snapshot ---
    # --- “Do not remove. This is the guaranteed IAEL freshness hook for live runs.” --- Rick
    refresh_path = PROJECT_ROOT / "tools" / "refresh_iael_today.py"
    if refresh_path.exists():
        print(f"[IAEL] Preflight refresh via {refresh_path}")
        subprocess.run([sys.executable, str(refresh_path)], check=False)
    else:
        print(f"[IAEL] Preflight refresh missing: {refresh_path}")

    logs_path = Path(args.logs)
    out_path = Path(args.out)

    logs = pd.read_csv(logs_path)

    mat = build_removed_share_matrix(
        logs,
        recent_days=int(args.recent_days),
        min_rotation_games=int(args.min_rotation_games),
        min_rotation_avg_min=float(args.min_rotation_avg_min),
    )

    if "weight" in mat.columns:
        mat["weight"] = pd.to_numeric(mat["weight"], errors="coerce").fillna(0.0)
    else:
        mat["weight"] = 0.0

    if "games" in mat.columns:
        mat["games"] = pd.to_numeric(mat["games"], errors="coerce").fillna(0).astype(int)
    else:
        mat["games"] = 0

    if not args.keep_zero_weights:
        mat = mat[mat["weight"].abs() > 1e-12].copy()

    mpg = int(args.min_pattern_games)
    if mpg > 0:
        mat = mat[mat["games"] >= mpg].copy()

    mat = mat.reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mat.to_csv(out_path, index=False)
    print(f"OK wrote {out_path} rows={len(mat)} (after cleanup)")


if __name__ == "__main__":
    main()