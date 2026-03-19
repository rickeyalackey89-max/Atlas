# Atlas Pipeline Call Chain (Current Status — 2026-03-07)

This is the current call chain after the live IAEL scoping fix, replay rebuild time fix, and historical-IAEL backtest wiring.

---

## Canonical live chain

```text
PowerShell
└─ .\run.ps1
   └─ python -m Atlas.cli live

src/Atlas/cli.py
└─ main()
   ├─ _hard_live_iael_preflight(repo_root)
   │  └─ tools/refresh_iael_today.py
   │     ├─ injury pull / parse
   │     ├─ publish normalized/latest.json
   │     ├─ mismatch audit CSV write
   │     ├─ scope live-fatal team mismatch check to active fetch_board teams (when available)
   │     └─ freshness enforcement
   │
   ├─ Atlas.runtime.orchestrator.run_today(...)
   │
   └─ post-run publish / bundle hooks

src/Atlas/runtime/orchestrator.py
└─ run_today(...)
   ├─ Stage 0: create RunContext + emit audit events
   │   └─ .atlas_audit/events_<run_id>.jsonl
   │
   ├─ Stage 1: fetch_raw_only(...)
   │   └─ tools/fetch_prizepicks_today.py --raw-only
   │       ├─ data/board/fetch_board.csv
   │       ├─ data/raw/prizepicks_*.json
   │       └─ roster_map downstream refresh
   │
   ├─ Stage 1b: run_refresh_nba_gamelogs(...)
   │   └─ tools/refresh_nba_gamelogs.py
   │
   ├─ Stage 2: rebuild_today(...)
   │   └─ tools/rebuild_today_from_any_raw.py
   │       ├─ data/board/today.csv
   │       └─ data/board/snapshots/today_<timestamp>.csv
   │
   ├─ Stage 2a: infer authoritative slate date from today.csv
   │   └─ set ATLAS_GAME_DATE=<game_date>
   │
   ├─ Stage 2b: fetch_rotowire_lines(game_date,...)
   │   └─ tools/fetch_rotowire_lines.py
   │       └─ data/input/rotowire_lines.json
   │
   ├─ Stage 3: build_share_matrix(...)
   │   └─ tools/build_share_matrix.py
   │       └─ data/model/share_matrix.csv
   │
   ├─ Stage 4: model_all(ctx)
   │   └─ python -m Atlas.engine.main
   │       └─ data/output/runs/<run_id>/...
   │
   ├─ Stage 5: calibration injection
   │   └─ scored_legs*.csv get p_cal
   │
   ├─ Stage 6: filter_latest_for_tags(...)
   │   └─ tools/filter_recommendations_live.py
   │       └─ data/output/latest/{all,early,main,late}/...
   │
   └─ Stage 7: bundle / telemetry
       └─ data/bundles/atlas_bundle_<run_id>.zip
```

---

## Canonical replay / telemetry chain (current baseline path)

```text
Historical raw JSONs
└─ tools/rebuild_today_from_any_raw.py (one raw at a time via ATLAS_REPLAY_RAW)
   ├─ rebuild_today.py in replay mode
   │  ├─ no fake minimum datetime
   │  ├─ no replay current-time filter
   │  └─ game_date stays authoritative from start_time
   └─ writes fresh today_<timestamp>.csv snapshots

scripts/dev/analysis/backtest/backtest_role_layer_ctx.py
└─ explicit --snapshot batch
   ├─ load board snapshot CSV
   ├─ load realized outcomes from Last10.csv
   ├─ derive slate date from board game_date first
   ├─ load historical normalized IAEL json for that slate
   ├─ score BASE (role disabled)
   ├─ score ROLE (role enabled, real iael_df passed through)
   └─ write backtest_role_layer_ctx_new_None_None.csv + meta.json
```

---

## Important current semantics

### Live IAEL gate
- Still enforced.
- Still writes mismatch audit.
- Still kills runs for active-slate mismatches.
- No longer kills runs for irrelevant off-slate mismatches.

### Snapshot naming
- Current replay snapshots are still named by artifact write timestamp.
- `game_date` inside the board is the authoritative historical slate date.
- Backtest logic should prefer `game_date`, not `today_<timestamp>.csv`, for historical lookup decisions.

### Baseline status
- Historical IAEL is now engaging in backtest.
- Reason mix now includes `ok`, `ok_combo`, `no_outs`, `combo_no_effect`, `no_beneficiary_match`.
- Current batch still needs duplicate-scenario cleanup before final knob decisions.

---

## Priority order from here

1. Finish telemetry baseline on the deduped historical cohort.
2. Turn knobs from the real baseline.
3. Cleanup / dead-code removal last.
