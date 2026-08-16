# WNBA 3L — Historical As-of Gate R0 Audit

Status: **USER AUTHORIZED / EXECUTION-READY DELEGATION**

Execution tier: **R0_ARTIFACT_AUDIT**

This delegation authorizes only a cheap architecture/time-arrow audit. It does **not** authorize historical replay, model fitting, outer/nested folds, candidate regeneration, threshold selection, validation/lockbox reads, or any Live/model mutation.

Prime Delegation is not WNBA workflow authority. Codex must reconcile this user-authorized task through the existing `slip-builders` lane and obey WNBA `AGENTS.md`, active Builder pointer/work order/state/evidence/process controls. Do not create a second controller.

## User decision

The user and Chat agree that the next serious 3L gate evaluation should use a **historical as-of / walk-forward / prequential procedure** rather than treating a fixed post-hoc rule on the 30 discovery dates as pristine OOS evidence.

For target date `D`, the intended causal sequence is:

```text
all settled information strictly before D
        ↓
train/update learner state using t < D only
        ↓
freeze learner/gate state
        ↓
expose D pregame candidate surface only
        ↓
make and freeze D selection
        ↓
ONLY THEN reveal D settlement
        ↓
append D to history
        ↓
advance to next date
```

The algorithm/procedure may be fixed in advance while its learned state changes through time. No date may use information originating on or after itself to influence its decision.

## Starting WNBA authority

Repository: `rickeyalackey89-max/Atlas-WNBA`

Canonical local root: `C:\Users\13142\Atlas\WNBA`

Branch: `builder-method-contract-v1`

Expected starting HEAD / direct remote SHA:

`bc71d9442580fe69812d6dbad87545006aabdd4e`

Expected active stop:

`BLOCKED_USER_REVIEW_WNBA_3L_V2_LEARNER_GATE_DECOMPOSITION`

Expected active step:

`builder_s5_3l_v2_learner_gate_decomposition_user_review`

If branch, HEAD, active Builder state, or protected authority differs, stop and report. Do not pull/rebase/reset/merge automatically in WNBA.

## Mandatory Prime runway

Read and obey:

`docs/coordination/PRIME_EXPERIMENT_RUNWAY.md`

This task is R0 only. It must end at user review. It may not auto-escalate into R1, R2, or R3.

Target wall-clock: minutes, not hours.

If the audit begins fitting or replaying models, stop as scope violation.

## Statistical authority and truth boundary

Current Builder discovery authority remains:

- 39 discovery dates;
- 30 legal/applicable current-stack 3L dates;
- 1,609 current 3L residual candidates;
- BAP-1/BAP-2 are methodology history only, not current statistical rows;
- validation reads = 0;
- lockbox reads = 0.

Discovery outcomes are already development-consumed. This R0 may inspect already-committed development evidence needed to understand chronology/schema, but it must not open validation or lockbox truth and must not tune a rule from outcome performance.

## Critical temporal-legality question

Do **not** assume existing OOF predictions are valid as-of inputs.

The stored pointwise logistic and V2 relational folds used leave-one-date-out training. Excluding target `D` is not sufficient for historical as-of legality if the fit included dates later than `D`.

For every candidate signal source intended for a future historical-as-of procedure, classify it as one of:

- `ASOF_LEGAL_REUSABLE` — value for D was generated using only information available by D;
- `ASOF_ILLEGAL_FUTURE_TRAINING` — D prediction/model state incorporated later settled dates;
- `ASOF_REGENERATABLE_PRIOR_ONLY` — current stored value is illegal for as-of use but can be recreated from t<D inputs;
- `ASOF_UNAVAILABLE` — required historical state cannot be reconstructed honestly.

This classification is a primary output.

## Candidate architecture family to formalize

Do not select a winner in R0. Formalize the minimum deterministic state/action contract for three related structures:

### G1 — Cross-arm agreement gate

