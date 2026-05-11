"""Quantify the regime gaps between regular season and playoff gamelogs."""
import pandas as pd
import numpy as np
import pathlib

gl = pd.read_csv('data/gamelogs/nba_gamelogs.csv', low_memory=False)
gl['game_date'] = pd.to_datetime(gl['game_date'], errors='coerce')
gl['minutes'] = pd.to_numeric(gl['minutes'], errors='coerce')

PLAYOFF_START = pd.Timestamp('2026-04-30')
reg = gl[gl['game_date'] < PLAYOFF_START]
po  = gl[gl['game_date'] >= PLAYOFF_START]

print("=== Minutes Distribution ===")
print(f"Regular season: mean={reg['minutes'].mean():.2f}  median={reg['minutes'].median():.1f}  std={reg['minutes'].std():.2f}")
print(f"Playoffs:       mean={po['minutes'].mean():.2f}  median={po['minutes'].median():.1f}  std={po['minutes'].std():.2f}")

# Starters only (30+ min)
reg_st = reg[reg['minutes'] >= 30]
po_st  = po[po['minutes'] >= 30]
print(f"\nStarters (>=30 min):")
print(f"  Regular season: {len(reg_st):,} rows  mean={reg_st['minutes'].mean():.2f}")
print(f"  Playoffs:       {len(po_st):,} rows  mean={po_st['minutes'].mean():.2f}")

# Pace proxy
if all(c in gl.columns for c in ['fga', 'fta', 'tov']):
    for df, lbl in [(reg, 'Regular season'), (po, 'Playoffs')]:
        fga = pd.to_numeric(df['fga'], errors='coerce').fillna(0)
        fta = pd.to_numeric(df['fta'], errors='coerce').fillna(0)
        tov = pd.to_numeric(df['tov'], errors='coerce').fillna(0)
        poss = fga + 0.44 * fta + tov
        print(f"\n{lbl} pace proxy (FGA+0.44*FTA+TOV): {poss.mean():.2f}")

# Rotation depth
if 'team' in gl.columns:
    print("\n=== Rotation Depth (players per team-game with any minutes) ===")
    for df, lbl in [(reg, 'Regular season'), (po, 'Playoffs')]:
        tg = df.groupby(['team', 'game_date'])['minutes'].count()
        print(f"  {lbl}: mean={tg.mean():.1f}  median={tg.median():.1f}")

# L20 window regime contamination on latest date
print("\n=== L20 Window Regime Contamination (as of today) ===")
latest = gl['game_date'].max()
l20_cutoff = latest - pd.Timedelta(days=28)  # ~20 game days
window = gl[gl['game_date'] >= l20_cutoff]
po_days = window[window['game_date'] >= PLAYOFF_START]['game_date'].dt.date.nunique()
reg_days = window[window['game_date'] < PLAYOFF_START]['game_date'].dt.date.nunique()
print(f"  Latest game date: {latest.date()}")
print(f"  L20 window since: {l20_cutoff.date()}")
print(f"  Playoff game-dates: {po_days}  |  Regular season game-dates: {reg_days}")
print(f"  Playoff fraction of L20 window: {po_days / max(po_days + reg_days, 1):.1%}")

# Rate comparison for key stats
print("\n=== Per-Minute Rate: Regular Season vs Playoffs ===")
for stat_col in ['pts', 'reb', 'ast', 'fg3m']:
    if stat_col not in gl.columns:
        continue
    for df, lbl in [(reg, 'RS'), (po, 'PO')]:
        mins = pd.to_numeric(df['minutes'], errors='coerce')
        stat = pd.to_numeric(df[stat_col], errors='coerce')
        valid = mins.notna() & mins.gt(0)
        rates = (stat[valid] / mins[valid]).dropna()
        print(f"  {stat_col.upper():<6} {lbl}: rate/min={rates.mean():.3f}")
    print()

# How much do starters actually play more in playoffs
print("=== Top-minutes players: regular season vs playoffs ===")
if 'player' in gl.columns:
    reg_top = reg.groupby('player')['minutes'].mean().sort_values(ascending=False).head(20)
    po_top_players = po.groupby('player')['minutes'].mean().sort_values(ascending=False).head(20)
    # Cross-reference: same players in both
    common = set(reg_top.index) & set(po_top_players.index)
    for p in sorted(common)[:10]:
        rs_min = reg[reg['player'] == p]['minutes'].mean()
        po_min = po[po['player'] == p]['minutes'].mean()
        print(f"  {p:<25} RS={rs_min:.1f}  PO={po_min:.1f}  delta={po_min-rs_min:+.1f}")
