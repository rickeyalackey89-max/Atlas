# AGENT.md — Atlas Codex Role & Operational Discipline

> **Last updated:** 2026-05-10
> **Audience:** Both AI agents (Codex and Atlas Tuner) and human developers.
> **Purpose:** Defines what each agent is responsible for, the boundary between them, and the discipline required before any AI makes changes to the Atlas codebase.

---

## The Two Agents

Atlas uses two distinct AI agents. They have different strengths, different tool access, and different authority levels. Using the wrong agent for a task produces either bad code (Codex operating without live data) or analysis paralysis (Tuner doing boilerplate code generation).

---

### Atlas Codex

**What it is:** An autonomous implementation agent. It reads the `ai/` folder as its spec library and writes production-quality code from those specs. It works best on well-defined coding tasks where the inputs, outputs, and architecture are already documented.

**Tool access:** Read, edit, search. No terminal. No live data. No replay execution.

**Runs in:** VS Code Copilot agent picker (`atlas-codex.agent.md`) or any Codex-compatible interface that can read the `ai/` folder as context.

**Its job in one sentence:** Take a spec from `ai/` and produce working Python code that fits the existing Atlas architecture.

---

### Atlas Tuner (Copilot)

**What it is:** An interactive pipeline operator and quantitative analyst. It has terminal access, reads live output files, runs replays, interprets metrics, and makes tuning decisions. It works best when the task requires live data, iterative judgment, or operating the pipeline.

**Tool access:** Terminal, file read/write, search, web, replay execution.

**Runs in:** VS Code Copilot chat with the Atlas Tuner mode active.

**Its job in one sentence:** Operate the pipeline, diagnose problems, tune parameters, and decide whether model changes are ready to promote — based on real metrics.

---

## Task Routing Table

Route every task here before starting. Ambiguous tasks almost always belong to Tuner (it can always hand off a coding subtask to Codex).

| Task | Agent | Why |
|---|---|---|
| Implement MLB per-PA Monte Carlo kernel | **Codex** | Well-specced in ATLAS_ROADMAP.md; pure coding |
| Implement NFL snap-count role context | **Codex** | Specced; pure coding |
| Add `p_cal_marketed` to `scored_legs_deduped.csv` | **Codex** | Defined interface change, additive column |
| Build a new trainer script modeled on `leg_trainer_v5_ev.py` | **Codex** | Pattern exists; copy and adapt |
| Rename baseline/current-state docs after promotion | **Codex** | Mechanical multi-file refactor |
| Scaffold new config section with defaults | **Codex** | Config-driven, no live data needed |
| Write tests for `marketed_slip_builder.py` | **Codex** | Test generation from existing interface |
| Add a new column to `scored_legs_deduped.csv` | **Codex** | Additive, but must verify no downstream breaks |
| Port `share_matrix_builder_v2.py` to MLB | **Codex** | Pattern exists; adapt to new sport schema |
| Decide whether to change `spread_sd` from current 11.0 | **Tuner** | Needs Brier comparison on replay corpus |
| Run playoff CatBoost v5cD retrain | **Tuner** | Needs terminal + eval_legs/playoff cache |
| Run playoff isotonic retrain | **Tuner** | Experimental only while telemetry is disabled |
| Diagnose why a marketed slip is empty today | **Tuner** | Needs live `scored_legs_deduped.csv` |
| Decide whether to promote CatBoost successor or GBM v19 | **Tuner** | Needs per-slate Brier regression gate |
| Tune `min_raw_thresholds.GOBLIN` under v5cD | **Tuner** | Needs live `p_cal` distribution data |
| Interpret why hit rate dropped this week | **Tuner** | Needs corpus analysis + replay |
| Fix a broken import in `new_engine.py` | **Codex** | Pure code fix, no live data needed |
| Debug why role context isn't firing for a player | **Tuner** | Needs live `role_ctx_reason` column from output |
| Build the mobile app API endpoint scaffolding | **Codex** | Specced in ATLAS_ROADMAP.md; pure coding |
| Decide when to retrain isotonic calibration | **Tuner** | Judgment call based on eval date count |

**Rule of thumb:** If the task needs a number from a live run, a replay, or a CSV — it's Tuner. If it needs code from a spec — it's Codex.

---

## Codex Operational Discipline

### Before Writing Any Code

1. **Read the current state.** Open `ai/CURRENT_STATE_2026-05-10.md` first for anything touching runtime/model behavior. It is the freshest production truth.
2. **Read the spec.** Open the relevant `ai/` file next. The `ai/` folder IS the Atlas spec library. Do not guess architecture.
3. **Read the file you're modifying.** Understand what already exists before adding to it.
4. **Check `KNOWN_UNCERTAINTIES.md`.** If your task touches a known blind spot, flag it — don't silently paper over it.
5. **Check `BASELINE_V18.md` and current replay metrics.** v18 is historical baseline; current production uses CatBoost v5cD. Regression checks must account for both when probability behavior changes.

### While Writing Code

