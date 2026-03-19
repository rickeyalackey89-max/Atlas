# Telemetry Corpus Reader — Full Reader v1.1

Generated: `2026-03-11T12:09:22+00:00`

## Primary corpus
- Label: `Telemetryruns_wrapper`
- Runs read: `9`
- Settled legs: `23885`

## Variant leaderboard
- `Telemetryruns_wrapper` score=0.086982 strict3=0.1 strict4=0.075 strict5=0.035 hit3=0.4144 hit4=0.304 pos=realized_core neg=stability_penalty

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
- Mode: `fit_candidate` (medium); Candidate stat_direction_light cleared overall and regime/time-window gates with corpus Brier improvement 0.001944.
  - `stat_direction_light` brier=0.22034 logloss=0.632263 ece=0.0449
  - `shrink_0.96` brier=0.221261 logloss=0.634555 ece=0.048894
  - `under_penalty_0.94` brier=0.221785 logloss=0.638368 ece=0.054302
  - `under_penalty_0.96` brier=0.221916 logloss=0.638742 ece=0.054871
  - `shrink_0.88` brier=0.219749 logloss=0.629219 ece=0.033193

## Logic recommendations
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration.py` -> inspect; Artifact-level candidate improved, but logic changes should be reviewed manually after artifact validation.
- `C:\Users\rick\projects\Atlas\src\Atlas\engine\calibration_map.py` -> inspect; Artifact-level candidate improved, but logic changes should be reviewed manually after artifact validation.
