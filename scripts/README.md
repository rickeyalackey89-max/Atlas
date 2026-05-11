# Atlas Scripts

Operational wrappers, ad-hoc analysis, diagnostics, validation checks, reports, marketing exports, and local automation live here.

## Folder Map

- `audits/` - one-off or periodic audit/evaluation scripts.
- `diagnostics/` - debugging, inspection, and root-cause investigation scripts.
- `experiments/` - sweeps, ablations, LOSO/LODO studies, prototypes, and research runs.
- `reports/` - result extraction, slip scoring reports, and historical post helpers.
- `validation/` - smoke checks, verification scripts, artifact checks, and production config checks.
- `marketing/` - winner/free-pick HTML and graphic export utilities.
- `dev/` - local development helpers.
- `artifacts/` - local script outputs that are useful for handoff but are not durable tools.

## Root Scripts

Keep scheduled or operator-facing automation at the root when external tooling may call the exact path:

- `run_iael_*.cmd`
- `task_*.xml`
- `setup_daily_automation.ps1`
- `task_8am_graphics.ps1`

Avoid adding new one-off Python files at the root. Put them in the smallest matching subfolder instead.

## Boundary With Tools

Use `tools/` for repeatable program runners that are part of the Atlas operating system:

- fetchers
- readers
- replay builders
- backfills
- trainers
- generators
- publishers
- calibrators

Use `scripts/` for investigations, checks, reports, experiments, and one-off maintenance.
