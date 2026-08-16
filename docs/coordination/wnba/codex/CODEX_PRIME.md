# WNBA Codex Prime

Status: **ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from the dedicated local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before execution, the mirror must be a valid clean Git worktree on branch `main` and must be fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** attempt to use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey the actual WNBA governing controls required by WNBA `AGENTS.md`.

While the WNBA Builder lane is active, `slip-builders` remains the sole workflow controller.

This document:

- does not create a second state machine;
- does not authorize Builder progression outside the exact user-approved task;
- does not authorize Live/model/promotion changes;
- does not convert `CHAT_AGENDA.md` ideas into permission;
- must fail closed if it conflicts with WNBA authority.

## Mandatory experiment runway

All Prime research work must obey:

`docs/coordination/PRIME_EXPERIMENT_RUNWAY.md`

Core rule:

> **Cheap runway before long takeoff.**

Execution tiers:

- `R0_ARTIFACT_AUDIT`
- `R1_ACTIONABILITY_CANARY`
- `R2_BOUNDED_PILOT`
- `R3_FULL_EXPERIMENT`

A runway task may never auto-escalate. Every higher tier requires a separate user-authorized Prime delegation after user/Chat review.

## Standing result handoff protocol

For every Prime-authorized task that creates or changes repository evidence/code and passes required validators/tests:

1. stage only exact authorized paths;
2. commit authorized target-repository changes;
3. push the governing target branch;
4. verify local HEAD == tracking ref == direct remote ref;
5. leave the worktree clean;
6. report final commit SHA and stop marker.

If no permanent repository changes are produced, do not invent a commit.

The preferred user handoff is the final SHA plus a short request for Chat review.

## Last completed delegation

Execution tier: **R2_BOUNDED_PILOT**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_pointwise_r2.md`

WNBA result commit:

`5eb96d83996e3f65c2ce021a5a3897b43f63da04`

Chat review disposition:

- diagnostic: `POINTWISE_ASOF_POSITIVE_NET`;
- strict historical-as-of pointwise result: 24 WIN / 6 LOSS / 0 NONBINARY;
- Atlas control: 20 WIN / 9 LOSS / 1 NONBINARY;
- repaired control losses: 2026-06-20, 2026-07-03, 2026-07-06, 2026-07-31;
- damaged control win: 2026-08-01;
- 2026-06-27 control NONBINARY became pointwise WIN;
- 29/29 expected fits completed in ~10.1 seconds;
- final-date parity passed;
- validation reads 0;
- lockbox reads 0;
- no relational work, gate tuning, Live/model mutation, or promotion occurred;
- WNBA stop: `BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_POINTWISE_R2`.

## Active user-authorized task

Execution tier: **R0_ARTIFACT_AUDIT**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_pointwise_freeze_readiness_r0.md`

Work-order publication commit:

`5549fee8b08aa5adc17b2097c00b2fb7f9a4b093`

Purpose:

**Audit whether causal pointwise is fully specified and deterministic enough for a separate 3L research/depletion freeze decision; characterize the remaining five meaningful failure dates plus the known supply-impossible date; and inventory the exact already-generated 4L residual surface after frozen 2L + causal pointwise 3L exact-road depletion.**

Expected starting WNBA commit:

`5eb96d83996e3f65c2ce021a5a3897b43f63da04`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_POINTWISE_R2`

Critical constraints:

- artifact analysis only;
- no pointwise refit or replay;
- no relational work;
- no gate/threshold/predicate tuning;
- no candidate regeneration;
- no actual 3L freeze/promotion/install;
- no 4L scoring/fitting/settlement optimization;
- exact-road depletion only;
- validation reads 0;
- lockbox reads 0;
- no Live/model mutation;
- target runtime minutes.

Codex must reconcile this user authorization through the existing `slip-builders` lane before any WNBA mutation or diagnostic artifact generation.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_3L_POINTWISE_FREEZE_READINESS_R0`

After completion, do not freeze 3L, begin 4L research, begin relational work, begin FromDeep, open validation/lockbox, or mutate Live/model authority automatically. Commit/push the R0 evidence, stop, and return the final WNBA SHA for Chat/user review.
