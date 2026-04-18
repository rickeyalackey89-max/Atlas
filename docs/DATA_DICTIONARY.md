# Atlas Data Dictionary

> **Last updated:** 2026-03-31 — reflects workspace after cleanup to D:\AtlasTestMarch26.

---

## Directory Structure

```
data/
├── archives/           # Historical snapshots (IAEL, bundles, etc.)
├── board/              # Today's PrizePicks board
│   ├── fetch_board.csv   # Raw fetched board
│   └── today.csv         # Canonical board for scoring kernel
├── bundles/            # Self-contained replay bundles (zip)
├── gamelogs/           # Rolling NBA game logs
│   └── nba_gamelogs.csv
├── input/              # External inputs for the current run
│   ├── external_priors_today.csv
│   ├── roster_map.csv
│   ├── rotowire_lines.json
│   └── slate.csv
├── model/              # Trained model artifacts (PRODUCTION-CRITICAL)
│   ├── ensemble/         # v14 GBM models (14 files + meta)
│   ├── calibration_map.json
│   ├── player_te_lookup.json
│   ├── posthoc_calibrator_coeffs.json
│   ├── posthoc_calibrator_coeffs_enriched.json
│   ├── posthoc_calibrator_gbm.txt
│   ├── posthoc_calibrator_gbm_meta.json
│   ├── posthoc_calibrator_gbm_over.txt
│   ├── posthoc_calibrator_gbm_under.txt
│   ├── share_matrix.csv
│   └── telemetry_calibration.*.json
├── output/             # Run outputs
│   ├── dashboard/        # IAEL + role metrics snapshots
│   ├── debug/            # Debug artifacts
│   ├── externalpriors/   # External prior snapshots
│   ├── injury/           # Normalized injury snapshots
│   ├── role_metrics/     # Role metrics outputs
│   └── runs/             # Timestamped run directories
│       └── <YYYYMMDD_HHMMSS>/
├── raw/                # Raw PrizePicks JSON snapshots
└── telemetry/          # Telemetry corpus and evaluation
    ├── games_logged/     # (empty)
    └── v9d_corpus/       # Current reader reference corpus (10 runs, 49,956 legs)
```

---

## Model Files (`data/model/`)

These files are **production-critical** and must not be moved or deleted.

### Ensemble (`data/model/ensemble/`)

| File | Purpose |
|---|---|
| `ensemble_meta.json` | v14 version stamp, features, params, metrics |
| `posthoc_calibrator_gbm_over_s{SEED}.txt` (×7) | LightGBM OVER models, one per seed |
| `posthoc_calibrator_gbm_under_s{SEED}.txt` (×7) | LightGBM UNDER models, one per seed |

Seeds: 65536, 9999, 137, 999, 98765, 54321, 12345. Architecture: `dn-d11nl50-top7-35feat`.

### Calibration Artifacts

| File | Purpose |
|---|---|
| `posthoc_calibrator_coeffs.json` | Base calibrator coefficients |
| `posthoc_calibrator_coeffs_enriched.json` | Enriched calibrator (combo-under features) |
| `posthoc_calibrator_gbm.txt` | Legacy single-seed GBM (fallback) |
| `posthoc_calibrator_gbm_over.txt` | Legacy single OVER model |
| `posthoc_calibrator_gbm_under.txt` | Legacy single UNDER model |
| `posthoc_calibrator_gbm_meta.json` | Calibrator metadata |
| `calibration_map.json` | Static calibration mapping |

### Telemetry Calibration

| File | Purpose |
|---|---|
| `telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.json` | **Active** isotonic calibration |
| `telemetry_calibration.isotonic_global_p_cal.json` | Global p_cal isotonic variant |
| `telemetry_calibration.isotonic_hybrid_roleoff_guarded.json` | Role-off guarded variant |

The active calibration is set by `telemetry.active_calibration` in `config.yaml`.

### Other Model Files

| File | Purpose |
|---|---|
| `share_matrix.csv` | Injury redistribution weights (rebuilt each run) |
| `player_te_lookup.json` | Player target-encoding lookup for GBM features |

---

## Input Files (`data/input/`)

| File | Purpose | Source |
|---|---|---|
| `rotowire_lines.json` | Spreads, totals, game schedule | Rotowire fetch |
| `external_priors_today.csv` | BettingPros consensus lines | BettingPros fetch |
| `roster_map.csv` | Team roster mappings | Manual/semi-auto |
| `slate.csv` | Today's game slate | Derived from board |

---

## Board Files (`data/board/`)

| File | Purpose |
|---|---|
| `fetch_board.csv` | Raw fetched PrizePicks board (before processing) |
| `today.csv` | Canonical board — the input to the scoring kernel |

---

## Output Files (`data/output/runs/<timestamp>/`)

Each run produces a timestamped directory with:

