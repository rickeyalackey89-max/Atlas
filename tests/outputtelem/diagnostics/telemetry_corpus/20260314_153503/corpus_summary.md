# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-14T20:35:11+00:00`

## Primary corpus
- Label: `FragUnderRuns_true_control`
- Runs read: `13`
- Settled legs: `40922`

## Variant leaderboard
- `FragUnderRuns_true_control` score=-0.075458 strict3=0.2442 strict4=0.124 strict5=0.2925 hit3=0.2823 hit4=0.2681 pos=realized_core neg=stability_penalty

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
  - `stat_direction_light` brier=0.209398 logloss=0.6052 ece=0.017491
  - `identity` brier=0.210157 logloss=0.607413 ece=0.03018
  - `under_penalty_0.98` brier=0.210247 logloss=0.607583 ece=0.031393
  - `shrink_0.92` brier=0.209742 logloss=0.605978 ece=0.022322
  - `shrink_0.88` brier=0.20977 logloss=0.606165 ece=0.02137

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
