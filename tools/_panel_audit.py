import pandas as pd
from pathlib import Path
import json

gl = pd.read_csv('data/gamelogs/nba_gamelogs.csv', low_memory=False)
print('=== Gamelog columns ===')
print(list(gl.columns))
print(f'\nRows: {len(gl):,}')
gl['game_date'] = pd.to_datetime(gl['game_date'], errors='coerce')
print(f'Date range: {gl["game_date"].min()} -> {gl["game_date"].max()}')
print(f'Unique players: {gl["player"].nunique()}')
print(f'Unique teams: {gl["team"].nunique()}')
print(f'Unique game_dates: {gl["game_date"].nunique()}')

# IAEL archive coverage
iael_root = Path('data/archives/iael/2026')
date_dirs = sorted([d for d in iael_root.iterdir() if d.is_dir()])
print(f'\n=== IAEL archive coverage ===')
print(f'Total date dirs: {len(date_dirs)}')
print(f'First: {date_dirs[0].name} | Last: {date_dirs[-1].name}')

# How many have invalidations.json + status.json
have_both = 0
have_invs_only = 0
sample_inv = None
for d in date_dirs:
    snaps = sorted([s for s in d.iterdir() if s.is_dir()])
    has_inv = any((s / 'injury_invalidations.json').exists() for s in snaps)
    has_status = any((s / 'status.json').exists() for s in snaps)
    if has_inv and has_status: have_both += 1
    elif has_inv: have_invs_only += 1
    if sample_inv is None and has_inv:
        for s in snaps:
            p = s / 'injury_invalidations.json'
            if p.exists(): sample_inv = p; break
print(f'Both invs+status: {have_both}')
print(f'Invs only:        {have_invs_only}')

if sample_inv:
    print(f'\n=== Sample injury_invalidations: {sample_inv} ===')
    j = json.loads(sample_inv.read_text())
    if isinstance(j, dict):
        print(f'Top keys: {list(j.keys())[:10]}')
        rows = j.get('invalidated_players') or j.get('rows') or []
        print(f'Row count: {len(rows)}')
        if rows: print(f'Sample row: {rows[0]}')
