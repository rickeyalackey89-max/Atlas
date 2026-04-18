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
DEFAULT_ROLE_METRICS_PATH = PROJECT_ROOT / "data" / "output" / "dashboard" / "role_metrics_latest.json"


def _load_role_metrics() -> pd.DataFrame | None:
    """Load the CraftedNBA role-metrics snapshot for DARKO/CPM/DRIP enrichment."""
    env_path = (os.environ.get("ATLAS_ROLE_METRICS_PATH") or "").strip()
    for candidate in (env_path, str(DEFAULT_ROLE_METRICS_PATH)):
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists() and p.is_file():
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                rows = obj.get("rows", []) if isinstance(obj, dict) else obj
                if isinstance(rows, list) and rows:
                    df = pd.DataFrame([r for r in rows if isinstance(r, dict)])
                    if not df.empty and "player" in df.columns:
                        print(f"[SHARE_MATRIX] Loaded role metrics from {p} ({len(df)} players)")
                        return df
            except Exception as exc:
                print(f"[SHARE_MATRIX] Failed to load role metrics from {p}: {exc}")
    print("[SHARE_MATRIX] No role metrics snapshot found — DARKO/CPM/DRIP enrichment skipped")
    return None


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

    role_metrics = _load_role_metrics()

    mat = generate_share_matrix_v2(
        logs,
        iael_df=None,
        role_metrics_df=role_metrics,
        recent_days=int(args.recent_days),
        min_rotation_games=int(args.min_rotation_games),
        min_rotation_avg_min=float(args.min_rotation_avg_min),
        min_pattern_games=int(args.min_pattern_games),
        keep_zero_weights=bool(args.keep_zero_weights),
    )

    if mat.empty:
        # Valid in replay when no injuries are active — write header-only file
        from Atlas.model.share_matrix_contract import REQUIRED_COLUMNS
        pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)).to_csv(out_path, index=False)
        print(f"OK wrote {out_path} rows=0 (no active injuries — empty share matrix)")
        return

    require_valid_share_matrix(mat)

    emit_share_matrix_csv(mat, out_path)
    print(f"OK wrote {out_path} rows={len(mat)} (after cleanup)")


if __name__ == "__main__":
    main()