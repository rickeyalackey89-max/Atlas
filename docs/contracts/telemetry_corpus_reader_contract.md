# Telemetry Corpus Reader v1 Contract

## Purpose
Read a full Atlas replay corpus as one telemetry surface and emit recommendations for:
- `config.yaml`
- calibration JSON artifact
- `calibration.py`
- `calibration_map.py`

The reader is recommendation-only. It must not modify core files.

## Entry point
`tools/telemetry_corpus_reader.py`

## Inputs
Required:
- `--corpus-input` : corpus root folder or corpus zip containing `runs/`
- `--config-path` : path to `config.yaml`

Optional:
- `--calibration-json-path`
- `--calibration-py-path`
- `--calibration-map-py-path`
- `--output-root`

## Canonical corpus artifacts read per run
- `eval_legs.csv`
- `scored_legs_deduped.csv`
- `recommended_*leg*.csv`
- `System/recommended_*leg*.csv`
- `Windfall/recommended_*leg*.csv`

## Output bundle
The tool writes a timestamped bundle under:
`.atlas_audit/diagnostics/telemetry_corpus/<timestamp>/`

Required files:
- `corpus_summary.json`
- `corpus_summary.md`
- `config_recommendations.json`
- `calibration_recommendations.json`
- `logic_recommendations.json`
- `per_run_metrics.csv`
- `corpus_metrics.csv`

## Decision rules
1. Read-only against Atlas core files.
2. Separate recommendation families:
   - pricing/config
   - calibration artifact
   - logic-source inspection
3. Always allow a no-change outcome.
4. Use corpus artifact evidence, not Oracle prose, as the recommendation basis.

## v1 behavior
- Supports folder or zip corpus input.
- Aggregates per-run telemetry into one corpus summary.
- Computes slip-level strict win rate by resolving `[id:<projection_id>]` leg tags against `eval_legs.csv`.
- Emits conservative recommendations with `apply_now=false` by default.
- Treats Variant 01 Standard coeffs as the locked current baseline unless corpus evidence clearly justifies inspection.
