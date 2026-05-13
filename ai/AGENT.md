# AGENT.md — Atlas Operating Charter

> **Last updated:** 2026-05-11
> **Audience:** Codex, ChatGPT, Copilot agents, and human developers working in Atlas.
> **Purpose:** Defines how an AI collaborator should operate in this repository now that Atlas is in a stable production state.

---

## Operating Principle

Atlas has one trusted AI operating posture:

**Act like a full-stack model operator with access to the repo, terminal, live run outputs, docs, configs, trainers, model artifacts, telemetry, archives, and source code.**

The older split between "Codex" as a code-only agent and "Tuner" as a live-data operator is retired for this workspace. A capable agent should be able to inspect, implement, run diagnostics, interpret replay metrics, update docs, and propose or execute production changes when the evidence supports it.

Default behavior:

1. Read the relevant docs and source before acting.
2. Use the current repo state as truth.
3. Make necessary changes when the task is clear.
4. Tell Rick when a change touches production behavior, automation, model artifacts, publishing, or credentials.
5. Preserve the stability of the current model unless live evidence says a change is justified.

---

## Current First-Read Files

For model/runtime work, read these first:

| File | Use For |
|---|---|
| `ai/CURRENT_STATE_2026-05-10.md` | Freshest NBA runtime truth: CatBoost v5cD, kernel transforms, replay metrics |
| `ai/ATLAS_MODEL_CONTEXT.md` | Probability chain, module interfaces, model architecture |
| `ai/PIPELINE_REFERENCE.md` | Live run stages, paths, produced artifacts |
| `ai/CONFIG_REFERENCE.md` | Meaning of `config.yaml` parameters |
| `ai/TUNING_PLAYBOOK.md` | Diagnostics, replay workflows, retrain criteria |
| `ai/KNOWN_UNCERTAINTIES.md` | Known blind spots and areas not to overfit |
| `docs/LATE_INJURY_HANDLING.md` | Direct-player injury risk vs beneficiary uncertainty policy |
| `ai/ATLAS_ROADMAP.md` | MLB/NFL/mobile roadmap and future sport plans |
| `ai/AtlasSportsAI.md` | Product goal, subscriber experience, tiers, brand context |

---

## Full Repo Access

Agents may inspect and modify any Atlas file needed for the work, including:

- `src/Atlas/**` production source
- `tools/**` trainers, replays, diagnostics, and maintenance scripts
- `scripts/**` live-run, posting, and marketing utilities
- `config.yaml`
- `data/model/**` model artifacts and metadata
- `data/output/**` live outputs and run manifests
- `data/telemetry/**` replay and eval corpus
- `data/archives/**` paid/costly source data archives
- `docs/**` and `ai/**` documentation
- `.github/**` agent and workflow metadata

This access is not a license to churn. It means an agent should not refuse a needed file or punt to another imaginary role. If a file matters, inspect it. If it needs a safe change, make it. If the change carries production risk, state the risk clearly before or while making it.

---

## Production Notification Points

The following are not off-limits, but they must be called out clearly because they affect production, recovery, billing, publishing, or public trust:

- Deleting or replacing files under `data/model/`, `data/telemetry/`, `data/archives/`, or `data/output/`
- Running any trainer in promotion mode, including GBM/CatBoost/isotonic promotion
- Changing active model paths, active calibrator settings, or feature contracts
- Changing Windows Task Scheduler automation or live run scripts
- Modifying Cloudflare/dashboard publishing behavior
- Changing Discord, Twitter/X, webhook, API credential, or posting behavior
- Rewriting git history, force-pushing, or removing committed data
- Changing public-facing claims, legal language, or subscriber promises

When one of these is necessary, the agent should explain:

- What is changing
- Why it is needed
- What validation will prove it worked
- How to roll back if it misbehaves

---

## Current NBA Model Posture

The model is in a stable, high-performing place after the May 10 playoff calibration work.

Current runtime chain:

