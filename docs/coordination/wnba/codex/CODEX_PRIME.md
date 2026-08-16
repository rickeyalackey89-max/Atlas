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
- final-date candidate identity, ranking, training-date set, and probabilities reproduced stored legal LODO state within 1e-10;
- both focused test runs passed 10/10;
- validation reads 0;
- lockbox reads 0;
- no relational work, gate tuning, Live/model mutation, or promotion occurred;
- WNBA stop: `BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_POINTWISE_R2`.

## Current status

No new execution is authorized.

The causal pointwise procedure is now the leading 3L research method on historical-as-of procedural evidence. Its 29/30 selection churn with only one damaged control win means Chat/user must first decide whether pointwise itself should become the 3L research backbone before spending ~5.1 hours on relational witness regeneration.

Do not begin relational profiling, G1/G3, a new learner, 4L, FromDeep, validation, lockbox, or Live/model work until a new user-authorized Prime delegation is published here.