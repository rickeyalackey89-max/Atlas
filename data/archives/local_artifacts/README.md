# Local Artifacts Archive

Loose repo-root logs, ad-hoc run notes, and temporary local outputs are archived here by date.

## Layout

- `YYYY-MM-DD/repo_root/` - files moved out of the repository root.
- `YYYY-MM-DD/logs/` - files moved out of the repository-level `logs/` folder.
- `YYYY-MM-DD/catboost/` - ignored CatBoost training telemetry output.
- `YYYY-MM-DD/outputtelem/` - historical sandbox telemetry moved out of the repo root.

## Tracking Rules

- Small `.txt` notes and summary `.csv` files may be tracked when they help preserve useful run context.
- Raw `.log`, `.err`, `.pid`, and `READ.txt` files are normally ignored by `.gitignore`; keep them local unless a summary needs to be promoted into `docs/` or `ai/`.
- `catboost_info/` and `docs.zip` are ignored generated artifacts; archiving them here is for local cleanup, not source control.
- Durable data archives, paid-cache inputs, model artifacts, and replay corpora should stay in their existing purpose-built `data/` locations.
