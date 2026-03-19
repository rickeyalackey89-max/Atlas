from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def _norm_str(s: pd.Series) -> pd.Series:
    return s.astype(str).fillna("").str.strip()


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: py .\\tools\\compare_today_csvs.py <replay_csv> <live_csv>")
        return 2

    replay_path = Path(sys.argv[1])
    live_path = Path(sys.argv[2])

    if not replay_path.exists():
        print(f"Missing replay CSV: {replay_path}")
        return 2
    if not live_path.exists():
        print(f"Missing live CSV: {live_path}")
        return 2

    a = pd.read_csv(replay_path)
    b = pd.read_csv(live_path)

    preferred_key = [
        "projection_id",
        "source_projection_id",
        "player_key",
        "stat",
        "line",
        "direction",
        "tier",
        "game_id",
        "game_date",
    ]
    key = [c for c in preferred_key if c in a.columns and c in b.columns]

    if not key:
        print("No shared comparison key columns found.")
        return 3

    aa = a.copy()
    bb = b.copy()

    for c in key:
        if c == "line":
            aa[c] = pd.to_numeric(aa[c], errors="coerce")
            bb[c] = pd.to_numeric(bb[c], errors="coerce")
        else:
            aa[c] = _norm_str(aa[c])
            bb[c] = _norm_str(bb[c])

    common_cols = [c for c in aa.columns if c in bb.columns]
    aa = aa[common_cols].copy()
    bb = bb[common_cols].copy()

    ga = aa.groupby(key, dropna=False).size().reset_index(name="n_replay")
    gb = bb.groupby(key, dropna=False).size().reset_index(name="n_live")

    print(f"key={key}")
    print(f"replay_rows={len(aa)}")
    print(f"live_rows={len(bb)}")
    print(f"replay_dup_keys={int((ga['n_replay'] > 1).sum())}")
    print(f"live_dup_keys={int((gb['n_live'] > 1).sum())}")

    outer = ga.merge(gb, on=key, how="outer").fillna(0)
    mismatched_counts = outer[outer["n_replay"] != outer["n_live"]].copy()
    print(f"key_count_mismatches={len(mismatched_counts)}")
    if not mismatched_counts.empty:
        print("count_mismatch_sample:")
        print(mismatched_counts.head(20).to_string(index=False))

    xa = aa.groupby(key, dropna=False).first().reset_index()
    xb = bb.groupby(key, dropna=False).first().reset_index()
    m = xa.merge(xb, on=key, how="outer", suffixes=("_replay", "_live"), indicator=True)

    left_only = int((m["_merge"] == "left_only").sum())
    right_only = int((m["_merge"] == "right_only").sum())
    both = int((m["_merge"] == "both").sum())

    print(f"left_only={left_only}")
    print(f"right_only={right_only}")
    print(f"shared_keys={both}")

    shared = m[m["_merge"] == "both"].copy()
    compare_cols = [c for c in common_cols if c not in key]
    diffs = []

    for c in compare_cols:
        rc = f"{c}_replay"
        lc = f"{c}_live"
        if rc not in shared.columns or lc not in shared.columns:
            continue
        s1 = shared[rc]
        s2 = shared[lc]
        if pd.api.types.is_numeric_dtype(s1) or pd.api.types.is_numeric_dtype(s2):
            neq = (
                pd.to_numeric(s1, errors="coerce").fillna(-999999)
                != pd.to_numeric(s2, errors="coerce").fillna(-999999)
            )
        else:
            neq = _norm_str(s1) != _norm_str(s2)
        changed = int(neq.sum())
        if changed > 0:
            diffs.append((c, changed))

    print(f"changed_columns={diffs[:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
