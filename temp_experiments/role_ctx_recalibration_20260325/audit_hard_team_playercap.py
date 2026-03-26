import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


import os


RUN_DIR = Path(
    os.environ.get(
        "ATLAS_AUDIT_RUN_DIR",
        r"c:/Users/rick/projects/Atlas/data/telemetry/replay_runs/exp_role_ctx_hard_team_playercap_20260326/20260326_115143/runs/20260326_065309",
    )
)
BOARDS = [
    "recommended_3leg.csv",
    "recommended_4leg.csv",
    "recommended_5leg.csv",
    "recommended_3leg_winprob.csv",
    "recommended_4leg_winprob.csv",
    "recommended_5leg_winprob.csv",
]


def main() -> None:
    if not RUN_DIR.exists():
        raise FileNotFoundError(f"Run dir not found: {RUN_DIR}")
    eval_df = pd.read_csv(RUN_DIR / "eval_legs.csv", low_memory=False)
    eval_df["source_projection_id"] = eval_df["source_projection_id"].astype(str)
    eval_df["direction"] = eval_df["direction"].astype(str).str.upper()

    out = {}
    for board in BOARDS:
        df = pd.read_csv(RUN_DIR / board)
        player_counts: dict[str, int] = {}
        same_team_violations = 0
        max_same_team_in_slip = 0

        for _, row in df.iterrows():
            teams = []
            players = []

            for idx in range(1, 6):
                val = row.get(f"leg_{idx}")
                if pd.isna(val):
                    continue
                text = str(val)
                player = text.split(" OVER ", 1)[0].split(" UNDER ", 1)[0].strip().lower()
                if player:
                    players.append(player)

                id_match = re.search(r"\[id:(\d+)\]", text)
                direction_match = re.search(r"\b(OVER|UNDER)\b", text)
                if not id_match or not direction_match:
                    continue

                matched = eval_df[
                    (eval_df["source_projection_id"] == id_match.group(1))
                    & (eval_df["direction"] == direction_match.group(1).upper())
                ]
                if not matched.empty:
                    team = str(matched.iloc[0].get("team", "")).strip()
                    if team:
                        teams.append(team)

            team_counts = Counter(teams)
            if team_counts:
                max_same_team_in_slip = max(max_same_team_in_slip, max(team_counts.values()))
                if any(value > 1 for value in team_counts.values()):
                    same_team_violations += 1

            for player in set(players):
                player_counts[player] = player_counts.get(player, 0) + 1

        out[board] = {
            "rows": len(df),
            "same_team_violations": same_team_violations,
            "max_same_team_in_slip": max_same_team_in_slip,
            "max_player_exposure": max(player_counts.values()) if player_counts else 0,
            "top_player_exposure": dict(sorted(player_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]),
        }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()