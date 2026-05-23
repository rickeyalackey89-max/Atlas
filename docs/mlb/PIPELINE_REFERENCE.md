# Atlas MLB Pipeline Reference

Status: development skeleton
Last updated: 2026-05-12

## Concept

Atlas MLB follows the same operating concept as Atlas NBA:

```text
raw board
  -> normalized board
  -> engine-readable board inputs
  -> scored legs
  -> source context
  -> advanced player profile context
  -> share matrix
  -> feature tables
  -> parameter models
  -> Sobol / QMC simulation
  -> market probability extraction
  -> calibration
  -> slip families
  -> run outputs
  -> replay/eval
```

The OpenAI operator layer is a post-score review gate. It is not part of source
normalization and must not change probabilities or picks.

## Current Implemented Flow

### Stage 1 - Fetch PrizePicks Raw Snapshots

Command:

```powershell
uv run atlas-mlb fetch prizepicks
```

Writes:

- `data/mlb/raw/prizepicks_all_sports/<date>/<timestamp>/payload.json`
- `data/mlb/raw/prizepicks_all_sports/<date>/<timestamp>/manifest.json`
- `data/mlb/raw/prizepicks/<date>/<timestamp>/payload.json`
- `data/mlb/raw/prizepicks/<date>/<timestamp>/manifest.json`

Rules:

- all-sports raw is preserved for audit/recovery
- MLB raw is the canonical replay board source
- manifests preserve checksums and request metadata

### Stage 2 - Normalize PrizePicks Board

Command:

```powershell
uv run atlas-mlb normalize board
```

Writes:

- `data/mlb/staged/board/<run_id>/normalized_board.jsonl`
- `data/mlb/staged/board/<run_id>/rejected_board.jsonl`
- `data/mlb/staged/board/<run_id>/normalize_manifest.json`

Rules:

- normalize broadly
- reject unsupported or malformed rows explicitly
- do not filter based on future model opinions here

### Stage 3 - Publish Engine Board Inputs

Command:

```powershell
uv run atlas-mlb prepare engine-board
```

Writes:

- `data/mlb/staged/engine_board/<run_id>/engine_board.csv`
- `data/mlb/staged/engine_board/<run_id>/engine_board.json`
- `data/mlb/staged/engine_board/<run_id>/engine_board_manifest.json`
- `data/mlb/staged/engine_board/latest.csv`
- `data/mlb/staged/engine_board/latest.json`
- `data/mlb/staged/engine_board/latest_manifest.json`

Purpose:

- stable engine-read CSV surface
- structured JSON companion
- manifest that links back to normalized board and raw snapshot

### Stage 4 - Score Engine Board

Command:

```powershell
uv run atlas-mlb score board
uv run atlas-mlb score board --parameter-table data/mlb/features/parameters/<run_id>/parameter_table.json
```

Writes:

- `data/mlb/replay_runs/<run_id>/scored_legs.csv` for replay runs
- `data/mlb/live_runs/<run_id>/scored_legs.csv` for live runs
- `data/mlb/<replay_runs|live_runs>/<run_id>/scored_legs_deduped.csv`
- `data/mlb/<replay_runs|live_runs>/<run_id>/scored_legs.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/score_manifest.json`
- `data/mlb/<replay_runs|live_runs>/<run_id>/simulation_manifest.json`
- `data/mlb/<replay_runs|live_runs>/latest_scored_legs.csv`
- `data/mlb/<replay_runs|live_runs>/latest_scored_legs_deduped.csv`
- `data/mlb/<replay_runs|live_runs>/latest_scored_legs.json`
- `data/mlb/<replay_runs|live_runs>/latest_score_manifest.json`
- `data/mlb/<replay_runs|live_runs>/latest_simulation_manifest.json`

Purpose:

- stable scored-leg contract
- first probability output surface
- model manifest with probability ranges, side counts, market counts, and paths

Current scorer:

- context-free market-prior baseline
- not CAT/GBM yet
- Sobol/QMC shell integrated
- baseline opportunity estimates attached to parameter and scored-leg artifacts
- when a parameter table is supplied, scored probabilities are driven by that replayable artifact
- `score_manifest.json` records parameter row matches and misses to catch silent scoring drift
- not calibrated for production decisions
- intended to lock contract shape before feature/model buildout

### Stage 4.5 - Execute Internal Board Pipeline

Command:

```powershell
uv run atlas-mlb run board --snapshot <payload-or-manifest> --run-id <run_id>
```

If `--snapshot` is omitted, the command uses the latest saved PrizePicks MLB
raw snapshot.

Live-mode behavior:

- `--run-mode live` always enables the live source refresh preflight.
- The preflight fetches Rotowire, Baseball Savant, ESPN injuries, StatsAPI teams,
  StatsAPI same-day schedule, StatsAPI MLB roster bulk, and a 14-day StatsAPI
  transaction window before feature construction.
- BettingPros is refreshed as the primary market source unless
  `--no-bettingpros-odds-refresh` is explicitly supplied.
- Replays do not fetch live identity sources; they consume captured, date-safe
  staged artifacts.

Writes:

