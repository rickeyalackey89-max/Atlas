# Atlas MLB Implementation Phases

Status: active architecture plan
Last updated: 2026-05-12

## Reference Pattern

NBA Atlas has a useful operational pattern:

```text
CLI
  -> live/replay authority boundary
  -> raw board snapshot
  -> normalized board
  -> game logs
  -> external priors
  -> injury/availability snapshot
  -> frozen run manifest
  -> share matrix
  -> parameter models
  -> Sobol / QMC simulation engine
  -> market probability extraction
  -> calibration layer
  -> slip families
  -> run artifact publish
  -> replay bundle
  -> next-day eval
  -> dashboard/Discord
```

MLB should reuse this order and discipline, not the NBA implementation.

## Phase 0: Repo Safety And Skeleton

Status: in progress

Goals:

- Remove copied NBA runtime/data/model surfaces.
- Keep MLB-dev command surface separate from NBA.
- Keep publishing disabled.
- Keep only MLB docs, config, source skeleton, tests, and empty data contracts.

Done:

- `AtlasMLB.ps1` is the local command surface.
- `data/mlb/` is the only active data root.
- `src/mlb/` is the active implementation package path. The Python import namespace remains `mlb`.
- Runtime boundaries exist for preflight, publishing, bundles, live delegation,
  replay delegation, and inspection.
- NBA live CLI and model artifacts are removed from MLB-dev.

Architecture rule:

- `cli.py` parses commands only.
- `runtime/preflight.py` owns safety/status checks.
- `runtime/publishing.py` owns dashboard and Discord guardrails.
- `runtime/bundles.py` owns replay/run artifact contracts.
- `runtime/live_delegation.py` owns live-run planning and guardrails.
- `runtime/replay_delegation.py` owns single replay and bundle replay planning.
- `runtime/inspection.py` owns read-only status/info reports.
- `evaluation/` owns deterministic anomalies, OpenAI operator review, reports,
  and publish decisions.

Run surfaces:

- `atlas-mlb live`: same-day live-run plan.
- `atlas-mlb replay single`: targeted one-run replay plan.
- `atlas-mlb replay bundle`: multi-run corpus/cache/trainer replay plan.
- `atlas-mlb operator`: operator AI evaluation plan.

## Phase 1: Source Snapshots

Goal: fetch and persist replayable raw source snapshots.

Status: implemented skeleton

Build:

- PrizePicks MLB board raw snapshot fetcher.
- ESPN MLB injuries raw snapshot fetcher.
- MLB StatsAPI team, roster, schedule, boxscore, and player game-log snapshot
  fetchers.
- MLB StatsAPI is the canonical game-log/box-score and minor-league source.

Artifacts:

- `data/mlb/raw/prizepicks/<date>/<timestamp>/payload.json`
- `data/mlb/raw/espn_injuries/<date>/<timestamp>/payload.*`
- `data/mlb/raw/espn_gamelogs/<date>/<timestamp>/payload.*`
- `manifest.json` beside each raw payload.

Exit criteria:

- Raw snapshots include checksum, source, timestamp, and request metadata.
- `atlas-mlb sources` can list configured sources.
- `atlas-mlb fetch prizepicks` can fetch and normalize the MLB board.
- `atlas-mlb fetch injuries` can fetch and normalize ESPN injuries.
- `atlas-mlb fetch statsapi-teams` can fetch and normalize MLB/MiLB teams.
- No scoring or publishing exists yet.

## Phase 2: Normalized Board

Goal: convert PrizePicks MLB board into canonical candidate rows.

Status: implemented skeleton

Build:

- Player/team/market normalizer.
- PrizePicks relation parser.
- Combo projection handling.
- Board snapshot writer.
- StatsAPI team, roster, schedule, boxscore, and player game-log normalizers.

Artifacts:

- `data/mlb/staged/board/<run_id>/normalized_board.parquet`
- `data/mlb/staged/board/<run_id>/normalized_board.jsonl`
- `data/mlb/<replay_runs|live_runs>/<run_id>/source_manifest.json`

Exit criteria:

- Every supported PrizePicks board market maps to a canonical market.
- Unsupported markets are explicit rejects, not silent drops.
- Player names and teams are stable enough for injury/game-log joins.

## Phase 3: Availability And Share Matrix

Goal: build baseball-specific role and availability context.

Build:

- ESPN injury normalizer.
- Starting lineup/probable starter slots.
- Batting-order probability fields.
- Pitcher role fields.
- Bullpen fatigue shell.
- Minor-league fallback prior contract.

Artifacts:

- `data/mlb/staged/injuries/<run_id>/injuries.jsonl`
- `data/mlb/features/share_matrix/<run_id>/share_matrix.parquet`

Exit criteria:

- Batter DNP/reboot risk can be flagged.
- Pitcher role uncertainty can be flagged.
- Plate appearance projection exists, even if v0 is simple.

## Phase 4: Settlement And Replay

Goal: score historical MLB outcomes before model training.

Replay types:

- Single replay: one run or raw snapshot set, used for focused debugging and
  run-level validation.
