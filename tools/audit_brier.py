"""Quick Brier audit across pretrainer_baseline_v17 replay runs."""
import pandas as pd
import numpy as np
import os
import glob

files = glob.glob('data/telemetry/replay_runs/**/eval_legs.csv', recursive=True)
files.sort(key=os.path.getmtime, reverse=True)

results = []
for f in files:
    try:
        df = pd.read_csv(f)
        if 'hit' not in df.columns or 'p_cal' not in df.columns:
            continue
        scored = df[df['hit'].notna()]
        if len(scored) < 50:
            continue
        brier = ((scored['p_cal'] - scored['hit'])**2).mean()
        hr = scored['hit'].mean()
        parts = f.replace('\\', '/').split('/')
        run_name = next((x for x in parts if 'pretrainer' in x or 'kernel' in x), 'unknown')
        results.append({
            'run': run_name,
            'n': len(scored),
            'brier': round(brier, 6),
            'hit_rate': round(hr, 4),
        })
    except Exception as e:
        print(f"Error {f}: {e}")

if not results:
    print("No results found.")
else:
    briars = [r['brier'] for r in results]
    print(f"Total runs analyzed: {len(results)}")
    print(f"Avg Brier across runs: {np.mean(briars):.6f}")
    print(f"Min Brier: {np.min(briars):.6f}")
    print(f"Max Brier: {np.max(briars):.6f}")
    print()
    for r in sorted(results, key=lambda x: x['run']):
        print(f"  {r['run'][-10:]}  n={r['n']:5d}  brier={r['brier']:.6f}  hr={r['hit_rate']:.4f}")
