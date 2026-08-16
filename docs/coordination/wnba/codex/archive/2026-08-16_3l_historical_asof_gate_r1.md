# WNBA 3L Historical As-of Gate — R1 Actionability Canary

Status: **USER AUTHORIZED / EXECUTION-READY DELEGATION**

Execution tier: **R1_ACTIONABILITY_CANARY**

Prime Delegation is not WNBA workflow authority. Codex must reconcile this user-authorized task through the existing WNBA `slip-builders` lane and obey WNBA `AGENTS.md`, the active Builder pointer, work order, state, evidence registry, process manifest, Git rules, and protected-data controls.

## Purpose

Prove that the historical-as-of 3L architecture can be regenerated and executed causally on a very small deterministic surface before any replay-scale experiment is authorized.

R1 is an **implementation/actionability canary**, not a performance backtest.

It must answer:

1. Can pointwise and A/B/D states be regenerated using strictly `t < D` settled history?
2. Does the regenerated chronologically final target reproduce the already-stored LODO base behavior when the historical training sets are mathematically identical?
3. Can G1/G2/G3 expose nondegenerate proposals/witnesses at the action interface without selecting a gate predicate?
4. Are shared states cached rather than redundantly refit?
5. What is the measured runtime/fit topology and updated full-sequence cost projection?

## Starting authority

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Canonical local root: `C:\Users\13142\Atlas\WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD / direct remote:

`f2e40be6d1beff5db0e6ed1dc178a68d21f9b512`

Expected starting stop:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R0`

Expected active step:

`builder_s5_3l_historical_asof_gate_r0_user_review`

If branch, HEAD, active Builder state, protected-data counters, or bound authority differs, stop and report. Do not pull/rebase/reset/merge the WNBA repo automatically.

## Bound R0 authority

R0 decision:

`ASOF_GATE_PROCEDURE_FEASIBLE_BUT_REQUIRES_BASE_REGENERATION`

R0 result commit:

`f2e40be6d1beff5db0e6ed1dc178a68d21f9b512`

R0 established:

- sealed pretruth 3L candidate/rank surface is as-of reusable;
- frozen 2L exact-road depletion is reusable with outcome columns excluded from D-time action;
- stored pointwise/V2 LODO predictions are not causal historical-as-of inputs on 29/30 dates;
- pointwise and A/B/D learned states must be regenerated from `H_D = {settled t < D}`;
- chronologically final applicable target `2026-08-13` is the one target where the stored LODO training set is already historical-as-of legal;
- G1/G2/G3 are feasible;
- no gate predicate/threshold/winner was selected at R0.

Use the exact R0 artifact manifest and hashes committed at the starting WNBA SHA. If a bound R0 artifact or its required source input has changed, stop.

## Deterministic canary target set

Do not choose dates using outcomes, prior repair knowledge, or convenience.

The R1 target set is mechanically fixed as:

### Sequential lifecycle probe

The **first three chronologically applicable targets for which G3 is legally eligible under the R0 cold-start contract**.

Resolve these dates from the sealed applicable-date list and record the resolution before fitting.

Process these three targets chronologically. For each target D:

`H_D settled t<D -> regenerate states -> freeze state/proposals/witnesses -> seal canary packet -> only then append D settlement to history for the next canary target`.

Settlement may be appended only to establish the next target's legal history. R1 must not score or compare canary performance, classify beneficial/harmful substitutions, or select a gate rule from these outcomes.

### Final parity/runtime probe

Also regenerate the chronologically final applicable target:

`2026-08-13`

This target is selected by chronology, not outcome. It serves two purposes:

1. worst-case/late-history runtime probe;
2. deterministic parity check because its stored LODO training set contains only dates earlier than D.

Do not use its settlement to choose any gate/predicate.

Total R1 target count: **4**.

## Prior-only pointwise regeneration

Use the existing frozen pointwise algorithm/feature contract only.

For each R1 D:

