# WNBA Codex Prime

Status: **NO ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from the dedicated local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before any future execution, the mirror must be a valid clean Git worktree on branch `main` and must be fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** attempt to use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey the actual WNBA governing controls required by WNBA `AGENTS.md`.

While the WNBA Builder lane is active, `slip-builders` remains the sole workflow controller.

This document:

- does not create a second state machine;
- does not authorize Builder progression on its own;
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

Execution tier: **R0_ARTIFACT_AUDIT**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_pointwise_freeze_readiness_r0.md`

WNBA result commit:

`64ac175dc1a2ec75f39fa5f9f91af4caed711fc2`

Chat review disposition:

- `POINTWISE_3L_RESEARCH_FREEZE_READY` accepted as advisory readiness;
- causal pointwise procedure is fully specified, deterministic, hash-bound, and suitable for a separate research/depletion freeze decision;
- remaining failures: Jul07/Jul28/Aug08/Aug13 `TOP_RANK_DISCRIMINATION`, Aug01 `ALREADY_CORRECT_CONTROL_DAMAGE`, Jul08 `SUPPLY_IMPOSSIBLE`;
- exact post-2L + post-pointwise-3L 4L residual contains 481 unique already-generated candidates across 30 dates;
- 15/30 dates have zero legal 4L residual candidates;
- residual inventory SHA-256: `5500a88c5d14c3a2e6d5f043decc1d88500678986035bce8a431560ac343bd09`;
- no 3L freeze was executed;
- no 4L scoring/fitting/grading occurred;
- validation reads 0;
- lockbox reads 0;
- no Live/model mutation;
- WNBA stop: `BLOCKED_USER_REVIEW_WNBA_3L_POINTWISE_FREEZE_READINESS_R0`.

## Current status

No new execution is authorized.

Recommended next decision is a **separate explicit user authorization** to freeze causal pointwise as the working 3L research/depletion method and then open 4L research on the exact 481-candidate residual inventory. The prior 4L diagnostic surface is not current authority because exact pointwise 3L depletion materially changes availability and leaves 15 zero-residual dates.

Do not execute the 3L freeze, begin 4L research, begin relational work, begin FromDeep, open validation/lockbox, or mutate Live/model authority until a new user-authorized Prime delegation is published here.