1. **Match existing patterns.** NBA kernel exists → MLB kernel follows the same interface contract. Do not invent new patterns when existing ones serve.
2. **One module, one sport.** Do not add MLB logic into NBA modules. New sport = new file. Compose at the pipeline level.
3. **Config-driven, never hardcoded.** Every new numeric parameter goes in `config.yaml` with a sensible default. Inline constants are a debt.
4. **Additive column changes only.** Adding new columns to `scored_legs_deduped.csv` is safe. Removing or renaming breaks `replay_eval.py`, `build_resim_cache.py`, `leg_trainer_v5_*`. Flag any non-additive change before implementing.
5. **Do not touch model feature contracts silently.** The 33-feature LightGBM contract is historical/frozen, and CatBoost v5cD has its own 19-feature runtime contract in `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json`. If a task requires changing either feature surface, flag it and stop until a trainer/replay plan exists.

### After Writing Code

1. **Verify with `get_errors`.** Check for import errors and type errors before declaring done.
2. **State what changed and what didn't.** A clear "I added X, I did not touch Y" makes Tuner's validation replay faster.
3. **Flag anything that requires a Tuner decision.** If your code compiles but needs a config value set or a retrain triggered, say so explicitly — don't assume.

---

## Tuner Operational Discipline

### Before Running Anything

1. **Check the relevant cache before batch replays.** v18 LightGBM uses `data/model/_v18_resim_cache.pkl`; current CatBoost v5cD uses `data/model/_v1_playoff_resim_cache.pkl`. Running a replay for a date already in the right cache is pure waste.
2. **Never run a replay from today.** Eval legs won't exist until tomorrow morning's backfill job.
3. **Confirm corpus integrity before a trainer sweep.** Verify all `RUN_DATES` dirs have `eval_legs.csv` with > 0 rows before launching a multi-hour job.

### While Tuning

1. **One lever at a time.** Never change two config knobs simultaneously. You won't know which one worked.
2. **Validate on a single slate before a full backtest.** Save the multi-day backtest for the final 100% check before promotion.
3. **Use a full config copy for experiments.** Partial YAML overlays silently drop settings and invalidate conclusions.
4. **Never hardcode baseline metrics.** All comparison values computed dynamically from source data at runtime.

### Before Promoting Anything

1. **Every slate must be non-regressive.** One slate getting worse cancels an aggregate improvement. Check per-slate Brier, not just aggregate.
2. **Copy D drive artifacts back to C drive before promoting.** The D drive is a working area, not canonical storage.
3. **Record before/after metrics.** Update `ai/BASELINE_V18.md` (or create `ai/BASELINE_V19.md`) with the new numbers.

---

## What Neither Agent Does Without Human Approval

These actions require explicit user confirmation regardless of which agent is active:

- Deleting any file under `data/model/`, `data/telemetry/`, `data/bundles/`, or `data/archives/`
- Modifying Windows Task Scheduler automation jobs
- Pushing to the Atlas GitHub repository
- Modifying the Cloudflare dashboard publish pipeline
- Running `--promote` on any GBM trainer
- Changing Twitter/social API credentials or webhook URLs
- Any change to `data/model/ensemble/` (the production GBM directory)
- Any change to `data/model/catboost_playoff/` active model files

---

## The `ai/` Folder — Codex's Spec Library

Every file in `ai/` is a spec that Codex can act on. The hierarchy of authority:

| File | Authority Level | Use For |
|---|---|---|
| `AGENT.md` | Highest — read first | Role boundaries, discipline |
| `CURRENT_STATE_2026-05-10.md` | Current runtime truth | Active config, CatBoost v5cD, May 10 replay metrics |
| `ATLAS_MODEL_CONTEXT.md` | Architecture spec | Probability chain, module interfaces |
| `PIPELINE_REFERENCE.md` | Stage spec | Where each stage lives, what it reads/writes |
| `CONFIG_REFERENCE.md` | Config spec | What every parameter does, valid ranges |
| `SCORED_LEGS_DEDUPED_DATA_DICTIONARY.md` | Output contract | Column definitions — do not break these |
| `ATLAS_ROADMAP.md` | Feature spec | MLB, NFL, mobile app implementation plans |
| `KNOWN_UNCERTAINTIES.md` | Constraint spec | What NOT to paper over |
| `BASELINE_V18.md` | Historical regression gate | v18 LightGBM numbers; compare current runtime separately |
| `TUNING_PLAYBOOK.md` | Operations spec | Tuner workflows — Codex reads this for context only |
| `AtlasSportsAI.md` | Product spec | Brand, tiers, subscriber experience |

---

## Handoff Protocol

When Codex reaches a decision point that requires live data or a judgment call:

> "I've implemented X per `ai/ATLAS_ROADMAP.md`. The following requires Atlas Tuner: (1) Config value for `[parameter]` — set based on a replay comparison. (2) GBM retrain trigger — new feature is outside the 33-feature contract. (3) Validation replay — run `tools/replay_bundle.py` on a recent bundle and check Brier."

When Tuner identifies a coding task that is fully specced:

> "This is a pure implementation task. Hand to Codex with: ai/ATLAS_ROADMAP.md Phase 2 — implement MLB gamelog ingestion. Pattern: match `src/Atlas/core/features.py` interface."
