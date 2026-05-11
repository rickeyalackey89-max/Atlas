# Local Artifacts Archive

Loose repo-root logs, ad-hoc run notes, and temporary local outputs are archived here by date.

## Layout

- `YYYY-MM-DD/repo_root/` - files moved out of the repository root.
- `YYYY-MM-DD/logs/` - files moved out of the repository-level `logs/` folder.

## Tracking Rules

- Small `.txt` notes and summary `.csv` files may be tracked when they help preserve useful run context.
- Raw `.log`, `.err`, `.pid`, and `READ.txt` files are normally ignored by `.gitignore`; keep them local unless a summary needs to be promoted into `docs/` or `ai/`.
- Durable data archives, paid-cache inputs, model artifacts, and replay corpora should stay in their existing purpose-built `data/` locations.
