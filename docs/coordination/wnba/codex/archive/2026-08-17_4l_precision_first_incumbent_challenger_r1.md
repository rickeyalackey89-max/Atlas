# WNBA 4L Precision-First Atlas Incumbent/Challenger R1

Status: **USER AUTHORIZED — R1 ACTIONABILITY / SELECTION-SEAL ONLY**

User authorization in Chat: **“I'm good with this direction.”**

## Purpose

Test one already-agreed conservative 4L architecture without grading it:

> Canonical Atlas rank-1 remains the incumbent. Two fixed strict historical-as-of candidate learners independently nominate one challenger from the same sealed 96-candidate/date R2 surface. Override Atlas only when both learners nominate the exact same non-incumbent candidate. Otherwise KEEP_ATLAS.

This is **not** a wholesale reranker and **not** a performance test. R1 only proves the causal machinery, actionability, determinism, and exact pre-outcome selection ledger. A later R2 may grade the sealed R1 selections only after separate user authorization.

## Starting authority

Canonical WNBA branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`cd645ed1fdfe857ec2b84f21a9653e6c2977de2a`

Current Builder stop:

`BLOCKED_USER_REVIEW_WNBA_4L_INCUMBENT_VS_FIRST_WINNER_FORENSIC_R0`

Accepted 4L controls:

- uniform R2 surface commit `fd0df85a70559d830cd2ae5e76a711453a9f4dca`;
- 23 eligible 3+ game dates;
- 2,208 candidates = 96/date;
- canonical Atlas control `14 WIN / 8 LOSS / 1 NONBINARY`;
- winner available 23/23;
- no-winner dates 0;
- incumbent-vs-first-winner forensic commit `cd645ed1fdfe857ec2b84f21a9653e6c2977de2a`.

The latest forensic **justifies trying this pre-existing architecture only**. It may not choose R1 features, thresholds, challenger depth, or override rules.

## Experiment tier

`R1_ACTIONABILITY_SELECTION_SEAL`

Cheap-runway requirement applies. No auto-escalation to performance grading.

## Scientific architecture — frozen before execution

### 1. Target surface

Use all and only the exact 23 sealed R2 dates and their exact 96 frozen candidates/date.

Do not regenerate, rescore, rerank, prune, expand, or top-K filter the target candidate surface.

Challenger universe = the full sealed 96-candidate target-date surface.

### 2. Strict historical-as-of time arrow

For every target date `D` in chronological order:

`fully settled development candidates from dates t<D -> fit both fixed learners -> freeze learner states -> score the sealed 96 candidates for D -> freeze both nominees -> apply exact-consensus rule -> seal selected candidate for D -> only then may D development labels become available for later dates`.

Same-date target outcomes may never influence either learner fit, target ranking, nominee identity, consensus, or selected candidate.

The execution receipt must prove the strict `t<D` census for every fitted target.

### 3. Fixed R1 feature contract

Do **not** feature-mine from the eight observed Atlas losses or from recurrence directions in the completed forensic.

Before the first fit, recover and seal the **entire numeric outcome-free feature-name surface already admitted by the completed incumbent-vs-first-winner forensic feature contract**:

- source namespaces: sealed R2 `score` and canonical R2 `annotation` fields only;
- use every numeric feature admitted by that forensic's deterministic feature-name contract;
- preserve its existing excluded-name token contract (`candidate_id`, `date`, `exact_road`/identity aliases, player/name, rank, outcome/settlement/truth/target/realized/row-id aliases);
- no feature may be added, removed, weighted, screened, selected, or reordered because of forensic outcome values;
- categorical features are excluded from R1 learner fitting; numeric composition/context counts already present remain eligible under the same deterministic contract.

Write one feature-contract artifact containing the exact ordered feature list and SHA-256 **before any learner fit**.

If the exact deterministic numeric feature contract cannot be reconstructed from the sealed R2 artifacts + completed forensic implementation/receipt without consulting target outcomes, stop fail-closed:

`BLOCKED_USER_REVIEW_WNBA_4L_CHALLENGER_R1_FEATURE_CONTRACT_UNRESOLVED`

Do not substitute a hand-selected G/Q/S, probability, EV, fragility, or other post-hoc list.

### 4. Training labels

Training labels may use only development-consumed dates `t<D`.

For R2-generated combinations absent from older candidate-ID truth, use the already-accepted immutable exact-selected-leg settlement adapter against sealed discovery leg truth. Do not use mutable raw season truth.

Binary candidate label:

- `1` = all four exact selected legs settle WIN;
- `0` = fully supported binary candidate with at least one LOSS;
- NONBINARY / unsupported candidate outcomes are excluded from learner fitting.

Use all gradable training candidates from each prior date.

Date equal weighting: each prior date contributes total sample weight `1.0`, divided evenly among its gradable candidates.

### 5. Shared preprocessing

For each target fold independently and using training `t<D` only:

- numeric feature order = sealed R1 feature contract;
- training median imputation per feature;
- add one missingness indicator only for features with missing training values;
- `StandardScaler` fit on training only;
- no target-date distribution statistic may influence preprocessing.

### 6. Learner A — LINEAR

Fixed estimator:

