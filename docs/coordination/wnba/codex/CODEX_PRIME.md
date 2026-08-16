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

## Active user-authorized task

Execution tier: **R1_ACTIONABILITY_CANARY**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_gate_r1.md`

Work-order publication commit:

`c356db51249a4a4e0c44e6590523f040eee03bac`

Purpose:

**Prove prior-only pointwise + A/B/D regeneration, time-arrow sealing, final-target parity, G1/G2/G3 action interfaces, cache reuse, and measured runtime on a four-target deterministic canary before any replay-scale experiment is considered.**

Expected starting WNBA commit:

`f2e40be6d1beff5db0e6ed1dc178a68d21f9b512`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R0`

Critical constraints:

- four canary targets only;
- first three chronologically eligible G3 targets + final applicable target `2026-08-13`;
- all learned state strictly from `t < D`;
- no gate predicate/threshold/winner selection;
- no full historical replay or 30-date performance result;
- no validation or lockbox;
- no Live/model mutation;
- target runtime <= 15 minutes;
- if resource bound is reached, stop at safe checkpoint rather than silently continuing.

Codex must reconcile this user authorization through the existing `slip-builders` lane before any WNBA mutation or canary execution.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R1`

After completion, do not begin R2/R3, another learner, 4L, or FromDeep automatically. Commit/push the R1 evidence, stop, and return the final WNBA SHA for Chat/user review.
