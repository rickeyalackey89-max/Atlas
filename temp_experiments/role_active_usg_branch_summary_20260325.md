# Role-Active USG Branch Summary 2026-03-25

## Completed

1. Built a slice audit for the matched five-run role-active corpus.
2. Patched `src/Atlas/engine/new_probability.py` so `role_metrics_usg_pct` feeds the existing fragility-only usage proxy through a tight stat-aware clamp.
3. Added a focused unit test in `tests/test_new_probability_role_metrics.py` and validated it.
4. Replayed the same five settled 2026-03-17 role-active bundles under the patched code.
5. Refit a role-active-only overlay from that rebuilt corpus and staged it separately.

## Slice audit readout

See `temp_experiments/role_active_slice_audit_20260325.md`.

Key result:
- `role_ctx_on` is the unstable slice.
- `recent_third` alone is effectively neutral.
- The `role_ctx_on_recent_third` intersection is weaker than the corpus baseline on `p_cal`, but still points back to the role-on seam rather than a pure recency seam.

## USG seam status

The code seam is active, but this replay corpus does not contain populated `role_metrics_usg_pct` values.

Coverage on the rebuilt role-active corpus:
- all settled rows with USG present: `0 / 20640`
- role_ctx_on rows with USG present: `0 / 1792`
- rows with `usage_usg_mult != 1.0`: `0`

Result:
- the patched code is staged and tested,
- but this corpus cannot exercise the USG change yet,
- so the replay/result set is identical to the prior role-active corpus.

## Updated corpus comparison

Reader output:
- `temp_experiments/role_active_usg_corpus_20260325/.atlas_audit/diagnostics/telemetry_corpus/20260325_091505/corpus_summary.md`

Result:
- `role_active_usg_20260317_matched` tied exactly with `role_active_only_corpus_20260325`
- top calibration candidate remained `isotonic_global_p_cal`
- verdict remained `keep_current_standard_with_calibration_only_lead`

## Staged overlay artifact

Role-active-only fitted overlay payload:
- `temp_experiments/role_active_only_overlay_fit_20260325.json`

This artifact is staged from the role-active-only five-run corpus and is intentionally separate from live calibration promotion.
