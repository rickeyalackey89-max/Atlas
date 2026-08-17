# WNBA 4L Sealed Pointwise Performance R2

Execution tier: **R2_BOUNDED_PILOT**

## Purpose

Grade the already-sealed strict historical-as-of 4L pointwise selections from WNBA commit `fbd986f967c4fb123349ce849bf0f9333ab15d60` against already-consumed discovery truth, compare them with the canonical `7-7-1` Atlas control, and determine whether pointwise has earned a separate freeze-readiness decision or whether the parked prior-only context variants still merit testing.

This task is **grading only**. The learner state and all target selections are already sealed.

## Bound authority

Expected starting WNBA commit:

`fbd986f967c4fb123349ce849bf0f9333ab15d60`

Expected WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_HISTORICAL_ASOF_POINTWISE_R1`

Bind and verify at minimum:

- R1 artifact manifest and summary;
- `four_leg_pointwise_asof_selection_ledger.csv` exactly as committed by R1;
- R0 pretruth seal / feature-control surface;
- R0 canonical control/supply forensic;
- discovery truth authority already consumed by R0/R1;
- frozen 3L research/depletion receipt and residual-inventory identity.

Fail closed on any hash or identity mismatch.

## Mandatory methodology

1. **No learner refit.** Do not call the 4L pointwise fitting path, regenerate probabilities, alter coefficients, or rebuild target selections.
2. Grade exactly the 15 already-sealed R1 target selections.
3. Preserve the 15 zero-residual dates as `MANDATORY_ABSTENTION_NO_RESIDUAL`; they are not losses and are outside the available-date performance denominator.
4. Compare pointwise and canonical Atlas control on the same 15 available dates.
5. Emit a per-date transition ledger with at least:
   - game date;
   - control candidate/result;
   - sealed pointwise candidate/result;
   - changed/not changed;
   - transition class: `BENEFICIAL`, `HARMFUL`, `NEUTRAL`, `NONBINARY_TRANSITION`;
   - R0 supply class: control win / ranking failure / supply impossible / nonbinary.
6. Emit aggregate pointwise W/L/NB and control W/L/NB.
7. Report:
   - repaired ranking-failure dates;
   - broken control-win dates;
   - neutral substitutions;
   - nonbinary transitions;
   - net pointwise win change versus control;
   - beneficial-minus-harmful substitutions;
   - behavior on the three R0 ranking failures (`2026-06-17`, `2026-07-22`, `2026-08-06`);
   - behavior on the four supply-impossible dates (`2026-07-08`, `2026-07-20`, `2026-07-28`, `2026-08-13`).
8. Do not search thresholds, gates, feature subsets, alternate regularization, or any post-hoc selective override rule.

## Predeclared practical bar

For this R2 only, the previously stated practical 4L bar is:

- at least **9 WIN** on the 15 available dates; and
- at least **+2 net WIN** versus the canonical 7-win control.

Report damage count separately; passing this bar is evidence for a **freeze-readiness review**, not automatic freeze authority.

Disposition labels:

- `POINTWISE_4L_PRACTICAL_BAR_MET` if both conditions hold;
- `POINTWISE_4L_PRACTICAL_BAR_NOT_MET` otherwise.

No other performance threshold may be invented after grading.

## Hard prohibitions

- no context regeneration or context arm;
- no pointwise refit;
- no candidate generation/regeneration;
- no gate/threshold/predicate tuning;
- no 4L freeze execution;
- no FromDeep execution;
- no validation reads;
- no lockbox reads;
- no Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- public/live slips are not evaluation authority;
- no R3 or follow-on task may auto-start.

## Runtime / runway

This should be artifact-only and complete in well under one minute. If a missing artifact would require refitting or reconstructing selections, stop fail-closed instead.

## Required evidence

Produce a compact summary/review packet plus per-date transition evidence, test receipts, input hashes, and protection counters proving:

- R1 selections were unchanged;
- no fitting path executed;
- validation reads = 0;
- lockbox reads = 0;
- context execution = false;
- Live/model mutation = false.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_SEALED_POINTWISE_PERFORMANCE_R2`

Commit/push only authorized WNBA evidence/code, verify local HEAD == tracking == direct remote, leave clean, preserve the protected stash, report final WNBA SHA, and stop.