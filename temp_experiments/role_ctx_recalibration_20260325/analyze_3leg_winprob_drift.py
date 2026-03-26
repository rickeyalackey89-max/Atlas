import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


BASE = Path(r"c:/Users/rick/projects/Atlas")
RUNS = {
    "sixth_cut_baseline": BASE / r"data/telemetry/replay_runs/live_config_rerun_20260317_sixth_cut_combo_under_midq_ra_trim/20260325_232835/runs/20260325_182937",
    "active_teamguard_cap5": BASE / r"data/telemetry/replay_runs/exp_active_config_teamguard_cap5_20260326/20260326_120749/runs/20260326_070912",
    "active_perleg_primary_4only": BASE / r"data/telemetry/replay_runs/exp_active_perleg_primary_4only_20260326/20260326_123834/runs/20260326_074006",
}
BOARD = "recommended_3leg_winprob.csv"


def leg_keys_from_row(row: pd.Series) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for idx in range(1, 4):
        text = str(row.get(f"leg_{idx}") or "")
        id_match = re.search(r"\[id:(\d+)\]", text)
        dir_match = re.search(r"\b(OVER|UNDER)\b", text)
        if id_match and dir_match:
            keys.append((id_match.group(1), dir_match.group(1).upper()))
    return keys


def eval_lookup(eval_df: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "source_projection_id",
        "direction",
        "hit",
        "stat",
        "tier",
        "player",
        "team",
        "role_ctx_outs_used",
        "p_adj",
        "p_cal",
    ]
    cols = [col for col in keep if col in eval_df.columns]
    out = eval_df[cols].copy()
    out["source_projection_id"] = out["source_projection_id"].astype(str)
    out["direction"] = out["direction"].astype(str).str.upper()
    return out.drop_duplicates(subset=["source_projection_id", "direction"], keep="first")


def board_leg_records(board_df: pd.DataFrame, eval_df: pd.DataFrame) -> pd.DataFrame:
    lookup = eval_lookup(eval_df)
    records: list[dict] = []
    for slip_idx, row in board_df.iterrows():
        key_set = set(leg_keys_from_row(row))
        if not key_set:
            continue
        matched = lookup[
            lookup.apply(lambda sample: (sample["source_projection_id"], sample["direction"]) in key_set, axis=1)
        ]
        if len(matched) != len(key_set):
            continue
        for leg_idx, (_, sample) in enumerate(matched.iterrows(), start=1):
            rec = sample.to_dict()
            rec["slip_idx"] = int(slip_idx)
            rec["leg_idx"] = int(leg_idx)
            records.append(rec)
    return pd.DataFrame(records)


def score_prefix(board_df: pd.DataFrame, eval_df: pd.DataFrame, n: int) -> dict | None:
    subset = board_df.head(n)
    if subset.empty:
        return None
    lookup = eval_lookup(eval_df)
    slip_hits: list[int] = []
    leg_hits: list[float] = []
    for _, row in subset.iterrows():
        key_set = set(leg_keys_from_row(row))
        if not key_set:
            continue
        matched = lookup[
            lookup.apply(lambda sample: (sample["source_projection_id"], sample["direction"]) in key_set, axis=1)
        ]
        if len(matched) != len(key_set):
            continue
        hits = pd.to_numeric(matched["hit"], errors="coerce").dropna().tolist()
        if len(hits) != len(key_set):
            continue
        slip_hits.append(1 if all(hit >= 1 for hit in hits) else 0)
        leg_hits.extend(hits)
    if not slip_hits:
        return None
    return {
        "slips": len(slip_hits),
        "slip_hit_rate": float(sum(slip_hits) / len(slip_hits)),
        "leg_hit_rate": float(sum(leg_hits) / len(leg_hits)) if leg_hits else None,
    }


def duplicate_counts(series: pd.Series, top_n: int = 10) -> dict[str, int]:
    counts = Counter(str(v) for v in series.dropna().tolist())
    return dict(counts.most_common(top_n))


def board_summary(board_df: pd.DataFrame, leg_df: pd.DataFrame) -> dict:
    summary = {
        "rows": int(len(board_df)),
        "avg_hit_prob": float(pd.to_numeric(board_df.get("hit_prob"), errors="coerce").mean()),
        "avg_avg_p": float(pd.to_numeric(board_df.get("avg_p"), errors="coerce").mean()),
        "avg_fragility": float(pd.to_numeric(board_df.get("avg_fragility"), errors="coerce").mean()),
        "avg_pen_total": float(pd.to_numeric(board_df.get("pen_total"), errors="coerce").mean()),
        "avg_role_ctx_on_share": float(pd.to_numeric(board_df.get("role_ctx_on_share"), errors="coerce").mean()),
    }
    if leg_df.empty:
        summary["matched_leg_rows"] = 0
        return summary
    role_used = pd.to_numeric(leg_df.get("role_ctx_outs_used", 0.0), errors="coerce")
    summary.update(
        {
            "matched_leg_rows": int(len(leg_df)),
            "player_counts": duplicate_counts(leg_df["player"]),
            "team_counts": duplicate_counts(leg_df["team"]),
            "stat_counts": duplicate_counts(leg_df["stat"]),
            "direction_counts": duplicate_counts(leg_df["direction"]),
            "tier_counts": duplicate_counts(leg_df["tier"]),
            "role_ctx_used_share": float(role_used.fillna(0.0).gt(0).mean()) if len(role_used) else 0.0,
            "mean_p_adj": float(pd.to_numeric(leg_df.get("p_adj"), errors="coerce").mean()),
            "mean_p_cal": float(pd.to_numeric(leg_df.get("p_cal"), errors="coerce").mean()),
        }
    )
    return summary


def overlap(base_board: pd.DataFrame, other_board: pd.DataFrame) -> dict:
    base_keys = {str(v) for v in base_board.get("slip_key", pd.Series(dtype=object)).dropna().tolist()}
    other_keys = {str(v) for v in other_board.get("slip_key", pd.Series(dtype=object)).dropna().tolist()}
    if not base_keys and not other_keys:
        return {"shared": 0, "base_only": 0, "other_only": 0}
    return {
        "shared": int(len(base_keys & other_keys)),
        "base_only": int(len(base_keys - other_keys)),
        "other_only": int(len(other_keys - base_keys)),
    }


def main() -> None:
    boards: dict[str, pd.DataFrame] = {}
    evals: dict[str, pd.DataFrame] = {}
    out: dict[str, dict] = {}
    for name, run_dir in RUNS.items():
        boards[name] = pd.read_csv(run_dir / BOARD)
        evals[name] = pd.read_csv(run_dir / "eval_legs.csv", low_memory=False)
        leg_df = board_leg_records(boards[name], evals[name])
        out[name] = {
            "board_summary": board_summary(boards[name], leg_df),
            "prefix_3": score_prefix(boards[name], evals[name], 3),
            "prefix_5": score_prefix(boards[name], evals[name], 5),
            "prefix_10": score_prefix(boards[name], evals[name], 10),
        }

    baseline_name = "active_teamguard_cap5"
    baseline_board = boards[baseline_name]
    out["overlap_vs_active_teamguard_cap5"] = {
        name: overlap(baseline_board, board_df)
        for name, board_df in boards.items()
        if name != baseline_name
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()