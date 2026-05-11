"""Full-season share-allocator panel builder.

Builds a labeled dataset of (out_player, beneficiary, game_date, stat_delta) tuples
from gamelogs alone. No engine reruns, no IAEL required.

Output: data/model/share_panel_<YYYYMMDD>.csv
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import sys

GL_PATH = Path('data/gamelogs/nba_gamelogs.csv')
OUT_DIR = Path('data/model')
OUT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_RECENCY = 5
MIN_PRESENT = 4
BASELINE_GAMES = 10
MIN_BASELINE = 4
MIN_AVG_MIN_OUT = 15.0     # only consider rotation outs
MIN_AVG_MIN_BEN = 8.0      # only consider rotation beneficiaries

STATS = ['minutes', 'pts', 'reb', 'ast', 'fg3m']

def log(msg: str) -> None:
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}', flush=True)

log('Loading gamelogs...')
gl = pd.read_csv(GL_PATH, low_memory=False)
gl['game_date'] = pd.to_datetime(gl['game_date'], errors='coerce')
gl = gl.dropna(subset=['game_date']).sort_values('game_date').reset_index(drop=True)
for c in STATS:
    gl[c] = pd.to_numeric(gl[c], errors='coerce').fillna(0.0)

# Drop teams with very few games (G-League pollution)
team_counts = gl.groupby('team')['game_date'].nunique()
valid_teams = team_counts[team_counts >= 40].index.tolist()
gl = gl[gl['team'].isin(valid_teams)].reset_index(drop=True)
log(f'Rows: {len(gl):,}  Teams: {gl["team"].nunique()}  Players: {gl["player"].nunique()}  Dates: {gl["game_date"].nunique()}')

# Team-game index
team_games = (
    gl.groupby(['team', 'game_date'], as_index=False)
      .size().rename(columns={'size': 'n_players'})
      .sort_values(['team', 'game_date'])
)
team_games['team_game_idx'] = team_games.groupby('team').cumcount()
log(f'Team-game rows: {len(team_games):,}')

# Index gl for fast lookup
gl_idx = gl.set_index(['team', 'player', 'game_date']).sort_index()
team_player_dates: dict[tuple[str, str], np.ndarray] = {}
for (team, player), pdf in gl.groupby(['team', 'player']):
    team_player_dates[(team, player)] = pdf['game_date'].values

# Precompute per-player career averages over all dates (for classification)
player_avg = gl.groupby(['team', 'player']).agg(
    avg_min=('minutes', 'mean'),
    avg_pts=('pts', 'mean'),
    avg_reb=('reb', 'mean'),
    avg_ast=('ast', 'mean'),
    avg_fg3m=('fg3m', 'mean'),
    n_games=('game_date', 'nunique'),
).reset_index()

def classify(row) -> str:
    if row['avg_min'] >= 32 or row['avg_pts'] >= 22:
        return 'star'
    if row['avg_min'] >= 24 or row['avg_pts'] >= 12:
        return 'core'
    if row['avg_min'] >= 15:
        return 'role'
    return 'bench'
player_avg['player_class'] = player_avg.apply(classify, axis=1)

# === Detect out events ===
log('Detecting out events...')
out_events: list[dict] = []

# For each team, get full sorted date list
team_date_lists: dict[str, list] = {}
for team, tdf in team_games.groupby('team'):
    team_date_lists[team] = tdf['game_date'].tolist()

for _, prow in player_avg.iterrows():
    if prow['avg_min'] < MIN_AVG_MIN_OUT or prow['n_games'] < 10:
        continue
    team = prow['team']; player = prow['player']
    games_played = set(team_player_dates.get((team, player), []))
    tdates = team_date_lists.get(team, [])
    for i in range(WINDOW_RECENCY, len(tdates)):
        gd = tdates[i]
        if gd in games_played:
            continue
        prior = tdates[i - WINDOW_RECENCY:i]
        if sum(1 for d in prior if d in games_played) >= MIN_PRESENT:
            out_events.append({
                'team': team, 'out_player': player, 'game_date': gd,
                'out_class': prow['player_class'],
                'out_avg_min': prow['avg_min'],
                'out_avg_pts': prow['avg_pts'],
                'out_avg_ast': prow['avg_ast'],
                'out_avg_reb': prow['avg_reb'],
                'out_avg_fg3m': prow['avg_fg3m'],
            })

out_df = pd.DataFrame(out_events)
log(f'Out events: {len(out_df):,}  unique out players: {out_df["out_player"].nunique()}')
log(f'By class: {out_df["out_class"].value_counts().to_dict()}')

# === Group simultaneous outs per (team, game_date) ===
log('Grouping simultaneous outs per game...')
outs_per_game = out_df.groupby(['team', 'game_date']).agg(
    n_outs=('out_player', 'count'),
    out_players=('out_player', lambda s: '|'.join(sorted(s))),
).reset_index()
log(f'Game-rows with at least one out: {len(outs_per_game):,}')
log(f'Distribution of n_outs: {outs_per_game["n_outs"].value_counts().to_dict()}')

# === Compute beneficiary deltas ===
log('Computing beneficiary deltas per game (this is the slow step)...')
records: list[dict] = []
out_df_by_team_date = out_df.set_index(['team', 'game_date']).sort_index()

n_done = 0
total = len(outs_per_game)
for _, gevent in outs_per_game.iterrows():
    team = gevent['team']; gd = gevent['game_date']
    n_outs = gevent['n_outs']
    out_players_set = set(gevent['out_players'].split('|'))
    # Box: teammates who played this game
    try:
        box = gl_idx.loc[(team, slice(None), gd)]
    except KeyError:
        n_done += 1
        continue
    if not isinstance(box, pd.DataFrame):
        n_done += 1
        continue
    box = box.reset_index()
    box = box[~box['player'].isin(out_players_set)]
    box = box[box['minutes'] > 0]

    # Build baseline: prior team games where ALL outs in current set actually played
    for out_player in out_players_set:
        op_played_dates = set(team_player_dates.get((team, out_player), []))
        # Use last BASELINE_GAMES team games prior to gd where out_player played
        prior_team_dates = [d for d in team_date_lists.get(team, []) if d < gd]
        baseline_dates = [d for d in reversed(prior_team_dates) if d in op_played_dates][:BASELINE_GAMES]
        if len(baseline_dates) < MIN_BASELINE:
            continue
        for _, b in box.iterrows():
            bname = b['player']
            pa_row = player_avg[(player_avg['team'] == team) & (player_avg['player'] == bname)]
            if len(pa_row) == 0:
                continue
            ben_avg_min = pa_row['avg_min'].iloc[0]
            if ben_avg_min < MIN_AVG_MIN_BEN:
                continue
            ben_class = pa_row['player_class'].iloc[0]
            # Baseline stats for this beneficiary on baseline_dates
            try:
                bsub = gl_idx.loc[(team, bname, baseline_dates)]
            except KeyError:
                continue
            if isinstance(bsub, pd.Series):
                bsub = bsub.to_frame().T
            elif not isinstance(bsub, pd.DataFrame):
                continue
            if len(bsub) < MIN_BASELINE:
                continue
            rec = {
                'team': team, 'game_date': gd, 'n_outs': n_outs,
                'out_player': out_player, 'out_class': out_df_by_team_date.loc[(team, gd)].pipe(
                    lambda x: x['out_class'].iloc[0] if isinstance(x, pd.DataFrame) and (x['out_player'] == out_player).any() else None
                ) if False else None,  # filled below
                'beneficiary': bname, 'ben_class': ben_class, 'ben_avg_min': ben_avg_min,
            }
            for s in STATS:
                rec[f'b_{s}_actual'] = float(b[s])
                rec[f'b_{s}_baseline'] = float(bsub[s].mean())
                rec[f'd_{s}'] = float(b[s]) - float(bsub[s].mean())
            records.append(rec)
    n_done += 1
    if n_done % 200 == 0:
        log(f'  {n_done}/{total} game-events processed, {len(records)} records so far')

panel = pd.DataFrame(records)
log(f'\nPanel rows: {len(panel):,}')

# Fill out_class via merge
panel = panel.drop(columns=['out_class'], errors='ignore')
panel = panel.merge(
    out_df[['team', 'game_date', 'out_player', 'out_class',
            'out_avg_min', 'out_avg_pts', 'out_avg_ast', 'out_avg_reb', 'out_avg_fg3m']],
    on=['team', 'game_date', 'out_player'], how='left'
)

# Save
date_tag = datetime.now().strftime('%Y%m%d')
out_path = OUT_DIR / f'share_panel_{date_tag}.csv'
panel.to_csv(out_path, index=False)
log(f'Saved: {out_path}')

# === Summary ===
log('\n=== Summary ===')
log(f'Total observations: {len(panel):,}')
log(f'Unique out players: {panel["out_player"].nunique()}')
log(f'Unique beneficiaries: {panel["beneficiary"].nunique()}')
log(f'Unique team-games: {panel.groupby(["team","game_date"]).ngroups:,}')
log(f'\nBy out_class x ben_class:')
xt = panel.groupby(['out_class', 'ben_class'], observed=True).size().unstack(fill_value=0)
print(xt.to_string())

log(f'\nMean d_minutes by (out_class, ben_class):')
print(panel.groupby(['out_class', 'ben_class'], observed=True)['d_minutes'].agg(['count', 'mean', 'median']).round(2).to_string())

log(f'\nMean d_pts by (out_class, ben_class):')
print(panel.groupby(['out_class', 'ben_class'], observed=True)['d_pts'].agg(['count', 'mean', 'median']).round(2).to_string())

log(f'\nMean d_ast by (out_class, ben_class):')
print(panel.groupby(['out_class', 'ben_class'], observed=True)['d_ast'].agg(['count', 'mean', 'median']).round(2).to_string())

log(f'\nMean d_reb by (out_class, ben_class):')
print(panel.groupby(['out_class', 'ben_class'], observed=True)['d_reb'].agg(['count', 'mean', 'median']).round(2).to_string())

log(f'\nMean d_fg3m by (out_class, ben_class):')
print(panel.groupby(['out_class', 'ben_class'], observed=True)['d_fg3m'].agg(['count', 'mean', 'median']).round(2).to_string())

# Pool conservation: sum of beneficiary minute swings per game vs out_player minutes
log('\n=== Minutes pool conservation (per game) ===')
pool = panel.groupby(['team', 'game_date']).agg(
    total_d_min=('d_minutes', 'sum'),
    total_out_min=('out_avg_min', 'sum'),
    n_outs=('n_outs', 'first'),
).reset_index()
pool['conservation_ratio'] = pool['total_d_min'] / pool['total_out_min'].replace(0, np.nan)
log(f'Median conservation ratio (recovered minutes / out minutes): {pool["conservation_ratio"].median():.2f}')
log(f'Mean:   {pool["conservation_ratio"].mean():.2f}')
log(f'IQR:    [{pool["conservation_ratio"].quantile(0.25):.2f}, {pool["conservation_ratio"].quantile(0.75):.2f}]')
log(f'(Should be near 1.0 — minutes are zero-sum: when one player sits, his minutes redistribute)')
