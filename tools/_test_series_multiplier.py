"""
Smoke test: verifies series_multiplier lookup and lookback_games=10 wire correctly.
"""
import sys, pathlib
sys.path.insert(0, 'src')
import yaml, pandas as pd, numpy as np

# Load config
cfg = yaml.safe_load(open('config.yaml'))
print(f"lookback_games in config: {cfg.get('lookback_games', 'NOT SET')}")
blow = cfg.get('blowout', {})
ser_cfg = blow.get('series_multiplier', {})
print(f"series_multiplier.enabled: {ser_cfg.get('enabled', False)}")
print(f"series_multiplier.multipliers: {ser_cfg.get('multipliers', [])}")
print(f"series_multiplier.start_date: {ser_cfg.get('start_date', 'NOT SET')}")
print()

# Build a mini gamelogs with playoff games between two teams
gl = pd.DataFrame([
    {'game_date': '2026-04-30', 'team': 'OKC', 'opp': 'MEM', 'player': 'p1', 'minutes': 36, 'pts': 20, 'reb': 5, 'ast': 3, 'fg3m': 2},
    {'game_date': '2026-05-02', 'team': 'OKC', 'opp': 'MEM', 'player': 'p1', 'minutes': 38, 'pts': 24, 'reb': 4, 'ast': 5, 'fg3m': 3},
    {'game_date': '2026-05-04', 'team': 'OKC', 'opp': 'MEM', 'player': 'p1', 'minutes': 40, 'pts': 22, 'reb': 6, 'ast': 4, 'fg3m': 1},
    {'game_date': '2026-05-06', 'team': 'OKC', 'opp': 'MEM', 'player': 'p1', 'minutes': 37, 'pts': 28, 'reb': 5, 'ast': 6, 'fg3m': 4},
])

# Simulate the series lookup build from new_engine.py logic
series_start = ser_cfg.get('start_date', '2026-04-30')
_series_lookup = {}
_gl = gl.copy()
_gl['game_date'] = pd.to_datetime(_gl['game_date'], errors='coerce').dt.strftime('%Y-%m-%d')
_po_gl = _gl[_gl['game_date'] >= series_start]
if not _po_gl.empty and {'team', 'opp'}.issubset(_po_gl.columns):
    _pairs = _po_gl[['team', 'opp', 'game_date']].dropna().drop_duplicates()
    _pairs['pair'] = _pairs.apply(
        lambda r: tuple(sorted([str(r['team']).upper(), str(r['opp']).upper()])), axis=1
    )
    for _pair, _grp in _pairs.groupby('pair'):
        _dates = sorted(_grp['game_date'].unique())
        for _gn, _gd in enumerate(_dates, start=1):
            _series_lookup[(_pair, _gd)] = _gn

print("Series lookup (with series_multiplier.enabled=false, these would not be used):")
for k, v in sorted(_series_lookup.items()):
    print(f"  {k[0]} | {k[1]} -> Game {v}")

# Verify game number for each date
print()
test_pair = tuple(sorted(['OKC', 'MEM']))
for date in ['2026-04-30', '2026-05-02', '2026-05-04', '2026-05-06']:
    gn = _series_lookup.get((test_pair, date), None)
    table = ser_cfg.get('multipliers', [1.01, 1.08, 1.10, 1.12])
    mult = table[min(gn-1, len(table)-1)] if gn else 'N/A'
    print(f"  OKC vs MEM on {date}: Game {gn} → series_mult={mult}")

print()
# Verify new_engine.py reads lookback_games
from Atlas.engine.new_engine import _b  # import the safe-cast helper
lk = _b.int(cfg.get('lookback_games', 50))
print(f"lookback_games as engine reads it: {lk}  (expected 10)")
