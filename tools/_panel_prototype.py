"""Panel feasibility prototype.

Goal: prove that a star-out signal in gamelogs produces measurable, sensible
beneficiary stat swings — i.e., that the panel approach can grade the share matrix.

Strategy:
1. Define "out" purely from gamelogs: a player played 4+ of their team's last 5 games
   but missed game G → flagged as out for G.
2. For each out, compute beneficiary-level stat deltas vs the same teammate's
   baseline over the prior 10 games where the out player played.
3. Aggregate by (out_role_class, beneficiary_role_class, stat) to see if the
   observed swings move the way the philosophy says they should.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

GL_PATH = Path('data/gamelogs/nba_gamelogs.csv')
WINDOW_BEFORE = 10
WINDOW_RECENCY = 5  # of last N team games, must have played 4+
MIN_PRESENT = 4

print('=== Loading gamelogs ===')
gl = pd.read_csv(GL_PATH, low_memory=False)
gl['game_date'] = pd.to_datetime(gl['game_date'], errors='coerce')
gl = gl.dropna(subset=['game_date']).sort_values('game_date').reset_index(drop=True)
gl['minutes'] = pd.to_numeric(gl['minutes'], errors='coerce').fillna(0.0)
for c in ('pts', 'reb', 'ast', 'fg3m'):
    gl[c] = pd.to_numeric(gl[c], errors='coerce').fillna(0.0)

print(f'Rows: {len(gl):,}  Players: {gl["player"].nunique()}  Teams: {gl["team"].nunique()}')

# Build per-team game schedule
team_games = (
    gl.groupby(['team', 'game_date'], as_index=False)
      .size()
      .rename(columns={'size': 'n_players'})
      .sort_values(['team', 'game_date'])
)
team_games['team_game_idx'] = team_games.groupby('team').cumcount()
print(f'Team-game rows: {len(team_games):,}')

# Merge team_game_idx onto player rows
gl = gl.merge(team_games[['team', 'game_date', 'team_game_idx']], on=['team', 'game_date'], how='left')

# For each (player, team) pair, compute their season averages and identify out games
print('\n=== Detecting out events ===')
out_events: list[dict] = []

# Restrict to playoff window (last ~30 days) for prototype speed
cutoff = gl['game_date'].max() - pd.Timedelta(days=30)
recent = gl[gl['game_date'] >= cutoff].copy()
print(f'Restricting to {cutoff.date()}+ for prototype: {len(recent):,} rows')

for (team, player), pdf in recent.groupby(['team', 'player']):
    pdf = pdf.sort_values('game_date')
    games_played = set(pdf['game_date'])
    avg_min = pdf['minutes'].mean()
    if avg_min < 15:  # only consider rotation players
        continue
    n_games = len(pdf)
    if n_games < 5:
        continue
    # All team games in the window
    tg = team_games[team_games['team'] == team].copy()
    tg = tg[tg['game_date'] >= recent['game_date'].min()].sort_values('game_date').reset_index(drop=True)
    for i in range(WINDOW_RECENCY, len(tg)):
        gd = tg.iloc[i]['game_date']
        if gd in games_played:
            continue  # he played, not out
        # Check last WINDOW_RECENCY games — was he in 4+ of them?
        prior_dates = tg.iloc[i - WINDOW_RECENCY:i]['game_date'].tolist()
        present_count = sum(1 for d in prior_dates if d in games_played)
        if present_count >= MIN_PRESENT:
            out_events.append({
                'team': team, 'player': player, 'game_date': gd,
                'avg_min': avg_min, 'avg_pts': pdf['pts'].mean(),
                'avg_reb': pdf['reb'].mean(), 'avg_ast': pdf['ast'].mean(),
                'season_games': n_games,
            })

out_df = pd.DataFrame(out_events)
print(f'Out events detected: {len(out_df):,}')
print(f'Unique out players: {out_df["player"].nunique()}')
print(f'Unique teams affected: {out_df["team"].nunique()}')
print(f'\nTop 10 most-frequent outs:')
print(out_df['player'].value_counts().head(10).to_string())

# Classify outs by minutes
def classify(row):
    if row['avg_min'] >= 32 or row['avg_pts'] >= 22:
        return 'star'
    if row['avg_min'] >= 24 or row['avg_pts'] >= 12:
        return 'core'
    return 'role'
out_df['out_class'] = out_df.apply(classify, axis=1)
print(f'\nOut class distribution:')
print(out_df['out_class'].value_counts().to_string())

# === For star outs, compute beneficiary swings ===
print('\n=== Beneficiary stat swings (star outs only) ===')
star_outs = out_df[out_df['out_class'] == 'star'].head(50)  # cap for prototype

records = []
for _, oev in star_outs.iterrows():
    team = oev['team']; gd = oev['game_date']; out_player = oev['player']
    # Beneficiaries = teammates who played in this game
    box = gl[(gl['team'] == team) & (gl['game_date'] == gd)]
    box = box[box['player'] != out_player]
    box = box[box['minutes'] > 0]
    for _, b in box.iterrows():
        bname = b['player']
        # Baseline: same player's stats over last 10 games where out_player WAS present
        out_present_dates = set(gl[(gl['team'] == team) & (gl['player'] == out_player) & (gl['game_date'] < gd)]['game_date'].tail(10))
        baseline = gl[(gl['team'] == team) & (gl['player'] == bname) & (gl['game_date'].isin(out_present_dates))]
        if len(baseline) < 4:
            continue
        records.append({
            'team': team, 'out_player': out_player, 'beneficiary': bname,
            'game_date': gd,
            'b_min_actual': b['minutes'],
            'b_min_baseline': baseline['minutes'].mean(),
            'b_pts_actual': b['pts'], 'b_pts_baseline': baseline['pts'].mean(),
            'b_ast_actual': b['ast'], 'b_ast_baseline': baseline['ast'].mean(),
            'b_reb_actual': b['reb'], 'b_reb_baseline': baseline['reb'].mean(),
        })

panel = pd.DataFrame(records)
print(f'Beneficiary observations: {len(panel):,}')
if len(panel) > 0:
    panel['d_min'] = panel['b_min_actual'] - panel['b_min_baseline']
    panel['d_pts'] = panel['b_pts_actual'] - panel['b_pts_baseline']
    panel['d_ast'] = panel['b_ast_actual'] - panel['b_ast_baseline']
    panel['d_reb'] = panel['b_reb_actual'] - panel['b_reb_baseline']
    print(f'\nMean swings (star out → teammate actual minus baseline):')
    print(f'  d_min: {panel["d_min"].mean():+.2f}  median: {panel["d_min"].median():+.2f}  std: {panel["d_min"].std():.2f}')
    print(f'  d_pts: {panel["d_pts"].mean():+.2f}  median: {panel["d_pts"].median():+.2f}  std: {panel["d_pts"].std():.2f}')
    print(f'  d_ast: {panel["d_ast"].mean():+.2f}  median: {panel["d_ast"].median():+.2f}  std: {panel["d_ast"].std():.2f}')
    print(f'  d_reb: {panel["d_reb"].mean():+.2f}  median: {panel["d_reb"].median():+.2f}  std: {panel["d_reb"].std():.2f}')
    # Slice by beneficiary class
    panel['ben_class'] = pd.cut(panel['b_min_baseline'], [0, 18, 28, 50], labels=['bench', 'role', 'starter'])
    print(f'\nMinute swing by beneficiary class:')
    print(panel.groupby('ben_class', observed=True)['d_min'].agg(['count', 'mean', 'median']).round(2).to_string())
    print(f'\nPoints swing by beneficiary class:')
    print(panel.groupby('ben_class', observed=True)['d_pts'].agg(['count', 'mean', 'median']).round(2).to_string())
    print(f'\nAssist swing by beneficiary class:')
    print(panel.groupby('ben_class', observed=True)['d_ast'].agg(['count', 'mean', 'median']).round(2).to_string())
