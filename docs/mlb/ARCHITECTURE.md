# Atlas MLB Architecture

Status: draft architecture  
Last updated: 2026-05-11

## Goal

Build an MLB prediction engine that can eventually power Atlas slips, dashboard surfaces, Discord posts, and replay/eval reporting while leaving the NBA model untouched.

## High-Level Shape

MLB should become a sport module, not a patched NBA pipeline.

```text
raw sources
  -> source normalization
  -> injury and availability layer
  -> share matrix
  -> parameter models
  -> Sobol / QMC simulation engine
  -> market probability extraction
  -> calibration layer
  -> slip construction
  -> deterministic anomaly checks
  -> operator AI evaluation
  -> publish decision
  -> replay/eval
  -> publishing adapters
```

## Runtime Boundary

The CLI is only the command surface. It must parse intent and delegate runtime
work to focused modules.

Runtime modules:

- `runtime/preflight.py`: safety checks, path creation, dev status reports.
- `runtime/paths.py`: repo and MLB data path resolution.
- `runtime/pipeline.py`: declarative live/replay pipeline stage lists.
- `runtime/publishing.py`: dashboard/Discord guardrails and publishing state.
- `runtime/bundles.py`: expected run artifacts and replay bundle contracts.
- `runtime/scoring.py`: thin runtime boundary for scored-leg generation.
- `runtime/live_delegation.py`: live-run plan and safety boundary.
- `runtime/replay_delegation.py`: single replay and bundle replay plan boundaries.
- `runtime/inspection.py`: read-only status/info reports used by the CLI.

The CLI should not own pipeline orchestration, publishing decisions, bundle
contracts, or tool execution logic. It may call the appropriate runtime boundary
for a requested command.

## Live And Replay Boundaries

Atlas MLB has three different run surfaces:

- Live run: same-day PrizePicks board scoring for slips, dashboard payloads, and
  later Discord publishing.
- Single replay: one targeted historical run for debugging, validation, or spot
  checks.
- Bundle replay: many historical runs grouped together to build a corpus, cache,
  LOSO set, or trainer input.

These surfaces must remain separate in command names, manifests, output folders,
and publishing permissions.

Rules:

- Live runs do not settle outcomes.
- Single replays may settle one historical run.
- Bundle replays aggregate many single replays.
- Replay outputs must not overwrite live artifacts.
- Publishing is disabled for replay paths by default.

## Accepted Probability Engine Direction

Atlas MLB is a simulation-first engine.

The core probability estimator will move toward Sobol / Quasi-Monte Carlo
simulation. Trained/statistical models estimate simulation inputs; the simulator
estimates outcome distributions and market probabilities.

Canonical decision doc:

- `docs/mlb/SOBOL_QMC_ENGINE_DECISION.md`

Rules:

- Sobol / QMC replaces noisy random sampling, not baseball modeling.
- CAT/GBM may be used as parameter models or calibration layers.
- OpenAI may review artifacts, but must not mutate probabilities or picks.
- Live and replay must use deterministic simulation seeds.

## Kernel 1: Game Environment

Purpose: estimate run environment and matchup context before player-level scoring.

Inputs:

- probable starters
- starting lineups
- bullpen usage and fatigue
- park factors
- weather, wind, roof state
- umpire context if available
- team handedness splits
- market implied totals and movement
- injury and call-up context

Outputs:

- expected run environment
- pitcher-side matchup pressure
- hitter-side matchup lift/suppression
- weather and park multipliers
- game-level confidence flags

## Kernel 2: Opportunity And Parameter Models

Purpose: estimate the uncertain inputs consumed by the simulator.

Batter parameters:

- projected plate appearances
- lineup slot stability
- pinch-hit risk
- handedness exposure
- event-rate priors by market

Pitcher parameters:

- projected batters faced
- projected pitch count
- leash stability
- third-time-through exposure
- K/BB/contact/damage event-rate priors

Outputs:

- parameter table
- parameter confidence fields
- source completeness flags
- simulation-ready distribution inputs

## Kernel 3: Sobol / QMC Player Prop Simulation

Purpose: score individual player markets using player role, matchup, and line context.

