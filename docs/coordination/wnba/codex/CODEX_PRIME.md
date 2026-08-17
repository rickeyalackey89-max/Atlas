# WNBA Codex Prime

Status: **NO ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from the dedicated local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before any future execution, the mirror must be a valid clean Git worktree on branch `main` and must be fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** attempt to use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey WNBA `AGENTS.md` and all governing controls required by the active `slip-builders` lane.

This document does not create a second state machine, does not authorize Live/model/promotion changes, and must fail closed on any authority conflict.

## Experiment runway

All 4L / FromDeep research is subject to `docs/coordination/PRIME_EXPERIMENT_RUNWAY.md` and the rule **Cheap runway before long takeoff.**

Execution tiers:

- `R0_ARTIFACT_AUDIT`
- `R1_ACTIONABILITY_CANARY`
- `R2_BOUNDED_PILOT`
- `R3_FULL_EXPERIMENT`

No runway task may auto-escalate.

## Validation doctrine

Public/live slips are operational outputs only and are **never validation, lockbox, promotion, or statistical authority**.

Builder sequence:

`frozen 2L -> frozen 3L -> research/freeze 4L -> research/freeze FromDeep -> protected validation -> final lockbox if methods remain unchanged`.

New unevaluated dates may enter a later protected-evidence inventory only if pregame surface/state can be proven sealed before outcome and their outcomes were not consumed in development.

## Standing result handoff

For authorized tasks producing permanent repo evidence/code: exact-path stage, commit, push, verify local HEAD == tracking == direct remote, leave clean, and report final SHA + stop marker. Never use broad staging/destructive Git commands or touch the protected stash.

## Last completed delegation

Execution tier: **R1_ACTIONABILITY_CANARY**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_historical_asof_pointwise_r1.md`

WNBA result commit:

`fbd986f967c4fb123349ce849bf0f9333ab15d60`

Chat review disposition:

- R1 causal/actionability runway PASSED;
- exact 481-candidate frozen 4L residual preserved;
- all 15 nonzero-residual target dates completed;
- 15 mandatory-abstention dates remained untouched;
- one canonical Atlas cold start on 2026-06-17;
- 14 expected prior-only fitted target states were completed, with cached/frozen-state reuse allowed by the sealed implementation;
- strict `t<D` time arrow passed;
- selections sealed before each target settlement append;
- 12/15 selections differed from canonical Atlas control;
- 14/14 fitted target rankings were nondegenerate;
- causal actionability observed = true;
- wall clock ~5.75 seconds under the 300-second cap;
- aggregate pointwise/control grading, repair/damage interpretation, and performance verdict were intentionally not emitted;
- context features/regeneration were not used;
- validation reads 0; lockbox reads 0;
- no candidate regeneration, FromDeep, Live/model mutation, threshold/gate, or promotion work;
- WNBA stop `BLOCKED_USER_REVIEW_WNBA_4L_HISTORICAL_ASOF_POINTWISE_R1`.

## Current status

No new execution is authorized.

The 4L pointwise selections are now causally sealed and sufficiently nondegenerate to justify a separate cheap performance review. The next candidate task should grade the already-sealed R1 selections against already-consumed discovery truth, compare them with the 7-7-1 canonical control, identify repairs/damages/neutral changes, and decide whether pointwise reaches a practical freeze bar or whether the parked prior-only context variants still merit testing.

That next review should require no learner refit unless a fail-closed integrity check proves an artifact is missing. It must not open validation/lockbox or begin FromDeep automatically.

## FromDeep strategic doctrine for later

After 4L is resolved, FromDeep should be rebuilt as a sparse market-owned Demon-OVER signal specialist rather than a highest-probability leftovers family.

Development should begin from the full eligible scored Demon-OVER leg universe, seal the pretruth surface, then append development settlement and audit what wins/loses and why by market. Candidate roads should be classified from evidence into supported/unsupported/unresolved signal states, with no minimum output count and honest abstention when no supported signal exists. Probability may be a secondary ranking/sanity input only after signal eligibility.

Do not reuse the legacy `builder_from_deep_research.py` development workflow as-is because it mixes discovery + validation evidence when declaring development candidate signals. Protected validation must remain sealed until 2L/3L/4L/FromDeep are frozen.