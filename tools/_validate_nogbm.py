"""Validate: GBM-off + p_for_cal isotonic vs current production stack."""
import json, pathlib, numpy as np, pandas as pd, sys
sys.path.insert(0, 'src')

cal_json = json.loads(pathlib.Path('data/model/telemetry_calibration.playoff_isotonic.json').read_text())

over_x = over_y = under_x = under_y = None
for key, val in cal_json.items():
    if not isinstance(val, dict):
        continue
    dir_ = val.get('direction', '').lower()
    mode = val.get('mode', '')
    if mode in ('isotonic_direction_split', 'isotonic_global', 'isotonic_blend'):
        if dir_ == 'over':
            over_x, over_y = val['x_points'], val['y_points']
        elif dir_ == 'under':
            under_x, under_y = val['x_points'], val['y_points']

print(f"OVER curve points: {len(over_x) if over_x else 0}")
print(f"UNDER curve points: {len(under_x) if under_x else 0}")
print(f"OVER x range: {min(over_x):.3f} - {max(over_x):.3f}" if over_x else "")
print(f"UNDER x range: {min(under_x):.3f} - {max(under_x):.3f}" if under_x else "")
print()

LIVE = pathlib.Path('data/telemetry/live_runs')
PLAYOFF_START = '2026-04-30'
frames = []
for path in sorted(LIVE.glob('*/eval_legs.csv')):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        continue
    needed = {'p_for_cal', 'p_cal', 'p_gbm', 'hit', 'direction', 'game_date'}
    if not needed.issubset(df.columns):
        continue
    df = df[df['game_date'] >= PLAYOFF_START].copy()
    if df.empty:
        continue
    frames.append(df)

combined = pd.concat(frames, ignore_index=True)
combined = combined.drop_duplicates(
    subset=['player', 'stat', 'direction', 'line', 'game_date']
).reset_index(drop=True)
combined['direction'] = combined['direction'].astype(str).str.lower()
for col in ['p_for_cal', 'p_cal', 'p_gbm', 'hit']:
    combined[col] = pd.to_numeric(combined[col], errors='coerce')
combined = combined[combined['hit'].isin([0, 1])].copy()


def apply_iso(row):
    p = row['p_for_cal']
    if np.isnan(p):
        return np.nan
    if row['direction'] == 'over' and over_x:
        return float(np.interp(p, over_x, over_y))
    elif row['direction'] == 'under' and under_x:
        return float(np.interp(p, under_x, under_y))
    return p


combined['p_new'] = combined.apply(apply_iso, axis=1)

n = len(combined)
n_dates = combined['game_date'].nunique()
hit = combined['hit']

print(f"N legs: {n:,}  dates: {n_dates}")
print()
print("BEFORE (current production stack):")
b_for = float(((combined['p_for_cal'] - hit) ** 2).mean())
b_gbm = float(((combined['p_gbm'] - hit) ** 2).mean())
b_cal = float(((combined['p_cal'] - hit) ** 2).mean())
print(f"  p_for_cal (no GBM, no iso):  Brier={b_for:.6f}")
print(f"  p_gbm (GBM applied):          Brier={b_gbm:.6f}")
print(f"  p_cal (GBM + old isotonic):   Brier={b_cal:.6f}")
print()
b_new = float(((combined['p_new'] - hit) ** 2).mean())
print("AFTER (GBM off, p_for_cal isotonic):")
print(f"  p_new:                         Brier={b_new:.6f}")
print(f"  Delta vs p_cal:               {b_new - b_cal:+.6f}")
print()

for dir_ in ['over', 'under']:
    sub = combined[combined['direction'] == dir_]
    h = sub['hit']
    print(f"{dir_.upper()} ({len(sub):,} legs):")
    print(f"  p_for_cal: {((sub['p_for_cal'] - h)**2).mean():.6f}")
    print(f"  p_gbm:     {((sub['p_gbm'] - h)**2).mean():.6f}")
    print(f"  p_cal old: {((sub['p_cal'] - h)**2).mean():.6f}")
    print(f"  p_new:     {((sub['p_new'] - h)**2).mean():.6f}")
    print()
