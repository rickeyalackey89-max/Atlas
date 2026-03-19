#!/usr/bin/env python3
from pathlib import Path
import sys, json
import pandas as pd
import numpy as np

from Atlas.runtime.telemetry_calibration import load_calibration, apply_calibration_to_column


def brier(p, y):
    p = pd.to_numeric(p, errors='coerce').clip(1e-6, 1-1e-6)
    y = pd.to_numeric(y, errors='coerce')
    mask = p.notna() & y.notna()
    if not mask.any():
        return None
    return float(((p[mask]-y[mask])**2).mean())


def logloss(p, y):
    p = pd.to_numeric(p, errors='coerce').clip(1e-6, 1-1e-6)
    y = pd.to_numeric(y, errors='coerce')
    mask = p.notna() & y.notna()
    if not mask.any():
        return None
    return float((-(y[mask]*np.log(p[mask]) + (1.0-y[mask])*np.log(1.0-p[mask]))).mean())


def ece(p, y, buckets=10):
    df = pd.DataFrame({'p': pd.to_numeric(p, errors='coerce'), 'y': pd.to_numeric(y, errors='coerce')}).dropna()
    if df.empty:
        return None
    bins = pd.interval_range(start=0.0, end=1.0, periods=buckets)
    df['bucket'] = pd.cut(df['p'].clip(0.0,1.0), bins=bins, include_lowest=True)
    total = len(df)
    ece_val = 0.0
    for _, grp in df.groupby('bucket', observed=False):
        if grp.empty:
            continue
        ece_val += (len(grp)/total) * abs(float(grp['p'].mean()) - float(grp['y'].mean()))
    return float(ece_val)


def main():
    project = Path('.').resolve()
    cal = load_calibration(project)
    # Prefer run-specific scored+eval pairs under the run folder (they contain `hit`).
    runs_root = project / 'outputtelem' / 'fidelity_20260316_230917Z' / 'runs'
    scored = None
    eval_df = None
    if runs_root.exists() and runs_root.is_dir():
        runs = sorted([p for p in runs_root.iterdir() if p.is_dir()])
        for run_dir in reversed(runs):
            cand_scored = run_dir / 'scored_legs_deduped.csv'
            cand_eval = run_dir / 'eval_legs.csv'
            if cand_scored.exists() and cand_eval.exists():
                scored = pd.read_csv(cand_scored)
                try:
                    eval_df = pd.read_csv(cand_eval)
                except Exception:
                    eval_df = None
                break
    # Fallback to top-level scored file if no run pair found
    if scored is None:
        scored_path = project / 'outputtelem' / 'fidelity_20260316_230917Z' / 'scored_legs_deduped.csv'
        if not scored_path.exists():
            print(json.dumps({'error':'scored file missing', 'path': str(scored_path)}))
            sys.exit(2)
        scored = pd.read_csv(scored_path)

    # If we have eval_df, merge hits into scored
    if eval_df is not None:
        key_col = None
        if 'projection_id' in scored.columns and 'projection_id' in eval_df.columns:
            key_col = 'projection_id'
        elif 'source_projection_id' in scored.columns and 'source_projection_id' in eval_df.columns:
            key_col = 'source_projection_id'
        if key_col is not None:
            hit_map = eval_df[[key_col, 'hit']].drop_duplicates()
            scored = scored.merge(hit_map, on=key_col, how='left')

    if 'hit' not in scored.columns:
        print(json.dumps({'error':'hit column missing', 'note':'no run-level eval_legs.csv found and top-level scored lacks hit'}))
        sys.exit(2)
    source_col = 'p_cal' if 'p_cal' in scored.columns else 'p_adj'
    base_p = pd.to_numeric(scored[source_col], errors='coerce').clip(0.0,1.0)
    y = pd.to_numeric(scored['hit'], errors='coerce')
    baseline = {}
    baseline['all'] = {'brier': brier(base_p, y), 'logloss': logloss(base_p, y), 'ece': ece(base_p, y)}
    if 'role_ctx_outs_used' in scored.columns:
        role_vals = pd.to_numeric(scored['role_ctx_outs_used'], errors='coerce').fillna(0)
        on_mask = role_vals > 0
        off_mask = role_vals <= 0
        if on_mask.any():
            baseline['role_on'] = {'brier': brier(base_p[on_mask], y[on_mask]), 'logloss': logloss(base_p[on_mask], y[on_mask]), 'ece': ece(base_p[on_mask], y[on_mask])}
        if off_mask.any():
            baseline['role_off'] = {'brier': brier(base_p[off_mask], y[off_mask]), 'logloss': logloss(base_p[off_mask], y[off_mask]), 'ece': ece(base_p[off_mask], y[off_mask])}
    else:
        baseline['role_on'] = None
        baseline['role_off'] = None

    if cal is None:
        print(json.dumps({'error':'no calibration loaded', 'baseline': baseline}))
        sys.exit(3)

    out = apply_calibration_to_column(scored, cal, source_col=source_col, out_col='p_cal_calib')
    new_p = pd.to_numeric(out['p_cal_calib'], errors='coerce').clip(0.0,1.0)
    after = {}
    after['all'] = {'brier': brier(new_p, y), 'logloss': logloss(new_p, y), 'ece': ece(new_p, y)}
    if 'role_ctx_outs_used' in out.columns:
        role_vals = pd.to_numeric(out['role_ctx_outs_used'], errors='coerce').fillna(0)
        on_mask = role_vals > 0
        off_mask = role_vals <= 0
        if on_mask.any():
            after['role_on'] = {'brier': brier(new_p[on_mask], y[on_mask]), 'logloss': logloss(new_p[on_mask], y[on_mask]), 'ece': ece(new_p[on_mask], y[on_mask])}
        if off_mask.any():
            after['role_off'] = {'brier': brier(new_p[off_mask], y[off_mask]), 'logloss': logloss(new_p[off_mask], y[off_mask]), 'ece': ece(new_p[off_mask], y[off_mask])}

    res = {'source_col': source_col, 'calibration_path': str(project / 'data' / 'model' / 'telemetry_calibration.json'), 'baseline': baseline, 'after': after}
    print(json.dumps(res, indent=2, sort_keys=True))

    try:
        improved = (after['all']['brier'] is not None and baseline['all']['brier'] is not None and after['all']['brier'] < baseline['all']['brier'])
    except Exception:
        improved = False
    role_on_ok = True
    try:
        if baseline.get('role_on') and after.get('role_on') and baseline['role_on']['brier'] is not None and after['role_on']['brier'] is not None:
            role_on_ok = after['role_on']['brier'] <= baseline['role_on']['brier'] + 1e-6
    except Exception:
        role_on_ok = True
    if improved and role_on_ok:
        sys.exit(0)
    else:
        sys.exit(4)


if __name__ == '__main__':
    main()
