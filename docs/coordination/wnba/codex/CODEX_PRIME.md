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

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_gate_r0.md`

WNBA result commit:

`f2e40be6d1beff5db0e6ed1dc178a68d21f9b512`

Chat review disposition:

- decision: `ASOF_GATE_PROCEDURE_FEASIBLE_BUT_REQUIRES_BASE_REGENERATION`;
- sealed pretruth candidate/rank and frozen 2L exact-road surfaces are historically reusable;
- stored pointwise and V2 LODO outputs are not causal historical-as-of inputs on 29/30 dates and must be regenerated using only `t < D` history;
- G1/G2/G3 are all feasible under prior-only regeneration;
- no fitting or replay occurred;
- validation reads 0;
- lockbox reads 0;
- no Live/model mutation;
- WNBA stop: `BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R0`.

## Current status

No new execution is authorized.

Recommended next tier is an `R1_ACTIONABILITY_CANARY` that proves prior-only regeneration, time-arrow sealing, cold-start handling, signal variation, and measured runtime on a small deterministic chronological surface before any bounded/full replay is considered.

Do not begin R1/R2/R3, 4L, FromDeep, validation, or lockbox work until a new user-authorized Prime delegation is published here.