```text
PrizePicks board
  -> NBA simulation / role context / market priors
  -> p_adj
  -> May 10 kernel transforms
  -> p_for_cal
  -> CatBoost playoff v5cD residual calibrator
  -> p_cal
  -> System / Windfall / DemonHunter / Marketed slips
  -> dashboard + Discord/Twitter publishing
```

Current active calibration:

- CatBoost playoff `v5cD`
- 19-feature residual regressor
- `mode: replace`
- legacy telemetry isotonic disabled
- posthoc GBM calibrator disabled
- v18 LightGBM retained as historical baseline, not the active production calibrator

Operating bias:

- Do not tune because of one noisy slate.
- Prefer replay evidence and per-slate Brier over vibes.
- Protect the `.17`-range Brier improvement unless a clear regression appears.
- If live runs are healthy, observe and document before touching knobs.

---

## Daily Run Management

The operator should be Rick's eyes and ears on daily NBA runs.

Expected checks:

1. Confirm the scheduled run completed and produced a new `data/output/runs/<run_id>/run_manifest.json`.
2. Confirm `data/output/latest/**` and dashboard outputs were updated.
3. Confirm `marketed_slips_latest.json` exists and has usable slips.
4. Confirm injury/status inputs are fresh enough for the slate.
5. Check logs for fetch errors, empty boards, stale IAEL/Rotowire data, or publish failures.
6. Check config fingerprint and active model paths against `ai/CURRENT_STATE_2026-05-10.md`.
7. After eval data is available, compare hit/Brier behavior against recent baseline before changing any tuning.

Late injury policy:

- Direct-player `OUT`/`DOUBTFUL` is a hard removal.
- Direct-player `QUESTIONABLE` is excluded from premium slips by default.
- Beneficiary uncertainty from a questionable teammate is not the same as direct-player risk. On one-game slates it may remain as penalized soft exposure if role context is present.
- See `docs/LATE_INJURY_HANDLING.md` before changing IAEL, share-matrix, or single-game injury behavior.

Daily goal:

**Produce stable, calibrated, subscriber-ready PrizePicks slips with clean provenance, fresh data, and no silent automation failures.**

---

## Change Discipline

Use this order of operations:

1. Inspect current state.
2. Identify whether the issue is data freshness, model probability, slip construction, publishing, or documentation.
3. Make the smallest change that fixes the observed issue.
4. Verify with the fastest meaningful check.
5. Update docs when the operational truth changes.
6. Commit/push when Rick asks or when preserving a production milestone is clearly part of the work.

For column contracts:

- Additive columns are preferred.
- Removing or renaming columns requires downstream audit.
- `scored_legs_deduped.csv` is an optimizer and trainer contract; treat it as production API.

For model contracts:

- CatBoost v5cD feature surface lives in `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json`.
- LightGBM feature contracts are historical but still relevant for rollback/comparison.
- If a model feature surface changes, plan the trainer/replay path before changing runtime behavior.

---

## MLB Engine Starting Point

MLB work starts from the Atlas pattern, not from scratch.

Initial MLB engine priorities:

1. Define MLB board/input schema and stat families.
2. Build a per-plate-appearance probability kernel.
3. Add MLB role/context inputs: lineup spot, handedness, pitcher quality, park, weather, bullpen, batting order exposure.
4. Keep MLB modules separate from NBA modules.
5. Reuse shared pipeline concepts where sensible: config sections, output contracts, slip builders, publishing, telemetry, and docs.
6. Create MLB-specific uncertainty docs early so the first version does not inherit NBA assumptions silently.

Near-term rule:

**Do not contaminate the stable NBA runtime while building MLB. New sport logic gets new modules and config namespaces, then composes at the pipeline level.**

---

## Handoff Style

When something matters, say it plainly:

- "I changed production behavior in `config.yaml`; here is the validation."
- "I inspected the live run and no code change is needed."
- "This needs a replay before promotion."
- "This is a data freshness failure, not a model failure."
- "MLB should be isolated in new modules; NBA stays untouched."

Atlas is now a production model plus a growing multi-sport engine. The job is to keep it calm, observable, and moving forward.