Atlas rank #1 is incumbent. A relational challenger becomes override-eligible only under a predeclared cross-arm agreement state, such as A/B/D challenger identity agreement plus positive incumbent-relative preference. R0 records available signals and chronology only; it must not optimize the predicate on outcomes.

### G2 — Selective pointwise gate

Pointwise proposes the challenger. A deterministic confidence/gate state decides KEEP/OVERRIDE. R0 inventories which pointwise confidence variables are legal as-of and which would require prior-only regeneration. Do not tune a confidence rule.

### G3 — Pointwise proposal + relational witness gate

Pointwise proposes **who**; relational A/B/D provide evidence about **whether Atlas #1 should be challenged**. Relational arms need not necessarily nominate the same candidate unless the future predeclared procedure explicitly requires it. R0 formalizes the state variables and chronology only.

The strategic working hypothesis is that G3 may better match the observed roles of the learners, but R0 has no promotion or selection authority.

## Required R0 audit A — time-arrow contract

Write a precise causal contract for target date `D` defining:

- `H_D`: all settled training history strictly before D;
- `X_D`: D pregame candidate/features available before settlement;
- learner/base-model state computed only from `H_D`;
- gate state computed only from `H_D`;
- selection/action frozen before D settlement;
- D truth unavailable to every fit, scaler, hyperparameter decision, threshold/support rule, confidence statistic, and candidate selection until after selection seal;
- after settlement only, D may append to history for later dates.

Include explicit prohibition on same-date or future-date information.

## Required R0 audit B — source legality matrix

Inventory every existing artifact/field needed for G1/G2/G3 and report:

- source path/artifact;
- field/signal;
- semantic role;
- whether it is pregame/outcome-free;
- how the stored value was generated;
- training date set used, if applicable;
- whether later-than-D dates entered the stored state;
- as-of legality classification;
- exact regeneration requirement if illegal;
- known reconstructability limitations.

At minimum inspect:

- current 3L candidate surface and Atlas ranks;
- pointwise logistic OOF outputs/model procedure;
- V2 A/B/C/D candidate scores, challenger selections, and fitted-procedure contract;
- frozen 2L depletion inputs;
- any scaler/hyperparameter selection procedures on which regenerated signals would depend.

## Required R0 audit C — cold-start contract

Historical as-of evaluation must handle early dates honestly.

Determine, without performance tuning:

- earliest date each base learner could legally fit/update;
- minimum class/support requirements imposed by existing algorithms;
- what happens before sufficient history exists;
- deterministic fallback state, normally Atlas control / insufficient-history abstention;
- whether pointwise and relational arms become eligible on different dates.

Do not backfill future dates to cure cold start.

## Required R0 audit D — adaptive procedure specification

Produce a **procedure blueprint**, not a fitted model.

For each G1/G2/G3 specify:

1. state carried from prior dates;
2. allowed update after each settled date;
3. base proposal generation on D;
4. gate inputs on D;
5. KEEP/OVERRIDE decision interface;
6. selection sealing step;
7. settlement append step;
8. cold-start fallback;
9. deterministic tie handling;
10. evidence/diagnostic outputs required for later audit.

No outcome-derived gate constants may be selected in R0.

## Required R0 audit E — computational topology before any replay

Estimate the cost of an honest prior-only historical replay if later authorized.

For each G1/G2/G3 and each required base learner regeneration path report:

- number of historical target dates;
- number of base learner fits/updates per date;
- whether hyperparameter selection itself requires prior-only inner temporal splits;
- estimated total fit count;
- which results can be cached legally without changing semantics;
- estimated CPU/resource class;
- measured cost of any **non-fitting** parsing/hash/schema audit performed in R0;
- projected R1/R2/R3 wall-clock range.

Do not execute those fits in R0.

If the projected approach resembles the prior V2 hundreds-of-fits topology, identify a cheaper equivalent causal procedure before recommending execution.

## Required R0 audit F — historical-vs-prospective evidence language

