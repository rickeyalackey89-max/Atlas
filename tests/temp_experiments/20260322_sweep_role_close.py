from pathlib import Path
import json
import re
import subprocess
import sys

import pandas as pd

repo = Path(r'c:/Users/rick/projects/Atlas')
config_path = repo / 'config.yaml'
backup = config_path.read_text(encoding='utf-8')
raw = repo / 'archives/bundles/prizepicks_20260317_060443/analysis/20260322_015825/workspace/data/raw/prizepicks_20260317_060443.json'
gamelogs = repo / 'archives/bundles/role_off_full_20260318_bundlecheck/analysis/20260319_190640/workspace/data/gamelogs/nba_gamelogs.csv'
backfill = [sys.executable, str(repo / 'tools/create_eval_leg_backtestv2.py'), '--gamelogs-path', str(gamelogs)]

step_values = [0.005, 0.010, 0.015]
close_values = [0.30, 0.35, 0.40]
results = []

try:
    for step in step_values:
        for close in close_values:
            text = backup
            text = text.replace('    blowout_role_step: 0.01', f'    blowout_role_step: {step:.3f}', 1)
            text = text.replace('  close_sens_mult: 0.35', f'  close_sens_mult: {close:.2f}', 1)
            config_path.write_text(text, encoding='utf-8')

            proc = subprocess.run([sys.executable, '-m', 'Atlas.cli', 'replay', '--raw', str(raw)], cwd=str(repo), capture_output=True, text=True)
            if proc.returncode != 0:
                raise SystemExit(f'replay failed for step={step} close={close}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}')
            match = re.search(r'Run folder:\s*(.+)', proc.stdout)
            if not match:
                raise SystemExit(f'could not find run folder for step={step} close={close}')
            run_dir = Path(match.group(1).strip())

            backfill_proc = subprocess.run(backfill + ['--run-dir', str(run_dir)], cwd=str(repo), capture_output=True, text=True)
            if backfill_proc.returncode != 0:
                raise SystemExit(f'backfill failed for step={step} close={close}:\nSTDOUT:\n{backfill_proc.stdout}\nSTDERR:\n{backfill_proc.stderr}')

            eval_path = run_dir / 'eval_legs.csv'
            scored_path = run_dir / 'scored_legs.csv'
            df = pd.read_csv(eval_path, low_memory=False)
            settled = df[df['push'].fillna(0) == 0].copy()
            scored = pd.read_csv(scored_path, low_memory=False)
            results.append({
                'step': step,
                'close': close,
                'run': run_dir.name,
                'brier_p_adj': float(settled['brier_p_adj'].mean()),
                'brier_p_cal': float(settled['brier_p_cal'].mean()),
                'under_relief_applied_scored': int(scored['under_relief_applied'].fillna(False).astype(bool).sum()) if 'under_relief_applied' in scored.columns else None,
            })
finally:
    config_path.write_text(backup, encoding='utf-8')

results_path = repo / 'temp_experiments' / '20260322_role_close_sweep.json'
results_path.parent.mkdir(parents=True, exist_ok=True)
results_path.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(f'wrote {results_path}')
print(json.dumps(results, indent=2))
