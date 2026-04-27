"""Fast Brier audit - pretrainer_baseline_v17 on D drive + recent live runs on C drive."""
import pandas as pd
import numpy as np
import os
import glob
from pathlib import Path

D_V17 = r'D:\\AtlasTestMarch26\\telemetry_replay_runs'
D_BACKTEST = r'D:\\AtlasTestMarch26\\backtests_full'
C_LIVE = r'C:\\Users\\rick\\projects\\Atlas\\data\\output\\runs'
D_CORPUS = r'D:\\AtlasTestMarch26\\telemetry_replay_runs'

_TAG_FILE = Path(__file__).resolve().parents[1] / \"data\" / \"telemetry\" / \"replay_runs\" / \".corpus_tag\"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else \"kernel_v2_perstat_corr015\"

results = []

def score_file(label, f, drive):
    try:
        # Quick column check first
        cols = pd.read_csv(f, nrows=0).columns.tolist()
        if 'hit' not in cols or 'p_cal' not in cols:
            return None
        df = pd.read_csv(f, usecols=['hit', 'p_cal', 'p_adj', 'p_role', 'direction'],
                         low_memory=False)
        scored = df[df['hit'].notna() & df['p_cal'].notna()]
        if len(scored) < 50:
            return None
        brier = float(((scored['p_cal'] - scored['hit'])**2).mean())
        hr = float(scored['hit'].mean())
        p_adj_brier = float(((scored['p_adj'] - scored['hit'])**2).mean()) if 'p_adj' in scored.columns else None
        over = scored[scored['direction'] == 'OVER'] if 'direction' in scored.columns else None
        under = scored[scored['direction'] == 'UNDER'] if 'direction' in scored.columns else None
        over_brier = float(((over['p_cal'] - over['hit'])**2).mean()) if over is not None and len(over) > 20 else None
        under_brier = float(((under['p_cal'] - under['hit'])**2).mean()) if under is not None and len(under) > 20 else None
        return {
            'label': label, 'drive': drive, 'n': len(scored),
            'brier_pcal': round(brier, 6),
            'brier_padj': round(p_adj_brier, 6) if p_adj_brier else None,
            'brier_over': round(over_brier, 6) if over_brier else None,
            'brier_under': round(under_brier, 6) if under_brier else None,
            'hr': round(hr, 4),
        }
    except Exception as e:
        print(f"  ERR {label}: {e}")
        return None

# --- D drive: pretrainer_baseline_v17 (moved from C) ---
print("D drive: pretrainer_baseline_v17 corpus")
v17_dirs = sorted(d for d in os.listdir(D_V17) if d.startswith('pretrainer_baseline_v17_'))
for d in v17_dirs:
    # Flat structure: eval_legs.csv directly in scenario dir
    f = os.path.join(D_V17, d, 'eval_legs.csv')
    if os.path.exists(f):
        date = d.replace('pretrainer_baseline_v17_', '')
        r = score_file(date, f, 'D-v17')
        if r:
            results.append(r)
            print(f"  {date}  n={r['n']:5d}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}")

# --- D drive: atlas replay corpus (active tag) ---
print(f\"\\nD drive: {_CORPUS_TAG} corpus\")
kv2_dirs = sorted(d for d in os.listdir(D_V17) if d.startswith(f'{_CORPUS_TAG}_'))
for d in kv2_dirs:
    f = os.path.join(D_V17, d, 'eval_legs.csv')
    if os.path.exists(f):
        date = d.replace(f'{_CORPUS_TAG}_', '')
        r = score_file(date, f, 'D-kv2')
        if r:
            results.append(r)
            print(f"  {date}  n={r['n']:5d}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}")

# --- D drive: backtests_full ---
print("\nD drive: backtests_full")
if os.path.exists(D_BACKTEST):
    for item in sorted(os.listdir(D_BACKTEST)):
        # Find eval_legs.csv (may be nested)
        fs = glob.glob(os.path.join(D_BACKTEST, item, '**', 'eval_legs.csv'), recursive=True)
        for f in fs:
            r = score_file(item[:40], f, 'D-bt')
            if r:
                results.append(r)
                print(f"  {item[:40]}  n={r['n']:5d}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}")

# --- C drive: recent live runs ---
print("\nC drive: recent live runs (last 20)")
if os.path.exists(C_LIVE):
    run_dirs = sorted(os.listdir(C_LIVE), reverse=True)[:20]
    for d in run_dirs:
        f = os.path.join(C_LIVE, d, 'eval_legs.csv')
        if os.path.exists(f):
            r = score_file(d, f, 'C-live')
            if r:
                results.append(r)
                print(f"  {d}  n={r['n']:5d}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}")

# --- Summary ---
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if not results:
    print("No results.")
else:
    # By drive/corpus
    for drv in ['D-v17', 'D-kv2', 'D-bt', 'C-live']:
        subset = [r for r in results if r['drive'] == drv]
        if not subset:
            continue
        briars = [r['brier_pcal'] for r in subset]
        print(f"\n{drv}: {len(subset)} runs")
        print(f"  Avg Brier: {np.mean(briars):.6f}")
        print(f"  Min Brier: {np.min(briars):.6f}  Max: {np.max(briars):.6f}")

    # Best overall
    all_briars = [r['brier_pcal'] for r in results]
    print(f"\nOverall ({len(results)} total runs):")
    print(f"  Avg Brier:    {np.mean(all_briars):.6f}")
    print(f"  Min Brier:    {np.min(all_briars):.6f}")
    print(f"  Max Brier:    {np.max(all_briars):.6f}")
    
    best = min(results, key=lambda x: x['brier_pcal'])
    print(f"\nBEST run: {best['label']} ({best['drive']})  brier={best['brier_pcal']:.6f}  hr={best['hr']:.4f}  n={best['n']}")
    
    print("\nALL RESULTS (sorted by date/label):")
    print(f"{'label':20s}  {'drv':6s}  {'n':>6s}  {'brier':>10s}  {'over':>10s}  {'under':>10s}  {'hr':>6s}")
    print('-' * 80)
    for r in sorted(results, key=lambda x: x['label']):
        print(f"{r['label'][:20]:20s}  {r['drive']:6s}  {r['n']:6d}  "
              f"{r['brier_pcal']:10.6f}  {str(r['brier_over'] or ''):>10s}  "
              f"{str(r['brier_under'] or ''):>10s}  {r['hr']:6.4f}")
