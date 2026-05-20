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
resolves the matching run from `live_runs` first and `test_runs` second, then
writes:

- `data/mlb/eval/<run_id>/eval_legs.csv`
- `data/mlb/eval/<run_id>/eval_slips.csv`
- `data/mlb/eval/<run_id>/slip_eval.json`

For Task Scheduler, add that PowerShell command as the 6am action, or pass
`-RunId <run_id>` when evaluating a specific replay.

Primary command:

```powershell
uv run atlas-mlb doctor
.\AtlasMLB.ps1 doctor
```

The PowerShell command is a local wrapper around the safe MLB development CLI,
not the old NBA live pipeline.
