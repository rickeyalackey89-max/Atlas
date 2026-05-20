# Atlas MLB Sobol / QMC Engine Decision

Status: accepted architecture decision
Last updated: 2026-05-12

## Decision

Atlas MLB will be built as a simulation-first probability engine.

The core probability estimator will move toward a Sobol / Quasi-Monte Carlo
simulation engine rather than a direct NBA-style CAT/GBM probability stack.

The accepted model shape is:

```text
source snapshots
  -> normalized board
  -> context and feature tables
  -> parameter models
  -> Sobol / QMC simulator
  -> market probability extraction
  -> calibration layer
  -> slip construction
  -> deterministic and OpenAI operator review
```

## Critical Boundary

Sobol / QMC does not replace baseball modeling.

It replaces noisy random sampling as the probability estimator after the engine
has estimated the baseball world.

Trained/statistical models still own:

- projected plate appearances
- pitcher leash and batters faced
- lineup slot stability
- batter event rates
- pitcher event rates
- bullpen exposure
- park/weather modifiers
- market-specific calibration

The simulator owns:

- game-path sampling
- player outcome distributions
- market probability extraction
- correlation-aware slip risk estimates

## Why This Is The Right MLB Direction

MLB props are path-dependent.

The relevant question is not only:

```text
What is the mean projection?
```

It is:

```text
What paths create the over or under?
How many failure points does that path have?
How wide is the outcome distribution?
How correlated are the legs?
```

Sobol / QMC supports this better than a flat projection model because it can
simulate the uncertainty in opportunity, matchup, game script, pitcher leash,
bullpen exposure, and environment.

## Non-Goals

- Do not build a pure hand-written simulator with no trained inputs.
- Do not let OpenAI set probabilities.
- Do not use NBA calibration thresholds as MLB acceptance gates.
- Do not collapse every market into one universal MLB model.
- Do not make simulation output non-deterministic between live and replay.

## Required Output Contract

The scored-leg surface should eventually include distribution and simulation
metadata, not just one probability.

Minimum future fields:

- `mean_projection`
- `median_projection`
- `p_over`
- `p_under`
- `p_push`
- `p10`
- `p25`
- `p75`
- `p90`
- `volatility_score`
- `fragility_score`
- `stability_score`
- `opportunity_type`
- `projected_opportunity`
- `opportunity_confidence`
- `opportunity_fragility_score`
- `opportunity_model_version`
- `simulation_n`
- `simulation_seed`
- `simulation_kernel_version`
- `parameter_model_version`
- `calibration_version`

## Phase 1 Simulator Scope

The first production-shaped simulator is intentionally narrow:

- deterministic Sobol seed management
- market-specific baseline distributions
- baseline parameter table
- baseline opportunity estimates for batter PA and pitcher leash/outs
- scored-leg distribution outputs
- simulation manifest
- operator input packet for deterministic and future AI review
- development slip-family artifacts
- deterministic operator hard-stop checks
- simple park/weather hooks
- basic fragility and volatility outputs
- replay-safe manifests

This phase can use simple parameter estimates. The goal is to lock the engine
shape before adding complex feature layers.

Implemented shell:

- `src/mlb/modeling/qmc.py`
- `src/mlb/modeling/opportunity.py`
- `src/mlb/modeling/parameters.py`
- scoring now consumes the generated parameter table during full board pipeline execution
- `src/mlb/runtime/pipeline_execution.py`
- `src/mlb/runtime/operator_packet.py`
- `uv run atlas-mlb run board`

## Phase 2 Scope

Add real parameter models:

- lineup slot and PA model
- pitcher leash model
- batter/pitcher handedness context
- K/BB/contact/damage event-rate models
- bullpen exposure model
- park/weather modifiers
- market-specific calibration

## Phase 3 Scope

Add advanced baseball interactions:

- pitch mix collisions
- pitch-level batter weaknesses
- defense and catcher context
- umpire zone context
- correlated slip simulation
- OpenAI operator analysis of simulation assumptions

## OpenAI Role

OpenAI is an operator and audit layer.

Allowed:

- summarize simulation output
- explain path quality
- detect anomalies in inputs or outputs
- produce operator reports
- recommend publish warnings or hard-stop review

Not allowed:

- change probabilities
- rewrite picks
- override deterministic hard stops
- invent source context not present in manifests

## Promotion Rule

No MLB probability engine should be promoted because it looks good on one slate.

Promotion requires:

- replay parity between live and replay
- deterministic simulation seeds
- market-level Brier/log-loss
- distribution calibration checks
- holdout slate validation
- source completeness manifests
- documented failure modes