Define the exact claims future stages may make:

- fixed/post-hoc discovery rule replay = development-consumed retrospective diagnostic;
- historical as-of replay of a predeclared learning procedure = historical as-of procedural evidence;
- future dates after procedure freeze = prospective evidence;
- untouched validation/lockbox remain separately protected and unopened.

Do not call a newly designed procedure tested on already-viewed discovery history "pristine unseen OOS". Preserve the distinction between causal date-level simulation and meta-level procedure selection from consumed development data.

## Required R0 decision output

Return one of:

- `ASOF_GATE_PROCEDURE_FEASIBLE_CHEAP_REPLAY`
- `ASOF_GATE_PROCEDURE_FEASIBLE_BUT_REQUIRES_BASE_REGENERATION`
- `ASOF_GATE_PROCEDURE_BLOCKED_BY_HISTORICAL_STATE_GAPS`
- `ASOF_GATE_R0_INCONCLUSIVE`

Also classify G1/G2/G3 independently for feasibility and projected cost.

R0 may recommend at most the **next runway tier** (`R1_ACTIONABILITY_CANARY` or `R2_BOUNDED_PILOT`). It may not authorize it.

## Explicitly prohibited

Do not:

- fit/re-fit pointwise logistic;
- fit/re-fit V2 A/B/C/D;
- run historical as-of selections;
- execute an outer/inner fold;
- choose/tune a gate threshold or logical predicate from outcomes;
- regenerate candidates;
- change frozen 2L or 3L control;
- begin 4L or FromDeep;
- open validation or lockbox truth;
- mutate RP24, minutes, allocator, calibration, QMC, dependence, RC1, rolling, maintenance, publication, or Live;
- turn the post-hoc A/B/D consensus pattern into promotion authority;
- launch any task expected to run longer than R0 without a new Prime authorization.

## Expected outputs

Create a compact R0 audit directory under the existing Builder Stage 5 development area with at minimum:

- `THREEL_HISTORICAL_ASOF_GATE_R0_SUMMARY.json`
- `THREEL_HISTORICAL_ASOF_GATE_R0_REVIEW.md`
- `three_leg_asof_signal_legality_matrix.csv`
- `three_leg_asof_cold_start_matrix.csv`
- `three_leg_asof_procedure_blueprints.json`
- `three_leg_asof_compute_topology.csv`
- artifact manifest / hashes.

If useful, add one small static schema/contract validator, but do not add fitting or replay code.

## Control / validation

Before execution:

- canonical WNBA guard passes;
- reconcile this user authorization through `slip-builders` as sole controller;
- bind exact paths and hashes;
- classify machine/evidence stage using the narrowest existing approved non-fitting diagnostic class.

After execution:

- governing Builder lane validator passes;
- method-contract validator passes;
- focused tests/contract checks pass if code was added;
- prove no fitting/replay API was invoked;
- prove validation reads = 0 and lockbox reads = 0;
- prove protected Live/model surfaces unchanged.

## Git

Standing WNBA Git rules remain binding:

- exact-path staging only;
- never `git add .`, `git add -A`, `git add --all`;
- never `git clean`, `git reset --hard`, force push, or protected-stash mutation.

After validators pass, commit and push authorized WNBA changes and verify local HEAD == tracking ref == direct remote ref. Leave worktree clean.

## Return

Return only a compact completion summary with:

1. starting authority proof;
2. elapsed R0 wall-clock;
3. exact input hashes;
4. proof no fit/replay occurred;
5. base-signal temporal legality result;
6. G1/G2/G3 feasibility classification;
7. cold-start findings;
8. projected causal replay topology/cost;
9. recommended next runway tier, if any;
10. validation reads;
11. lockbox reads;
12. tests/validators;
13. changed paths;
14. final WNBA commit SHA;
15. local/tracking/direct-remote equality;
16. final stop marker.

Final stop marker:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R0`
