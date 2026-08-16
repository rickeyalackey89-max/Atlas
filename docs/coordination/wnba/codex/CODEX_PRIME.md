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

Execution tier: **R1_ACTIONABILITY_CANARY**

WNBA result commit:

`6789f0a595bf3956f42146e8742005febd7cc080`

Chat review:

- causal prior-only pointwise + relational regeneration worked on the first three sealed targets;
- no temporal leakage detected;
- G3 can score a pointwise proposal when relational nominees differ;
- shared caches worked without G3 duplicate refits;
- final target hit the 900-second watchdog before relational parity could complete;
- current A/B/D full causal topology projects to ~5.1 hours;
- full pointwise-only causal sequence projects to ~2.2 minutes;
- therefore relational G1/G3 is not yet authorized.

## Active user-authorized task

Execution tier: **R2_BOUNDED_PILOT**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_pointwise_r2.md`

Work-order publication commit:

`efbf0f494e5d176552f4d07952d191bf76c304a7`

Purpose:

**Run the complete strict historical-as-of pointwise sequence only, using the existing frozen pointwise procedure with learned state regenerated from `t < D` history for every target.**

Expected starting WNBA commit:

`6789f0a595bf3956f42146e8742005febd7cc080`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R1`

Critical constraints:

- pointwise only;
- 30-date applicable ledger with `2026-06-17` cold-start Atlas control and expected 29 pointwise fits thereafter;
- strict `t < D` learned state;
- fixed existing pointwise features / `C=1` / preprocessing / weighting / tie semantics;
- no relational A/B/C/D regeneration;
- no G1/G3;
- no gate/threshold/predicate tuning;
- final-date pointwise parity required;
- hard runtime budget 10 minutes;
- validation reads 0;
- lockbox reads 0;
- no Live/model mutation;
- no promotion authority.

Codex must reconcile this user authorization through the existing `slip-builders` lane before any WNBA mutation or R2 execution.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_POINTWISE_R2`

After completion, do not begin relational profiling, G1/G3, R3, another learner, 4L, or FromDeep automatically. Commit/push the R2 evidence, stop, and return the final WNBA SHA for Chat/user review.