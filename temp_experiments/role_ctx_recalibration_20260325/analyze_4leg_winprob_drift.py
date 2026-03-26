import json
import re
from pathlib import Path

import pandas as pd


BASE = Path(r"c:/Users/rick/projects/Atlas")
RUNS = {
    "baseline": BASE / r"data/telemetry/replay_runs/live_config_rerun_20260317_sixth_cut_combo_under_midq_ra_trim/20260325_232835/runs/20260325_182937",
    "promoted_active": BASE / r"data/telemetry/replay_runs/exp_role_ctx_promoted_active_20260325/20260326_022546/runs/20260325_212708",
    "funnel_broad_late": BASE / r"data/telemetry/replay_runs/exp_role_ctx_funnel_broad_late_20260325/20260326_024050/runs/20260325_214205",
}
BOARD = "recommended_4leg_winprob.csv"


def leg_keys_from_row(row: pd.Series) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for idx in range(1, 5):
        val = row.get(f"leg_{idx}")
        if pd.isna(val):
            continue
        text = str(val)
        id_match = re.search(r"\[id:(\d+)\]", text)
        dir_match = re.search(r"\b(OVER|UNDER)\b", text)
        if id_match and dir_match:
            keys.append((id_match.group(1), dir_match.group(1).upper()))
    return keys


def score_prefix(board_df: pd.DataFrame, eval_df: pd.DataFrame, n: int):
    subset = board_df.head(n)
    if subset.empty:
        return None
    eval_small = eval_df[["source_projection_id", "direction", "hit", "stat", "tier", "player", "team"]].copy()
    eval_small["source_projection_id"] = eval_small["source_projection_id"].astype(str)
    eval_small["direction"] = eval_small["direction"].astype(str).str.upper()
    slip_hits = []
    leg_hits = []
    leg_meta: list[dict] = []
    for _, row in subset.iterrows():
        keys = leg_keys_from_row(row)
        if not keys:
            continue
        key_set = set(keys)
        matched = eval_small[
            eval_small.apply(lambda sample: (sample["source_projection_id"], sample["direction"]) in key_set, axis=1)
        ].drop_duplicates(subset=["source_projection_id", "direction"], keep="first")
        if len(matched) != len(keys):
            continue
        vals = pd.to_numeric(matched["hit"], errors="coerce").dropna().tolist()
        if len(vals) != len(keys):
            continue
        slip_hits.append(1 if all(v >= 1 for v in vals) else 0)
        leg_hits.extend(vals)
        leg_meta.extend(matched.to_dict("records"))
    if not slip_hits:
        return None
    meta_df = pd.DataFrame(leg_meta) if leg_meta else pd.DataFrame()
    return {
        "slips": len(slip_hits),
        "slip_hit_rate": float(sum(slip_hits) / len(slip_hits)),
        "leg_hit_rate": float(sum(leg_hits) / len(leg_hits)) if leg_hits else None,
        "players_top": meta_df["player"].value_counts().head(8).to_dict() if not meta_df.empty else {},
        "stats_top": meta_df["stat"].value_counts().to_dict() if not meta_df.empty else {},
        "teams_top": meta_df["team"].value_counts().head(8).to_dict() if not meta_df.empty else {},
        "tiers": meta_df["tier"].value_counts().to_dict() if not meta_df.empty else {},
        "directions": meta_df["direction"].value_counts().to_dict() if not meta_df.empty else {},
    }


def board_summary(board_df: pd.DataFrame):
    return {
        "rows": int(len(board_df)),
        "avg_hit_prob": float(pd.to_numeric(board_df["hit_prob"], errors="coerce").mean()),
        "avg_avg_p": float(pd.to_numeric(board_df["avg_p"], errors="coerce").mean()),
        "avg_fragility": float(pd.to_numeric(board_df["avg_fragility"], errors="coerce").mean()),
        "avg_pen_total": float(pd.to_numeric(board_df["pen_total"], errors="coerce").mean()),
        "avg_role_ctx_on_share": float(pd.to_numeric(board_df["role_ctx_on_share"], errors="coerce").mean()),
        "avg_role_ctx_on_legs": float(pd.to_numeric(board_df["role_ctx_on_legs"], errors="coerce").mean()),
    }


def main() -> None:
    out = {}
    for name, run_dir in RUNS.items():
        board_df = pd.read_csv(run_dir / BOARD)
        eval_df = pd.read_csv(run_dir / "eval_legs.csv", low_memory=False)
        out[name] = {
            "board_summary": board_summary(board_df),
            "prefix_4": score_prefix(board_df, eval_df, 4),
            "prefix_5": score_prefix(board_df, eval_df, 5),
            "prefix_10": score_prefix(board_df, eval_df, 10),
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()