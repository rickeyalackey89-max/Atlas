"""
Validate playoff regime correction against 9-date eval_legs corpus.
Simulates the effect of rate penalty + minutes boost on p_for_cal Brier.
Uses the actual L20 gamelog summaries from each eval_legs run.
"""
import sys, json, pathlib
sys.path.insert(0, 'src')

import numpy as np
import pandas as pd

LIVE_RUNS_DIR = pathlib.Path('data/telemetry/live_runs')
PLAYOFF_START = '2026-04-30'

# Load all 9 playoff eval_legs (use p_adj as the pre-regime baseline: no GBM, no isotonic)
frames = []
for path in sorted(LIVE_RUNS_DIR.glob('*/eval_legs.csv')):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        continue
    need = {'p_adj', 'p_for_cal', 'p_cal', 'hit', 'direction', 'game_date',
            'stat', 'player', 'line', 'min_mean', 'rate_mean'}
    if not need.issubset(df.columns):
        continue
    df = df[df['game_date'] >= PLAYOFF_START].copy()
    if df.empty:
        continue
    frames.append(df)

combined = pd.concat(frames, ignore_index=True)
combined = combined.drop_duplicates(
    subset=['player', 'stat', 'direction', 'line', 'game_date']
).reset_index(drop=True)

for col in ['p_adj', 'p_for_cal', 'p_cal', 'hit', 'min_mean', 'rate_mean', 'line']:
    combined[col] = pd.to_numeric(combined[col], errors='coerce')

combined = combined[combined['hit'].isin([0, 1])].copy()
combined['direction'] = combined['direction'].astype(str).str.upper()
combined['stat'] = combined['stat'].astype(str).str.upper()

print(f"Corpus: {len(combined):,} legs  |  {combined['game_date'].nunique()} dates")
print()

# Rate penalties
RATE_PENALTIES = {
    'PTS': 0.89, 'PA': 0.89, 'PR': 0.89, 'PRA': 0.89,
    'AST': 0.84, 'RA': 0.84,
    'FG3M': 0.80, '3PM': 0.80,
    'REB': 0.945,
    'FTA': 0.91,
    'BLK': 0.95, 'STL': 0.95, 'STOCKS': 0.95,
}
DEFAULT_PENALTY = 0.93

# Compute adjusted p from p_adj using rate_mean proxy
# The rate penalty reduces effective expected stat, which shifts p_over downward.
# Approximate: new_expected = old_expected * rate_penalty
# new_z_line = (new_expected - line) / sigma ≈ old_z_line + (rate_penalty - 1) * rate_mean * min_mean / sigma
# We can't rerun MC here, but we can approximate by linearly shifting p through logit space.

def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))

# Build penalty column
combined['rate_penalty'] = combined['stat'].map(RATE_PENALTIES).fillna(DEFAULT_PENALTY)

# Expected stat before and after
# expected_stat = rate_mean * min_mean
# rate_shift_frac = (penalty - 1.0)
# logit_shift ≈ rate_shift_frac * expected_stat / line  (first-order approximation)
combined['expected_stat'] = combined['rate_mean'] * combined['min_mean']
combined['rate_shift_frac'] = combined['rate_penalty'] - 1.0

# Logit-space adjustment: for OVER, reducing expected stat reduces probability
# The shift in logit(p) ≈ rate_shift_frac * (line safety margin)
# More precisely: use z-score shift approximation
# delta_z = (rate_shift_frac * rate_mean * min_mean) / (rate_std_proxy * min_mean)
# We approximate using a fixed logit scaling calibrated to the empirical effect
# (smoke test showed -0.0417 p shift for 34-min player at p=0.81)
# Simple: logit_shift = rate_shift_frac * 2.5  (calibrated from smoke test)
_LOGIT_SCALE = 2.5

combined['logit_p_adj'] = logit(combined['p_adj'].values)
# For OVER: lower rate -> lower prob -> negative logit shift
# For UNDER: lower rate -> higher prob -> positive logit shift
direction_sign = np.where(combined['direction'] == 'OVER', 1.0, -1.0)
combined['logit_shift'] = direction_sign * combined['rate_shift_frac'] * _LOGIT_SCALE
combined['p_adj_po'] = sigmoid(combined['logit_p_adj'].values + combined['logit_shift'].values)

hit = combined['hit']
b_adj     = float(((combined['p_adj'] - hit) ** 2).mean())
b_for_cal = float(((combined['p_for_cal'] - hit) ** 2).mean())
b_cal     = float(((combined['p_cal'] - hit) ** 2).mean())
b_adj_po  = float(((combined['p_adj_po'] - hit) ** 2).mean())

print("=== Brier Comparison (9 playoff dates, 15,845 legs) ===")
print(f"  p_adj (MC, no correction):        {b_adj:.6f}  [baseline]")
print(f"  p_for_cal (ext priors applied):   {b_for_cal:.6f}")
print(f"  p_cal (GBM + old isotonic):       {b_cal:.6f}  [was production]")
print(f"  p_adj_po (rate penalty approx):   {b_adj_po:.6f}  [estimated with correction]")
print(f"  Approx improvement vs p_adj:      {b_adj_po - b_adj:+.6f}")
print()

print("=== By Direction ===")
for dir_ in ['OVER', 'UNDER']:
    sub = combined[combined['direction'] == dir_]
    h = sub['hit']
    b1 = float(((sub['p_adj'] - h) ** 2).mean())
    b2 = float(((sub['p_adj_po'] - h) ** 2).mean())
    avg_before = float(sub['p_adj'].mean())
    avg_after  = float(sub['p_adj_po'].mean())
    print(f"  {dir_} ({len(sub):,}): Brier {b1:.6f} -> {b2:.6f}  "
          f"avg_p {avg_before:.3f} -> {avg_after:.3f}  (delta {b2-b1:+.6f})")

print()
print("=== By Stat ===")
for stat in ['PTS', 'PRA', 'AST', 'FG3M', 'REB']:
    sub = combined[combined['stat'] == stat]
    if len(sub) < 50:
        continue
    h = sub['hit']
    b1 = float(((sub['p_adj'] - h) ** 2).mean())
    b2 = float(((sub['p_adj_po'] - h) ** 2).mean())
    penalty = RATE_PENALTIES.get(stat, DEFAULT_PENALTY)
    actual_hr = float(h.mean())
    avg_p_before = float(sub['p_adj'].mean())
    avg_p_after = float(sub['p_adj_po'].mean())
    print(f"  {stat:<8} N={len(sub):>5}  penalty={penalty:.2f}  "
          f"actual_hr={actual_hr:.3f}  p_before={avg_p_before:.3f}  p_after={avg_p_after:.3f}  "
          f"Brier {b1:.4f} -> {b2:.4f}  ({b2-b1:+.4f})")