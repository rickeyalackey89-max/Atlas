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

- **exact selected leg identity** = player + market + tier + side + line; this is the only upstream-depletion unit. Legacy artifact fields named `exact_road` may remain for compatibility but mean exact selected leg identity in this context.
- **signal road** = a conditional evidence bucket/rule such as probability/fragility/minutes/edge conditions. Signal roads are not depleted because one selected leg matched them.

Never perform player-wide depletion or signal-road depletion unless a future explicit contract authorizes it.

## Standing result handoff

For authorized tasks producing permanent repo evidence/code: exact-path stage, commit, push, verify local HEAD == tracking == direct remote, leave clean, and report final SHA + stop marker. Never use broad staging/destructive Git commands or touch the protected stash.

## Last completed delegation

Execution tier: **R0_ARTIFACT_AUDIT**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_residual_leg_supply_coverage_r0.md`

WNBA result commit:

`978cca95d3701737232dc8e507e9a6ba7f04c301`

Accepted Chat review:

- disposition `CURRENT_4L_CANDIDATE_SURFACE_UNDERCOVERS_STRUCTURALLY_LEGAL_RESIDUAL_SUPPLY`;
- 23/23 3+ game discovery slates retained a legal 4L witness after frozen 2L + frozen pointwise-3L exact-selected-leg depletion;
- eight prior zero-materialized dates were candidate-surface coverage gaps: 2026-06-28, 2026-07-09, 2026-07-11, 2026-07-18, 2026-07-30, 2026-07-31, 2026-08-02, 2026-08-07;
- seven true structural abstentions were all sub-three-game slates: 2026-07-03, 2026-07-05, 2026-07-07, 2026-07-12, 2026-07-29, 2026-08-01, 2026-08-08;
- residual eligible-leg supply on 3+ game slates min/median/max = 217/730/1021;
- no outcomes, validation, lockbox, fitting, candidate generation, Live/model mutation, freeze, or promotion;
- WNBA stop `BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`.

Strategic correction:

The old 481-candidate / 15-nonzero-date materialized residual is incomplete and cannot serve as the full current 4L research surface. The old 7-7-1 control and 5-9-1 pointwise result remain scoped evidence on that incomplete surface only. The old 9-5-1 ceiling is withdrawn.

## Active user-authorized task

Execution tier: **R1_ACTIONABILITY_CANARY**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_post_depletion_stateful_generator_r1.md`

Work-order publication commit:

`ec17e06506c7db9ff3e251823677cc3ee9c09dd3`

Purpose:

**Prove that the canonical/current WNBA 4L candidate-construction machinery can run after frozen 2L + frozen 3L exact-selected-leg depletion, generate deterministic legal pretruth candidates on representative coverage gaps, and preserve scoring/contract parity on an existing nonzero control date.**

Expected starting WNBA commit:

`978cca95d3701737232dc8e507e9a6ba7f04c301`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`

Exact canary dates:

- `2026-06-28` — 4-game coverage gap, 229 residual legs;
- `2026-07-09` — 3-game coverage gap, 702 residual legs;
- `2026-08-07` — later 3-game coverage gap, 775 residual legs;
- `2026-06-19` — earliest chronological 3-game existing-nonzero parity/control date, chosen structurally and not by outcome.

Critical constraints:

- stateful order is full outcome-free leg pool -> remove frozen 2L exact selected-leg identities -> remove frozen 3L exact selected-leg identities -> generate 4L candidates;
- reuse canonical/current candidate-construction machinery; do not invent a parallel builder;
- three coverage-gap dates must produce nonzero legal candidate surfaces or emit a precise generator/coverage blocker;
- on 2026-06-19, overlapping exact candidate identities must preserve pretruth scoring semantics and the prior Atlas control candidate must remain representable if its four exact legs remain residual;
- prove deterministic regeneration;
- preserve unchanged 4L structural contract;
- hard generation cap 15 minutes across the four authorized dates; heartbeat if generation itself exceeds 2 minutes;
- no target outcome reads or grading;
- no winner search;
- no pointwise/context/relational/nonlinear learner fitting;
- no signal-road/threshold/gate/feature/hyperparameter tuning;
- no full 23-date generation;
- no patching the eight gaps into the old surface as a final research surface;
- no 4L freeze or promotion;
- no FromDeep;
- validation reads 0;
- lockbox reads 0;
- no Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- no follow-on auto-start.

If canonical generator reuse requires architectural changes, fail closed and report the blocker rather than inventing a replacement inside this R1.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_POST_DEPLETION_STATEFUL_GENERATOR_R1`

Commit/push authorized evidence/code, verify local HEAD == tracking == direct remote, leave clean, preserve protected stash, report final WNBA SHA + stop marker, and stop.

## Next if R1 passes — NOT AUTHORIZED BY THIS TASK

A separately authorized outcome-blind regeneration should rebuild **all 23 eligible 3+ game dates** from the same post-depletion stateful generator so the new 4L surface has one uniform lineage. Do not patch only the eight historical gaps.

Only after that new uniform candidate surface is sealed should discovery truth be opened separately to establish a new Atlas 4L baseline and determine whether a ranking learner is needed. Context-consensus remains parked until then.

## FromDeep agreed architecture

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md` remains the agreed future design. FromDeep is a sparse market-owned Demon-OVER signal specialist built from a discovery-only full scored-leg census, GREEN/RED/GRAY signal roads, bad-road vetoes, probability secondary only, honest abstention, and strict historical-as-of evaluation. Execution remains unauthorized until 4L is resolved.
