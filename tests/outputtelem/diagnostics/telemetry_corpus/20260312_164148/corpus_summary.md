# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-12T21:41:48+00:00`

## Primary corpus
- Label: `telemetry_ab_challenger`
- Runs read: `1`
- Settled legs: `2181`

## Variant leaderboard
- `telemetry_ab_challenger` score=0.485932 strict3=0.25 strict4=0.2222 strict5=0.0 hit3=0.1822 hit4=0.2392 pos=realized_core neg=stability_penalty

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
- Mode: `fit_candidate` (medium); Candidate shrink_0.88 cleared overall and regime/time-window gates with corpus Brier improvement 0.005614.
  - `shrink_0.88` brier=0.226247 logloss=0.643337 ece=0.0857
  - `shrink_0.92` brier=0.227595 logloss=0.647405 ece=0.087016
  - `stat_direction_light` brier=0.227637 logloss=0.648555 ece=0.089101
  - `shrink_0.96` brier=0.229154 logloss=0.65264 ece=0.094603
  - `under_penalty_0.96` brier=0.230862 logloss=0.659249 ece=0.10383

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> inspect; Artifact-level candidate improved, but logic changes should be reviewed manually after artifact validation.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> inspect; Artifact-level candidate improved, but logic changes should be reviewed manually after artifact validation.
