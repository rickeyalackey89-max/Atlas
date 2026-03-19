# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-12T20:22:39+00:00`

## Primary corpus
- Label: `Telemetryruns_cal_challenger`
- Runs read: `23`
- Settled legs: `78866`

## Variant leaderboard
- `Telemetryruns_cal_challenger` score=-0.011302 strict3=0.2013 strict4=0.1592 strict5=0.0811 hit3=0.2889 hit4=0.2797 pos=realized_core neg=stability_penalty

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
  - `stat_direction_light` brier=0.209834 logloss=0.606294 ece=0.017547
  - `identity` brier=0.210604 logloss=0.608608 ece=0.030114
  - `under_penalty_0.98` brier=0.210702 logloss=0.608806 ece=0.031315
  - `under_penalty_0.96` brier=0.210825 logloss=0.60906 ece=0.032515
  - `shrink_0.92` brier=0.210133 logloss=0.606926 ece=0.021853

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
