# Atlas Docs

Last updated: 2026-05-11

This folder is the durable engineering documentation for Atlas. The `ai/` folder can carry operator-facing summaries and handoff notes, but this `docs/` folder should be the long-term repo reference.

## Start Here

- [Current State](CURRENT_STATE_2026-05-10.md) — active NBA runtime truth: CatBoost playoff v5cD, May 10 kernel transforms, replay metrics.
- [Model Context](ATLAS_MODEL_CONTEXT.md) — model architecture, active probability chain, config knobs, and debugging flow.
- [Pipeline Reference](PIPELINE_REFERENCE.md) — live run file-to-file trace, publishing, Discord, and evaluation artifacts.
- [Website To-Do](WEBSITE_TODO.md) — dashboard, 6AM eval, canonical report run, and Discord posting requirements.
- [Known Uncertainties](KNOWN_UNCERTAINTIES.md) — current blind spots and areas not to overfit.
- [Tuning Playbook](TUNING_PLAYBOOK.md) — diagnostic workflow before changing model or slip-builder behavior.
- [Docs Audit](DOCS_AUDIT_2026-05-11.md) — summary of the May 11 docs cleanup and remaining trainer-audit gap.

## Reference Docs

- [Data Dictionary](DATA_DICTIONARY.md) — repo data layout and important artifacts.
- [Scored Legs Data Dictionary](SCORED_LEGS_DEDUPED_DATA_DICTIONARY.md) — current `scored_legs_deduped.csv` column surface.
- [Replay and Live Run Rules](REPLAY_AND_LIVE_RUN_RULES.md) — strict replay versus live run contract.
- [Baseline v18 + Current Runtime](BASELINE_V18.md) — historical LightGBM baseline plus current CatBoost runtime reference.
- [Trainer Requirements](TRAINER_REQUIREMENTS.md) — historical trainer requirements. This file is intentionally not refreshed yet; trainers need a dedicated audit before being treated as current.

## Subfolders

- [contracts](contracts/) — interface contracts for telemetry readers and adapters.
- [experiments](experiments/) — historical experiments and research notes. Treat these as provenance unless a doc explicitly says active.
- [features](features/) — feature and subsystem design notes.
- [mobileGPT](mobileGPT/) — mobile workflow for ChatGPT, Codex, GitHub, and VS Code handoffs.
- [enviroment](enviroment/) — captured local environment snapshots. The folder name is historical.

## Cleanup Rules

- If a doc describes old production behavior, either update it or add a clear historical/superseded banner.
- If a doc is duplicated at the root and in a subfolder, keep the subfolder copy and delete the redundant root copy.
- If a trainer doc references current production, verify it against manifests and active config before trusting it.
- Prefer short status headers over burying caveats deep in the doc.
