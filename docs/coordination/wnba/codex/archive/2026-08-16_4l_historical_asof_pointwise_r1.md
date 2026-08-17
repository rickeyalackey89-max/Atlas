# WNBA 4L Historical As-Of Pointwise R1

Execution tier: `R1_ACTIONABILITY_CANARY`

## User-authorized purpose

Run one cheap, deterministic, strict historical-as-of pointwise 4L sequence on the exact frozen post-3L residual surface to prove causal actionability before any performance benchmark, context arm, or broader 4L research is authorized.

This R1 is intentionally cheap. R0 projects the complete causal pointwise topology at roughly 14 production fits / 1–3 minutes, so R1 may execute the complete 15-available-date causal selection sequence while **withholding aggregate performance interpretation** until a separate user-authorized review/next tier.

## Required starting authority

Expected WNBA branch: `builder-method-contract-v1`

Expected starting WNBA commit:

`d6cf1a561e660596cb28d1e2f557290b02b3d4d5`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_4L_POST_POINTWISE_RESIDUAL_R0`

Bind exactly:

- frozen 3L research/depletion receipt;
- R0 pretruth 4L candidate/feature/control ledger;
- R0 pretruth seal;
- R0 current control/supply forensic;
- exact 481-candidate residual inventory and hashes.

The 15 zero-residual dates remain mandatory abstentions and are not learner targets.

## Fixed candidate learner

Use the frozen pointwise architecture as a fixed 4L candidate-ranking hypothesis. Do not tune it.

Features, in this exact order:

1. `component_P`
2. `component_Q`
3. `component_G`
4. `component_V`
5. `component_M`
6. `component_W`
7. `component_S`
8. `component_A`
9. `concentration_penalty`
10. `atlas_slip_score`
11. `joint_qmc_probability`
12. `independent_strict_probability`
13. `minimum_leg_probability`
14. `mean_leg_probability`
15. `minimum_probability_edge`
16. `mean_probability_edge`
17. `minimum_projection_edge`
18. `mean_projection_edge`
19. `expected_net_value_estimate`
20. `expected_net_value_floor`
21. `maximum_minutes_fragility`
22. `maximum_stat_fragility`
23. `slate_game_count`
24. `original_rank_percentile`
25. `atlas_rank_percentile`

Model procedure:

- fold/target-local training medians;
- add a fold/target-local missing indicator only where required by the frozen pointwise semantics;
- `StandardScaler`;
- `LogisticRegression`;
- L2 penalty;
- `C=1.0`;
- `solver=lbfgs`;
- `fit_intercept=true`;
- `max_iter=5000`;
- `random_state=42`;
- date-equal candidate weighting: each prior training date contributes total weight 1 across its gradable binary candidate rows;
- no feature selection, no hyperparameter search, no context features, no threshold/gate.

Selection tie order:

1. predicted pointwise probability descending;
2. Atlas score descending;
3. joint QMC probability descending;
4. minimum leg probability descending;
5. original rank ascending;
6. candidate id lexical ascending.

## Historical as-of time arrow

For every nonzero-residual target date `D`:

`settled eligible 4L candidate history t<D -> build preprocessing/model state -> freeze/hash learner state -> score D pretruth candidates -> freeze/hash selected candidate -> only then permit D development settlement -> append D to history`

No same-date or later-than-D candidate outcome may influence state, preprocessing, fitting, ranking, or selection for `D`.

Mandatory-abstention dates have no target selection and add no 4L candidate training rows.

Cold start:

- use the canonical Atlas control while prior history lacks both positive and negative gradable candidate labels;
- R0 projects 14 production fits after cold start; fail closed and report if the exact legal topology differs.

## R1 actionability outputs

R1 must produce durable, hash-bound evidence sufficient to verify:

- exact target-date list and cold-start behavior;
- exact training-date census for every fitted target;
- all training dates strictly `< D`;
- state/preprocessing hashes per target;
- selected candidate and predicted score/probability per target;
- canonical Atlas control identity for comparison **without grading the comparison in R1**;
- selection seal created before target settlement access;
- selection divergence/churn from canonical Atlas control;
- fit count and runtime by target;
- deterministic completion sentinel and final stop;
- mandatory abstentions unchanged.

R1 may read already-consumed discovery/development truth only in the strict time-arrow order needed to train later dates. It must **not** emit an aggregate pointwise W/L/NB record, beneficial/harmful substitution counts, repair count, success/failure verdict versus the 7-7-1 control, or choose/promote/freeze the 4L method.

The scientific question for R1 is only:

> Can the fixed pointwise learner operate causally on the exact 4L surface, generate nondegenerate selections, and complete within the cheap projected topology?

## Resource runway

Expected production topology: ~14 fits.

Projected wall clock from R0: 1–3 minutes.

Hard R1 wall-clock budget: 5 minutes.

If the runtime bound is reached, stop at the next safe pre-fit checkpoint, preserve completed causal receipts, and report the resource stop. Do not silently continue.

## Forbidden work

R1 does **not** authorize:

- context regeneration or context features;
- aggregate performance comparison or repair/damage interpretation;
- R2/R3 auto-escalation;
- candidate generation/regeneration;
- changing 2L or frozen 3L;
- FromDeep work;
- validation reads;
- lockbox reads;
- public/live slip evaluation authority;
- Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- promotion, installation, or prospective claims.

Validation reads must remain 0.

Lockbox reads must remain 0.

## Governance and Git

Reconcile this exact authorization through the existing WNBA `slip-builders` controller before execution.

After successful authorized work:

- stage exact authorized paths only;
- never use `git add .`, `git add -A`, or `git add --all`;
- do not touch the protected stash;
- commit and push `builder-method-contract-v1`;
- verify local HEAD == tracking ref == direct remote ref;
- leave the WNBA worktree clean;
- report final WNBA SHA.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_HISTORICAL_ASOF_POINTWISE_R1`

Do not begin R2, context regeneration, FromDeep, validation, lockbox, or Live/model work after reaching this stop.
