# Atlas Pipeline Reference

> **Last updated:** 2026-05-10 — full file-to-file trace of the live pipeline.
> **Current runtime:** CatBoost playoff v5cD active; v18 LightGBM and telemetry isotonic disabled.

---

## Working Directory — CRITICAL

**All Atlas commands and tools must run from `C:\Users\13142\Atlas` (workspace root).**

```powershell
# CORRECT
cd C:\Users\13142\Atlas
$env:PYTHONIOENCODING='utf-8'
py -m Atlas.cli live                          # live run
py Atlas\tools\marketed_slip_trainer_v2.py    # trainer

# WRONG — inner folder breaks relative path resolution for calibration JSONs
cd C:\Users\13142\Atlas\Atlas
py tools\marketed_slip_trainer_v2.py          # DO NOT DO THIS
```

Relative paths like `data/model/marketed_calibration.json` resolve against CWD. Running from the inner `Atlas\Atlas` directory causes calibration files to silently fall back to hardcoded values, producing wrong results.

---

## Entry Points

| Command | Purpose |
|---|---|
| `python -m Atlas.cli live` | Production live run (fetches fresh data, scores, publishes) |
| `python -m Atlas.cli replay --raw <path>` | Deterministic replay from pinned raw JSON |
| `python tools/replay_bundle.py <bundle.zip> --scenario-id <name>` | Bundle replay |
| `python -m Atlas.cli tools list` | List available tools |

CLI defined in `src/Atlas/cli.py`. Delegates to `src/Atlas/runtime/orchestrator.py` → `run_today()`.

---

## Pipeline Stages (execution order)

### Stage 0 — Contract Check
**Module:** `src/Atlas/contracts/model_contract.py`
| Reads | Writes |
|---|---|
| `config.yaml` | *(none — validation only)* |

---

### Stage 1 — Fetch Raw Board
**Tool:** `tools/fetch_apis.py --raw-only`
| Reads | Writes |
|---|---|
| PrizePicks API (live) OR `--raw` JSON (replay) | `data/board/fetch_board.csv` |
| | `data/raw/prizepicks_YYYYMMDD_HHMMSS.json` |

> **Replay:** raw JSON passed via `--raw` is used directly. Nothing fetched from API.
> **No-slate guard:** if `fetch_board.csv` has zero data rows, pipeline exits cleanly.

---

### Stage 1b — Refresh Gamelogs *(live only)*
**Tool:** `tools/refresh_nba_gamelogs.py`
| Reads | Writes |
|---|---|
| NBA Stats API | `data/gamelogs/nba_gamelogs.csv` |
| | `data/telemetry/games_logged/YYYY-MM-DD_games_logged.csv` |

---

### Stage 2 — Rebuild today.csv
**Tool:** `tools/rebuild_today_from_any_raw.py`
| Reads | Writes |
|---|---|
| `data/raw/prizepicks_*.json` (latest or `--raw` pin) | `data/board/today.csv` |
| | `data/board/snapshots/today_YYYYMMDD_HHMMSS.csv` |

Sets `ATLAS_GAME_DATE` env var from board data.

---

### Stage 2a.5 — Fetch Role Metrics Snapshot
**Tool:** `tools/fetch_crafted_player_stats.py --game-date YYYY-MM-DD`
| Reads | Writes |
|---|---|
| CraftedNBA API | `data/output/dashboard/role_metrics_latest.json` |
| | `data/output/dashboard/role_metrics_latest.html` |
| | `data/output/dashboard/role_metrics_snapshot_manifest.json` |
| | `data/output/role_metrics/snapshots/YYYY-MM-DD/craftednba_player_stats_*.json` |
| | `data/output/role_metrics/snapshots/YYYY-MM-DD/craftednba_player_stats_*.html` |

---

### Stage 2b — Fetch Rotowire Lines
**Tool:** `tools/fetch_rotowire_lines.py`
| Reads | Writes |
|---|---|
| Rotowire API | `data/input/rotowire_lines.json` |
| | `data/input/rotowire_lines_last_good.json` |

