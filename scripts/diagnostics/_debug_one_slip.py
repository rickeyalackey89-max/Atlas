import pandas as pd, yaml, sys
sys.path.insert(0, "C:/Users/13142/Atlas/NBA/src")
from Atlas.core.slip_scoring import _format_leg, _score_slip
from Atlas.core.slip_builders import _tier_counts_from_legs, _windfall_mix_ok
from Atlas.core.payout_tables import POWER_MULT

cfg = yaml.safe_load(open("C:/Users/13142/Atlas/NBA/config.yaml", encoding="utf-8"))
cfg["slip_build"]["min_leg_prob"] = 0.0

df = pd.read_csv("C:/Users/13142/Atlas/NBA/data/telemetry/v18_corpus/20260225/scored_legs_deduped.csv", low_memory=False)

g = df[df["tier"]=="GOBLIN"].iloc[10]
s = df[df["tier"]=="STANDARD"].iloc[10]
d = df[df["tier"]=="DEMON"].iloc[10]
chosen = [g, s, d]

for r in chosen:
    pid = str(r["projection_id"]).strip()
    player = str(r["player"]).strip()
    print(f"  {r['tier']}: player={player}  pid={repr(pid)}  pid_is_nan={pid.lower()=='nan'}")

players = [str(r["player"]).strip().lower() for r in chosen]
pids    = [str(r["projection_id"]).strip() for r in chosen]
print("Dup players:", len(set(players)) != len(players), players)
print("Dup pids:   ", len(set(pids)) != len(pids))

scored = _score_slip(chosen, 3, POWER_MULT[3], pricing_engine="atlas", cfg=cfg)
legs_str = scored.get("legs", "")
print("legs_str:", legs_str)
print("mix_ok:", _windfall_mix_ok(3, legs_str))
print("tier_counts:", _tier_counts_from_legs(legs_str))

