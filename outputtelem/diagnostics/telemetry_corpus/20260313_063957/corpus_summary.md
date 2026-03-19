# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-13T11:40:02+00:00`

## Primary corpus
- Label: `Telemetryruns_cal_targeted_lift_v2`
- Runs read: `12`
- Settled legs: `38741`

## Variant leaderboard
- `Telemetryruns_cal_targeted_lift_v2` score=-0.032918 strict3=0.1371 strict4=0.1474 strict5=0.1773 hit3=0.3109 hit4=0.2917 pos=realized_core neg=stability_penalty

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
  - `stat_direction_light` brier=0.208451 logloss=0.603017 ece=0.014698
  - `identity` brier=0.209106 logloss=0.604881 ece=0.027858
  - `shrink_0.92` brier=0.208838 logloss=0.603931 ece=0.020489
  - `shrink_0.96` brier=0.208895 logloss=0.604075 ece=0.023623
  - `shrink_0.88` brier=0.208935 logloss=0.604319 ece=0.023435

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
