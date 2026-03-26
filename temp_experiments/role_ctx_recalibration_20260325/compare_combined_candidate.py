import ast
import json
import re
from pathlib import Path

import pandas as pd


BASE = Path(r"c:/Users/rick/projects/Atlas")
RUNS = {
    "baseline": BASE / r"data/telemetry/replay_runs/live_config_rerun_20260317_sixth_cut_combo_under_midq_ra_trim/20260325_232835/runs/20260325_182937",
    "role_ctx_proposed": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_cal_20260325/20260326_015547/runs/20260325_205650",
    "promoted_active": BASE / r"data/telemetry/replay_runs/exp_role_ctx_promoted_active_20260325/20260326_022546/runs/20260325_212708",
    "role_ctx_proposed_hit": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_hit_20260325/20260326_020049/runs/20260325_210158",
    "role_ctx_proposed_h010": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_h010_20260325/20260326_022716/runs/20260325_212826",
    "role_ctx_proposed_h015": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_h015_20260325/20260326_022853/runs/20260325_213000",
    "role_ctx_proposed_search400": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_search400_20260325/20260326_023124/runs/20260325_213234",
    "role_ctx_proposed_search500": BASE / r"data/telemetry/replay_runs/exp_role_ctx_proposed_search500_20260325/20260326_023237/runs/20260325_213355",
    "funnel_broad_early": BASE / r"data/telemetry/replay_runs/exp_role_ctx_funnel_broad_early_20260325/20260326_023852/runs/20260325_214004",
    "funnel_narrow_early": BASE / r"data/telemetry/replay_runs/exp_role_ctx_funnel_narrow_early_20260325/20260326_024008/runs/20260325_214046",
    "funnel_broad_late": BASE / r"data/telemetry/replay_runs/exp_role_ctx_funnel_broad_late_20260325/20260326_024050/runs/20260325_214205",
    "search500_broad_late": BASE / r"data/telemetry/replay_runs/exp_role_ctx_search500_broad_late_20260325/20260326_024313/runs/20260325_214435",
    "broad_late_penalty_winprob": BASE / r"data/telemetry/replay_runs/exp_role_ctx_broad_late_penalty_winprob_20260325/20260326_025251/runs/20260325_215404",
    "broad_late_penalty_rolecap": BASE / r"data/telemetry/replay_runs/exp_role_ctx_broad_late_penalty_rolecap_20260325/20260326_025550/runs/20260325_215704",
    "hard_team_playercap": BASE / r"data/telemetry/replay_runs/exp_role_ctx_hard_team_playercap_20260326/20260326_115143/runs/20260326_065309",
    "hard_team_playercap5": BASE / r"data/telemetry/replay_runs/exp_role_ctx_hard_team_playercap5_20260326/20260326_115908/runs/20260326_070031",
    "active_teamguard_cap5": BASE / r"data/telemetry/replay_runs/exp_active_config_teamguard_cap5_20260326/20260326_120749/runs/20260326_070912",
    "active_perleg_tuned": BASE / r"data/telemetry/replay_runs/exp_active_perleg_tuned_20260326/20260326_121337/runs/20260326_071506",
    "active_perleg_tuned_fixed": BASE / r"data/telemetry/replay_runs/exp_active_perleg_tuned_fixed_20260326/20260326_122544/runs/20260326_072700",
    "active_perleg_primary_only": BASE / r"data/telemetry/replay_runs/exp_active_perleg_primary_only_20260326/20260326_123251/runs/20260326_073408",
    "active_perleg_primary_only_fix": BASE / r"data/telemetry/replay_runs/exp_active_perleg_primary_only_fix_20260326/20260326_123535/runs/20260326_073659",
    "active_perleg_primary_4only": BASE / r"data/telemetry/replay_runs/exp_active_perleg_primary_4only_20260326/20260326_123834/runs/20260326_074006",
    "winprob3_precision_a": BASE / r"data/telemetry/replay_runs/exp_winprob3_precision_a_20260326/20260326_124622/runs/20260326_074753",
    "winprob3_precision_b": BASE / r"data/telemetry/replay_runs/exp_winprob3_precision_b_20260326/20260326_124802/runs/20260326_074933",
    "winprob_rank_a": BASE / r"data/telemetry/replay_runs/exp_winprob_rank_a_20260326/20260326_130506/runs/20260326_080654",
    "winprob_rank_b": BASE / r"data/telemetry/replay_runs/exp_winprob_rank_b_20260326/20260326_130702/runs/20260326_080836",
    "hit_penalty_a": BASE / r"data/telemetry/replay_runs/exp_hit_penalty_a_20260326/20260326_131412/runs/20260326_081542",
    "hit_penalty_b": BASE / r"data/telemetry/replay_runs/exp_hit_penalty_b_20260326/20260326_131553/runs/20260326_081729",
    "hit3_playercap2": BASE / r"data/telemetry/replay_runs/exp_hit3_playercap2_20260326/20260326_133221/runs/20260326_083412",
    "hit3_playercap1": BASE / r"data/telemetry/replay_runs/exp_hit3_playercap1_20260326/20260326_133421/runs/20260326_083605",
    "hit34_playercap2_3": BASE / r"data/telemetry/replay_runs/exp_hit34_playercap2_3_20260326/20260326_134505/runs/20260326_084640",
    "hit34_playercap2_4": BASE / r"data/telemetry/replay_runs/exp_hit34_playercap2_4_20260326/20260326_134654/runs/20260326_084829",
}
BOARDS = [
    "recommended_3leg.csv",
    "recommended_4leg.csv",
    "recommended_5leg.csv",
    "recommended_3leg_winprob.csv",
    "recommended_4leg_winprob.csv",
    "recommended_5leg_winprob.csv",
]


