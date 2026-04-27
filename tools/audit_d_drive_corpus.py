"""Compute Brier across D drive corpus eval_legs.csv files."""
import pandas as pd
import numpy as np
import os
from pathlib import Path

_TAG_FILE = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "replay_runs" / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"

results = []
base = r'D:\AtlasTestMarch26\telemetry_replay_runs'

for d in sorted(os.listdir(base)):
    if not d.startswith(_CORPUS_TAG):
        continue
    ef = os.path.join(base, d, 'eval_legs.csv')
    if not os.path.exists(ef):
        continue
    try:
        df = pd.read_csv(ef, low_memory=False)
        if 'hit' not in df.columns or 'p_cal' not in df.columns:
            continue
        scored = df[df['hit'].notna() & df['p_cal'].notna()]
        if len(scored) < 50:
            continue
        brier = float(((scored['p_cal'] - scored['hit'])**2).mean())
        hr = float(scored['hit'].mean())
        # Also check p_adj and p_role for the chain
        p_adj_brier = float(((scored['p_adj'] - scored['hit'])**2).mean()) if 'p_adj' in scored.columns else None
        p_role_brier = float(((scored['p_role'] - scored['hit'])**2).mean()) if 'p_role' in scored.columns else None
        date = d.replace(f'{_CORPUS_TAG}_', '')
        results.append({
            'date': date,
            'n': len(scored),
            'brier_pcal': round(brier, 6),
            'brier_padj': round(p_adj_brier, 6) if p_adj_brier else None,
            'brier_prole': round(p_role_brier, 6) if p_role_brier else None,
            'hr': round(hr, 4),
        })
    except Exception as e:
        print(f'ERR {d}: {e}')

print(f'Total D drive corpus dates: {len(results)}')
print()
print(f"{'date':12s}  {'n':>6s}  {'brier_pcal':>12s}  {'brier_padj':>12s}  {'brier_prole':>12s}  {'hr':>6s}")
print('-' * 70)
for r in results:
    flag = ' *** HIGH ***' if r['brier_pcal'] > 0.220 else ''
    print(f"{r['date']:12s}  {r['n']:6d}  {r['brier_pcal']:12.6f}  "
          f"{str(r['brier_padj']):>12s}  {str(r['brier_prole']):>12s}  {r['hr']:6.4f}{flag}")

if results:
    briars = [r['brier_pcal'] for r in results]
    print()
    print(f'Avg Brier (p_cal): {np.mean(briars):.6f}')
    print(f'Min Brier: {np.min(briars):.6f}')
    print(f'Max Brier: {np.max(briars):.6f}')
    print(f'Median Brier: {np.median(briars):.6f}')
