# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-12T00:23:25+00:00`

## Primary corpus
- Label: `Telemetryruns_control`
- Runs read: `10`
- Settled legs: `37944`

## Variant leaderboard
- `Telemetryruns_control` score=-0.056763 strict3=0.2251 strict4=0.0967 strict5=0.0836 hit3=0.2794 hit4=0.2782 pos=realized_core neg=stability_penalty

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
  - `stat_direction_light` brier=0.210049 logloss=0.606786 ece=0.017986
  - `identity` brier=0.210777 logloss=0.609035 ece=0.029457
  - `under_penalty_0.98` brier=0.210873 logloss=0.609226 ece=0.030463
  - `shrink_0.88` brier=0.21027 logloss=0.607319 ece=0.01873
  - `shrink_0.92` brier=0.210281 logloss=0.607263 ece=0.020983

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> keep; No structural calibration logic change is supported by the corpus yet.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> keep; No structural calibration logic change is supported by the corpus yet.
