# Atlas MLB Dev Gutting Plan

Status: active plan  
Last updated: 2026-05-11

## Principle

Remove or quarantine copied NBA behavior only after the MLB replacement boundary exists.

## Keep For Now

- Python environment files.
- Packaging skeleton.
- Shared runtime patterns worth reusing.
- Tests that validate generic contracts.
- Docs that explain operating philosophy.

## Quarantine First

Copied NBA code should be treated as legacy reference until reviewed.

Candidates:

- NBA fetchers.
- NBA injury and role metrics.
- NBA trainer scripts.
- NBA stage orchestration.
- NBA dashboard publishing assumptions.
- NBA eval/gamelog settlement tools.

## Replace With MLB

Initial replacements:

- `src/mlb/cli.py`
- `src/mlb/runtime/paths.py`
- `src/mlb/domain/markets.py`
- `config/sports/mlb.yaml`
- `data/mlb/` folder contract.

## First Gutting Pass

1. Make the dev runner call MLB skeleton commands only.
2. Add MLB docs and config.
3. Add MLB package namespace.
4. Add empty data folder contract.
5. Mark copied NBA live jobs as legacy and non-production.

## Second Gutting Pass

1. Move NBA-specific tools into a legacy reference folder or delete them.
2. Remove copied scheduled task XML files.
3. Remove NBA-specific data snapshots from MLB Dev after confirming they are not needed.
4. Replace old CLI entrypoints with MLB-only commands.
5. Add MLB replay fixture tests.

## Safety Rules

- Never gut the production NBA repo.
- Never delete copied MLB-dev files without confirming they are not the only local copy of a useful artifact.
- Prefer small migrations with a status check after each.
- Keep MLB publishing disabled until replay validation exists.
