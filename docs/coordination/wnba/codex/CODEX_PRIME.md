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

Execution tier: **R0_ARTIFACT_AUDIT**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_gate_r0.md`

Work-order publication commit:

`fce39c002ca9196f3070879980d557265896f6f3`

Purpose:

**Audit and formalize a deterministic historical-as-of 3L gate-learning procedure before any replay or fitting is authorized.**

Critical question:

Existing pointwise/V2 LODO outputs must not be assumed time-causal. R0 must determine whether each base signal is reusable as-of, requires t<D regeneration, or is historically unavailable.

Candidate structures to formalize without selecting/tuning a winner:

- G1 cross-arm agreement gate;
- G2 selective pointwise gate;
- G3 pointwise proposal + relational witness gate.

Expected starting WNBA commit:

`bc71d9442580fe69812d6dbad87545006aabdd4e`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_3L_V2_LEARNER_GATE_DECOMPOSITION`

No model fit, historical replay, candidate regeneration, threshold/predicate tuning, validation/lockbox read, 4L/FromDeep work, or Live/model mutation is authorized.

Target runtime: minutes. If fitting/replay or unexpectedly expensive work would be required, stop and report instead of escalating.

Codex must reconcile this user authorization through the existing `slip-builders` lane before any WNBA mutation or diagnostic artifact generation.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R0`

After completion, do not begin R1/R2/R3 automatically. Commit/push the R0 evidence, stop, and return the final WNBA SHA for Chat/user review.