def brier(df: pd.DataFrame, col: str) -> float:
    sample = df[[col, "hit"]].dropna()
    if sample.empty:
        return float("nan")
    probs = pd.to_numeric(sample[col], errors="coerce")
    hits = pd.to_numeric(sample["hit"], errors="coerce")
    mask = probs.notna() & hits.notna()
    if not mask.any():
        return float("nan")
    return float(((probs[mask] - hits[mask]) ** 2).mean())


def leg_keys_from_legs(val) -> list[tuple[str, str]]:
    if pd.isna(val):
        return []
    text = str(val)
    try:
        parsed = ast.literal_eval(text)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        keys = []
        for item in parsed:
            if isinstance(item, dict):
                projection_id = item.get("source_projection_id")
                direction = item.get("direction")
                if projection_id is not None and direction is not None:
                    keys.append((str(projection_id), str(direction).upper()))
        if keys:
            return keys
    needle = "'source_projection_id': "
    start = 0
    keys = []
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        j = idx + len(needle)
        k = j
        while k < len(text) and text[k] not in ",}":
            k += 1
        projection_id = text[j:k].strip().strip("'\"")
        direction_match = re.search(r"'direction':\s*'([^']+)'", text[k:])
        if projection_id and direction_match:
            keys.append((projection_id, direction_match.group(1).upper()))
        start = k
    if keys:
        return keys
    fallback_keys = []
    for piece in text.split("|"):
        id_match = re.search(r"\[id:(\d+)\]", piece)
        direction_match = re.search(r"\b(OVER|UNDER)\b", piece)
        if id_match and direction_match:
            fallback_keys.append((id_match.group(1), direction_match.group(1).upper()))
    return fallback_keys


def score_board(run_dir: Path, board_name: str):
    rec_path = run_dir / board_name
    eval_path = run_dir / "eval_legs.csv"
    if not rec_path.exists() or not eval_path.exists():
        return None
    rec = pd.read_csv(rec_path)
    eva = pd.read_csv(eval_path, low_memory=False)
    if rec.empty or eva.empty:
        return None
    if "source_projection_id" not in eva.columns or "direction" not in eva.columns or "hit" not in eva.columns:
        return None
    eva = eva[["source_projection_id", "direction", "hit"]].copy()
    eva["source_projection_id"] = eva["source_projection_id"].astype(str)
    eva["direction"] = eva["direction"].astype(str).str.upper()
    slip_hits = []
    leg_hits = []
    leg_count = 0
    for _, row in rec.iterrows():
        keys = leg_keys_from_legs(row.get("legs"))
        if not keys:
            continue
        key_set = set(keys)
        matched = eva[eva.apply(lambda sample: (sample["source_projection_id"], sample["direction"]) in key_set, axis=1)]
        matched = matched.drop_duplicates(subset=["source_projection_id", "direction"], keep="first")
        if len(matched) != len(keys):
            continue
        values = pd.to_numeric(matched["hit"], errors="coerce").dropna().tolist()
        if len(values) != len(keys):
            continue
        slip_hits.append(1 if all(value >= 1 for value in values) else 0)
        leg_hits.extend(values)
        leg_count += len(values)
    if not slip_hits:
        return None
    return {
        "slips": len(slip_hits),
        "legs": leg_count,
        "slip_hit_rate": float(sum(slip_hits) / len(slip_hits)),
        "leg_hit_rate": float(sum(leg_hits) / len(leg_hits)) if leg_hits else float("nan"),
    }


def main() -> None:
    out = {}
    for name, run_dir in RUNS.items():
        eval_df = pd.read_csv(run_dir / "eval_legs.csv", low_memory=False)
        out[name] = {
            "brier_p_adj": brier(eval_df, "p_adj"),
            "brier_p_cal": brier(eval_df, "p_cal"),
            "boards": {board: score_board(run_dir, board) for board in BOARDS},
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()