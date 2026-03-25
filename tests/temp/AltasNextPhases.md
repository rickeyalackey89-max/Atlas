# Atlas Next Phases — 2026-03-16

## Purpose
This is the locked next-step plan after tonight’s work. The goal is to stop thrashing, fix replay fidelity once, and then return to real model testing with confidence.

## Current state
A few things are now clear:

- `new_probability.py` likely did need retuning, and the current fragility direction appears better aligned with Atlas than the older path.
- Live and replay are not currently operating with the same information fidelity.
- Replay can recreate row shape and run the engine, but it is missing important live-time context in some cases.
- External priors had a real bug in `external_priors.py`:
  - it was nudging `p` instead of `p_adj`
  - YAML fallback was still live and could contaminate behavior
- The main blocker now is backtest fidelity, not another round of blind probability tweaking.

## Locked priorities
1. No more core file changes tonight.
2. The active priority is replay/backtest fidelity.
3. After fidelity is corrected, return to real model testing and let the reader judge the correct model state.
4. Only after that do we decide whether the current `new_probability.py` direction stays, gets adjusted, or gets reverted.

# Phase 1 — Archive live Rotowire context properly
## Goal
Make sure live-time Rotowire context is preserved for future replay/backtest use.

## Required outcome
For every live run going forward, create and archive the Rotowire JSON used by the live model.

## Destination
It should be written alongside the IAEL archive flow, in the same general archive family/location where IAEL artifacts already go.

## Why this matters
Replay currently cannot recreate the true live model state if the Rotowire artifact is overwritten every run and never archived.

# Phase 2 — Clean replay/backtest artifact output behavior
## Goal
Backtest should stop writing external-prior artifacts into the same place as live-run artifacts.

## Required outcome
Replay/backtest should write its external-prior resolved CSV into the replay run’s own output folder, alongside the rest of that replay’s run artifacts.

# Phase 3 — Fix replay/backtest fidelity once and benchmark it
## Goal
Make replay ingest the right information properly and establish one fidelity benchmark that can be trusted.

## Required outcome
Replay should ingest the correct archived live artifacts when they exist and reproduce the real scoring environment as closely as the contract allows.

# Phase 4 — Return to actual model testing
## Goal
Once backtest fidelity is corrected, return to real A/B testing and let the reader evaluate the correct model state.

# Phase 5 — Finalize external priors and optional last seam
## Goal
After replay fidelity and probability testing are settled, make sure externals are functioning exactly as intended and decide whether the final awareness seam is needed.

# Atlas Next Phases — Updated 2026-03-18

## Purpose
This is the locked next-step plan after the replay-fidelity and new-probability work completed in the 2026-03-18 chat. The goal is to stop thrashing, keep the fixed plumbing stable, and decide how Atlas should evaluate and adopt the current reshaped model direction.

## Current state
A few things are now clear:

- `new_probability.py` did need reshaping, and the current direction is intentional and user-preferred.
- Replay/backtest fidelity was materially improved.
- Live Rotowire is now archived for future replay use.
- Replay/backtest external-prior artifacts no longer need to pollute live-style folders.
- Replay can now ingest historical Rotowire and external-prior context on the corrected path.
- Replay/game-universe parity for already-started games was fixed by mirroring live-time exclusion behavior.
- The replay-thinness excuse is no longer the main blocker for judging the current branch.
- The reader eventually surfaced a real calibration-only lead: `telemetry_key_role_off_light`.
- The user’s practical judgment is that the current reshaped model is already outperforming the locked standard in the ways that matter operationally.

## Locked priorities
1. Do not reopen already-fixed fidelity plumbing unless a new concrete defect appears.
2. Do not reopen stale-file lineage questions; runtime files remain authoritative.
3. Keep schema frozen by default.
4. Keep changes surgical and auditable.
5. Treat the current `new_probability.py` reshape as the intended branch, not an accidental side path.
6. The next real question is no longer replay plumbing. It is how to judge and adopt the improved branch.

# Phase 1 — Preserve the fixed fidelity plumbing
## Goal
Do not regress the seams that were fixed in this chat.

## Fixed seams that should remain stable
- live Rotowire archival in `fetch_rotowire_lines.py`
- replay historical Rotowire injection
- replay historical external-prior injection
- external-priors debug artifact routing for live vs backtest
- started-game replay parity gate in `backtest_v2.py`

# Phase 2 — Bank the current new-probability reshape
## Goal
Preserve the current core branch as the working reshape baseline.

## What this branch now includes conceptually
- directional fragility (mainly OVER-side breakability)
- usage inside fragility only
- stronger handling for star usage realities
- reduced UNDER-side punishment through targeted UNDER blowout/haircut work
- role-context-aware carve-outs to avoid over-helping unstable role-context rows

# Phase 3 — Treat calibration as the narrow remaining lever
## Goal
Use late calibration as the narrow, auditable lever rather than reopening broad core changes.

## Current best calibration-only lead
- `telemetry_key_role_off_light`

## Interpretation
- calibration is applied late to `p_cal`
- role-context-off rows can receive a light map
- role-context-on rows should remain protected from over-calibration

# Phase 4 — Decide how Atlas should judge this branch
## Goal
Resolve the mismatch between:
- the reader’s conservative promotion policy
- the user’s observed practical superiority of the reshaped model

## The real decision to make
Choose whether Atlas should:
1. continue using the reader as a hard promotion gate for core-path reshapes, or
2. treat the reader as a diagnostic/conservative guide while allowing the practically superior branch to become the working model

# Phase 5 — Resume testing only in controlled, surgical form
## Goal
If any more tuning is done, it must be narrow and attributable.

## Acceptable future seams
- very small role-context carve-outs
- calibration-only map refinement
- direct evaluation of practical slip/hit-rate superiority vs the locked standard

## Not acceptable
- broad new core rewrites
- reopening already-fixed fidelity plumbing
- schema drift
- blind stack-on-stack experiments with no attribution plan