- `LogisticRegression`;
- penalty `l2`;
- `C=1.0`;
- solver `lbfgs`;
- `fit_intercept=True`;
- `max_iter=5000`;
- `random_state=42` where accepted by installed sklearn;
- sample weights = date-equal weights above.

No hyperparameter search.

### 7. Learner B — INTERACTION

Use the identical sealed numeric base feature contract and preprocessing semantics, with one deterministic expansion only:

`PolynomialFeatures(degree=2, interaction_only=True, include_bias=False)`

Then `StandardScaler` and the exact same `LogisticRegression` specification as Learner A.

No interaction screening, pruning, threshold search, feature selection, or hyperparameter search.

### 8. Cold start / fit impossibility

If a target date has no legal prior training history, fewer than two binary outcome classes, or either fixed learner cannot fit faithfully under the frozen contract:

`KEEP_ATLAS_CONTROL`

Record the exact reason. Do not invent fallback learners.

### 9. Nomination and tie-break

Each learner ranks all 96 target candidates by its predicted candidate-win probability descending.

Tie-break, in order:

1. frozen Atlas final scorer rank ascending;
2. frozen `ATLAS_SLIP_SCORE` descending;
3. frozen raw `joint_qmc_probability` descending;
4. candidate id lexical ascending.

Each learner nominates exactly its rank-1 candidate when fitted.

### 10. Precision-first consensus rule

Let `A_D` be canonical Atlas rank-1 for date `D`.

- If both fitted learners nominate the **exact same candidate id** `C_D` and `C_D != A_D`, select `C_D` and mark `CONSENSUS_OVERRIDE`.
- Otherwise select `A_D` and mark `KEEP_ATLAS`.
- Cold-start / fit-impossible target = `KEEP_ATLAS`.

No probability-margin threshold. No score threshold. No confidence threshold. No top-K rule. No incumbent-weakness threshold. No hand-written signal road.

The only R1 override gate is **exact nominee identity consensus** between the two fixed learners.

## R1 outcome boundary

R1 is selection/actionability evidence only.

Permitted:

- prior development labels `t<D` for fitting;
- after a target selection is sealed, that date's development labels may become training history for later targets.

Prohibited:

- computing or reporting R1 selected WIN/LOSS/NONBINARY record;
- counting beneficial/harmful overrides;
- comparing R1 selected outcomes to Atlas outcomes;
- inspecting whether a nominee/override won on its own target date for R1 conclusions;
- validation or lockbox access.

The selection ledger must be fully sealed before any separate R2 performance operation exists.

## R1 required outputs

Seal and report:

1. exact ordered 23-date census;
2. R1 feature-contract artifact + hash;
3. per-date strict `t<D` training-date/member/candidate census;
4. per-date preprocessing/learner-state hashes;
5. Learner A nominee candidate id + frozen Atlas rank;
6. Learner B nominee candidate id + frozen Atlas rank;
7. exact nominee-consensus boolean;
8. final R1 selected candidate id;
9. action `KEEP_ATLAS`, `CONSENSUS_OVERRIDE`, or cold-start keep reason;
10. selected-candidate seal covering all 23 dates;
11. total learner fit count;
12. linear/interaction nondegenerate ranking count;
13. exact-consensus override count;
14. KEEP_ATLAS count;
15. nominee Atlas-rank distributions;
16. measured runtime and projected/actual resource class;
17. same-date target-outcome-before-selection reads = 0;
18. validation reads = 0;
19. lockbox reads = 0.

Do **not** include target-date performance.

## Actionability interpretation

R1 can establish only whether the fixed architecture is causal, deterministic, nondegenerate, computationally bounded, and capable of producing a sealed override surface.

- `0` consensus overrides is a valid finding and normally makes R2 unnecessary.
- nonzero consensus overrides permit Chat/user to decide whether a separate R2 grading is worth spending development outcome attention on.
- override count itself is not a performance gate and must not be tuned.

## Resource contract

Expected maximum fits: approximately `2 × (23 - cold_start_dates)`; normally <=44 learner fits.

Before full execution, time the first four legal learner fits without changing the method. If projected total wall clock exceeds 15 minutes, stop at resource review with no R1 performance authority and report the measured topology. Do not silently continue a long run.

No multi-hour execution is authorized.

## Hard prohibitions

- no wholesale reranker;
- no target-date outcome leakage;
- no feature mining from the eight forensic losses;
- no G/Q/S-only handcrafted feature list;
- no threshold or margin tuning;
- no hyperparameter search;
- no candidate top-K restriction;
- no candidate generation/rescoring/Atlas reranking;
- no validation;
- no lockbox;
- no FromDeep;
- no 4L freeze/install/promotion;
- no Live/model/minutes/calibration/allocator/QMC/dependence mutation;
- no public-slip evaluation authority;
- no follow-on R2 auto-start.

## Git and governance

Use the canonical WNBA worktree and current Builder controller. This is **not** a `SEALED_ARTIFACT_FORENSIC` because fitting is authorized; normal non-fast-path Builder governance applies.

Exact-path staging only. Never broad-stage or touch the protected stash.

Commit/push authorized R1 implementation/evidence, verify local HEAD == tracking == direct remote, leave clean, and report final WNBA SHA.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_PRECISION_FIRST_CHALLENGER_R1`

No R2 performance grading, 4L freeze decision, or FromDeep task may auto-start from this work order.
