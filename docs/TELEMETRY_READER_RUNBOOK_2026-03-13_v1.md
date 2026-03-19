# TELEMETRY READER RUNBOOK (v1, 2026-03-13)

## Purpose
This file explains:
- what the telemetry reader is
- what it reads
- what it outputs
- how to command it
- how it fits into current Atlas testing
- what the current testing goal is

---

## 1. What the telemetry reader is

`tools/telemetry_corpus_reader.py` is a standalone replay telemetry judge.

It is **not** the replay generator.
It is **not** Oracle.
It is **not** the allocator.

Its job is to:
- read a replay corpus
- summarize corpus-level calibration + slip behavior
- compare control vs challenger corpora
- produce configuration and calibration recommendations
- refuse promotion when the evidence is weak

The current workflow treats the telemetry reader as the main **baseline / challenger evaluator**.

---

## 2. What generates the telemetry corpus

Replay generation comes from **Backtest v2**, not the reader.

Canonical replay runner:
- `py -m Atlas.model.backtest_v2 ...`

Replay writes canonical run folders.
The reader consumes those run folders after replay is done.

---

## 3. What artifacts the reader needs

### Per run, it needs:
- `eval_legs.csv`
- `scored_legs_deduped.csv`

### It also benefits from:
- recommended slip CSVs
- `meta.json`

### Corpus layouts supported:
- `root/runs/<run_id>/...`
- `root/<run_id>/...`

### If a run is incomplete:
- the hardened reader skips it instead of hard-failing

### For older telemetry runs:
If `eval_legs.csv` is missing, use:
- `tools/create_eval_leg_backtestv2.py`

That reconstructs `eval_legs.csv` from:
- legacy `scored_legs_deduped.csv`
- `data/gamelogs/nba_gamelogs.csv`

---

## 4. What the reader outputs

Typical outputs include:
- `corpus_summary.json`
- `corpus_summary.md`
- `config_recommendations.json`
- `calibration_recommendations.json`
- `logic_recommendations.json`
- `candidate_scores.json`
- `per_run_metrics.csv`
- `corpus_metrics.csv`
- `drift_metrics.csv`
- `regime_tables.xlsx`
- `proposed_config_patch.yaml`
- `proposed_calibration.json`
- `patch_plan.json`

Outputs are written under:
- `.atlas_audit/diagnostics/telemetry_corpus/<timestamp>/`

---

## 5. How to run it

### Example control reader command
`cd C:\Users\rick\projects\Atlas; py .\tools\telemetry_corpus_reader.py --corpus-input "C:\Users\rick\projects\Atlas\outputtelem\Telemetryruns_control_targeted_lift_v2" --config-path "C:\Users\rick\projects\Atlas\config.yaml" --calibration-json-path "C:\Users\rick\projects\Atlas\data\model\calibration_map.json" --calibration-py-path "C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py" --calibration-map-py-path "C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py" --output-root "C:\Users\rick\projects\Atlas"`

### Example challenger reader command
`cd C:\Users\rick\projects\Atlas; py .\tools\telemetry_corpus_reader.py --corpus-input "C:\Users\rick\projects\Atlas\outputtelem\Telemetryruns_cal_targeted_lift_v2" --config-path "C:\Users\rick\projects\Atlas\config.yaml" --calibration-json-path "C:\Users\rick\projects\Atlas\data\model\calibration_map.json" --calibration-py-path "C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py" --calibration-map-py-path "C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py" --output-root "C:\Users\rick\projects\Atlas"`

---

## 6. How telemetry calibration testing works

### Stable rules
These stay fixed during telemetry calibration testing:
- Standard baseline stays locked to Variant 01
- `calibration_map.json` stays identity/neutral
- allocator logic stays untouched
- replay corpus stays fixed
- same truth file stays fixed

### Only one thing changes between control and challenger
- `data/model/telemetry_calibration.json`

### Control
- rename or remove `telemetry_calibration.json`
- replay same corpus

### Challenger
- copy challenger artifact into:
  - `data/model/telemetry_calibration.json`
- replay same corpus

### Then
- run the telemetry reader on control
- run the telemetry reader on challenger
- compare the two reader bundles

---

## 7. Current telemetry runtime behavior

Telemetry calibration now applies as a late overlay in the p_cal flow.

### Current telemetry features supported
- `k_shrink`
- `standard_under_penalty`
- `mult`
- `bucket_rules`
- final `cap`

### Proof columns now written
- `telemetry_cal_key`
- `telemetry_k_shrink`
- `telemetry_under_penalty`
- `telemetry_mult`
- `telemetry_bucket_mult`
- `telemetry_cal_applied`
- `p_cal_src` shows `+telemetry` when the overlay fired

This is how we prove a challenger actually changed the replay output.

---

## 8. What the current testing goal is

The current mission is:

### Goal
Find a telemetry calibration challenger that:
- improves corpus-level **Brier**
- improves corpus-level **log loss**
- does not materially damage protected slip surfaces
- clears enough regime / time-window gates to be promotable

### Current status
Failed challenger families:
- mixed stat-direction
- under-only
- penalty-only under
- upper-bucket cooling

Most promising family:
- **targeted lift**
- derived from the telemetry calibration diagnostic

### Best current challenger
- `telemetry_calibration_targeted_lift_v2.json`

Open question:
- does `targeted_lift_v2` beat control strongly enough on the full corpus to promote?

---

## 9. Diagnostic tool

If the next challenger fails, do not guess the next one blindly.
Use:
- `tools/telemetry_calibration_diagnostic.py`

### Example command
`cd C:\Users\rick\projects\Atlas; py .\tools\telemetry_calibration_diagnostic.py --corpus-input "C:\Users\rick\projects\Atlas\outputtelem\Telemetryruns_control_bucket_v1" --output-root "C:\Users\rick\projects\Atlas"`

### Diagnostic outputs
- `diagnostic_summary.json`
- `diagnostic_summary.md`
- bucket diagnostics
- stat/direction diagnostics
- games-used diagnostics
- role-context diagnostics
- questionable diagnostics
- p_cal source diagnostics
- top overconfident slices
- top underconfident slices

### Rule
Diagnostic tool is:
- **diagnostics only**
- no auto promotion
- no auto patch proposal

---

## 10. Current best practice loop

1. Build telemetry challenger artifact
2. Run single-raw A/B first
3. If it looks structurally clean, run full corpus A/B
4. Run telemetry reader on control and challenger
5. Compare bundle outputs
6. Promote only if the challenger genuinely wins
7. If challenger fails, run diagnostics before creating the next one

This is the current Atlas telemetry calibration workflow.
