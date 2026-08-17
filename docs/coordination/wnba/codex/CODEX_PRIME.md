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

Execution tier: **R0_ARTIFACT_AUDIT**

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_4l_residual_leg_supply_coverage_r0.md`

WNBA result commit:

`978cca95d3701737232dc8e507e9a6ba7f04c301`

Chat review disposition:

- `CURRENT_4L_CANDIDATE_SURFACE_UNDERCOVERS_STRUCTURALLY_LEGAL_RESIDUAL_SUPPLY` accepted;
- 30 dates audited outcome-blind;
- 23 dates were 3+ game public-4L-eligible slates;
- every one of those 23 dates had a legal residual 4L witness after frozen 2L + frozen pointwise-3L exact-selected-leg depletion;
- 15 dates had nonzero materialized 4L candidate surfaces;
- 8 prior zero-materialized dates were reclassified as `CANDIDATE_SURFACE_COVERAGE_GAP`;
- 7 prior zero-materialized dates were confirmed `TRUE_STRUCTURAL_ABSTENTION`, all because the slate had fewer than 3 games under the unchanged public 4L family contract;
- the 8 coverage-gap dates are 2026-06-28, 2026-07-09, 2026-07-11, 2026-07-18, 2026-07-30, 2026-07-31, 2026-08-02, 2026-08-07;
- the 7 true structural abstention dates are 2026-07-03, 2026-07-05, 2026-07-07, 2026-07-12, 2026-07-29, 2026-08-01, 2026-08-08;
- residual structurally eligible leg supply on 3+ game slates was min/median/max 217/730/1021;
- no outcome, validation, or lockbox reads; no fitting, candidate generation, Live/model mutation, freeze, or promotion;
- WNBA stop `BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`.

## Strategic correction after R0

The prior 481-candidate materialized residual is not an adequate current 4L research surface.

The old 15-date control result (7-7-1) and pointwise result (5-9-1) remain valid only as evidence on that incomplete materialized surface. They do **not** define a complete 4L opportunity denominator, and the previously discussed 9-5-1 learned-method ceiling is withdrawn because eight structurally legal 3+ game dates were absent from the materialized candidate surface.

The correct eligible slate denominator for current 4L discovery research is now structurally 23 dates, with seven sub-three-game dates as true family-contract abstentions. Legal feasibility does not imply quality signal or mandatory publication.

## Candidate next architecture — NOT AUTHORIZED

The current candidate next step is a tiny **post-depletion stateful 4L candidate-generator R1 canary**, before any ranking learner.

Core architecture:

1. frozen 2L selection occurs;
2. remove only its exact selected leg identities;
3. frozen causal pointwise 3L selection occurs from the residual pool;
4. remove only its exact selected leg identities;
5. only then invoke the canonical/current 4L candidate-construction machinery on the remaining scored-leg pool;
6. preserve the unchanged 4L structural contract and pretruth scoring semantics;
7. do not use outcomes to generate, filter, rank, or select candidates.

Do not merely append replacement candidates to the eight gap dates. If the canary passes, the next full surface should regenerate one uniform post-depletion 4L candidate surface for **all 23 eligible 3+ game dates** so the research surface has one consistent lineage.

Suggested R1 canary dates are selected only for structural/resource diversity, not outcomes:

- `2026-06-28`: 4-game coverage-gap date, 229 residual structurally eligible legs;
- `2026-07-09`: 3-game coverage-gap date, 702 residual legs;
- `2026-08-07`: later 3-game coverage-gap date, 775 residual legs;
- plus one existing nonzero 3-game parity/control date to verify the stateful invocation does not silently change the family contract or scoring semantics.

R1 purpose should be to identify/reuse the canonical candidate generator, prove it can operate after upstream depletion, emit deterministic nonzero legal candidate surfaces on the gap canaries, preserve contract/parity on the nonzero control date, and measure runtime/resource topology.

No outcome grading, signal-road tuning, context learner, pointwise rerank, validation, lockbox, FromDeep, Live/model mutation, freeze, or promotion belongs in that canary.

After a successful canary, a separately authorized full outcome-blind regeneration should build the uniform 23-date stateful 4L candidate surface. Only then should discovery truth be opened in a separate step to establish the new canonical Atlas 4L baseline and supply/ranking anatomy. Context-consensus ranking remains parked until that new baseline exists.

## FromDeep agreed architecture

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md` remains the agreed future design. FromDeep is a sparse market-owned Demon-OVER signal specialist built from a discovery-only full scored-leg census, GREEN/RED/GRAY signal roads, bad-road vetoes, probability secondary only, honest abstention, and strict historical-as-of evaluation. Execution remains unauthorized until 4L is resolved.
