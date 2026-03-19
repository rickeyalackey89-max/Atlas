# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-14T20:35:20+00:00`

## Primary corpus
- Label: `FragUnderRuns_challenger`
- Runs read: `13`
- Settled legs: `40922`

## Variant leaderboard
- `FragUnderRuns_challenger` score=-0.117732 strict3=0.1376 strict4=0.0607 strict5=0.131 hit3=0.2838 hit4=0.2674 pos=realized_core neg=stability_penalty

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
  - `stat_direction_light` brier=0.209374 logloss=0.605139 ece=0.017343
  - `identity` brier=0.210134 logloss=0.607355 ece=0.030301
  - `under_penalty_0.98` brier=0.210227 logloss=0.607535 ece=0.031511
  - `shrink_0.92` brier=0.209723 logloss=0.605933 ece=0.022433
  - `shrink_0.88` brier=0.209753 logloss=0.606126 ece=0.021476

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
