import json
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\rick\projects\Atlas")
INJ = ROOT / r"data\output\injury\normalized\2026-03-09_03_30PM.json"
SHARE = ROOT / r"data\model\share_matrix.csv"
ORACLE = ROOT / r"tools\oracle_tuner.py"

spec = importlib.util.spec_from_file_location("oracle_tuner", ORACLE)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load module from {ORACLE}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

with open(INJ, "r", encoding="utf-8") as f:
    obj = json.load(f)
rows = obj if isinstance(obj, list) else (obj.get("rows") or obj.get("data") or obj.get("players") or [])


def is_impact_out(r: dict) -> bool:
    status = str(r.get("status") or "").strip().lower()
    reason = str(r.get("reason") or "").strip().lower()
    if status == "probable" or r.get("tag_probable") is True:
        return False
    allowed_status = {"out", "doubtful", "questionable"}
    if status and status not in allowed_status:
        return False
    if not reason:
        return False
    non_impact = [
        "gleague", "g league", "g-league",
        "two-way", "two way",
        "assignment", "on assignment",
        "g league two-way", "gleague-two-way",
    ]
    if any(k in reason for k in non_impact):
        return False
    impact = [
        "injury", "illness", "soreness",
        "sprain", "strain", "fracture", "concussion",
        "rest", "suspension",
        "not with team", "personal", "family",
        "return to competition", "conditioning",
        "ankle", "knee", "hamstring", "groin", "back", "foot", "wrist", "shoulder",
    ]
    return any(k in reason for k in impact)

sm = pd.read_csv(SHARE)
sm_team_col = mod._find_col(sm, ["team", "team_abbrev", "team_u"])
sm_player_col = mod._find_col(sm, ["out_player", "player", "player_name", "name", "player_key"])
share_players_by_team = {}
if sm_team_col and sm_player_col:
    tmp = sm[[sm_team_col, sm_player_col]].copy()
    tmp[sm_team_col] = tmp[sm_team_col].astype(str).str.strip().str.upper()
    tmp[sm_player_col] = tmp[sm_player_col].astype(str).str.strip().map(mod._player_key)
    for t, g in tmp.groupby(sm_team_col):
        share_players_by_team[str(t)] = set(g[sm_player_col].tolist())

TARGETS = ["Isaiah Collier", "Walker Kessler", "Lauri Markkanen", "Jusuf Nurkic"]

count = 0
for name in TARGETS:
    r = next(
        (
            row for row in rows
            if str(row.get("team") or "").strip().upper() == "UTA"
            and str(row.get("player") or row.get("player_name") or row.get("name") or "").strip() == name
        ),
        None,
    )
    if r is None:
        print({"player": name, "found_in_injury_file": False})
        continue
    out_frac = mod._as_float(r.get("out_frac"), 0.0)
    t_raw = r.get("team")
    t = mod._iael_team_to_abbrev(t_raw) if t_raw else None
    p = r.get("player") or r.get("player_name") or r.get("name")
    p_norm = mod._player_key(str(p)) if p else ""
    in_share = bool(share_players_by_team and (t in share_players_by_team) and (p_norm in share_players_by_team[t]))
    oracle_eligible = bool(
        is_impact_out(r)
        and out_frac >= mod.IAEL_PLAYER_OUT_FRAC_THRESHOLD
        and bool(t and p)
        and (not share_players_by_team or (t not in share_players_by_team) or in_share)
    )
    if oracle_eligible:
        count += 1
    print({
        "player": str(p),
        "status": r.get("status"),
        "reason": r.get("reason"),
        "out_frac": out_frac,
        "impact_out": is_impact_out(r),
        "player_key": p_norm,
        "team_abbrev": t,
        "in_share_players_team": in_share,
        "oracle_eligible": oracle_eligible,
    })

print({"ELIGIBLE_UTA_COUNT": count, "THRESHOLD": mod.IAEL_PLAYER_OUT_FRAC_THRESHOLD})
