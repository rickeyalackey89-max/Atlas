# MLB Migration Readiness - 2026-05-20

## Current Recommendation

Do not promote the v7 depth/iteration sweep, the wide residual-scale artifact, or the v2 stacker yet.

Keep the current v6 tuned CAT artifact plus strict builder thresholds as the migration candidate:

- `data/mlb/model/cat_probability_kernel_v6_23date_live_context/scale_tuning/tuned_best_config.json`
- Replay corpus: `data/mlb/eval/corpus_replay_20260426_20260518_dk_per_game_live_fidelity_v2`
- Builder trainer: `data/mlb/model/slip_builder_policy_v8_strict_baseline_tuned_overlay`
- Strict-builder replay: `data/mlb/eval/corpus_replay_20260426_20260518_v6_tuned_strict_builder_v1`

## Replay Results

Live-fidelity replay, 23 dates, v6 tuned artifact:

- Weighted brier: `0.164292`
- Weighted logloss: `0.498967`
- Weighted win rate: `0.337363`
- Context coverage mean:
  - advanced: `0.973724`
  - lineup: `0.764617`
  - market: `0.544625`
  - player history: `0.964857`
  - probable pitcher: `0.997437`
  - roster: `0.965143`

Worst date brier pockets:

- `2026-05-05`: `0.175645`
- `2026-04-30`: `0.171920`
- `2026-05-13`: `0.171087`
- `2026-05-08`: `0.170842`
- `2026-05-01`: `0.169367`

Worst market pockets:

- `pitching_outs`: `0.233825`
- `pitcher_fantasy_score`: `0.220939`
- `earned_runs_allowed`: `0.216815`
- `walks_allowed`: `0.206978`
- `pitches_thrown`: `0.201117`
- `walks`: `0.199534`
- `hitter_strikeouts`: `0.197946`
- `hitter_fantasy_score`: `0.192856`

## CAT Attempts

v7 depth/iteration sweep:

- Tested deeper trees and higher-iteration candidates.
- First completed candidates regressed against v6.
- Stopped the sweep to avoid spending hours on a clearly worse path.

v6 residual scale tuning:

- Current scale tuning: fair LODO brier `0.17984945`
- Wide scale tuning: fair LODO brier `0.17981360`
- Wide tuning is only `0.00003585` better on brier and worse for slip selection, so it should not be promoted.

v2 probability stacker:

- Fair LODO brier: `0.17962226`
- Delta versus raw v6: `-0.00131413`
- Live-fidelity replay brier regressed from `0.164292` to `0.165034`
- Live-fidelity System/Windfall slip results regressed, so the stacker should not be promoted yet.

## Slip Builder Results

Fair builder trainer using v6 tuned LODO overlay after strict thresholds were promoted:

- Best variant: `baseline`
- Objective score: `0.324326`
- Settled rate: `0.937198`
- Settled slips: `194`

Family-level fair slip results for strict `baseline`:

- Marketed: `22-27-1`, slip win rate `0.440000`, leg win rate `0.826087`
- System: `24-39-1`, slip win rate `0.375000`, leg win rate `0.801527`
- Windfall: `17-41-1`, slip win rate `0.288136`, leg win rate `0.702586`
- DemonHunter: `4-17-0`, slip win rate `0.190476`, leg win rate `0.521739`

Live-fidelity strict-builder corpus results:

- Marketed: `37-7-0`, slip win rate `0.840909`
- System: `51-9-1`, slip win rate `0.836066`
- Windfall: `27-26-1`, slip win rate `0.500000`
- DemonHunter: `7-8-0`, slip win rate `0.466667`

Live-fidelity corpus slip results are operational smoke-test metrics, not fair promotion metrics, because the artifact has seen the replay dates. They still matter for migration because they verify the live path, payout/tier rules, and family output contract.

## Remaining Migration Gates

1. Run a live smoke test during a valid capture window.
2. Confirm live source contract is `pass` or timing-pending only for games not inside the DK-ready window.
3. Confirm no game already started appears in slips.
4. Confirm no next-day game appears in same-day slips.
5. Confirm live artifacts include source manifests for PP, BettingPros, DK, weather, lineup, roster, player history, and payout quote.
6. Keep the strict builder thresholds already promoted in `src/mlb/runtime/slips.py`.
7. Keep collecting new live days. Fair LODO is still around `0.1796`, not sub `.17`; more out-of-sample live days are required before claiming that target.

## Tomorrow Migration Plan

1. Keep MLB-dev isolated until the live smoke passes.
2. Register the live pull cadence with `scripts/mlb/register_live_pull_schedule.ps1`.
3. Run live at `11:00`, `14:30`, `17:00`, and `19:00` Central.
4. Review every live source manifest after each run.
5. If all four runs are clean, migrate the source tree and docs into the planned AtlasSportsAI structure.
6. Do not move raw replay artifacts into the production repository.
7. Promote only the v6 tuned artifact unless the next live days prove the stacker is better out of sample.
