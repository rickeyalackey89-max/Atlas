#!/usr/bin/env python3
from __future__ import annotations

"""Compare the latest two PrizePicks board snapshots.

Robust to legacy snapshot schemas and duplicate keys.

Key improvements:
- Accepts both 'board_*.csv' and legacy 'today_*.csv'
- If expected key columns are missing (e.g., 'tier'), degrades the join key
- Handles duplicate keys by taking the first row for comparisons (still good for telemetry counts)

Outputs:
- data/board/snapshots/movement_latest.csv
"""

import argparse
import glob
import os
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return start.resolve()
from typing import List, Optional, Any

import pandas as pd
PROJECT_ROOT = find_repo_root(Path(__file__))
SNAP_DIR = PROJECT_ROOT / "data" / "board" / "snapshots"

PREFERRED_KEY_COLS = ["projection_id", "player", "stat", "line", "tier", "direction"]

def _latest_two_snapshot_paths(snap_dir: Path) -> List[str]:
    patterns = [
        str(snap_dir / "board_*.csv"),
        str(snap_dir / "today_*.csv"),
    ]
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files = list({os.path.abspath(p) for p in files})  # de-dupe
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:2]

def _choose_key_cols(a: pd.DataFrame, b: pd.DataFrame) -> List[str]:
    cols_a = set(a.columns)
    cols_b = set(b.columns)
    cols = [c for c in PREFERRED_KEY_COLS if c in cols_a and c in cols_b]
    if not cols:
        for fallback in (["projection_id"], ["player", "stat", "line"], ["player", "stat"]):
            if all(c in cols_a and c in cols_b for c in fallback):
                cols = fallback
                break
    return cols

def _ensure_direction(df: pd.DataFrame) -> pd.DataFrame:
    if "direction" not in df.columns and "pick" in df.columns:
        df = df.copy()
        df["direction"] = df["pick"]
    return df

def _scalar(v: Any) -> Any:
    """Convert pandas scalars / Series to a comparable scalar."""
    if isinstance(v, pd.Series):
        if len(v) == 0:
            return None
        return v.iloc[0]
    return v

def _safe_get(df: pd.DataFrame, k: str, col: str) -> Optional[Any]:
    if col not in df.columns:
        return None
    try:
        v = df.loc[k, col]
    except Exception:
        return None
    return _scalar(v)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap_dir", default=str(SNAP_DIR))
    ap.add_argument("--out", default=str(SNAP_DIR / "movement_latest.csv"))
    args = ap.parse_args()

    snap_dir = Path(args.snap_dir)
    if not snap_dir.exists():
        print(f"Snapshot dir missing: {snap_dir}")
        return 2

    latest = _latest_two_snapshot_paths(snap_dir)
    if len(latest) < 2:
        print(f"Need at least 2 snapshots in {snap_dir}")
        return 1

    newer_path = latest[0]
    older_path = latest[1]

    older = pd.read_csv(older_path)
    newer = pd.read_csv(newer_path)

    older = _ensure_direction(older)
    newer = _ensure_direction(newer)

    key_cols = _choose_key_cols(older, newer)
    if not key_cols:
        print("Could not find common key columns between snapshots.")
        print("Columns (older):", sorted(older.columns.tolist()))
        print("Columns (newer):", sorted(newer.columns.tolist()))
        return 3

    a = older.copy()
    b = newer.copy()
    a["__key__"] = a[key_cols].astype(str).agg("|".join, axis=1)
    b["__key__"] = b[key_cols].astype(str).agg("|".join, axis=1)

    # Index may have duplicates; that's OK as long as we treat loc results as first row.
    a_map = a.set_index("__key__", drop=False)
    b_map = b.set_index("__key__", drop=False)

    keys_a = set(a_map.index)
    keys_b = set(b_map.index)

    added = sorted(keys_b - keys_a)
    removed = sorted(keys_a - keys_b)
    stayed = sorted(keys_a & keys_b)

    change_rows = []
    fields = ["projection_id","player","stat","line","tier","direction","more_allowed","less_allowed","start_time"]

    for k in stayed:
        row = {"key": k}
        for col in fields:
            row[f"{col}_old"] = _safe_get(a_map, k, col)
            row[f"{col}_new"] = _safe_get(b_map, k, col)

        changed = False
        for col in ["line","tier","direction","more_allowed","less_allowed"]:
            if col in a.columns and col in b.columns:
                if row.get(f"{col}_old") != row.get(f"{col}_new"):
                    changed = True
        if changed:
            change_rows.append(row)

    out = []
    for k in added:
        out.append({"change_type": "ADDED", "key": k})
    for k in removed:
        out.append({"change_type": "REMOVED", "key": k})
    for r in change_rows:
        out.append({"change_type": "CHANGED", **r})

    out_df = pd.DataFrame(out)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)

    print(f"Comparing (older) {Path(older_path).name} -> (newer) {Path(newer_path).name}")
    print(f"Key cols: {key_cols}")
    print(f"ADDED: {len(added)}  REMOVED: {len(removed)}  CHANGED: {len(change_rows)}")
    print(f"Wrote: {out_path} (rows={len(out_df)})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