- `data/mlb/staged/board/<run_id>/normalized_board.jsonl`
- `data/mlb/staged/engine_board/<run_id>/engine_board.csv`
- `data/mlb/features/player_props/<run_id>/feature_table.csv`
- `data/mlb/features/parameters/<run_id>/parameter_table.csv`
- `data/mlb/features/advanced_context/<run_id>/advanced_context.csv`
- `data/mlb/replay_runs/<run_id>/...` for replay mode
- `data/mlb/live_runs/<run_id>/...` for live mode
- `scored_legs.csv` and `scored_legs_deduped.csv`
- `System/recommended_2leg.csv` through `System/recommended_5leg.csv`
- `Windfall/recommended_2leg.csv` through `Windfall/recommended_5leg.csv`
- `demonhunter.csv`
- `marketed_slips.csv` and `marketed_slips.json`
- `slips/slips_manifest.json` with the enforced Atlas tier-mix contract
- `slips/payout_quote_manifest.json` for PrizePicks payout quote replay fidelity
- `source_selection_manifest.json` with the live/replay source contract,
  selected market dirs, context source paths, as-of timing classification, and
  missing live-enabled source warnings
- `operator/anomalies.jsonl`
- `operator/operator_input.json`
- `operator/publish_decision.json`
- `operator/operator_report.md`
- eval writes `data/mlb/eval/<run_id>/eval_legs.*`, `eval_slips.*`, and `slip_eval.json`
- `run_manifest.json`

Purpose:

- execute the current development pipeline without publishing externally
- prove the QMC scoring contract end-to-end
- lock the feature-table boundary before real lineup/weather/injury joins
- preserve advanced player-profile context as a neutral/non-fatal source layer
- lock scoring to the generated parameter-table artifact before Sobol/QMC simulation
- keep CLI orchestration delegated to runtime modules
- produce an operator packet that future OpenAI review can consume without mutating probabilities
- quote live PrizePicks payouts for live runs and write flagged fallback quotes for replay/test runs
- produce replayable artifacts for future settlement/eval

### Stage 5 - Context Sources

Planned MLB context sources:

- ESPN injuries
- StatsAPI teams
- StatsAPI rosters
- StatsAPI schedules/game IDs
- StatsAPI box scores
- StatsAPI player game logs
- minor-league roster/stat source when finalized
- source-neutral advanced player profiles from Baseball Savant, Rotowire, or
  another provider

Implemented context stages:

- `prepare advanced-profiles` stages hitter/pitcher profile rows into a stable
  profile contract.
- `prepare advanced-context` joins staged profiles to the engine board and emits
  per-prop context scores.
- `run board` builds advanced context automatically. If no profile source exists,
  it writes neutral rows and records missing coverage in manifests.
- `run board --run-mode live` refreshes same-day source context before building
  `market_context`, `injury_context`, `statsapi_context`, `roster_context`,
  `player_history_context`, `transaction_context`, `matchup_context`, and
  `advanced_context`.
- `market_context` selects normalized odds source directories by actual
  `game_date` rows, not folder timestamp text, so historical BettingPros
  backfills cannot pollute a live slate manifest.
- Live MLB should run multiple same-day pulls in Central time: `11:00`,
  `13:30`, `16:30`, and `19:30`. Each pull fetches a fresh board, excludes
  already-started games from the engine board, and refreshes market context for
  the remaining slate.
- The scheduled runner is the umbrella-root `run-live-sports.cmd`; sport-local
  runners remain available for manual/operator runs.
- DraftKings supplemental context is evaluated per game. A late game can remain
  timing-pending while an early game is already DK-ready; the source-selection
  manifest records `ready_game_count`, `pending_game_count`, and per-game target
  times.

### Stage 6 - Simulation And Model Layer

Planned:

- share matrix
- game environment features
- player prop features
- parameter models for opportunity, leash, and event rates
- Sobol / QMC simulation engine
- market probability extraction
- CAT/GBM candidates for parameters and calibration
- slip family construction
- deterministic anomaly checks
- OpenAI operator review
- run manifest and output package

## Live vs Replay

Live:

- fetches fresh PrizePicks snapshots
- writes latest engine board inputs
- writes run outputs to `data/mlb/live_runs/<run_id>/`
- publishes current MLB dashboard payloads through `atlas-dashboard`
- does not write replay/corpus outputs

Replay:

- loads pinned raw snapshots
- normalizes from the pinned board
- writes isolated engine board inputs
- writes run outputs to `data/mlb/replay_runs/<run_id>/`
- must not publish externally

Corpus replay:

- uses only strict-fidelity replay members
- writes aggregate artifacts to `data/mlb/corpus_replays/<corpus_id>/`
- may feed CAT/LODO and builder training only after source contracts pass

Eval:

- evaluates completed live or replay outputs after games settle
- writes to `data/mlb/eval/<run_id>/`
- is separate from live publishing and separate from corpus replay storage

## Guardrails

- PrizePicks is the product source of truth.
- Raw snapshots come before any transformation.
- Engine inputs are internal artifacts, not dashboard publishes.
- Replays must use saved raw snapshots.
- OpenAI review is post-score only.