> **Replay:** uses pinned `$env:ATLAS_ROTOWIRE_LINES_PATH` or bundle snapshot.

---

### Stage 2c — Fetch External Priors
**Tools:** `tools/fetch_bettingpros_props.py` + `tools/fetch_oddsapi_props.py`
| Reads | Writes |
|---|---|
| BettingPros API | `data/input/bettingpros_props_today.csv` |
| | `data/archives/bettingpros/bettingpros_props_YYYY-MM-DD.csv` |
| OddsAPI | `data/input/oddsapi_props_today.csv` |
| | `data/input/odds_market_today.json` |
| | `data/archives/oddsapi/oddsapi_props_YYYY-MM-DD.csv` |
| *(merged output)* | `data/input/external_priors_today.csv` |

---

### Stage 2d — IAEL Refresh + Snapshot Freeze *(live only)*

**IAEL refresh** — `tools/refresh_iael_today.py`:
| Reads | Writes |
|---|---|
| NBA injury PDF (`ak-static.cms.nba.com`) | `data/output/dashboard/injury_invalidations_latest.json` |
| | `data/output/dashboard/status_latest.json` |
| | `data/output/dashboard/invalidations_latest.json` |

**Normalized injury snapshot** (written by normalizer inside IAEL refresh):
| Reads | Writes |
|---|---|
| `data/output/dashboard/injury_invalidations_latest.json` | `data/output/injury/normalized/YYYY-MM-DD_HH_MMxm.json` |
| | `data/output/injury/normalized/latest.json` |

