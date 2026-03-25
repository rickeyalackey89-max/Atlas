from pathlib import Path
import json
import os
import re
import subprocess
import sys

import pandas as pd

repo = Path(r'c:/Users/rick/projects/Atlas')
config_path = repo / 'temp_experiments/20260320/exp_volatility/config.yaml'
backup = config_path.read_text(encoding='utf-8')
raw_current = repo / 'archives/bundles/prizepicks_20260317_060443/analysis/20260322_015825/workspace/data/raw/prizepicks_20260317_060443.json'
raw_patchtest = repo / 'data/telemetry/Last 10/prizepicks_20260317_060443.json'
gamelogs = repo / 'archives/bundles/role_off_full_20260318_bundlecheck/analysis/20260319_190640/workspace/data/gamelogs/nba_gamelogs.csv'
backfill = [sys.executable, str(repo / 'tools/create_eval_leg_backtestv2.py'), '--gamelogs-path', str(gamelogs)]

step_values = [0.005, 0.010, 0.015]
results = []
env = os.environ.copy()
env['ATLAS_CONFIG_PATH'] = str(config_path)


def _raise_with_output(prefix: str, proc: subprocess.CompletedProcess[str]) -> None:
    message = '\n'.join([prefix, 'STDOUT:', proc.stdout, 'STDERR:', proc.stderr])
    raise SystemExit(message)


def _resolve_run_dir(label: str, stdout: str) -> Path:
    match = re.search(r'Run folder:\s*(.+)', stdout)
    if match:
        return Path(match.group(1).strip())

    analysis_match = re.search(r'\[REPLAY\] analysis_root=(.+)', stdout)
    engine_match = re.search(r'\[REPLAY\] engine_run_id=(.+)', stdout)
    if analysis_match and engine_match:
        analysis_root = Path(analysis_match.group(1).strip())
        scenario_id = analysis_root.parent.parent.name
        ts = analysis_root.name
        return repo / 'data' / 'output' / 'sandbox_runs' / scenario_id / ts / 'runs' / engine_match.group(1).strip()

    raise SystemExit(f'could not find run folder for {label}')


try:
    for step in step_values:
        text = backup.replace('  blowout_role_step: 0.01', f'  blowout_role_step: {step:.3f}', 1)
        config_path.write_text(text, encoding='utf-8')

        for label, raw_path, replay_cmd in [
            ('current', raw_current, [sys.executable, '-m', 'Atlas.cli', 'replay', '--raw']),
            ('patchtest', raw_patchtest, [sys.executable, str(repo / 'tools/replay_scenario.py')]),
        ]:
            if label == 'current':
                proc = subprocess.run(replay_cmd + [str(raw_path)], cwd=str(repo), capture_output=True, text=True, env=env)
            else:
                proc = subprocess.run(
                    replay_cmd + [str(raw_path), '--scenario-id', 'role_off_full_20260318_patchtest'],
                    cwd=str(repo),
                    capture_output=True,
                    text=True,
                    env=env,
                )
            if proc.returncode != 0:
                _raise_with_output(f'replay failed for {label} step={step}', proc)

            run_dir = _resolve_run_dir(label, proc.stdout)

            backfill_proc = subprocess.run(
                backfill + ['--run-dir', str(run_dir)],
                cwd=str(repo),
                capture_output=True,
                text=True,
                env=env,
            )
            if backfill_proc.returncode != 0:
                _raise_with_output(f'backfill failed for {label} step={step}', backfill_proc)

            eval_path = run_dir / 'eval_legs.csv'
            scored_path = run_dir / 'scored_legs.csv'
            df = pd.read_csv(eval_path, low_memory=False)
            settled = df[df['push'].fillna(0) == 0].copy()
            scored = pd.read_csv(scored_path, low_memory=False)
            results.append({
                'label': label,
                'step': step,
                'run': run_dir.name,
                'brier_p_adj': float(settled['brier_p_adj'].mean()),
                'brier_p_cal': float(settled['brier_p_cal'].mean()),
                'under_relief_applied_scored': int(scored['under_relief_applied'].fillna(False).astype(bool).sum()) if 'under_relief_applied' in scored.columns else None,
            })
finally:
    config_path.write_text(backup, encoding='utf-8')

results_path = repo / 'temp_experiments' / '20260322_compare_blowout_role.json'
results_path.parent.mkdir(parents=True, exist_ok=True)
results_path.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(f'wrote {results_path}')
print(json.dumps(results, indent=2))