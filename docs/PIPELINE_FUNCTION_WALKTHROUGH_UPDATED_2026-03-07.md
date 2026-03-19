# Atlas Pipeline Function Walkthrough (Current Status — 2026-03-07)

This is the current execution walkthrough for Atlas after the latest live-stability and replay/backtest fixes.

It is organized by the current canonical spine:

`run.ps1 -> Atlas.cli live -> IAEL preflight -> orchestrator.run_today -> fetch -> rebuild -> rotowire -> share matrix -> Atlas.engine.main -> latest/placeable publish -> bundle/export`

---

## Current operating status

### What is now fixed
- **Live IAEL gate is working again.** The preflight still refreshes injuries, republishes `normalized/latest.json`, writes mismatch audit CSVs, and enforces freshness, but the team-mismatch kill switch is now scoped to the **active actionable slate** when `data/board/fetch_board.csv` exists.
- **Replay rebuild time handling is fixed properly.** Live mode still applies strict CT `today + not started` filtering. Replay mode no longer relies on a fake minimum datetime and no longer applies a current-time filter.
- **Backtest telemetry now injects historical IAEL.** `backtest_role_layer_ctx.py` now loads historical normalized injury files per snapshot using the board's `game_date` first, then passes `iael_df` into the simulator.

### What is not yet final
- **Baseline selection is in progress.** Backtests now engage real RoleCtx reason paths (`ok`, `ok_combo`, `no_outs`, etc.), but the current 10-snapshot cohort still needs duplicate-scenario cleanup before it should be treated as the final baseline.
- **Cleanup / dead-code removal is still last.** The model is runnable again; cleanup is deferred until baseline + knob tuning are locked.

---

## 0) Human entry

### `run.ps1`
**Role:** Operational wrapper.

- Starts the CLI in the intended environment.
- Keeps human invocation consistent.
- Exists to reduce ad-hoc drift, not to own business logic.

---

## 1) Authority surface (CLI)

### `src/Atlas/cli.py :: main(argv=None)`
**Role:** Defines what a real `live` run is.

- Parses mode.
- Runs live preflight.
- Calls `Atlas.runtime.orchestrator.run_today(...)`.
- Runs post-run publish/bundle hooks.

### `_hard_live_iael_preflight(repo_root)`
**Role:** Live-only safety gate.

Current behavior:
- Runs `tools/refresh_iael_today.py`.
- Requires refresh/freshness to succeed.
- Preserves mismatch audit logging.
- Only hard-stops on mismatches relevant to the **current actionable slate** when `fetch_board.csv` is available.

**Why it matters:**
- Preserves system integrity for the live board.
- Stops irrelevant off-slate mismatch noise from killing the model.

---

## 2) Injury refresh / preflight

### `tools/refresh_iael_today.py`
**Role:** Pull, normalize, publish, and validate IAEL state.

Current behavior:
- Runs the injury pull/parse pipeline.
- Publishes newest normalized file to `data/output/injury/normalized/latest.json`.
- Writes mismatch audit CSVs when team mismatches are detected.
- Uses `fetch_board.csv` teams, when present, to scope **live-fatal** mismatch enforcement to the active slate.
- Still enforces freshness.

**Operational consequence:**
- The kill switch still exists.
- It now fires on mismatches that can actually affect the current live run.

---

## 3) Orchestrator (canonical stage graph)

### `src/Atlas/runtime/orchestrator.py :: run_today(...)`
**Role:** Canonical stage sequencing.

This is still the real stage owner.

### Stage 0 — run context + audit
- Creates `run_id`.
- Appends `.atlas_audit/events_<run_id>.jsonl`.

### Stage 1 — fetch board
#### `fetch_raw_only(...)`
Usually invokes `tools/fetch_prizepicks_today.py --raw-only`.

Outputs:
- `data/board/fetch_board.csv`
- raw snapshot JSON under `data/raw/...`

Current notes:
- Fetch also refreshes `roster_map.csv` downstream.
- This remains the roster self-heal authority inside the model path.

### Stage 1b — gamelog refresh (best effort)
#### `run_refresh_nba_gamelogs(...)`
Invokes `tools/refresh_nba_gamelogs.py`.

Still non-blocking.

### Stage 2 — rebuild canonical board
#### `rebuild_today(...)`
Invokes `tools/rebuild_today_from_any_raw.py`.

