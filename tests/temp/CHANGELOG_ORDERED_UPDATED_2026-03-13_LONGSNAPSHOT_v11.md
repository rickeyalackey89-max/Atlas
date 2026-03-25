# CHANGELOG (ordered, updated v11)

## 1) Standard baseline locked
- Baseline decision completed from replay telemetry, not Oracle.
- Variant 01 remains the locked Standard baseline:
  - `pp_kernel.coeffs.DEFAULT.STANDARD.a = 0.3164`
  - `pp_kernel.coeffs.DEFAULT.STANDARD.b = -0.2880`
- Variant 02 was rejected as too aggressive on shorter System slips.

## 2) Calibration map stabilized
- Broken/crushing calibration map was neutralized with a valid identity-style `calibration_map.json`.
- Live WinProb sanity returned after that change.
- Decision locked:
  - keep `calibration_map.json` neutral during telemetry calibration testing.

## 3) Telemetry corpus reader built and hardened
- Built standalone telemetry reader.
- Reader evolved through multiple hardening passes:
  - corpus layout support:
    - `root/runs/<run_id>`
    - `root/<run_id>`
  - skip non-run folders and incomplete runs
  - support legacy source id shapes
  - protected ranking formula
  - time-window / regime promotion gates
  - diagnostic outputs
- Reader is now the main replay telemetry judge.

## 4) Legacy eval reconstruction
- Built `tools/create_eval_leg_backtestv2.py`.
- Reconstructs `eval_legs.csv` for older telemetry runs using:
  - `scored_legs_deduped.csv`
  - `data/gamelogs/nba_gamelogs.csv`
- This made older telemetry readable by the corpus tools.

## 5) Telemetry calibration integration bug found
- Early A/B tests showed control and challenger corpora were identical.
- Root cause:
  - telemetry calibration artifact existed
  - replay path did not consume it
- This was a runtime wiring issue, not a reader issue.

## 6) Telemetry integration patch applied
- Integrated telemetry calibration into the p_cal flow.
- Changed:
  - `src/Atlas/runtime/telemetry_calibration.py`
  - `src/Atlas/engine/new_engine.py`
  - `src/Atlas/engine/main.py`
  - `src/Atlas/runtime/orchestrator.py`
- Added proof columns to artifacts:
  - `telemetry_cal_key`
  - `telemetry_k_shrink`
  - `telemetry_under_penalty`
  - `telemetry_mult`
  - `telemetry_bucket_mult`
  - `telemetry_cal_applied`
  - `p_cal_src += "+telemetry"`
- Single-raw A/B proved the seam was fixed.

## 7) Telemetry challenger family results

### 7.1 Mixed stat-direction challenger
- Built after first corpus recommendations.
- Once runtime integration was fixed, full-corpus A/B showed it did not improve enough.
- Rejected.

### 7.2 UNDER-only challenger
- Narrower artifact than mixed map.
- Failed single-raw.
- Rejected.

### 7.3 Penalty-only UNDER challenger
- Tiny `standard_under_penalty`, no stat multipliers.
- Slight positive single-raw.
- Failed on full corpus.
- Rejected.

### 7.4 Upper-bucket cooling challenger
- Added `bucket_rules` support to telemetry runtime.
- Single-raw looked structurally clean.
- Failed on full corpus.
- Rejected.

## 8) Telemetry diagnostic pass built
- Built `tools/telemetry_calibration_diagnostic.py`.
- Outputs:
  - bucket diagnostics
  - stat/direction slice diagnostics
  - games-used slice diagnostics
  - role-context slice diagnostics
  - questionable slice diagnostics
  - p_cal source slice diagnostics
- This shifted the calibration strategy from broad cooling to targeted lifts.

## 9) Diagnostic conclusion
- Biggest recurring miss pattern is not broad overheating.
- Strongest underconfidence slices are:
  - `FG3M UNDER`
  - `RA UNDER`
  - `PRA UNDER`
  - `REB UNDER`
  - `PA UNDER`
  - `PR UNDER`
- Additional underconfident useful slices:
  - `PR OVER`
  - `PRA OVER`
  - `PTS OVER`
  - `PA OVER`

## 10) Targeted lift v1
- Built `telemetry_calibration_targeted_lift_v1.json`.
- Single-raw: clean pass.
- Full corpus: first real challenger to improve both Brier and log loss.
- Reader still did not auto-promote because gates remained strict.
- Decision:
  - do not promote yet
  - build softened v2

## 11) Targeted lift v2
- Built `telemetry_calibration_targeted_lift_v2.json`.
- Softer version of v1, same keys, smaller multipliers.
- Single-raw: clean pass.
- Current open task:
  - run full fixed-corpus A/B
  - run telemetry reader on control and challenger
  - compare whether v2 clears enough gates to promote

## 12) Current ordered next steps
1. Run full control corpus for `targeted_lift_v2`
2. Run full challenger corpus for `targeted_lift_v2`
3. Run telemetry reader on both corpora
4. Compare Brier/logloss + slip protection gates
5. Decide:
   - promote `targeted_lift_v2`
   - soften further into v3
   - or keep identity if v2 still does not clear gates

## 13) What remains stable
- Variant 01 Standard baseline is still locked.
- Calibration map stays identity.
- Oracle is not the baseline chooser.
- Telemetry reader + diagnostic tools are now the primary decision framework.
