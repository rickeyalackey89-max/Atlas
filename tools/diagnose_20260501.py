"""Diagnose 2026-05-01: why is raw Brier 0.2241 and calibrator regressing +7.09 mB?

Mirrors the 2026-05-06 diagnostic style. Looks for:
- single-game-dominance (one game = X% of legs)
- direction skew (UNDER overconfidence)
- per-stat anomalies
- big margin misses (favorite blowouts in wrong direction)
- player outliers
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/model/_v1_playoff_resim_cache.pkl"
TARGET_DATE = "2026-05-01"

print("=" * 78, flush=True)
print(f"DIAGNOSE  {TARGET_DATE}", flush=True)
print("=" * 78, flush=True)

with open(CACHE, "rb") as f:
    cache = pickle.load(f)
df = cache["cv"].copy()
df["game_date"] = df["game_date"].astype(str).str[:10]
df = df[df["game_date"] == TARGET_DATE].copy()
df = df.dropna(subset=["hit"])
df = df[df["hit"].isin([0, 1, 0.0, 1.0])]
df["hit"] = df["hit"].astype(float)

print(f"\nLegs: {len(df):,}", flush=True)
print(f"Hit rate: {df['hit'].mean():.4f}", flush=True)
print(f"Cols of interest: p, p_role, p_adj, p_cal, p_for_cal", flush=True)
for c in ["p", "p_role", "p_adj", "p_for_cal", "p_cal"]:
    if c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        b = float(((s - df["hit"]) ** 2).mean())
        print(f"  {c:12s}  mean={s.mean():.4f}  Brier={b:.4f}", flush=True)

# Per-game breakdown
print("\n=== Per-game breakdown (by team/opp pair) ===", flush=True)
if "team" in df.columns and "opp" in df.columns:
    df["game_key"] = df.apply(lambda r: "|".join(sorted([str(r["team"]).upper(), str(r["opp"]).upper()])), axis=1)
    games = df.groupby("game_key").agg(
        n=("hit", "size"),
        hit_rate=("hit", "mean"),
        p_adj_mean=("p_adj", lambda x: pd.to_numeric(x, errors="coerce").mean()),
        brier=("hit", lambda h: float(((pd.to_numeric(df.loc[h.index, "p_adj"], errors="coerce") - h) ** 2).mean())),
    ).sort_values("n", ascending=False)
    games["pct_of_slate"] = (games["n"] / games["n"].sum() * 100).round(1)
    print(games.to_string(), flush=True)
    top = games.iloc[0]
    print(f"\nTop game: {games.index[0]}  ({top['n']} legs, {top['pct_of_slate']:.1f}% of slate, Brier={top['brier']:.4f})", flush=True)

# Direction
print("\n=== Direction breakdown ===", flush=True)
if "direction" in df.columns:
    for d, sub in df.groupby(df["direction"].astype(str).str.upper()):
        p_adj_vals = pd.to_numeric(sub["p_adj"], errors="coerce")
        b = float(((p_adj_vals - sub["hit"]) ** 2).mean())
        print(f"  {d:6s}  n={len(sub):5d}  hit={sub['hit'].mean():.4f}  p_adj_mean={p_adj_vals.mean():.4f}  Brier={b:.4f}", flush=True)

# Stat
print("\n=== Stat breakdown ===", flush=True)
if "stat" in df.columns:
    for s, sub in df.groupby(df["stat"].astype(str).str.upper()):
        if len(sub) < 30:
            continue
        p_adj_vals = pd.to_numeric(sub["p_adj"], errors="coerce")
        b = float(((p_adj_vals - sub["hit"]) ** 2).mean())
        print(f"  {s:8s}  n={len(sub):5d}  hit={sub['hit'].mean():.4f}  p_adj={p_adj_vals.mean():.4f}  Brier={b:.4f}", flush=True)

# Margin / blowout
print("\n=== Blowout regime (q_blowout buckets) ===", flush=True)
if "q_blowout" in df.columns:
    q = pd.to_numeric(df["q_blowout"], errors="coerce")
    df["q_bucket"] = pd.cut(q, [0, 0.1, 0.3, 0.5, 1.01], labels=["calm", "med", "high", "extreme"])
    for b, sub in df.groupby("q_bucket", observed=True):
        p_adj_vals = pd.to_numeric(sub["p_adj"], errors="coerce")
        br = float(((p_adj_vals - sub["hit"]) ** 2).mean())
        print(f"  q={b!s:10s} n={len(sub):5d}  hit={sub['hit'].mean():.4f}  p_adj={p_adj_vals.mean():.4f}  Brier={br:.4f}", flush=True)

# Per-team performance
print("\n=== Per-team Brier (top 6 worst) ===", flush=True)
if "team" in df.columns:
    team_brier = df.groupby(df["team"].astype(str).str.upper()).apply(
        lambda x: float(((pd.to_numeric(x["p_adj"], errors="coerce") - x["hit"]) ** 2).mean()),
        include_groups=False,
    )
    team_n = df.groupby(df["team"].astype(str).str.upper()).size()
    team_hit = df.groupby(df["team"].astype(str).str.upper())["hit"].mean()
    t = pd.DataFrame({"n": team_n, "hit_rate": team_hit, "brier": team_brier}).sort_values("brier", ascending=False)
    print(t.head(6).round(4).to_string(), flush=True)

# Biggest misses
print("\n=== Top 10 biggest individual misses (high p_adj, hit=0 or low p_adj, hit=1) ===", flush=True)
df["p_adj_num"] = pd.to_numeric(df["p_adj"], errors="coerce")
df["miss"] = (df["p_adj_num"] - df["hit"]).abs()
cols = [c for c in ["player", "team", "opp", "stat", "line", "direction", "tier", "p_adj_num", "hit"] if c in df.columns]
print(df.sort_values("miss", ascending=False).head(10)[cols].to_string(index=False), flush=True)

print("\n" + "=" * 78, flush=True)
print("CONCLUSION HEURISTIC", flush=True)
print("=" * 78, flush=True)
if "game_key" in df.columns:
    top_pct = games["pct_of_slate"].iloc[0]
    if top_pct > 40:
        print(f"  Top game dominates {top_pct:.1f}% of slate -- single-game variance risk HIGH", flush=True)
    else:
        print(f"  Top game is {top_pct:.1f}% of slate -- single-game dominance NOT the cause", flush=True)
print(f"  Raw p_adj Brier: {float(((pd.to_numeric(df['p_adj'], errors='coerce') - df['hit']) ** 2).mean()):.4f}", flush=True)
print(f"  Slate hit rate:  {df['hit'].mean():.4f}", flush=True)
print(f"  Mean p_adj:      {pd.to_numeric(df['p_adj'], errors='coerce').mean():.4f}", flush=True)
