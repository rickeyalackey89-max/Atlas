# WNBA Codex Prime

Status: **ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from the dedicated local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before execution, the mirror must be a valid clean Git worktree on branch `main` and must be fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** attempt to use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey WNBA `AGENTS.md` and all governing controls required by the active `slip-builders` lane.

This document does not create a second state machine, does not authorize Live/model/promotion changes, and must fail closed on any authority conflict.

## Experiment runway

All 4L / FromDeep research is subject to `docs/coordination/PRIME_EXPERIMENT_RUNWAY.md` and **Cheap runway before long takeoff**. No runway tier may auto-escalate.

## Validation doctrine

Public/live slips are operational outputs only and are **never validation, lockbox, promotion, or statistical authority**.

Builder sequence:

`frozen 2L -> frozen 3L -> research/freeze 4L -> research/freeze FromDeep -> protected validation -> final lockbox if methods remain unchanged`.

## Terminology guardrail

Do not use `road` ambiguously in new 4L evidence.

- **exact selected leg identity** = player + market + tier + side + line; this is the only upstream-depletion unit.
- **signal road** = a conditional evidence bucket/rule such as probability/fragility/minutes/edge conditions. Signal roads are not depleted because one selected leg matched them.

Never perform player-wide depletion or signal-road depletion unless a future explicit contract authorizes it.

## Standing result handoff

For authorized tasks producing permanent repo evidence/code: exact-path stage, commit, push, verify local HEAD == tracking == direct remote, leave clean, and report final SHA + stop marker. Never use broad staging/destructive Git commands or touch the protected stash.

## Last completed delegation

Execution tier: **R1_ACTIONABILITY_REPAIR**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_stateful_generator_parity_repair_r1a.md`

WNBA result commit:

`1f71ec936e7b23a7f537336056eaf4ae4209e9c7`

Accepted Chat review:

- disposition `STATEFUL_4L_PARITY_REPAIR_R1A_PASS`;
- prior stateful-generator R1 is rehabilitated as an actionability pass;
- 12 common June 19 exact candidate identities reproduced;
- raw Atlas scorer-input mismatches = 0;
- symmetric context mismatches = 0 across 324 comparisons;
- symmetric Atlas scorer mismatches = 0;
- final exact-identity scorer-order parity = true;
- prior canonical Atlas control remained representable;
- generator-local original-rank mismatches are diagnostic only and did not alter final scorer order;
- R1A candidate generation = 0;
- target outcome reads = 0; validation reads = 0; lockbox reads = 0;
- no fitting, grading, winner search, tuning, 4L freeze, FromDeep, Live/model/scorer/context-semantic mutation;
- WNBA stop `BLOCKED_USER_REVIEW_WNBA_4L_STATEFUL_GENERATOR_PARITY_REPAIR_R1A`.

## Accepted 4L stateful-generation conclusion

The canonical/current 4L generator can operate deterministically **after** frozen 2L and frozen pointwise-3L exact-selected-leg depletion without semantic drift.

The old 481-candidate / 15-nonzero-date residual is incomplete and must not be used as the final current 4L research authority.

## Active user-authorized task

Execution tier: **R2_BOUNDED_PILOT**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-17_4l_uniform_stateful_candidate_surface_r2.md`

Work-order publication commit:

`df3260c606a4e33f19ee8b5f08ddf29af0284388`

Expected starting WNBA commit:

`1f71ec936e7b23a7f537336056eaf4ae4209e9c7`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_STATEFUL_GENERATOR_PARITY_REPAIR_R1A`

Purpose:

**Build and pretruth-seal one uniform outcome-blind stateful 4L candidate surface across all and only the 23 structurally eligible 3+ game discovery dates.**

Critical constraints:

- derive the 23-date census from sealed residual-supply R0 authority and assert count = 23;
- one uniform lineage across all 23 dates; do not patch only the eight old coverage gaps;
- stateful order is sealed pregame pool -> frozen 2L exact-leg depletion -> frozen pointwise-3L exact-leg depletion -> canonical `fresh_four_leg_frontier` -> canonical context annotation -> canonical Atlas 4L scoring -> pretruth seal;
- exact selected-leg depletion only; no player-wide or signal-road depletion;
- generate each date once; do not double all 23 dates;
- the four prior R1 canary dates (2026-06-19, 2026-06-28, 2026-07-09, 2026-08-07) must reproduce the already-sealed R1 candidate identity/order/scorer hashes under the same bound inputs;
- preserve the full within-date candidate population when Atlas scorer percentile/midrank components are computed;
- seal raw candidates, canonical context annotations, Atlas score ledger, per-date hashes, upstream depletion identities, contract/source hashes, and exact ordered 23-date census before any outcomes are opened;
- no target outcome reads or grading;
- no winner search;
- no learner fitting or context-consensus;
- no signal-road/threshold/gate/feature/hyperparameter/weight/depth tuning;
- no 4L freeze/install/promotion/publication;
- no FromDeep;
- validation reads = 0;
- lockbox reads = 0;
- no Live/model/minutes/calibration/allocator/QMC/dependence/scorer/context-semantic mutation;
- no follow-on auto-start.

Resource contract:

- expected generator calls = 23 single-pass calls;
- learner fits = 0;
- one date in memory at a time;
- expected wall clock roughly 5–10 minutes including evidence overhead;
- hard surface-construction cap = 20 minutes excluding focused tests/lint/validator cleanup;
- heartbeat at least every 3 completed dates or every 2 minutes.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`

Commit/push authorized evidence/code, verify local HEAD == tracking == direct remote, leave clean, preserve protected stash, and report final WNBA SHA + artifact paths + date/candidate census + R1 canary-continuity result + target/validation/lockbox reads + stop marker.

## Next if R2 passes — NOT AUTHORIZED BY THIS TASK

A separate artifact-only forensic may then open **already-consumed discovery truth only** against the sealed uniform 23-date surface to establish the new canonical Atlas 4L baseline and supply/ranking anatomy.

That later forensic must not open protected validation or lockbox and must not automatically launch any learner. Context-consensus remains parked until the new uniform baseline proves ranking research is warranted.

## FromDeep agreed architecture

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md` remains the agreed future design. FromDeep is a sparse market-owned Demon-OVER signal specialist built from a discovery-only full scored-leg census, GREEN/RED/GRAY signal roads, bad-road vetoes, probability secondary only, honest abstention, and strict historical-as-of evaluation. Execution remains unauthorized until 4L is resolved.
