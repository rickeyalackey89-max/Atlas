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

- **exact selected leg identity** = player + market + tier + side + line; this is the unit depleted downstream after upstream family selection. Legacy artifact field names such as `exact_road` may remain for compatibility but mean exact selected leg identity in this context.
- **signal road** = a conditional evidence bucket/rule such as probability/fragility/minutes/edge conditions. Signal roads are not depleted because one selected leg matched them.

Never perform player-wide depletion or signal-road depletion unless a future explicit contract authorizes it.

## Standing result handoff

For authorized tasks producing permanent repo evidence/code: exact-path stage, commit, push, verify local HEAD == tracking == direct remote, leave clean, and report final SHA + stop marker. Never use broad staging/destructive Git commands or touch the protected stash.

## Last completed delegation

Execution tier: **R2_BOUNDED_PILOT**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_sealed_pointwise_performance_r2.md`

WNBA result commit:

`b4d85ec3c6d28038831759be502019596c2eb187`

Accepted Chat review:

- pointwise = 5 WIN / 9 LOSS / 1 NONBINARY;
- canonical control = 7 WIN / 7 LOSS / 1 NONBINARY;
- pointwise net wins = -2;
- repaired 2026-08-06 only;
- broke control wins on 2026-06-19, 2026-07-02, and 2026-07-06;
- fixed 25-feature pointwise architecture rejected as a wholesale 4L reranker;
- no validation, lockbox, FromDeep, Live/model mutation, or 4L freeze occurred;
- WNBA stop `BLOCKED_USER_REVIEW_WNBA_4L_SEALED_POINTWISE_PERFORMANCE_R2`.

## 4L supply interpretation correction

The current 481-row residual is an **already-materialized candidate surface**, not proof of all legal post-2L/post-3L combinations available from the underlying scored-leg pool.

The 15 dates with zero materialized 4L candidates must not be called true abstentions until the active R0 proves the underlying residual leg pool cannot construct a legal 4L.

Valid structural classes for this audit are:

- `TRUE_STRUCTURAL_ABSTENTION`
- `CANDIDATE_SURFACE_COVERAGE_GAP`
- `MATERIALIZED_SURFACE_NONZERO`

Sparse 4L output is acceptable when scarcity is real. Sparse output caused by a prematurely narrow materialized candidate surface is not evidence of signal abstention.

The user expects a full three-game WNBA slate to often retain substantial opportunity after only two exact selected 2L legs and three exact selected 3L legs are consumed. Treat that as a diagnostic expectation, **not a forced fill quota**.

## Active user-authorized task

Execution tier: **R0_ARTIFACT_AUDIT**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_residual_leg_supply_coverage_r0.md`

Work-order publication commit:

`7ebd252d26e4996e1840742f8512985d0f952ffe`

Purpose:

**Audit the full underlying post-2L/post-3L residual leg pool outcome-blind, determine legal 4L feasibility by date, and distinguish true structural abstention from current candidate-surface undercoverage before any next learner is fit.**

Expected starting WNBA commit:

`b4d85ec3c6d28038831759be502019596c2eb187`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_SEALED_POINTWISE_PERFORMANCE_R2`

Critical constraints:

- bind frozen 2L and frozen pointwise-3L selected-leg identities exactly;
- remove only exact selected leg identities, never whole players or signal roads;
- reconstruct underlying outcome-free residual scored-leg supply from existing sealed authority;
- derive and report the unchanged 4L structural contract from WNBA authority before feasibility counting;
- classify every audited date as true structural abstention, candidate-surface coverage gap, or nonzero materialized surface;
- separately summarize 3-game-or-larger slates;
- deterministic bounded feasibility search/witnesses only; no expensive exhaustive enumeration required;
- no candidate generation/regeneration;
- no new witness grading or winner search;
- no pointwise/context fitting;
- no thresholds/gates/hyperparameter search;
- no 4L freeze;
- no FromDeep;
- validation reads 0;
- lockbox reads 0;
- no Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- no follow-on auto-start.

Codex must reconcile this authorization through the existing `slip-builders` lane before permanent WNBA evidence generation.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`

After completion, commit/push authorized evidence/code, verify local HEAD == tracking == direct remote, leave clean, preserve protected stash, report final WNBA SHA + stop marker, and stop.

## Candidate context method — PARKED PENDING R0

If and only if the current materialized surface is adequate, the leading ranking candidate remains an Atlas-incumbent prior-only context-consensus challenger:

1. strict settled `t<D` regeneration of the fixed linear and interaction context learners;
2. canonical Atlas control is incumbent;
3. override only if both fixed context learners nominate the same challenger;
4. no threshold tuning;
5. no pointwise participation.

This is not authorized by the active R0.

## FromDeep agreed architecture

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md` remains the agreed future design. FromDeep is a sparse market-owned Demon-OVER signal specialist built from a discovery-only full scored-leg census, GREEN/RED/GRAY signal roads, bad-road vetoes, probability secondary only, honest abstention, and strict historical-as-of evaluation. Execution remains unauthorized until 4L is resolved.
