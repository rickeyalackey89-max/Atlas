# Telemetry Corpus Reader Summary

Generated at: 2026-03-11T00:28:07+00:00

## Corpus
- Corpus root: `C:\Users\rick\projects\Atlas\data\output\backtests\baseline_standard_variant_01_20260310`
- Runs read: 10
- Settled eval rows: 37944
- Mean hit rate: 0.421291
- Mean p_adj: 0.389389
- Mean p_cal: 0.397378
- Brier p_adj: 0.211735
- Brier p_cal: 0.211539

## Config recommendations
- `pp_kernel.coeffs.DEFAULT.STANDARD.a` -> keep `0.3164` (medium); Variant 01 is the locked Standard baseline and corpus telemetry does not show enough drift to justify another Standard coeff move.
- `pp_kernel.coeffs.DEFAULT.STANDARD.b` -> keep `-0.288` (medium); Variant 01 is the locked Standard baseline and corpus telemetry does not show enough drift to justify another Standard coeff move.
- `slip_rank.ev_payout_power` -> keep `2` (medium); Keep current EV ranking power until a corpus-level comparison shows a cleaner improvement without shorter-slip degradation.
- `slip_build.target_pool_mult` -> keep `200` (medium); Hold slip-build knobs steady in v1; current corpus reader is recommendation-only and has not run a controlled ablation on build-space knobs.
- `slip_build.phase1_frac` -> keep `0.2` (medium); Hold slip-build knobs steady in v1; current corpus reader is recommendation-only and has not run a controlled ablation on build-space knobs.
- `slip_build.phase1_pool_frac` -> keep `0.5` (medium); Hold slip-build knobs steady in v1; current corpus reader is recommendation-only and has not run a controlled ablation on build-space knobs.
- `slip_build.beam_width` -> keep `200` (medium); Hold slip-build knobs steady in v1; current corpus reader is recommendation-only and has not run a controlled ablation on build-space knobs.
- `slip_build.max_slips_per_player` -> keep `4` (medium); Hold slip-build knobs steady in v1; current corpus reader is recommendation-only and has not run a controlled ablation on build-space knobs.

## Calibration recommendation
- Mode: `keep_identity` (high); Observed calibrated probabilities do not materially outperform p_adj on corpus Brier score; keep neutral calibration.

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; Bonus-only logic should remain untouched unless corpus evidence shows the bonus is systematically harming calibration.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; Map-based calibration should remain neutral/identity until a fitted map materially improves corpus metrics.
