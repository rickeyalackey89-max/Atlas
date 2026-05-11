"""
Test 1: Minutes boost only (rate_penalty = 1.0, no rate correction).
Test 2: Rate penalty only (no minutes boost).
Compares both against p_adj baseline on 9-date playoff corpus.
Uses logit-space approximation for rate penalty and direct p-shift for minutes boost.
"""
import sys, pathlib
sys.path.insert(0, 'src')
import numpy as np
import pandas as pd

LIVE_RUNS_DIR = pathlib.Path('data/telemetry/live_runs')
PLAYOFF_START = '2026-04-30'

# Load corpus
frames = []
for path in sorted(LIVE_RUNS_DIR.glob('*/eval_legs.csv')):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        continue
    need = {'p_adj', 'p_for_cal', 'hit', 'direction', 'game_date',
            'stat', 'player', 'line', 'min_mean', 'rate_mean', 'min_std'}
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

for col in ['p_adj', 'p_for_cal', 'hit', 'min_mean', 'rate_mean', 'line', 'min_std']:
    combined[col] = pd.to_numeric(combined[col], errors='coerce')
combined = combined[combined['hit'].isin([0, 1])].copy()
combined['direction'] = combined['direction'].astype(str).str.upper()
combined['stat'] = combined['stat'].astype(str).str.upper()

print(f"Corpus: {len(combined):,} legs  |  {combined['game_date'].nunique()} dates")

RATE_PENALTIES = {
    'PTS': 0.89, 'PA': 0.89, 'PR': 0.89, 'PRA': 0.89,
    'AST': 0.84, 'RA': 0.84,
    'FG3M': 0.80, '3PM': 0.80,
    'REB': 0.945, 'FTA': 0.91,
    'BLK': 0.95, 'STL': 0.95, 'STOCKS': 0.95,
}

def logit(p): return np.log(np.clip(p, 1e-6, 1-1e-6) / (1 - np.clip(p, 1e-6, 1-1e-6)))
def sigmoid(x): return 1.0 / (1.0 + np.exp(-x))

combined['rate_penalty'] = combined['stat'].map(RATE_PENALTIES).fillna(0.93)

# --- Model: MINUTES BOOST ONLY ---
# Elite starters (min_mean >= 33): +6 min boost
# Core starters (min_mean >= 30): +3.5 min boost
# Effect: expected_stat = rate_mean * (min_mean + boost)
# New p approximated via logit shift proportional to expected_stat change
ELITE_FLOOR, CORE_FLOOR = 33.0, 30.0
ELITE_BOOST, CORE_BOOST = 6.0, 3.5

combined['min_boost'] = 0.0
elite_mask = combined['min_mean'] >= ELITE_FLOOR
core_mask  = (combined['min_mean'] >= CORE_FLOOR) & ~elite_mask
combined.loc[elite_mask, 'min_boost'] = ELITE_BOOST
combined.loc[core_mask,  'min_boost'] = CORE_BOOST

# Expected stat before and after boost
combined['exp_stat_before'] = combined['rate_mean'] * combined['min_mean']
combined['exp_stat_after_boost'] = combined['rate_mean'] * (combined['min_mean'] + combined['min_boost'])
# Fractional change in expected stat
combined['min_boost_frac'] = (combined['exp_stat_after_boost'] - combined['exp_stat_before']) / \
    (combined['exp_stat_before'].clip(lower=0.1))

# Logit shift: OVER p goes up when expected_stat rises
_LOGIT_SCALE = 2.5
dir_sign = np.where(combined['direction'] == 'OVER', 1.0, -1.0)
combined['logit_p_adj'] = logit(combined['p_adj'].values)

# Minutes boost only
combined['p_min_only'] = sigmoid(
    combined['logit_p_adj'].values + dir_sign * combined['min_boost_frac'].values * _LOGIT_SCALE
)

# Rate penalty only
combined['rate_shift_frac'] = combined['rate_penalty'] - 1.0
combined['p_rate_only'] = sigmoid(
    combined['logit_p_adj'].values + dir_sign * combined['rate_shift_frac'].values * _LOGIT_SCALE
)

# Both combined
combined['p_both'] = sigmoid(
    combined['logit_p_adj'].values
    + dir_sign * combined['min_boost_frac'].values * _LOGIT_SCALE
    + dir_sign * combined['rate_shift_frac'].values * _LOGIT_SCALE
)

hit = combined['hit']
b_adj      = float(((combined['p_adj'] - hit) ** 2).mean())
b_for_cal  = float(((combined['p_for_cal'] - hit) ** 2).mean())
b_min_only = float(((combined['p_min_only'] - hit) ** 2).mean())
b_rate_only= float(((combined['p_rate_only'] - hit) ** 2).mean())
b_both     = float(((combined['p_both'] - hit) ** 2).mean())

print()
print("=== Brier Comparison (9 playoff dates, logit-space approximation) ===")
print(f"  p_adj  (MC baseline, no correction):    {b_adj:.6f}  [baseline]")
print(f"  p_for_cal (ext priors applied):          {b_for_cal:.6f}")
print(f"  p_min_only  (minutes boost ONLY):        {b_min_only:.6f}  ({b_min_only - b_adj:+.6f})")
print(f"  p_rate_only (rate penalty ONLY):         {b_rate_only:.6f}  ({b_rate_only - b_adj:+.6f})")
print(f"  p_both      (boost + penalty combined):  {b_both:.6f}  ({b_both - b_adj:+.6f})")
print()

print("=== By Direction ===")
for dir_ in ['OVER', 'UNDER']:
    sub = combined[combined['direction'] == dir_]
    h = sub['hit']
    b1 = float(((sub['p_adj'] - h) ** 2).mean())
    bm = float(((sub['p_min_only'] - h) ** 2).mean())
    br = float(((sub['p_rate_only'] - h) ** 2).mean())
    bb = float(((sub['p_both'] - h) ** 2).mean())
    p_avg = float(sub['p_adj'].mean())
    actual = float(h.mean())
    boosted_avg = float(sub['p_min_only'].mean())
    print(f"  {dir_} ({len(sub):,} legs):  actual_hr={actual:.3f}  model_avg={p_avg:.3f}")
    print(f"    Brier: baseline={b1:.6f}  min_only={bm:.6f}({bm-b1:+.5f})  "
          f"rate_only={br:.6f}({br-b1:+.5f})  both={bb:.6f}({bb-b1:+.5f})")
    if dir_ == 'OVER':
        print(f"    min_boost pushes avg p to: {boosted_avg:.3f}")
    print()

print("=== Boosted players breakdown ===")
boosted = combined[combined['min_boost'] > 0]
n_elite = int(elite_mask.sum())
n_core  = int(core_mask.sum())
print(f"  Elite starters (>= {ELITE_FLOOR} min): {n_elite:,} legs, boost +{ELITE_BOOST}")
print(f"  Core starters  (>= {CORE_FLOOR} min): {n_core:,} legs, boost +{CORE_BOOST}")
print(f"  Total boosted: {len(boosted):,} / {len(combined):,} legs")
print()
print("=== Key Insight ===")
print(f"  OVER model avg: {combined[combined['direction']=='OVER']['p_adj'].mean():.3f}  "
      f"  OVER actual: {combined[combined['direction']=='OVER']['hit'].mean():.3f}")
print(f"  Gap: model is {combined[combined['direction']=='OVER']['p_adj'].mean() - combined[combined['direction']=='OVER']['hit'].mean():+.3f} vs actual")
print("  (negative = model already too PESSIMISTIC on OVER -> corrections that push p up help)")
