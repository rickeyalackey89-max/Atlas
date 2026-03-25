#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import numpy as np
from Atlas.engine import calibration_map

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

map_path = str((proj / 'data' / 'model' / 'telemetry_calibration.v2.json').resolve())
res = calibration_map.apply_calibration_column(scored, map_path=map_path, in_col='p_adj', out_col='p_cal', warn=False)

print('rows', len(res))
print('has_telemetry_col', 'p_cal_telemetry' in res.columns)
if 'telemetry_cal_applied' in res.columns:
    print('telemetry_applied_count', int(res['telemetry_cal_applied'].astype(bool).sum()))

if 'p_cal_telemetry' in res.columns and 'p_cal' in res.columns:
    p_cal = pd.to_numeric(res['p_cal'], errors='coerce')
    p_tel = pd.to_numeric(res['p_cal_telemetry'], errors='coerce')
    diff = (p_tel - p_cal).dropna()
    print('diff_mean', float(diff.mean()))
    print('diff_std', float(diff.std()))
    print('\nSAMPLE_ROWS:')
    cols = ['p_adj','p_cal','p_cal_telemetry','telemetry_cal_applied','telemetry_cal_key']
    avail = [c for c in cols if c in res.columns]
    print(res[avail].head(10).to_string(index=False))
else:
    print('no telemetry overlay produced; showing map output sample')
    cols = ['p_adj','p_cal']
    avail = [c for c in cols if c in res.columns]
    print(res[avail].head(10).to_string(index=False))
