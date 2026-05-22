# Atlas MLB Scripts

Status: MLB development only.

This folder is intentionally sparse after removing copied NBA automation.

Use scripts for:

- local developer helpers
- one-off inspections
- manual source probes
- small migration utilities

Morning eval helper:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\mlb\run_prior_day_eval.ps1
```

By default this evaluates yesterday. It fetches prior-day StatsAPI boxscores,
resolves every matching run for the highest-priority scope (`live_runs`, then
`replay_runs`, then legacy `test_runs`), then writes one eval folder per run:

- `data/mlb/eval/<run_id>/eval_legs.csv`
- `data/mlb/eval/<run_id>/eval_slips.csv`
- `data/mlb/eval/<run_id>/slip_eval.json`

For Task Scheduler, add that PowerShell command as the 6am action. Pass
`-RunId <run_id>` only when evaluating one specific run.

Primary command:

```powershell
uv run atlas-mlb doctor
.\AtlasMLB.ps1 doctor
```

The PowerShell command is a local wrapper around the safe MLB development CLI,
not the old NBA live pipeline.
