"""Debug: count exactly which check rejects candidates in the system builder loop."""
import pandas as pd, yaml, sys, random, os
from collections import Counter
sys.path.insert(0, "C:/Users/13142/Atlas/Atlas/src")
from Atlas.core.slip_scoring import _format_leg, _slip_key, _score_slip
from Atlas.core.slip_builders import _tier_counts_from_legs
from Atlas.core.payout_tables import POWER_MULT

cfg = yaml.safe_load(open("C:/Users/13142/Atlas/Atlas/config.yaml", encoding="utf-8"))
cfg["slip_build"]["min_leg_prob"] = 0.0
cfg["slip_build"].pop("leg_quality_filters", None)

df = pd.read_csv(
    "C:/Users/13142/Atlas/Atlas/data/telemetry/v18_corpus/20260225/scored_legs_deduped.csv",
    low_memory=False
)

# Build p_eff and edge_score (like the builder does internally)
df["p_eff"] = df["p_cal"].copy()
df["edge_score"] = df["p_eff"] - 0.5
df["allocator_score"] = df["edge_score"]

sb = cfg.get("slip_build", {})
max_players_per_team = int(sb.get("max_players_per_team", 2))
no_same_game = bool(sb.get("no_same_game_within_slip", False))
max_same_stat = int(sb.get("max_same_stat", 0) or 0)
max_dir = sb.get("max_direction_per_slip")
n_legs = 3

# Build tier buckets (top 650 per tier)
required_tiers = ["GOBLIN", "STANDARD"]
buckets = {}
for t in required_tiers:
    sub = df[df["tier"] == t].sort_values("allocator_score", ascending=False).head(650).reset_index(drop=True)
    buckets[t] = [sub.iloc[i] for i in range(len(sub))]
    print(f"{t} bucket: {len(buckets[t])} rows, {sub['player'].nunique()} unique players")
    print(f"  top5 players: {sub['player'].value_counts().head(5).to_dict()}")
    print(f"  p_eff range: [{sub['p_eff'].min():.3f}, {sub['p_eff'].max():.3f}]")
    print(f"  team col present: {'team' in sub.columns}")
    if "team" in sub.columns:
        print(f"  top3 teams: {sub['team'].value_counts().head(3).to_dict()}")

mix = {"GOBLIN": 1, "STANDARD": 1}

rng = random.Random(42)
phase_buckets = {t: buckets[t][:65] for t in required_tiers}

rejects = Counter()
ATTEMPTS = 50000

for attempt in range(ATTEMPTS):
    chosen = []
    for t, need in mix.items():
        chosen.extend(rng.sample(phase_buckets[t], int(need)))

    pids, players, ok = [], [], True
    for r in chosen:
        if "projection_id" not in r.index:
            ok = False; break
        pid = str(r["projection_id"]).strip()
        if not pid or pid.lower() == "nan":
            ok = False; break
        pids.append(pid)
        player_name = str(r.get("player", "")).strip().lower()
        players.append(player_name)

    if not ok:
        rejects["missing_pid"] += 1; continue
    if len(set(pids)) != len(pids):
        rejects["dup_pid"] += 1; continue
    if len(set(players)) != len(players):
        rejects["dup_player"] += 1; continue

    if max_players_per_team > 0:
        teams = []
        for r in chosen:
            for k in ("team","team_abbrev","player_team"):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != "nan":
                        teams.append(v); break
        if teams:
            tc = Counter(teams)
            if max(tc.values()) > max_players_per_team:
                rejects["same_team"] += 1; continue

    if no_same_game:
        games = []
        for r in chosen:
            for k in ("game_id","gameId"):
                if k in r.index:
                    v = str(r[k]).strip()
                    if v and v.lower() != "nan":
                        games.append(v); break
        if len(set(games)) != len(games):
            rejects["same_game"] += 1; continue

    if max_same_stat > 0:
        stats = [str(r.get("stat","")).strip().upper() for r in chosen]
        sc = Counter(stats)
        if sc and max(sc.values()) > max_same_stat:
            rejects["same_stat"] += 1; continue

    # score_slip
    scored = _score_slip(chosen, n_legs, POWER_MULT[n_legs], pricing_engine="atlas", cfg=cfg)
    legs_str = scored.get("legs", "")

    # mix_ok — system just needs G+S
    tcs = _tier_counts_from_legs(legs_str)
    if tcs.get("GOBLIN", 0) < 1 or tcs.get("STANDARD", 0) < 1:
        rejects["mix_ok"] += 1; continue

    rejects["OK"] += 1

total = sum(rejects.values())
print(f"\nAttempts={ATTEMPTS}, total={total}")
for k, v in rejects.most_common():
    pct = 100.0 * v / total if total else 0
    print(f"  {k}: {v} ({pct:.1f}%)")