Batter markets:

- hits
- singles
- doubles
- triples
- total bases
- hits + runs + RBIs
- home runs
- runs
- RBI
- plate appearances
- walks
- strikeouts
- stolen bases
- hitter fantasy score

Pitcher markets:

- strikeouts
- outs recorded
- earned runs
- hits allowed
- walks allowed
- pitches thrown
- pitcher fantasy score, if platform-supported

Outputs:

- mean and median projection
- p-over, p-under, and p-push
- distribution percentiles
- fair line / fair price
- edge versus market
- confidence tier
- volatility, fragility, and stability scores
- simulation seed and kernel version

## Market Layer

The market layer must normalize platform-specific prop names into canonical MLB markets.

Requirements:

- preserve source line and odds
- preserve sportsbook/platform provenance
- map equivalent markets across sources
- reject unsupported markets explicitly
- keep void/postponement rules separate from scoring logic

## Scoring Engine Boundary

Initial implemented scorer:

- `modeling/probability.py`: market-prior probability baseline backed by the Sobol/QMC shell.
- `modeling/qmc.py`: deterministic Sobol/QMC market simulation helper.
- `modeling/opportunity.py`: baseline batter/pitcher opportunity estimator.
- `modeling/features.py`: baseline player-prop feature-table writer.
- `modeling/parameters.py`: baseline simulation parameter artifact writer.
- `modeling/engine.py`: converts engine-board rows into scored-leg artifacts.
- `runtime/pipeline_execution.py`: internal end-to-end board pipeline executor.
- `runtime/operator_packet.py`: review packet writer for deterministic and future OpenAI review.
- `runtime/scoring.py`: CLI/runtime adapter for `atlas-mlb score board`.

Rules:

- The first scorer is contract scaffolding, not a production model.
- Sobol / QMC simulation should replace internals without breaking run/replay contracts.
- CAT/GBM should be treated as parameter or calibration candidates, not the primary MLB engine shape.
- The engine must not fetch sources, publish externally, or make dashboard decisions.

## Source Layer

Initial source plan:

- PrizePicks MLB board for player markets and lines.
- ESPN MLB injuries for broad injury status and notes.
- ESPN MLB game logs / box scores for settlement and history.
- Minor-league roster and stat source for call-up priors once selected.
- External market/stat priors for sportsbook context and line movement.

PrizePicks should be broad-first: fetch all MLB board markets and filter after scoring instead of pre-deciding a narrow board.

## Share Matrix

Keep the NBA share-matrix concept, but replace the implementation.

MLB share matrix responsibilities:

- lineup probability
- batting-order slot stability
- projected plate appearances
- platoon risk
- injury replacement risk
- pitcher rotation state
- opener/bulk pitcher risk
- bullpen fatigue
- defensive adjustment context

## Replay First

Replay integrity comes before live automation.

Minimum replay contract:

- immutable raw snapshot
- normalized board snapshot
- source manifests
- feature table snapshot
- model artifact manifest
- scored output
- outcome/eval table
- run metadata with config hash

## Operator AI Layer

The operator AI layer reviews outputs after model scoring and slip construction.
It is a publish gate, not a scoring layer.

Responsibilities:

- run deterministic anomaly checks
- call OpenAI evaluator when enabled
- write operator reports
- write publish decisions
- block dashboard publish on hard stops

Guardrails:

- AI must not change probabilities.
- AI must not rewrite picks.
- AI cannot override deterministic hard stops.
- OpenAI calls are opt-in through environment configuration.
- The operator input packet is read-only context; it does not authorize
  probability or slip mutation.

## Publishing Later

Publishing should remain disabled until:

- market taxonomy is stable
- replay can score historical MLB days
- evaluation metrics are trusted
- dashboard payload schema is reviewed
- Discord channel routing is defined

## Protected Boundaries

- Do not import production NBA model artifacts as MLB baselines.
- Do not use NBA Brier/calibration thresholds as MLB acceptance criteria.
- Do not let MLB Dev publish to production dashboard automatically.
- Do not modify `C:\Users\13142\Atlas\Atlas` while building MLB Dev.