| File/Dir | Purpose |
|---|---|
| `scored_legs.csv` | All scored legs (may contain duplicates across alt lines) |
| `scored_legs_deduped.csv` | **Primary diagnostic file** — deduplicated, full probability chain |
| `System/system_3.csv` | 3-leg system slips |
| `System/system_4.csv` | 4-leg system slips |
| `System/system_5.csv` | 5-leg system slips |
| `Windfall/windfall_3.csv` | 3-leg windfall slips |
| `Windfall/windfall_4.csv` | 4-leg windfall slips |
| `Windfall/windfall_5.csv` | 5-leg windfall slips |
| `demonhunter.csv` | Best all-DEMON tier slips at each leg count |
| `*_winprob.csv` variants | Same families sorted by hit probability instead of EV |
| `meta.json` | Run metadata (timestamps, config hash, etc.) |

### `scored_legs_deduped.csv` Column Reference

See [ATLAS_MODEL_CONTEXT.md](ATLAS_MODEL_CONTEXT.md) for the full column-by-column breakdown.

Quick reference for the probability chain:
```
p (raw MC) → p_role (role-adjusted) → p_adj (blowout-adjusted)
  → p_for_cal (sent to GBM) → p_cal (calibrated output)
```

---

## Telemetry / Evaluation (`data/telemetry/`)

### `v9d_corpus/` — Reader Reference Corpus

Contains 10 replay runs (49,956 total legs across 22 dates) used to validate the v9d
baseline. This is the pinned evaluation corpus — do not delete.

Each run directory contains:
- `scored_legs_deduped.csv` — model outputs
- `eval_legs.csv` — truth-backed evaluation with `actual_stat` and `hit` columns
- `meta.json` — run metadata

### `eval_legs.csv` — Truth-Backed Evaluation File

Produced by `replay_eval.py` during replay evaluation. Key columns beyond scored_legs:

| Column | Purpose |
|---|---|
| `actual_stat` | Realized stat value from box score |
| `hit` | 1 if the leg hit, 0 if not |
| `brier` | Per-leg Brier score component |
| `p_adj` | Probability used for Brier calculation |

This is the file used for all Brier score computations and reader backtests.

---

## Bundles (`data/bundles/`)

Self-contained zip files for deterministic replay. Each bundle contains:
- Raw PrizePicks JSON snapshot
- IAEL injury snapshots (invalidations, status, normalized)
- Rotowire lines snapshot
- Role metrics snapshot (when available)

Named: `atlas_bundle_YYYYMMDD_HHMMSS.zip`

Use with: `python tools/replay_bundle.py <bundle.zip> --scenario-id <name>`

---

## Game Logs (`data/gamelogs/`)

| File | Purpose |
|---|---|
| `nba_gamelogs.csv` | Rolling NBA player game logs — source for share matrix, feature engineering, and Monte Carlo rate estimation |

Refreshed each live run by `tools/refresh_nba_gamelogs.py`. Not refreshed during replay.

---

## Archives (`data/archives/`)

Historical snapshots organized by date. Contains IAEL snapshots, bundle analysis outputs,
and other archived artifacts. Used as fallback inputs for replay when pinned paths are specified.

---

## Config (`config.yaml`)

The single configuration file controlling all model behavior. Key sections:

| Section | Controls |
|---|---|
| `pp_kernel` | PrizePicks pricing coefficients per stat/tier |
| `telemetry` | Active calibration, schema version, calibration policy |
| `role_ctx` | Role context bounds, under-relief gates |
| `posthoc_calibrator` | GBM ensemble toggle and paths |
| `blowout` | Spread sensitivity, structural adjustment rules |
| `slip_build` | Beam width, diversity penalties, per-leg overrides |
| `optimizer` | Top-N selection, external priors config |

See [ATLAS_MODEL_CONTEXT.md](ATLAS_MODEL_CONTEXT.md) for detailed config knob reference.

---

## Archived to D:\AtlasTestMarch26\

The following were moved out of the workspace on 2026-03-31 during cleanup:

| Archive Folder | Original Location | Size |
|---|---|---|
| `atlas_audit_full/` | `.atlas_audit/` | 558 MB |
| `telemetry_replay_runs/` | `data/telemetry/replay_runs/` | 5.8 GB |
| `telemetry_control_runs/` | `data/telemetry/control_runs/` | 78 MB |
| `telemetry_corpus_expand/` | `data/telemetry/corpus_expand/` | 7 MB |
| `telemetry_last10/` | `data/telemetry/Last 10/` | 55 MB |
| `backtests_full/` | `data/output/backtests/` | 249 MB |
| `model_backups/` | `data/model/` (stale files) | ~40 MB |
| `dot_tmp/` | `.tmp/` | 8 MB |
| `outputtelem_full/` | `outputtelem/` | — |
| `temp_experiments_full/` | `temp_experiments/` | — |
| `dead_code_hunter_full/` | `dead-code-hunter/` | — |
| `engine_backups/` | Dead engine files | — |
| `src_dead/` | Dead src files | — |
| `root_files/` | Root-level text/reference files | — |
| `scripts_dev_full/` | `scripts/dev/` training scripts | — |
| `tests_temp_full/` | `tests/temp/` | — |