Outputs:
- `data/board/today.csv`
- `data/board/snapshots/today_<timestamp>.csv`

Current notes:
- **Live mode:** strict CT `today + not started` gate remains intact.
- **Replay mode:** no current-time filter; rebuilds the board represented by the historical raw.
- `game_date` is derived from the game start time and should be treated as authoritative.
- Snapshot filenames are currently still artifact write stamps, not trustworthy historical slate IDs.

### Stage 2a — authoritative slate date
- Orchestrator infers one `game_date` from `today.csv`.
- Sets `ATLAS_GAME_DATE`.

### Stage 2b — Rotowire context
#### `fetch_rotowire_lines(game_date, ...)`
Invokes `tools/fetch_rotowire_lines.py`.

Outputs:
- `data/input/rotowire_lines.json`
- `data/input/rotowire_lines_last_good.json`

### Stage 3 — share matrix / role context
#### `build_share_matrix(...)`
Invokes `tools/build_share_matrix.py`.

See [SHARE_MATRIX_REFERENCE.md](SHARE_MATRIX_REFERENCE.md) for the matrix build, load, and matching rules.

Outputs:
- `data/model/share_matrix.csv`

Current note:
- This remains part of the canonical live path.
- Cleanup work should preserve this stage and remove bypasses around it, not around the orchestrator.

### Stage 4 — engine boundary
#### `model_all(ctx)`
Invokes `python -m Atlas.engine.main`.

Outputs under `data/output/runs/<run_id>/`:
- `scored_legs.csv`
- `scored_legs_deduped.csv`
- `System/recommended_{3,4,5}leg.csv`
- `Windfall/recommended_{3,4,5}leg.csv`
- corresponding `_winprob` outputs

### Stage 5 — calibration injection
- Appends `p_cal` into scored-leg artifacts.

### Stage 6 — latest / placeability filtering
#### `filter_latest_for_tags(...)`
Invokes `tools/filter_recommendations_live.py` per tag.

Outputs:
- `data/output/latest/all/...`
- `data/output/latest/early/...`
- `data/output/latest/main/...`
- `data/output/latest/late/...`

### Stage 7 — bundle / telemetry
- Writes bundle zip.
- Keeps run forensics and replay evidence.

---

## 4) Engine internals

### `src/Atlas/engine/main.py :: main()`
**Role:** Converts canonical board + context into scored legs and slips.

Conceptual steps:
1. Load config + inputs.
2. Sanitize / normalize board rows.
3. Apply IAEL hard invalidations.
4. Score legs (`p_adj`, EV inputs, context fields).
5. Build slips.
6. Rank / dedupe / export.

Current baseline note:
- The live engine remains the thing the backtest must approximate.
- Baseline work is only valid if replay/backtest reflects the same contextual stack used here.

---

## 5) Historical replay / backtest status

### `scripts/dev/analysis/backtest/backtest_role_layer_ctx.py`
**Role:** Current telemetry baseline driver.

Current behavior:
- Loads explicit board snapshots.
- Loads realized outcomes from `Last10.csv` (or configured logs path).
- Loads historical IAEL from `data/output/injury/normalized` using snapshot-board `game_date` first.
- Passes `iael_df` into `simulate_leg_probability_new(...)`.
- Produces BASE vs ROLE summaries and a detailed CSV.

What changed materially:
- It no longer runs with `iael_df=None` for every row.
- RoleCtx now engages on historical replays with real reason paths.

Current evidence from the latest batch:
- `no_outs` rows dominate but move only slightly.
- `ok_combo` and `ok` rows show materially larger mean absolute delta.
- ROLE improves Brier on most snapshots, but the current batch includes a duplicate scenario and should not yet be treated as the final baseline.

---

## 6) Dashboard / export

### `scripts/dev/export/export_cloudflare_payload.py`
Builds the canonical dashboard JSON from `data/output/latest/<tag>/...`.

### `AtlasDashboard/publish-atlas.ps1`
Copies payload into the dashboard repo and deploys.

---

## Final trust hierarchy

1. **Live placeable surface:** `data/output/latest/<tag>/...`
2. **Run forensics:** `data/output/runs/<run_id>/...` + `.atlas_audit/...`
3. **Replay / telemetry artifacts:** explicit-snapshot backtest outputs
4. **Cleanup / removal work:** deferred until baseline + knob tuning are locked
