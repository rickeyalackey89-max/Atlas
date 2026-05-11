"""Verify post-kernel replay corpus: per-date Brier, hit rate, sample sizes."""
from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path

TAG = 'atlas_replay_postkernel_20260510_130246'
ROOT = Path('data/telemetry/replay_runs')

dirs = sorted([d for d in ROOT.iterdir() if d.name.startswith(TAG)])
print(f'Found {len(dirs)} corpus dirs for tag {TAG}\n')

rows = []
for d in dirs:
    date = d.name.split('_')[-1]
    runs = list((d / 'runs').glob('*'))
    if not runs:
        # legs are at top level
        ev = d / 'eval_legs.csv'
        sc = d / 'scored_legs_deduped.csv'
    else:
        run = sorted(runs)[-1]
        ev = run / 'eval_legs.csv'
        sc = run / 'scored_legs_deduped.csv'
    if not ev.exists():
        # Try at top level
        ev = d / 'eval_legs.csv'
        sc = d / 'scored_legs_deduped.csv'
    if not ev.exists():
        rows.append({'date': date, 'status': 'MISSING_EVAL', 'n': 0})
        continue
    df = pd.read_csv(ev, low_memory=False)
    n = len(df)
    if 'hit' not in df.columns:
        rows.append({'date': date, 'status': 'NO_HIT_COL', 'n': n})
        continue
    df_truth = df.dropna(subset=['hit'])
    n_truth = len(df_truth)
    if n_truth == 0:
        rows.append({'date': date, 'status': 'NO_TRUTH', 'n': n, 'n_truth': 0})
        continue
    hit = df_truth['hit'].astype(float)
    p_cal = pd.to_numeric(df_truth.get('p_cal'), errors='coerce')
    p_adj = pd.to_numeric(df_truth.get('p_adj'), errors='coerce')
    brier_cal = float(((p_cal - hit) ** 2).mean()) if p_cal.notna().any() else np.nan
    brier_adj = float(((p_adj - hit) ** 2).mean()) if p_adj.notna().any() else np.nan
    rows.append({
        'date': date, 'status': 'OK', 'n': n, 'n_truth': n_truth,
        'hit_rate': float(hit.mean()),
        'brier_cal': round(brier_cal, 5),
        'brier_adj': round(brier_adj, 5),
        'mean_p_cal': round(float(p_cal.mean()), 4),
    })

summary = pd.DataFrame(rows)
print(summary.to_string(index=False))

ok = summary[summary['status'] == 'OK']
if len(ok) > 0:
    total_legs = ok['n_truth'].sum()
    weighted_brier_cal = (ok['brier_cal'] * ok['n_truth']).sum() / total_legs
    weighted_brier_adj = (ok['brier_adj'] * ok['n_truth']).sum() / total_legs
    weighted_hit = (ok['hit_rate'] * ok['n_truth']).sum() / total_legs
    print(f'\n=== Aggregate (truth-backed) ===')
    print(f'Dates: {len(ok)}/{len(summary)}  Truth legs: {total_legs:,}')
    print(f'Hit rate:   {weighted_hit:.4f}')
    print(f'Brier p_cal: {weighted_brier_cal:.5f}')
    print(f'Brier p_adj: {weighted_brier_adj:.5f}')
