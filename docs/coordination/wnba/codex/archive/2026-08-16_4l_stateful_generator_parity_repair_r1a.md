# WNBA 4L Stateful Generator Parity Repair R1A

Execution tier: `R1_ACTIONABILITY_REPAIR`

User authorization: 2026-08-16 — proceed with the parity-harness repair after review of WNBA commit `1e9930253ca3113842a687e188210321424c2d8a`.

## Purpose

Repair **only** the June 19 parity adjudication for the already-completed post-depletion stateful 4L generator R1 canary.

The prior R1 established that the canonical generator produced 96 legal candidates on each authorized date, twice, deterministically, including all three former coverage-gap dates. It stopped at `STATEFUL_4L_GENERATOR_R1_FAIL_PARITY` because the parity harness was mis-specified.

This repair must determine whether the already-sealed R1 generated surface preserves the actual authorized pretruth/context/scorer semantics on the common June 19 candidate identities.

This is **not** authorization to regenerate the four-date canary, generate the 23-date surface, grade candidates, fit a learner, or alter the generator/scorer/context architecture.

## Authority and starting state

Repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA commit:

`1e9930253ca3113842a687e188210321424c2d8a`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_4L_POST_DEPLETION_STATEFUL_GENERATOR_R1`

Bind and preserve the prior R1 evidence. Do not rewrite or delete it.

Key sealed R1 artifacts:

- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_post_depletion_stateful_generator_r1/STATEFUL_4L_GENERATOR_R1_SUMMARY.json`
  - SHA-256 `119ceb18e6d03a63bfdcac76d714480ba12ca63d291f8de7ecc8e75b14d08f2d`
- `.../stateful_4l_candidate_surface.json.gz`
  - SHA-256 `becfb756361c68d5580722ef02094eaea3c658233ac6f8b786fd022856332763`
- `.../stateful_4l_parity_control_2026-06-19.json`
  - SHA-256 `bbb6d1250df589920066e4b9b107d02e2741e7f9c3773b6b5364e3dd72e80c79`

Prior sealed June 19 authority remains the R0 pretruth surface:

- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_post_pointwise_residual_r0/four_leg_candidate_feature_control_pretruth.csv`
  - SHA-256 `d29fd94cada8bd4ba5012b473bb5d55bec3170394e2224076c0a15079218568d`
- `.../FOURL_POST_POINTWISE_RESIDUAL_R0_PRETRUTH_SEAL.json`
  - bind the existing sealed authority exactly.

Validation and lockbox remain unopened.

## Accepted diagnosis from Chat review

The previous `FAIL_PARITY` must not be treated as generator failure without this repair.

Three parity-harness defects were identified:

1. **Context comparison asymmetry.** The previous harness compared the old R0 ledger after canonical context annotation to raw newly generated candidate objects before that annotation. The 324 reported feature mismatches equal 12 common candidates × 27 interaction-context fields and were dominated by expected-value-vs-null comparisons.
2. **Scorer population asymmetry.** `score_family_candidates` is within-pool percentile/midrank based. The old score components were created on the old June 19 candidate pool, while the previous parity harness re-scored only the 12 common candidates and compared those values directly to scores from a different population. That comparison cannot establish scorer drift.
3. **Unauthorized full-set requirement.** The Prime R1 work order explicitly said exact regenerated-set equality was **not required**. The previous parity pass nevertheless required all 16 old June 19 candidates to be represented. R1 observed 12 common identities and the prior canonical Atlas control remained representable.

The repair must remove those adjudication defects without relaxing the actual authorized semantic requirements.

## No new candidate generation

Do not call the canonical generator to produce new research candidate surfaces in this R1A.

Use the already-sealed R1 `stateful_4l_candidate_surface.json.gz` as the new generated-side authority.

Tests may use synthetic fixtures, but no new development-date candidate surface may become evidence in this repair.

## June 19 common-identity contract

Reconstruct the old and new June 19 candidate objects outcome-blind.

- Old side: recover the canonical candidate objects from the same sealed current-stack source lineage used to build the R0 pretruth ledger, including the existing prepared-fresh precedence rule where applicable.
- New side: recover the June 19 candidate objects from the sealed R1 candidate-surface artifact.
- Match by exact four-leg candidate identity, not by outcome.
- The expected observed common-identity census from R1 is 12. If the bound sealed artifacts no longer reproduce that census, fail closed as authority drift.
- Exact set equality with all 16 old candidates is **not** a pass requirement.
- The prior canonical Atlas control candidate must remain representable if its exact four legs remain residual.

## Raw scorer-input parity

Before any context annotation or scoring comparison, compare the actual primitive inputs consumed by the fixed Atlas 4L scorer for each common identity.

At minimum compare, with repository numeric tolerance:

- `mean_leg_probability`
- `minimum_leg_probability`
- `joint_qmc_probability`
- `mean_projection_edge`
- `minimum_projection_edge`
- `expected_net_value_estimate`
- `expected_net_value_floor`
- `mean_probability_edge`
- `minimum_probability_edge`
- `maximum_minutes_fragility`
- `maximum_stat_fragility`
- exact leg identities
- `game_ids`
- `player_keys`
- market / market-family identities used by concentration logic
- any other field demonstrably consumed by `score_family_candidates` for 4L.

Do not compare post-context fields here. Do not invent new scorer inputs.

Any real primitive mismatch is a parity failure and must be itemized by candidate/field.

## Symmetric context-annotation parity

Apply the **same existing canonical context annotation pipeline** to both old and new common candidate objects before comparing context features.

Use the current authoritative functions/semantics already used by the R0 context annotation lineage; do not define a new context formula.

Compare the complete fixed interaction-context feature contract symmetrically, including the 27 existing fields from `INTERACTION_CONTEXT`.

The repair must distinguish:

- annotation missing because the prior harness compared pre-annotation to post-annotation; versus
- a genuine context semantic mismatch after the same annotation function is applied to both sides.

## Symmetric scorer parity

Scorer parity must use the **same candidate comparison population on both sides**.

- Build the old common 12-candidate set.
- Build the new common 12-candidate set.
- Score each complete 12-candidate set with `score_family_candidates(..., family=4, depleted_roads=<same frozen depletion set>)`.
- Compare raw metrics, component availability, effective component weights, P/Q/G/V/M/W/S/A component values, concentration terms, concentration penalty, `ATLAS_SLIP_SCORE`, and final scorer order by matched exact identity.
- `original_candidate_rank` may be reported diagnostically because it is generator-local and is not itself a weighted score component. It must not be silently used to excuse a different final order; if final order differs, isolate whether an exact score tie plus original-rank tie-break is the only cause and fail/report rather than auto-waive.

Do not compare scores produced from different candidate populations.

## Required repair evidence

Write new additive repair evidence under a distinct R1A output root. Do not overwrite the prior R1 evidence.

At minimum emit:

- repair summary and review;
- bound-input/hash receipt;
- common-identity census;
- raw scorer-input parity receipt;
- symmetric context-annotation parity receipt;
- symmetric scorer parity receipt;
- prior-control representability receipt;
- focused implementation/final tests;
- artifact manifest.

Keep evidence outcome-free.

## Explicit prohibitions

Do not:

- generate/regenerate a development-date 4L candidate surface;
- modify `fresh_four_leg_frontier` semantics or candidate depth;
- modify the Atlas scorer formula/weights;
- modify context feature definitions;
- read target outcomes or settlement truth;
- grade candidates/slips or search for winners;
- fit pointwise, context, relational, nonlinear, or other learners;
- tune thresholds, signal roads, gates, features, weights, hyperparameters, or confidence rules;
- generate the full 23-date candidate surface;
- freeze or promote 4L;
- execute FromDeep;
- read validation truth;
- read lockbox truth;
- mutate Live, model, minutes, calibration, allocator, QMC, dependence, or promotion state;
- auto-start follow-on work.

Required reads:

- target outcome reads = 0
- validation reads = 0
- lockbox reads = 0

## Dispositions

Emit exactly one primary disposition:

- `STATEFUL_4L_PARITY_REPAIR_R1A_PASS`
- `STATEFUL_4L_PARITY_REPAIR_R1A_FAIL_RAW_INPUT_PARITY`
- `STATEFUL_4L_PARITY_REPAIR_R1A_FAIL_CONTEXT_PARITY`
- `STATEFUL_4L_PARITY_REPAIR_R1A_FAIL_SCORER_PARITY`
- `STATEFUL_4L_PARITY_REPAIR_R1A_BLOCKED_AUTHORITY_DRIFT`
- `STATEFUL_4L_PARITY_REPAIR_R1A_BLOCKED_RESOURCE`

A PASS means the prior R1 stateful generator canary is methodologically rehabilitated as an actionability pass: deterministic post-depletion generation worked and the common June 19 candidate semantics are parity-safe under a correctly symmetric test.

A PASS does **not** authorize the 23-date regeneration. That remains a separate user/Chat decision.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_STATEFUL_GENERATOR_PARITY_REPAIR_R1A`

After permanent authorized evidence/code changes: exact-path stage only, commit, push, verify local HEAD == tracking ref == direct remote ref, leave clean, preserve the protected stash, report final WNBA SHA + stop marker, and stop.
