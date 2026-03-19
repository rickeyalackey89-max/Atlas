#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import numpy as np
import json

proj = Path('.').resolve()
corpus = proj / 'outputtelem' / 'fidelity_20260316_230917Z'
scored = None
runs_root = corpus / 'runs'
if runs_root.exists() and runs_root.is_dir():
    runs = sorted([p for p in runs_root.iterdir() if p.is_dir()])
    for run in reversed(runs):
        cand = run / 'scored_legs_deduped.csv'
        if cand.exists():
            scored = pd.read_csv(cand)
            break
if scored is None:
    scored_path = corpus / 'scored_legs_deduped.csv'
    if scored_path.exists():
        scored = pd.read_csv(scored_path)
if scored is None:
    print('NO_SCORED_FILE')
    raise SystemExit(2)

if 'p_adj' not in scored.columns:
    if 'p_cal' in scored.columns:
        scored['p_adj'] = scored['p_cal']
    else:
        print('NO_PRED_COLUMN')
        raise SystemExit(3)

has_p_cal = 'p_cal' in scored.columns
has_p_cal_tel = 'p_cal_telemetry' in scored.columns

p_adj = pd.to_numeric(scored['p_adj'], errors='coerce').clip(0.0,1.0)
res = {'total_rows': int(len(scored)), 'p_cal_exists': bool(has_p_cal), 'p_cal_telemetry_exists': bool(has_p_cal_tel)}

if has_p_cal:
    p_cal = pd.to_numeric(scored['p_cal'], errors='coerce').clip(0.0,1.0)
    mask = p_adj.notna() & p_cal.notna()
    n_mask = int(mask.sum())
    res.update({'n_computable': n_mask})
    if n_mask > 0:
        diff = p_cal[mask] - p_adj[mask]
        res.update({
            'pcal_diff_mean': float(diff.mean()),
            'pcal_diff_std': float(diff.std()),
            'pcal_diff_min': float(diff.min()),
            'pcal_diff_max': float(diff.max()),
            'pcal_increased': int((diff > 0).sum()),
            'pcal_decreased': int((diff < 0).sum()),
        })
    if 'hit' in scored.columns and n_mask > 0:
        y = pd.to_numeric(scored['hit'], errors='coerce')
        brier_adj = float(((p_adj[mask] - y[mask])**2).mean())
        brier_cal = float(((p_cal[mask] - y[mask])**2).mean())
        res.update({'brier_adj': brier_adj, 'brier_cal': brier_cal, 'brier_delta': brier_adj - brier_cal})

if has_p_cal_tel and has_p_cal:
    p_cal = pd.to_numeric(scored['p_cal'], errors='coerce').clip(0.0,1.0)
    p_tel = pd.to_numeric(scored['p_cal_telemetry'], errors='coerce').clip(0.0,1.0)
    mask2 = p_cal.notna() & p_tel.notna()
    n2 = int(mask2.sum())
    if n2 > 0:
        diff2 = p_tel[mask2] - p_cal[mask2]
        res.update({
            'pcal_tel_diff_mean': float(diff2.mean()),
            'pcal_tel_diff_std': float(diff2.std()),
            'pcal_tel_diff_min': float(diff2.min()),
            'pcal_tel_diff_max': float(diff2.max()),
            'pcal_tel_increased': int((diff2 > 0).sum()),
            'pcal_tel_decreased': int((diff2 < 0).sum()),
        })
        if 'hit' in scored.columns:
            y2 = pd.to_numeric(scored['hit'], errors='coerce')
            brier_tel = float(((p_tel[mask2] - y2[mask2])**2).mean())
            res.update({'brier_tel': brier_tel, 'brier_cal_vs_tel_delta': float(res.get('brier_cal', 0.0) - brier_tel)})

print(json.dumps(res, indent=2))