- training history is strictly `t < D`;
- C remains fixed at `1` as in the existing pointwise contract;
- recompute medians, missing indicators, scaler, coefficients, and any learned preprocessing from H_D only;
- score D's sealed pretruth candidate surface only after state freeze;
- record pointwise proposal candidate ID, Atlas rank, score, incumbent-relative quantity if defined by the frozen interface, exact roads, state hash, and training-date manifest.

No new pointwise feature, hyperparameter, threshold, or confidence rule is authorized.

## Prior-only A/B/D regeneration

Use the existing frozen V2 A/B/D feature/model definitions only.

For each R1 D:

- every training and inner-selection date must be `< D`;
- preserve the existing C grid `{0.1, 1, 10}`;
- any inner C selection must be conducted entirely within H_D;
- recompute learned scaler/model/C-selection state from H_D only;
- do not regenerate V2-C for R1;
- do not run the old V2 override gate;
- do not select an `INF`/finite threshold.

For each of A/B/D record:

- its nominal top ranks-2-to-5 challenger;
- challenger score/margin relative to incumbent;
- chosen C;
- state hash;
- exact prior-only training/inner manifests.

## G1/G2/G3 actionability interfaces

R1 does **not** choose or test a gate predicate.

It only proves that the required action inputs exist causally.

### G1 — cross-arm agreement interface

Expose A/B/D nominal challenger identities and incumbent-relative preferences for each R1 target.

Do not decide how many arms must agree or what score/margin floor should apply.

### G2 — selective pointwise interface

Expose the pointwise proposal and its frozen pregame confidence/margin fields already defined by the frozen pointwise interface.

Do not choose a confidence threshold or KEEP/OVERRIDE rule.

### G3 — pointwise proposal + relational witness interface

Pointwise proposes **who**.

For that exact pointwise-proposed candidate, compute A/B/D witness values versus the Atlas incumbent from the already-regenerated A/B/D states, even when an arm's own nominal challenger is a different candidate.

Record:

- pointwise proposal candidate ID;
- A/B/D nominal challenger IDs;
- A/B/D witness values on the pointwise proposal;
- whether each nominal challenger equals the pointwise proposal;
- signs and magnitudes of witness values;
- no aggregated witness decision.

Do not select a 2-of-3, 3-of-3, all-positive, score-floor, or other witness predicate in R1.

## Final-target parity requirement

For `2026-08-13`, historical-as-of regeneration and stored LODO training sets should be the same date set.

Compare regenerated outputs against the existing stored pointwise and V2 A/B/D base outputs.

Require:

- exact training-date-set equality;
- exact selected C equality for A/B/D where the stored interface records it;
- exact proposal/challenger candidate identity equality;
- exact deterministic tie-order behavior;
- numeric score/probability/margin parity to absolute tolerance `1e-10`, unless an already-governing repository contract is stricter.

Do **not** loosen the tolerance after seeing a mismatch.

If parity fails, disposition must be `R1_FAIL_PARITY` and the task stops. Do not continue into broader regeneration.

## Cache/reuse requirement

Within each D:

- pointwise state is fit once and shared by G2/G3;
- A/B/D states are each fit once and shared by G1/G3;
- G3 witness scoring must not refit A/B/D;
- state/cache keys must bind H_D hash + frozen feature/model contract + source bytes + D.

Report expected fit count versus actual fit count. Duplicate fitting is an R1 failure unless required by the predeclared existing nested C procedure and explicitly accounted for in the topology.

## Nondegeneracy/actionability diagnostics

R1 is not a performance test, but it must identify whether the action surface is mechanically degenerate.

Report, without using settlement to optimize anything:

- any NaN/undefined pointwise proposal or A/B/D witness;
- whether A/B/D witness values are numerically identical across all arms and all four targets;
- whether all A/B/D nominal challenger identities collapse to one identical pattern on all targets;
- whether G3 can score the pointwise proposal when one or more A/B/D arms nominate a different challenger;
- whether pointwise and relational states/proposals change as H_D grows.

