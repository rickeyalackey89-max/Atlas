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

Execution tier: **R1_ACTIONABILITY_CANARY**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_post_depletion_stateful_generator_r1.md`

WNBA result commit:

`1e9930253ca3113842a687e188210321424c2d8a`

Repository disposition:

`STATEFUL_4L_GENERATOR_R1_FAIL_PARITY`

Accepted Chat review:

- canonical `fresh_four_leg_frontier` generated 96 legal candidates on all four authorized dates, twice;
- identity/order/score hashes were deterministic across both passes;
- all three former coverage-gap dates generated nonzero surfaces;
- June 19 had 12 common exact candidate identities out of the 16 old materialized candidates;
- prior canonical Atlas control remained representable;
- target outcome reads 0, validation reads 0, lockbox reads 0;
- no fitting, Live/model mutation, freeze, promotion, or 23-date generation;
- the reported parity failure is **not accepted as generator failure** pending the active parity-harness repair.

## Accepted parity-harness diagnosis

The prior parity adjudication had three methodological defects:

1. It compared old **post-context-annotation** rows against new raw generated rows before the same annotation pipeline was applied. The 324 feature mismatches equal 12 common candidates × 27 fixed interaction-context fields and were dominated by expected-value-vs-null comparisons.
2. It re-scored only the 12 common candidates and compared those percentile/midrank-based Atlas components to old scores produced from a different candidate population. `score_family_candidates` must be compared on the same candidate population on both sides.
3. It required all 16 old June 19 candidates to reappear even though the Prime R1 work order explicitly stated exact-set equality was not required. Common-identity semantic parity plus prior-control representability was the authorized requirement.

Therefore the active repair must adjudicate parity symmetrically without changing generator, scorer, or context semantics.

## Active user-authorized task

Execution tier: **R1_ACTIONABILITY_REPAIR**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_stateful_generator_parity_repair_r1a.md`

Work-order publication commit:

`92004b21338a286e48d0a5c00a18069a886ba268`

Expected starting WNBA commit:

`1e9930253ca3113842a687e188210321424c2d8a`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_POST_DEPLETION_STATEFUL_GENERATOR_R1`

Purpose:

**Repair only the June 19 parity harness using already-sealed R1 candidate evidence and determine whether the stateful generator R1 should be rehabilitated as an actionability pass.**

Critical constraints:

- preserve prior failed R1 evidence; write additive R1A evidence only;
- do **not** generate/regenerate development-date candidate surfaces;
- bind the sealed R1 candidate surface and old R0 pretruth authority exactly;
- reproduce the expected 12 common June 19 exact identities or fail authority drift;
- exact equality with all 16 old materialized candidates is not required;
- compare actual raw Atlas scorer primitives before annotation;
- apply the same canonical context annotation pipeline to both old and new common candidates, then compare the complete fixed interaction-context contract;
- score the complete old common 12-candidate set and complete new common 12-candidate set separately using the same family/depletion semantics, then compare components/scores/final order by exact identity;
- original generator-local rank may be diagnostic only, but may not silently excuse a changed final scorer order;
- prior canonical Atlas control must remain representable;
- no outcomes, grading, winner search, learner fitting, threshold/gate/signal-road tuning, 23-date generation, 4L freeze, FromDeep, validation, lockbox, Live/model mutation, or follow-on auto-start.

Required reads:

- target outcome reads = 0
- validation reads = 0
- lockbox reads = 0

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_STATEFUL_GENERATOR_PARITY_REPAIR_R1A`

After completion, commit/push authorized evidence/code, verify local HEAD == tracking == direct remote, leave clean, preserve protected stash, report final WNBA SHA + stop marker, and stop.

## Next if R1A passes — NOT AUTHORIZED BY THIS TASK

A separately authorized outcome-blind regeneration should rebuild **all 23 eligible 3+ game dates** from the same stateful post-depletion generator so the new 4L surface has one uniform lineage. Do not patch only the eight historical gaps.

Only after that uniform surface is sealed should discovery truth be opened separately to establish the new Atlas 4L baseline and decide whether any ranking learner is needed. Context-consensus remains parked until then.

## FromDeep agreed architecture

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md` remains the agreed future design. FromDeep is a sparse market-owned Demon-OVER signal specialist built from a discovery-only full scored-leg census, GREEN/RED/GRAY signal roads, bad-road vetoes, probability secondary only, honest abstention, and strict historical-as-of evaluation. Execution remains unauthorized until 4L is resolved.
