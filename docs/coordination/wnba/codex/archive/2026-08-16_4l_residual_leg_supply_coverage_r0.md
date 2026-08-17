# WNBA 4L Residual Leg Supply + Candidate Coverage R0

Execution tier: **R0_ARTIFACT_AUDIT**

Status: **USER AUTHORIZED**

## Purpose

Before any further 4L learner/context experiment, determine whether the apparent 4L scarcity is real underlying leg-supply scarcity or an artifact of the already-materialized 4L candidate surface.

The current post-2L/post-3L 4L inventory contains 481 materialized candidates and 15 dates with zero materialized candidates. Those zero dates are **not yet proven true 4L abstentions**.

This audit must inspect the underlying sealed pregame leg surface after frozen upstream selection depletion and classify the actual source of 4L scarcity without generating new candidates or using outcome quality.

## Terminology — mandatory

Do not use the word `road` ambiguously in new evidence.

For this task:

- **exact selected leg identity** = the specific selected leg identity historically represented by fields such as `exact_road`, i.e. player + market + tier + side + line under the canonical identity contract;
- **signal road** = a conditional signal bucket/rule such as probability/fragility/minutes/edge conditions. Signal roads are **not depleted** merely because one selected leg matched them.

Frozen family depletion removes only exact selected leg identities selected upstream. It does **not** remove:

- the entire player;
- all props for that player;
- all lines/tiers/sides for the market;
- a signal road/bucket.

If legacy WNBA artifacts/code use the field name `exact_road`, preserve compatibility but label it in the R0 report as a legacy alias for **exact selected leg identity**.

## Starting authority

WNBA repository:

`rickeyalackey89-max/Atlas-WNBA`

Branch:

`builder-method-contract-v1`

Expected starting WNBA HEAD:

