"""Retrain playoff isotonic on p_for_cal (MC signal, pre-GBM) for GBM-disabled mode."""
import json, sys, time, pathlib, shutil
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, 'src')

LIVE_RUNS_DIR = pathlib.Path('data/telemetry/live_runs')
OUTPUT_FILE   = pathlib.Path('data/model/telemetry_calibration.playoff_isotonic.json')
PLAYOFF_START = '2026-04-30'
SOURCE_COL    = 'p_for_cal'

REQUIRED = {'player', 'stat', 'direction', 'line', 'game_date', SOURCE_COL, 'hit'}

frames = []
for path in sorted(LIVE_RUNS_DIR.glob('*/eval_legs.csv')):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        continue
    if not REQUIRED.issubset(df.columns):
        continue
    df = df[df['game_date'] >= PLAYOFF_START].copy()
    if df.empty:
        continue
    df[SOURCE_COL] = pd.to_numeric(df[SOURCE_COL], errors='coerce')
    df['hit'] = pd.to_numeric(df['hit'], errors='coerce')
    df = df[df[SOURCE_COL].notna() & df['hit'].isin([0, 1])].copy()
    df['direction'] = df['direction'].astype(str).str.strip().str.lower()
    frames.append(df[['player', 'stat', 'direction', 'line', 'game_date', SOURCE_COL, 'hit']])

combined = pd.concat(frames, ignore_index=True)
before = len(combined)
combined = combined.drop_duplicates(
    subset=['player', 'stat', 'direction', 'line', 'game_date']
).reset_index(drop=True)

n_dates = combined['game_date'].nunique()
dates = sorted(combined['game_date'].unique())
print(f"Dedup: {before:,} -> {len(combined):,} unique legs across {n_dates} dates")
print(f"Dates: {dates}")

over_df  = combined[combined['direction'] == 'over'].copy()
under_df = combined[combined['direction'] == 'under'].copy()
print(f"OVER  {len(over_df):,} | model avg={over_df[SOURCE_COL].mean():.3f} actual={over_df['hit'].mean():.3f}")
print(f"UNDER {len(under_df):,} | model avg={under_df[SOURCE_COL].mean():.3f} actual={under_df['hit'].mean():.3f}")


def fit_and_eval(df, label):
    probs = df[SOURCE_COL].to_numpy(dtype=float)
    hits  = df['hit'].to_numpy(dtype=float)
    ir = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds='clip')
    ir.fit(probs, hits)
    cal = ir.predict(probs)
    b_before = float(np.mean((probs - hits) ** 2))
    b_after  = float(np.mean((cal - hits) ** 2))
    print(f"  {label}: Brier {b_before:.6f} -> {b_after:.6f}  (delta {b_after - b_before:+.6f})")
    return ir.X_thresholds_.tolist(), ir.y_thresholds_.tolist()


print()
over_x, over_y   = fit_and_eval(over_df, 'OVER ')
under_x, under_y = fit_and_eval(under_df, 'UNDER')

# Backup existing then patch direction-split curves in JSON
backup = OUTPUT_FILE.with_name(
    OUTPUT_FILE.stem + '_pre_nogbm_' + time.strftime('%Y%m%d_%H%M') + '.json'
)
shutil.copy(OUTPUT_FILE, backup)
print(f"\nBackup: {backup.name}")

existing = json.loads(OUTPUT_FILE.read_text())
now = time.strftime('%Y-%m-%dT%H:%M:%S')
SPLIT_MODES = ('isotonic_direction_split', 'isotonic_global', 'isotonic_blend')

for key, val in existing.items():
    if not isinstance(val, dict):
        continue
    direction = val.get('direction', '').lower()
    mode = val.get('mode', '')
    if mode not in SPLIT_MODES:
        continue
    if direction == 'over':
        val['x_points'] = over_x
        val['y_points'] = over_y
        val['source_col'] = SOURCE_COL
        val['retrained'] = now
    elif direction == 'under':
        val['x_points'] = under_x
        val['y_points'] = under_y
        val['source_col'] = SOURCE_COL
        val['retrained'] = now

OUTPUT_FILE.write_text(json.dumps(existing, indent=2))
print(f"Saved: {OUTPUT_FILE}")
print()
print("Isotonic now trained on p_for_cal (MC signal, pre-GBM).")
print("Next step: set posthoc_calibrator.enabled: false in config.yaml")