- Bundle replay: many single replays grouped by manifest, used for corpus
  refreshes, caches, LOSO experiments, and trainer input.

Build:

- Outcome resolver for all supported markets.
- PrizePicks DNP/reboot/first-inning exceptions.
- Replay run format.
- Eval table writer.

Artifacts:

- `data/mlb/replay_runs/<run_id>/scored_candidates.parquet`
- `data/mlb/eval/<run_id>/eval_legs.parquet`
- `data/mlb/replay_runs/<run_id>/run_manifest.json`

Exit criteria:

- At least one full historical slate settles end-to-end.
- Fantasy score helpers match the PrizePicks scoring chart.
- DNP and reboot states are separate from losses.

## Phase 5: Simulation-Ready Baselines

Goal: establish MLB-native parameter baselines before CAT/GBM complexity.

Status: development shell implemented

Build:

- Market-level baseline rates.
- Simple hitter PA priors.
- Simple pitcher leash and outs/pitch-count priors.
- Simple recent-form priors.
- Handedness/platoon priors.
- Park/weather placeholder features.
- First simulation-ready parameter table.

Artifacts:

- `data/mlb/model/baseline_v0/`
- `data/mlb/features/player_props/<run_id>/feature_table.csv`
- `data/mlb/features/player_props/<run_id>/feature_manifest.json`
- `data/mlb/features/parameters/<run_id>/parameter_table.csv`
- `data/mlb/features/parameters/<run_id>/parameter_table.json`
- `data/mlb/features/parameters/<run_id>/parameter_manifest.json`

Exit criteria:

- Every scored candidate has parameter provenance.
- Baseline parameter quality can be audited by market and player type.

## Phase 6: Sobol / QMC Simulation Engine

Status: development shell implemented

Goal: estimate MLB market probabilities through deterministic game-path simulation.

Build:

- deterministic Sobol seed policy
- baseline parameter table
- hitter PA simulation
- pitcher leash / batters-faced simulation
- market-specific outcome distributions
- distribution percentiles
- volatility, fragility, and stability scores
- simulation manifests
- operator input packets

Artifacts:

- `data/mlb/<replay_runs|live_runs>/<run_id>/simulation_manifest.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/scored_legs.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/scored_legs_deduped.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/scored_legs.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/operator_input.json`

Exit criteria:

- No NBA artifacts are referenced.
- Live and replay outputs match under the same raw inputs and seed.
- Simulation metadata is sufficient to reproduce every probability.
- Baseline Brier/log-loss can be computed by market.

Current implemented command:

```powershell
uv run atlas-mlb run board --snapshot <payload-or-manifest> --run-id <run_id>
```

## Phase 6.5: Parameter Models And Calibration

Goal: improve simulator inputs and calibrate simulator outputs.

Build:

- feature table builder
- train/eval split strategy
- market-specific feature groups
- CAT/GBM or other parameter model candidates
- probability calibration diagnostics

Artifacts:

- `data/mlb/model/parameter_models_v0/`
- `data/mlb/model/calibration_v0/`
- `feature_contract.json`
- `model_manifest.json`

Exit criteria:

- Parameter models beat simple baselines on held-out slates.
- Calibration improves market-level probability quality without breaking replay.
- Feature contracts are reproducible.

## Phase 7: Slip Families

Goal: create website-compatible MLB slips.

Build:

- Atlas System slip CSVs.
- Atlas Windfall slip CSVs.
- DemonHunter slip CSV.
- Marketed slip JSON and CSV.
- Slip-level eval.

Artifacts:

- `data/mlb/<replay_runs|live_runs>/<run_id>/System/recommended_2leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/System/recommended_3leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/System/recommended_4leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/System/recommended_5leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/Windfall/recommended_2leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/Windfall/recommended_3leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/Windfall/recommended_4leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/Windfall/recommended_5leg.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/demonhunter.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/marketed_slips.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/marketed_slips.json`

Exit criteria:

- Slip output shape can be adapted to dashboard payload.
- Correlation and same-game rules are explicit.
- Pitcher versus opposing hitter restriction is enforced.

## Phase 7.5: Operator AI Evaluation

Goal: review scored output before dashboard publishing.

Build:

- Deterministic anomaly checks.
- OpenAI evaluator with schema-valid response.
- Operator report writer.
- Publish decision writer.
- Hard-stop publish gate.

Artifacts:

- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/operator_input.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/anomalies.jsonl`
- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/ai_evaluation.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/operator_report.md`
- `data/mlb/<replay_runs|live_runs>/<run_id>/operator/publish_decision.json`

Exit criteria:

- Publish cannot happen after deterministic hard-stop findings.
- AI evaluation is optional and credential-gated.
- Replay paths do not publish by default.
- Operator report is readable before any dashboard write.

## Phase 8: Dashboard And Discord

Goal: publish MLB outputs only after replay/eval confidence exists.

Build:

- Dashboard payload adapter.
- Discord free/premium routing.
- Daily run status.
- Performance windows.

Exit criteria:

- Publishing remains opt-in.
- Dry-run payload validates before any production dashboard write.
- Discord posts are disabled by default.