**Snapshot freeze** (written by engine's publish stage — `publish_run_outputs.py`):
| Reads | Writes |
|---|---|
| `data/output/dashboard/injury_invalidations_latest.json` | `data/output/runs_manifest/YYYYMMDD_HHMMSS/injury_invalidations_latest.json` |
| `data/output/dashboard/status_latest.json` | `data/output/runs_manifest/YYYYMMDD_HHMMSS/status_latest.json` |
| `data/output/dashboard/role_metrics_latest.json` | `data/output/runs_manifest/YYYYMMDD_HHMMSS/role_metrics_latest.json` |
| | `data/output/runs_manifest/YYYYMMDD_HHMMSS/injury_snapshot_manifest.json` |

> **Replay:** uses pinned `$env:ATLAS_IAEL_INVALIDATIONS_PATH`, `$env:ATLAS_IAEL_STATUS_PATH`, `$env:ATLAS_IAEL_NORMALIZED_PATH`.

> **IAEL archive** (source for future replay): `data/archives/iael/2026/YYYY-MM-DD/YYYYMMDD_HHMMSSZ/`
> Contains: `injury_invalidations.json`, `status.json`, `rotowire_lines.json`

---

### Stage 3 — Build Share Matrix
**Tool:** `tools/build_share_matrix.py` (uses `src/Atlas/model/share_matrix_builder_v2.py`)
| Reads | Writes |
|---|---|
| `data/gamelogs/nba_gamelogs.csv` | `data/model/share_matrix.csv` |
| `data/output/runs_manifest/YYYYMMDD_HHMMSS/role_metrics_latest.json` | |

---

### Stage 3 (cont) — Engine Scoring

**Entry:** `src/Atlas/engine/main.py`
**Kernel path:** `new_engine.py` → `new_probability.py` → May 10 kernel transforms → CatBoost v5cD → slip builders → publish stage

**Reads:**
| File | Purpose |
|---|---|
| `data/board/today.csv` | All legs to score |
| `data/gamelogs/nba_gamelogs.csv` | Player history (windowed stats, pace, opponent defense) |
| `data/model/share_matrix.csv` | Role context (injury redistribution weights) |
| `data/output/dashboard/injury_invalidations_latest.json` | OUT/DOUBTFUL filtering |
| `data/output/dashboard/role_metrics_latest.json` | Role metrics snapshot |
| `data/input/rotowire_lines.json` | Spreads + game totals (blowout, q_blowout) |
| `data/input/external_priors_today.csv` | BettingPros + OddsAPI merged priors |
| `data/input/odds_market_today.json` | Market consensus |
| `data/model/ensemble/*.txt` | Historical v18 GBM models; currently disabled |
| `data/model/telemetry_calibration.playoff_isotonic.json` | Isotonic calibration file; currently disabled |
| `data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm` | Active CatBoost playoff calibrator |
| `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json` | Active CatBoost feature/parameter contract |
| `data/model/marketed_calibration.json` | Marketed slip leg calibration |

**Probability chain per leg:**
```
p (raw Monte Carlo 10K sim)
  -> p_role       (share matrix role adjustment)
  -> p_adj_pre_under_relief
  -> p_adj        (blowout/fragility + under-relief)
  -> p_adj        (after May 10 kernel transforms)
  -> p_for_cal    (currently p_adj universally)
  -> p_catboost   (CatBoost v5cD residual calibrator)
  -> p_cal        (production calibrated probability)
  -> p_cal_marketed (marketed_calibration.json haircut)
```

**Writes — `data/output/runs/YYYYMMDD_HHMMSS/`:**
| File | Description |
|---|---|
| `run_manifest.json` | Config fingerprint, model version, calibration state |
| `scored_legs.csv` | All scored legs (all columns, pre-dedup) |
| `scored_legs_deduped.csv` | Best leg per player/stat/direction (optimizer input) |
| `System/recommended_3leg.csv` | System 3-leg slips (sorted by score_adj) |
| `System/recommended_4leg.csv` | System 4-leg slips |
| `System/recommended_5leg.csv` | System 5-leg slips |
| `System/recommended_3leg_winprob.csv` | System 3-leg sorted by win probability |
| `System/recommended_4leg_winprob.csv` | System 4-leg sorted by win probability |
| `System/recommended_5leg_winprob.csv` | System 5-leg sorted by win probability |
| `Windfall/recommended_3leg.csv` | Windfall 3-leg slips |
| `Windfall/recommended_4leg.csv` | Windfall 4-leg slips |
| `Windfall/recommended_5leg.csv` | Windfall 5-leg slips |
| `Windfall/recommended_3leg_winprob.csv` | Windfall 3-leg sorted by win probability |
| `Windfall/recommended_4leg_winprob.csv` | Windfall 4-leg sorted by win probability |
| `Windfall/recommended_5leg_winprob.csv` | Windfall 5-leg sorted by win probability |
| `demonhunter.csv` | Best 3/4/5-leg all-DEMON slips |
| `marketed_slips.json` | Marketed subscriber slips (structured JSON with legs + metadata) |
| `marketed_slips.csv` | CSV companion (one row per leg across all marketed slips) |
| `recommended_3leg.csv` | Legacy mirror of System 3-leg |
| `recommended_4leg.csv` | Legacy mirror of System 4-leg |
| `recommended_5leg.csv` | Legacy mirror of System 5-leg |
| `recommended_3leg_winprob.csv` | Legacy mirror of System 3-leg winprob |
| `recommended_4leg_winprob.csv` | Legacy mirror of System 4-leg winprob |
| `recommended_5leg_winprob.csv` | Legacy mirror of System 5-leg winprob |

**Writes — `data/output/` (shared surfaces):**
| File | Description |
|---|---|
| `data/output/marketed_slips_latest.json` | Latest marketed slips (Discord/Twitter source) |
| `data/output/dashboard/cloudflare_payload.json` | Dashboard payload (Cloudflare trigger source) |
| `data/output/injury/normalized/YYYY-MM-DD_HH_MMxm.json` | Normalized injury snapshot for this run |
| `data/output/injury/normalized/latest.json` | Copy/symlink to latest normalized snapshot |

---

### Stage 4 — Post-Run Archive (`cli.py`)

`_archive_run_to_telemetry()` copies key artifacts after every live run:
| Source | Destination |
|---|---|
| `data/output/runs/{run_id}/scored_legs_deduped.csv` | `data/telemetry/live_runs/{run_id}/scored_legs_deduped.csv` |
| `data/output/runs/{run_id}/scored_board.csv` | `data/telemetry/live_runs/{run_id}/scored_board.csv` |
| `data/output/runs/{run_id}/meta.json` | `data/telemetry/live_runs/{run_id}/meta.json` |
| `data/output/runs/{run_id}/slip_results.csv` | `data/telemetry/live_runs/{run_id}/slip_results.csv` |

`_write_full_run_bundle()` creates a self-contained replay bundle:
| Source | Destination |
|---|---|
| Run outputs + raw JSON + IAEL snapshots | `data/bundles/atlas_bundle_{run_id}.zip` |
| `data/bundles/atlas_bundle_{run_id}.zip` | `data/telemetry/live_runs/{run_id}/atlas_bundle_{run_id}.zip` |
| `data/bundles/atlas_bundle_{run_id}.zip` | `data/telemetry/bundles/atlas_bundle_{run_id}.zip` |

> `eval_legs.csv` is NOT written by the live run. It is written by the **6 AM backfill job** after game results are available.

---

### Stage 5 — Generate Daily Graphics CSV
**Tool:** `tools/generate_daily_graphics_csv.py --latest`
| Reads | Writes |
|---|---|
| `data/output/runs/{run_id}/scored_legs_deduped.csv` | `data/output/graphics/daily_top_picks_YYYYMMDD.csv` |
| `data/output/runs/{run_id}/marketed_slips.csv` | `data/output/latest/daily_top_picks.csv` |

---

### Stage 6 — Cloudflare Dashboard Publish (`cli.py`)

`_publish_to_cloudflare_dashboard()`:
| Source | Destination | Mechanism |
|---|---|---|
| `data/output/dashboard/cloudflare_payload.json` | `atlas-dashboard/public/data/cloudflare_payload.json` | git add + commit + push → Cloudflare Pages deploy |

---

### Stage 7 — Discord Post *(best-effort, non-fatal)*
**Tool:** `tools/discord_post.py --picks-today`
| Reads | Writes |
|---|---|
| `data/output/marketed_slips_latest.json` | Discord webhook (external) |

---

### Stage 8 — Twitter Post *(best-effort, non-fatal)*
**Tool:** `tools/twitter_post.py --picks-today`
| Reads | Writes |
|---|---|
| `data/output/marketed_slips_latest.json` | Twitter API (currently 402 CreditsDepleted) |

---

## Source Code Map

```text
src/Atlas/
├── cli.py                          # CLI entry point (live/replay/tools) + post-run archive
├── __init__.py
├── contracts/
│   └── model_contract.py           # Stage 0 — config schema validation
├── core/                           # Shared utilities
│   ├── dedupe.py                   # Leg deduplication (alt lines -> best pick)
│   ├── external_priors.py          # BettingPros/OddsAPI prior nudge (bounded tanh)
│   ├── features.py                 # 33-feature GBM feature engineering
│   ├── iael_filter.py              # OUT/DOUBTFUL removal, questionable tagging
│   ├── marketed_slip_builder.py    # Marketed subscriber slip builder
│   ├── matchup_enricher.py         # Matchup context enrichment
│   ├── minutes.py                  # Blowout adjustment + minutes sensitivity
│   ├── payout_tables.py            # PrizePicks tier payout coefficients
│   ├── pp_pricing.py               # PrizePicks pricing model
│   ├── share_name_key.py           # Canonical player name normalization
│   ├── slip_builders.py            # Beam-search slip builder (System/Windfall/DemonHunter)
│   └── slip_scoring.py             # Slip-level EV and win probability scoring
├── engine/                         # Scoring engine
│   ├── api.py                      # EngineOutputs dataclass
│   ├── catboost_calibrator.py      # Active CatBoost playoff v5cD runtime calibrator
│   ├── calibration.py              # GBM ensemble calibrator (7 seeds x 2 directions)
│   ├── calibration_map.py          # Telemetry calibration overlay application
│   ├── main.py                     # Engine orchestration: load -> score -> calibrate -> build -> publish
│   ├── new_engine.py               # v14 scoring kernel entry point
│   └── new_probability.py          # Monte Carlo kernel (10K sim, role context, blowout, under-relief)
├── model/                          # Model builders
│   ├── share_matrix_builder_v2.py  # Share matrix construction from gamelogs
│   ├── share_matrix_contract.py    # Column contract for share_matrix.csv
│   └── team_share_allocator_v2.py  # Injury redistribution allocator (depth, severity, caps)
├── runtime/                        # Execution infrastructure
│   ├── archive_writer.py           # Archive management helpers
│   ├── bundles.py                  # write_bundle_zip() — self-contained replay bundle
│   ├── obs.py                      # Observability (events, timers, audit log)
│   ├── orchestrator.py             # Pipeline orchestrator (run_today())
│   ├── paths.py                    # Path resolution
│   ├── replay_eval.py              # Replay evaluation -> eval_legs.csv with truth labels
│   ├── run_context.py              # Run context (run_id, mode, env vars)
│   └── telemetry_calibration.py    # Isotonic calibration: load, apply, train
└── stages/
    ├── fetch/                      # Data fetchers (board, rotowire, role metrics)
    ├── filter/                     # Pre-score filters (IAEL, dedup)
    ├── optimize/
    │   └── build_slips_today.py    # BuiltSlips dataclass + slip orchestration (System/Windfall/DH)
    ├── prep_for_optimizer/         # Pre-optimizer feature prep
    ├── publish/
    │   └── publish_run_outputs.py  # Write run directory artifacts (Stage 3 outputs)
    ├── rebuild/                    # today.csv reconstruction
    └── score/                      # Scoring stage wrappers

tools/
├── batch_replay_backfill.py        # Batch replay from bundles/raw JSONs (corpus expansion)
├── backfill_iael_rotowire.py       # Synthesize IAEL stubs for dates missing archive snapshots
├── build_share_matrix.py           # Share matrix builder (called by orchestrator)
├── create_eval_leg_backtestv2.py   # 6 AM backfill: match scored legs -> eval_legs.csv
├── demonhunter_trainer_v4.py       # DemonHunter builder param sweep
├── diagnose_winprob.py             # Calibration diagnostics by probability tier
├── discord_post.py                 # Discord webhook poster
├── fetch_bettingpros_props.py      # BettingPros external priors fetch
├── fetch_crafted_player_stats.py   # CraftedNBA role metrics fetch
├── fetch_oddsapi_props.py          # OddsAPI external priors fetch
├── fetch_rotowire_lines.py         # Rotowire spreads/totals fetch
├── gbm_v19_train.py                # Current GBM trainer pattern (LODO cross-validation)
├── catboost_playoff_v5cD_full_corpus.py # Trains active v5cD full-corpus CatBoost model
├── replay_v5cD_corpus.py           # 10-date v5cD replay validation
├── slip_eval_v5cD_corpus.py        # v5cD slip-level evaluation
├── generate_daily_graphics_csv.py  # Daily graphics CSV generator
├── leg_trainer_v5_ev.py            # Slip builder param sweep (EV optimizer)
├── leg_trainer_v5_hit.py           # Slip builder param sweep (hit rate optimizer)
├── marketed_slip_trainer_v3.py     # Marketed slip builder param sweep
├── refresh_iael_today.py           # IAEL injury data refresh
├── refresh_nba_gamelogs.py         # NBA game logs updater
├── replay_bundle.py                # Single-bundle replay with scenario ID
├── telemetry_corpus_reader.py      # Multi-run aggregate analysis (LODO, slices, cal candidates)
├── train_direction_calibrator.py   # Direction-split isotonic calibration training
├── train_playoff_isotonic.py       # Playoff isotonic calibration training
└── twitter_post.py                 # Twitter API poster
```

---

## Live vs Replay

| Aspect | Live | Replay |
|---|---|---|
| Data source | Fresh API fetch | Pinned raw JSON + archived artifacts |
| Output root | `data/output/runs/{run_id}/` | `data/telemetry/replay_runs/{run_id}/` |
| Injury source | Live IAEL refresh | Pinned IAEL snapshot (invalidations + status + normalized) |
| Rotowire source | Fresh fetch | Pinned snapshot |
| Publish latest surfaces | Yes | **No** |
| Game log refresh | Yes | **No** |
| Cloudflare push | Yes | **No** |
| Discord/Twitter post | Yes | **No** |
| Missing artifact | Fetch or fail | **Hard stop** |

### Replay Commands

```powershell
# Standard replay — pinned raw JSON
python -m Atlas.cli replay --raw data\raw\prizepicks_YYYYMMDD_HHMMSS.json

# Strict replay — all artifacts pinned (no live fallback)
$env:ATLAS_STRICT_REPLAY = "1"
$env:ATLAS_DATA_DIR = "data"
$env:ATLAS_OUT_DIR = "<output_dir>"
$env:ATLAS_GAMELOGS_PATH = "data\gamelogs\nba_gamelogs.csv"
$env:ATLAS_REPLAY_RAW = "<raw_json_path>"
$env:ATLAS_ROTOWIRE_LINES_PATH = "data\archives\iael\2026\<date>\<ts>\rotowire_lines.json"
$env:ATLAS_IAEL_INVALIDATIONS_PATH = "data\archives\iael\2026\<date>\<ts>\injury_invalidations.json"
$env:ATLAS_IAEL_STATUS_PATH = "data\archives\iael\2026\<date>\<ts>\status.json"
$env:ATLAS_IAEL_NORMALIZED_PATH = "data\output\injury\normalized\<snapshot>.json"
python -m Atlas.cli replay --raw data\raw\prizepicks_YYYYMMDD_HHMMSS.json

# Bundle replay — self-contained zip (preferred for corpus backfill)
python tools/replay_bundle.py data\bundles\atlas_bundle_YYYYMMDD_HHMMSS.zip --scenario-id <name>
```

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `ATLAS_STRICT_REPLAY` | `1` = strict replay mode (no live fetches, hard stop on missing artifact) |
| `ATLAS_GAME_DATE` | Override game date (YYYY-MM-DD) |
| `ATLAS_CONFIG_PATH` | Override config.yaml path |
| `ATLAS_DATA_DIR` | Override data directory root |
| `ATLAS_OUT_DIR` | Override output directory |
| `ATLAS_BOARD_PATH` | Override board CSV path |
| `ATLAS_GAMELOGS_PATH` | Override gamelogs CSV path |
| `ATLAS_REPLAY_RAW` | Pinned raw board JSON (replay) |
| `ATLAS_IAEL_INVALIDATIONS_PATH` | Pinned injury invalidations JSON |
| `ATLAS_IAEL_STATUS_PATH` | Pinned injury status JSON |
| `ATLAS_IAEL_NORMALIZED_PATH` | Pinned normalized injury snapshot |
| `ATLAS_ROTOWIRE_LINES_PATH` | Pinned Rotowire lines JSON |
| `ATLAS_ROLE_METRICS_PATH` | Pinned role metrics JSON |
| `ATLAS_FS_ENFORCE` | `warn` or `hard` — filesystem write enforcement |
| `PYTHONIOENCODING` | Set to `utf-8` for all runs |

---

## Daily Automation

Six Windows Task Scheduler jobs run daily (wake from sleep):

| Time | Job | What it does |
|---|---|---|
| **6:00 AM** | `run_iael_6am_eval.cmd` | Refresh gamelogs -> backfill `eval_legs.csv` for all yesterday's runs |
| **8:00 AM** | `run_iael_morning.cmd` | Full live run #1 of 4 — fetch, score, publish, bundle, dashboard push |
| **11:00 AM** | `run_iael_11am.cmd` | Full live run #2 of 4 |
| **2:30 PM** | `run_iael_230pm.cmd` | Full live run #3 of 4 |
| **4:30 PM** | `task_8am_graphics.ps1` | Free slip run — generates daily free pick graphics and posts to Discord |
| **5:30 PM** | `run_iael_530pm.cmd` | Full live run #4 of 4 (evening / playoff window) |

All tasks: `WakeToRun=true`, `StartWhenAvailable=true`.
Query: `schtasks /query /tn "Atlas\*"`

### 6 AM Eval Backfill Detail

```
tools/create_eval_leg_backtestv2.py
  reads:  data/gamelogs/nba_gamelogs.csv   <- yesterday's box scores (refreshed first)
          data/telemetry/live_runs/{yesterday_11am}/scored_legs_deduped.csv
          data/telemetry/live_runs/{yesterday_230pm}/scored_legs_deduped.csv
  writes: data/telemetry/live_runs/{run_id}/eval_legs.csv
          data/output/runs/{run_id}/eval_legs.csv
```

`eval_legs.csv` is the **only truth-backed file for Brier/AUC/log-loss evaluation.**
`scored_legs_deduped.csv` lacks the `hit` column — never use it as an eval source.

---

## Telemetry Archive Layout

```text
data/telemetry/
+-- live_runs/
|   +-- {run_id}/                       # One dir per live run
|       +-- scored_legs_deduped.csv     # Written by _archive_run_to_telemetry (cli.py)
|       +-- scored_board.csv
|       +-- meta.json
|       +-- slip_results.csv
|       +-- eval_legs.csv               # Written by 6 AM backfill job (next morning)
|       +-- atlas_bundle_{run_id}.zip   # Copy from data/bundles/
+-- bundles/
|   +-- atlas_bundle_{run_id}.zip       # Duplicate copy of all bundles
+-- replay_runs/
|   +-- {scenario_id}/                  # One dir per bundle/strict replay
|       +-- scored_legs_deduped.csv
|       +-- eval_legs.csv
|       +-- ...
+-- games_logged/
|   +-- YYYY-MM-DD_games_logged.csv     # Per-date gamelog refresh log
+-- v9d_corpus/                         # Reference corpus -- DO NOT DELETE
    +-- (10 runs, 49,956 legs)
```

---

## Key Canonical Data Files

| File | Written by | Read by |
|---|---|---|
| `data/board/today.csv` | `rebuild_today_from_any_raw.py` | Engine (`main.py`) |
| `data/gamelogs/nba_gamelogs.csv` | `refresh_nba_gamelogs.py` | Engine (features), share matrix builder, eval backfill |
| `data/model/share_matrix.csv` | `build_share_matrix.py` | Engine (`new_probability.py`) |
| `data/model/ensemble/*.txt` | GBM trainer (`gbm_v19_train.py` / historical trainers) | Historical GBM path (`calibration.py`) |
| `data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm` | `catboost_playoff_v5cD_full_corpus.py` | Active engine (`catboost_calibrator.py`) |
| `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json` | `catboost_playoff_v5cD_full_corpus.py` | Active engine (`catboost_calibrator.py`) |
| `data/model/telemetry_calibration.playoff_isotonic.json` | `train_playoff_isotonic.py` | Optional telemetry path; currently disabled |
| `data/model/marketed_calibration.json` | `marketed_slip_trainer_v3.py` | Engine (`marketed_slip_builder.py`) |
| `data/input/external_priors_today.csv` | `fetch_bettingpros_props.py` + `fetch_oddsapi_props.py` | Engine (`external_priors.py`) |
| `data/output/marketed_slips_latest.json` | Engine publish stage | Discord post, Twitter post |
| `data/output/dashboard/cloudflare_payload.json` | Engine | `_publish_to_cloudflare_dashboard()` -> Cloudflare Pages |
| `data/telemetry/live_runs/{id}/eval_legs.csv` | 6 AM backfill | All evaluation tools (corpus reader, Brier, AUC) |
| `data/model/_v18_resim_cache.pkl` | v18 GBM training workflow | Historical LightGBM baseline |
| `data/model/_v1_playoff_resim_cache.pkl` | `build_playoff_resim_cache.py` | Active CatBoost v5cD training |