`b4d85ec3c6d28038831759be502019596c2eb187`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_4L_SEALED_POINTWISE_PERFORMANCE_R2`

Upstream research state:

- 2L remains frozen;
- 3L pointwise is frozen for research/depletion only at `2b1fca797eebefdb0da190099681460f22036eb1`;
- 3L development evidence remains 24-6-0 historical-as-of procedural evidence;
- 4L pointwise wholesale reranker is rejected by R2 at `b4d85ec3c6d28038831759be502019596c2eb187`;
- context-consensus ranking remains parked pending this supply audit;
- FromDeep execution remains unauthorized;
- validation reads = 0;
- lockbox reads = 0.

Known current materialized 4L residual inventory:

- 481 unique candidates;
- 30 represented dates;
- 15 dates with nonzero materialized candidates;
- 15 dates with zero materialized candidates;
- inventory SHA-256 `5500a88c5d14c3a2e6d5f043decc1d88500678986035bce8a431560ac343bd09`.

## Hard authority and safety boundary

Before acting, read and obey WNBA `AGENTS.md` and all existing controls required by the active `slip-builders` lane.

Reconcile this task through the existing Builder controller. Do not create a parallel state machine.

Git safety remains unchanged:

- never `git add .`, `git add -A`, or `git add --all`;
- never `git clean`, `git reset --hard`, force push, or rewrite the protected stash;
- exact-path staging only;
- protected stash must remain untouched.

## Phase A — bind the exact upstream depletion state

Recover and hash-bind the authoritative frozen upstream selected-leg identities for every legally reachable 4L discovery date:

1. exact selected leg identities from frozen 2L;
2. exact selected leg identities from frozen causal pointwise 3L;
3. the current sealed pregame/scored-leg surface from which 4L could legally draw.

Fail closed if the exact upstream selected identities cannot be deterministically reconstructed from authoritative artifacts.

Do **not** infer depletion from player identity or signal-road membership.

## Phase B — reconstruct the residual leg pool, not the old 4L candidate list

For each date legally reachable by 4L under the unchanged family contract:

1. start from the authoritative outcome-free scored/pregame leg surface available to Builder research;
2. remove only exact selected leg identities consumed by frozen 2L and frozen 3L;
3. apply the unchanged 4L family structural eligibility contract required at selection time;
4. do not apply any new quality threshold, context rule, learner score, post-hoc winner knowledge, or signal-road veto;
5. preserve every other distinct legal leg, including other markets/tiers/sides/lines for an upstream-used player if the family contract otherwise allows that leg.

Before counting, record the exact authoritative 4L structural constraints discovered from WNBA authority. Do not invent or relax them in Prime.

## Phase C — prove feasibility and candidate-surface coverage

For every audited date, emit at minimum:

- game date;
- slate game count;
- pre-depletion eligible leg count;
- count of exact 2L selected leg identities removed;
- count of exact 3L selected leg identities removed;
- post-depletion eligible leg count;
- post-depletion unique player count;
- post-depletion distinct game count;
- post-depletion market/tier/side counts needed to explain structural feasibility;
- current already-materialized 4L candidate count;
- whether at least one legal 4L can be constructed from the residual leg pool under the unchanged contract;
- a deterministic legal witness combination when feasible;
- reason code when infeasible.

Do not spend hours exhaustively enumerating the combinatorial space. The R0 question is primarily **zero versus nonzero legal feasibility and coverage diagnosis**. A deterministic bounded search/backtracking procedure may stop after proving feasibility and may optionally emit a small bounded witness set. If exact combination counting is trivially cheap, it may be included, but it is not required.

## Required date classification

Every date must receive exactly one structural supply classification:

- `TRUE_STRUCTURAL_ABSTENTION`
  - the residual underlying leg pool cannot form any legal 4L under the unchanged family contract;

- `CANDIDATE_SURFACE_COVERAGE_GAP`
  - at least one legal 4L is feasible from residual underlying legs, but the already-materialized 4L candidate count is zero;

- `MATERIALIZED_SURFACE_NONZERO`
  - the already-materialized surface contains at least one 4L candidate; report underlying residual feasibility alongside it.

Do **not** call any date `SIGNAL_ABSTENTION` in this R0. Signal quality has not been tested here.

## Full-slate diagnostic emphasis

The user expects that a full three-game WNBA slate, after consuming only two exact 2L legs and three exact 3L legs, will often still contain substantial underlying 4L opportunity across the remaining scored-leg/player surface.

Treat that as a **diagnostic expectation, not a forced output quota**.

The report must therefore separately summarize 3-game-or-larger slates:

- number of such dates;
- median/min/max residual eligible leg count;
- median/min/max residual unique player count;
- count with legal 4L feasibility;
- count with zero materialized candidates despite legal feasibility;
- count of genuine structural abstentions and exact reasons.

If only a small number of full slates are feasible, explain the structural blocker from the data/contract. Do not manufacture candidates to satisfy the expectation.

## Outcome boundary

This is a supply/coverage audit, not a performance test.

- no target outcome is needed to establish legal 4L feasibility;
- do not grade newly discovered witness combinations;
- do not search for winners;
- do not use settlement to decide which legs or combinations are legal;
- already-consumed R0/R2 result labels may remain referenced only as provenance, not as an input to the feasibility search.

## Prohibited execution

This task does **not** authorize:

- 4L candidate generation/regeneration for research or runtime;
- exhaustive combination generation as a surrogate candidate expansion;
- context fitting/regeneration;
- pointwise fitting/refitting;
- threshold/gate/hyperparameter search;
- 4L performance grading beyond already-existing provenance;
- 4L freeze;
- FromDeep execution;
- validation reads;
- lockbox reads;
- Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- promotion authority.

## Required artifacts

Write a deterministic R0 packet under a new directory such as:

`data/wnba/bap2_work/builder_stage_5/current_atlas_4l_residual_leg_supply_coverage_r0/`

At minimum include:

1. `FOURL_RESIDUAL_LEG_SUPPLY_COVERAGE_R0_SUMMARY.json`
2. `FOURL_RESIDUAL_LEG_SUPPLY_COVERAGE_R0_REVIEW.md`
3. `four_leg_residual_leg_supply_by_date.csv`
4. `four_leg_zero_materialized_date_classification.csv`
5. `four_leg_legal_witnesses.csv` or equivalent bounded witness artifact
6. input/hash receipt
7. artifact manifest
8. focused tests/validator evidence required by WNBA controls.

The summary must explicitly state:

- counts of `TRUE_STRUCTURAL_ABSTENTION` versus `CANDIDATE_SURFACE_COVERAGE_GAP`;
- how many of the prior 15 zero-materialized dates were reclassified as coverage gaps;
- 3-game-or-larger slate summary;
- whether the 481-candidate surface is adequate for the next ranking test or whether bounded candidate-surface expansion must be considered first;
- `validation_reads: 0`;
- `lockbox_reads: 0`;
- `candidate_generation_executed: false`;
- `learner_fitting_executed: false`.

## Interpretation rule

Possible advisory dispositions include:

- `CURRENT_4L_SURFACE_SUPPLY_ADEQUATE_FOR_CONTEXT_RANKING`
- `CURRENT_4L_SURFACE_UNDERCOVERS_LEGAL_RESIDUAL_SUPPLY`
- `MIXED_4L_SUPPLY_LIMITATION_REQUIRES_USER_REVIEW`

These are advisory only. Do not auto-start candidate expansion or context ranking.

## Required stop

`BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`

After completion:

- exact-path stage only;
- commit and push authorized WNBA evidence/code;
- verify local HEAD == tracking ref == direct remote ref;
- leave WNBA clean;
- preserve protected stash;
- report final WNBA SHA + stop marker;
- stop.
