"""Full D drive Atlas data audit - find all eval_legs.csv across both drives."""
import pandas as pd
import numpy as np
import os
import glob

print("=" * 70)
print("SCANNING D DRIVE - ALL ATLAS REPLAY DIRS")
print("=" * 70)

D_BASES = [
    r'D:\AtlasTestMarch26\telemetry_replay_runs',
    r'D:\AtlasTestMarch26\telemetry_control_runs',
    r'D:\AtlasTestMarch26\telemetry_corpus_expand',
    r'D:\AtlasTestMarch26\telemetry_last10',
    r'D:\AtlasTestMarch26\backtests_full',
    r'D:\Atlasall\AtlasRelics',
]

all_eval_files = []

for base in D_BASES:
    if not os.path.exists(base):
        continue
    found = glob.glob(os.path.join(base, '**', 'eval_legs.csv'), recursive=True)
    print(f"\n{base}")
    print(f"  eval_legs.csv files: {len(found)}")
    all_eval_files.extend(found)

print(f"\nTotal eval_legs.csv on D drive: {len(all_eval_files)}")

# Also scan the C drive replay runs for completeness
C_BASE = r'C:\Users\rick\projects\Atlas\data\telemetry\replay_runs'
c_found = glob.glob(os.path.join(C_BASE, '**', 'eval_legs.csv'), recursive=True)
print(f"Total eval_legs.csv on C drive (replay_runs): {len(c_found)}")

all_files = all_eval_files + c_found
all_files.sort(key=os.path.getmtime, reverse=True)

print("\n" + "=" * 70)
print("COMPUTING BRIER ACROSS ALL RUNS")
print("=" * 70)

results = []
seen_paths = set()

for f in all_files:
    # Deduplicate by canonical path
    canon = os.path.normpath(f).lower()
    if canon in seen_paths:
        continue
    seen_paths.add(canon)
    
    try:
        df = pd.read_csv(f, low_memory=False)
        if 'hit' not in df.columns or 'p_cal' not in df.columns:
            continue
        scored = df[df['hit'].notna() & df['p_cal'].notna()]
        if len(scored) < 50:
            continue
        brier = float(((scored['p_cal'] - scored['hit'])**2).mean())
        hr = float(scored['hit'].mean())
        
        p_adj_brier = float(((scored['p_adj'] - scored['hit'])**2).mean()) if 'p_adj' in scored.columns else None
        
        # Extract a readable run label
        parts = f.replace('\\', '/').split('/')
        # Try to find pretrainer/kernel/scenario label
        label = 'unknown'
        for i, p in enumerate(parts):
            if any(x in p for x in ['pretrainer', 'kernel_v2', 'structural', 'control', 'tune', 'live_v']):
                label = p
                break
        
        # Get date from path
        import re
        date_m = re.search(r'(\d{8})', label)
        date_str = date_m.group(1) if date_m else 'unknown'
        
        drive = 'D' if f.startswith('D:') else 'C'
        
        results.append({
            'date': date_str,
            'label': label[:50],
            'drive': drive,
            'n': len(scored),
            'brier_pcal': round(brier, 6),
            'brier_padj': round(p_adj_brier, 6) if p_adj_brier else None,
            'hr': round(hr, 4),
            'path': f,
        })
    except Exception as e:
        print(f"ERR: {f[:80]}: {e}")

# Sort by date then drive
results.sort(key=lambda x: (x['date'], x['drive']))

print(f"\nTotal scorable runs: {len(results)}")
print()
print(f"{'date':10s}  {'drv':3s}  {'n':>6s}  {'brier_pcal':>12s}  {'brier_padj':>12s}  {'hr':>6s}  label")
print('-' * 90)

by_date = {}
for r in results:
    d = r['date']
    if d not in by_date:
        by_date[d] = []
    by_date[d].append(r)

for date in sorted(by_date.keys()):
    runs = by_date[date]
    # Show best run per date (lowest brier)
    best = min(runs, key=lambda x: x['brier_pcal'])
    flag = ' *** HIGH ***' if best['brier_pcal'] > 0.220 else ''
    print(f"{best['date']:10s}  {best['drive']:3s}  {best['n']:6d}  {best['brier_pcal']:12.6f}  "
          f"{str(best['brier_padj']):>12s}  {best['hr']:6.4f}  {flag}")
    # If multiple runs for same date, show others
    if len(runs) > 1:
        for r in runs:
            if r is best:
                continue
            print(f"  {'':10s}  {r['drive']:3s}  {r['n']:6d}  {r['brier_pcal']:12.6f}  "
                  f"{str(r['brier_padj']):>12s}  {r['hr']:6.4f}  {r['label'][:40]}")

print()
if results:
    briars = [r['brier_pcal'] for r in results]
    print(f"Overall stats across {len(results)} runs:")
    print(f"  Avg Brier (p_cal): {np.mean(briars):.6f}")
    print(f"  Min Brier:         {np.min(briars):.6f}")
    print(f"  Max Brier:         {np.max(briars):.6f}")
    print(f"  Median Brier:      {np.median(briars):.6f}")
    
    # Best 5 runs
    best5 = sorted(results, key=lambda x: x['brier_pcal'])[:5]
    print(f"\nBEST 5 RUNS:")
    for r in best5:
        print(f"  {r['date']}  {r['drive']}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}  n={r['n']}  {r['label'][:50]}")
    
    # Worst 5 runs
    worst5 = sorted(results, key=lambda x: x['brier_pcal'], reverse=True)[:5]
    print(f"\nWORST 5 RUNS:")
    for r in worst5:
        print(f"  {r['date']}  {r['drive']}  brier={r['brier_pcal']:.6f}  hr={r['hr']:.4f}  n={r['n']}  {r['label'][:50]}")
