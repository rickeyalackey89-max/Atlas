# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-13T01:41:49+00:00`

## Primary corpus
- Label: `Telemetryruns_cal_bucket_v1`
- Runs read: `13`
- Settled legs: `40922`

## Variant leaderboard
- `Telemetryruns_cal_bucket_v1` score=-0.047077 strict3=0.1433 strict4=0.1442 strict5=0.1031 hit3=0.2849 hit4=0.2679 pos=realized_core neg=stability_penalty

## Config recommendations
- `pp_kernel.coeffs.DEFAULT.STANDARD.a` -> `0.3164` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `pp_kernel.coeffs.DEFAULT.STANDARD.b` -> `-0.288` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_rank.ev_payout_power` -> `2` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_build.target_pool_mult` -> `200` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_build.phase1_frac` -> `0.2` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_build.phase1_pool_frac` -> `0.5` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_build.beam_width` -> `200` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.
- `slip_build.max_slips_per_player` -> `4` (high); Current value remains the leading or statistically tied corpus choice after regime/time-window gates.

## Calibration recommendation
- Mode: `keep_identity` (high); Calibration alternatives do not clear the regime/time-window promotion gates.
  - `stat_direction_light` brier=0.209354 logloss=0.605089 ece=0.01729
  - `identity` brier=0.210116 logloss=0.60731 ece=0.030469
  - `under_penalty_0.98` brier=0.210213 logloss=0.607501 ece=0.031676
  - `shrink_0.96` brier=0.209834 logloss=0.606258 ece=0.026158
  - `shrink_0.92` brier=0.20971 logloss=0.6059 ece=0.022588

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