Do not create a gate rule from observed variation.

## Time-arrow/sealing proof

For every R1 D create a machine-readable receipt proving:

- max training date `< D`;
- max inner-selection date `< D`;
- no D settlement field was loaded before state/proposal/witness seal;
- state hash frozen before D surface scoring;
- proposal/witness packet hash frozen before settlement append;
- D settlement appended only after seal where needed for the sequential lifecycle probe;
- no future backfill during cold start.

Adversarial tests must fail closed on same-date or future-date contamination.

## Runtime/resource boundary

R1 should remain a cheap canary.

Target wall clock: **<= 15 minutes**.

Record per-target and per-component fit counts/timing.

If R1 reaches 15 minutes without completion, stop at the next safe checkpoint and return `R1_FAIL_RESOURCE_BOUND`; do not silently continue into a long run.

Use the measured canary timings plus the exact R0 arithmetic topology to update projections for:

- full pointwise prior-only sequence;
- full A/B/D prior-only sequence;
- full G1;
- full G3 with shared caches.

No R2/R3 execution may follow automatically.

## Explicitly prohibited

Do not:

- run the complete historical replay;
- compute or report a 30-date G1/G2/G3 win/loss record;
- classify R1 target actions as beneficial/harmful for architecture selection;
- choose/tune an agreement count, witness predicate, score floor, confidence threshold, or gate constant;
- select a winning architecture;
- refit or redesign features;
- add a new learner;
- regenerate candidates or frozen 2L selections;
- open validation or lockbox;
- begin 4L or FromDeep;
- mutate Live/model/minutes/calibration/allocator/QMC/dependence/RC1;
- use BAP-1/BAP-2 statistical rows;
- auto-start R2 or R3.

## R1 dispositions

Return exactly one primary disposition:

- `R1_ACTIONABILITY_CANARY_PASS`
- `R1_FAIL_TEMPORAL_LEAKAGE`
- `R1_FAIL_PARITY`
- `R1_FAIL_DEGENERATE_INTERFACE`
- `R1_FAIL_RESOURCE_BOUND`
- `R1_INCONCLUSIVE`

A PASS means only that causal regeneration/action interfaces work and a larger experiment may be designed. It does not establish profitability or gate superiority.

## Validation/tests

Before execution:

- canonical WNBA guard passes;
- reconcile this authorization through `slip-builders`;
- bind exact authorized paths;
- validation reads = 0;
- lockbox reads = 0.

After execution require:

- Builder lane validator pass;
- method-contract validator pass;
- focused positive tests pass;
- adversarial future-date contamination test passes;
- adversarial same-date-outcome preload test passes;
- final-target parity test passes for a PASS disposition;
- cache reuse/fit-count test passes;
- no full replay/performance-ranking path was invoked;
- validation reads = 0;
- lockbox reads = 0.

## Git

Standing WNBA Git rules remain binding:

- exact-path staging only;
- never `git add .`, `git add -A`, `git add --all`;
- never `git clean`, `git reset --hard`, or force push;
- protected stash untouched.

After validators pass, commit and push authorized WNBA changes and verify local HEAD == tracking ref == direct remote ref. Leave worktree clean.

## Return

Return:

1. starting authority proof;
2. resolved deterministic four-target canary set;
3. bound source/input hashes;
4. pointwise prior-only manifests/state hashes/proposals;
5. A/B/D prior-only manifests/C choices/state hashes/nominal challengers;
6. G3 witness-on-pointwise-proposal packets;
7. strict time-arrow/sealing receipts;
8. `2026-08-13` parity report;
9. expected vs actual fit/cache counts;
10. per-target/component timings;
11. updated full-sequence runtime projection;
12. nondegeneracy/actionability diagnostics;
13. primary R1 disposition;
14. validation reads;
15. lockbox reads;
16. tests/validators;
17. changed paths;
18. final commit SHA and local/tracking/direct-remote equality.

Final stop marker:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R1`
