# PIPELINE TALK-TO (Current, Hand-Curated — 2026-03-07)

This replaces the older regex-style talk-to map with the current operational spine only.

---

## Current canonical owners

### `src/Atlas/cli.py`
**Owns:**
- mode selection
- live preflight
- handoff to orchestrator
- post-run bundle/publish hooks

**Talks to:**
- `tools/refresh_iael_today.py`
- `src/Atlas/runtime/orchestrator.py`
- bundle/publish helpers

**Should not own:**
- core stage sequencing
- board rebuilding logic
- share-matrix logic
- slip building logic

---

### `tools/refresh_iael_today.py`
**Owns:**
- injury pull / parse invocation
- normalized injury publish to `latest.json`
- mismatch audit writing
- freshness enforcement
- active-slate mismatch gating

**Talks to:**
- injury parser pipeline
- `data/output/injury/normalized/*.json`
- `data/board/fetch_board.csv` (for active-slate scoping)
- `data/input/roster_map.csv`

**Current rule:**
- audit everything
- only kill live on mismatches that matter to the actionable slate

---

### `src/Atlas/runtime/orchestrator.py`
**Owns:**
- run context
- stage order
- subprocess boundary management
- audit event emission
- calibration injection
- latest surface filtering
- bundle writing

**Talks to:**
- `tools/fetch_prizepicks_today.py`
- `tools/refresh_nba_gamelogs.py`
- `tools/rebuild_today_from_any_raw.py`
- `tools/fetch_rotowire_lines.py`
- `tools/build_share_matrix.py`
- `python -m Atlas.engine.main`
- `tools/filter_recommendations_live.py`

**Should remain the only stage sequencer.**

---

### `tools/fetch_prizepicks_today.py`
**Owns:**
- board fetch
- raw board persistence
- `fetch_board.csv`
- roster refresh downstream of fetch

**Talks to:**
- PrizePicks raw board
- `data/board/fetch_board.csv`
- `data/raw/prizepicks_*.json`
- `data/input/roster_map.csv`

**Important current note:**
- This remains the roster self-heal authority in the existing live path.
- The earlier attempt to add a separate roster preflight tool was intentionally rolled back.

---

### `tools/rebuild_today_from_any_raw.py` + `src/Atlas/stages/rebuild/rebuild_today.py`
**Owns:**
- canonical board rebuild
- `today.csv`
- append-only snapshot creation
- live vs replay time gating

**Current semantics:**
- live: strict CT `today + not started`
- replay: no current-time filter; use raw payload's start times
- `game_date` is authoritative
- snapshot filename stamp is not trustworthy historical identity

---

### `tools/fetch_rotowire_lines.py`
**Owns:**
- market context fetch
- freshness / date match contract for Rotowire file

---

### `tools/build_share_matrix.py`
**Owns:**
- role/share matrix artifact
- `data/model/share_matrix.csv`

**Current note:**
- This remains on the canonical live spine.
- Cleanup should remove wrappers and bypasses around it, not around orchestrator stage ownership.

---

### `src/Atlas/engine/main.py`
**Owns:**
- board scoring
- IAEL hard invalidations inside engine scoring path
- slip generation
- run-folder outputs

**Talks to:**
- `today.csv`
- `rotowire_lines.json`
- `share_matrix.csv`
- `data/output/runs/<run_id>/...`

---

### `scripts/dev/analysis/backtest/backtest_role_layer_ctx.py`
**Owns:**
- historical telemetry comparison path
- explicit-snapshot backtest
- BASE vs ROLE scoring
- historical IAEL loading per snapshot

**Current semantics:**
- no longer runs everything with `iael_df=None`
- prefers board `game_date` over snapshot filename for historical IAEL lookup
- current baseline batch is useful but still needs duplicate-scenario cleanup

---

## Current cleanup boundary

Cleanup is explicitly **not** first anymore.

The current priority is:
1. telemetry baseline
2. knob tuning
3. cleanup / waste removal

That means any removal work should preserve these canonical owners and remove only duplicate entrypoints, wrappers, and stale side paths that do not serve this spine.
