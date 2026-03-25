# Role Context Strength Plan

## Goal
Improve Brier and logloss by giving the calibration layer a continuous signal for how strong the role-context effect is, instead of only a binary on/off split.

## Why this next
- The runtime already exposes `role_ctx_outs_used`, `role_ctx_mult`, and `role_ctx_reason`.
- The judge already has binary role-on / role-off families, so the remaining gap is likely how strongly role context should apply, not whether it exists.
- A continuous feature is more likely to move calibration gradually than another hard gate.

## Proposed feature family
- Name: `role_context_strength`
- Input signals:
  - `role_ctx_outs_used`
  - `role_ctx_mult`
  - `role_ctx_reason` as a fallback diagnostic only
- Basic behavior:
  - derive a normalized strength score from the role-context signal already present on each row
  - use that score to interpolate between role-off and role-on behavior instead of applying one or the other wholesale

## First implementation target
- Add one candidate family in `tools/telemetry_corpus_reader.py` that blends the existing role-off and role-on transforms using a continuous strength weight.
- Keep the first version conservative:
  - no new runtime-only knobs
  - no change to the under-relief logic
  - no change to slip ranking

## Pass criteria
- Lower corpus Brier and logloss versus the current active baseline.
- No collapse on the role-context slices.
- If the improvement is only one metric, do not promote it.

## Next step after this
- Implement the candidate family and run the same corpus comparison.

## Current promotion note
- Latest reader verdict: `keep_current_standard_with_calibration_only_lead`.
- Top calibration candidate: `isotonic_global_p_cal`.
- Corpus outcome on the wrapped local corpus:
  - Brier: `0.198285`
  - Logloss: `0.575175`
  - Eligible slices passed: `6/6`
- Interpretation:
  - This is a clean calibration overlay lead.
  - It is not yet full variant promotion evidence.
  - The reader still blocks config promotion because the primary corpus remains the config leader and the variant gates did not clear broadly enough.