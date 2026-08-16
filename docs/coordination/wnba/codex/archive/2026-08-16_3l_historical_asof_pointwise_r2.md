# WNBA 3L — Historical As-of Pointwise R2

Status: **USER AUTHORIZED / EXECUTION-READY DELEGATION**

Execution tier: **R2_BOUNDED_PILOT**

Prime Delegation is not WNBA workflow authority. Codex must reconcile this user-authorized task through the existing `slip-builders` lane and obey WNBA `AGENTS.md`, the active Builder pointer, work order, state, evidence registry, process manifest, protected Git controls, and the Prime experiment runway.

## User decision

After reviewing R1 commit `6789f0a595bf3956f42146e8742005febd7cc080`, the user authorizes the cheapest scientifically useful next step:

**Run the complete strict historical-as-of pointwise sequence only, before spending on relational regeneration.**

This task asks whether the previously promising pointwise learner survives true `t < D` reconstruction.

It does **not** authorize relational A/B/C/D regeneration, G1/G3, gate tuning, validation, lockbox, Live/model changes, 4L, or FromDeep.

## Starting WNBA authority

Repository: `rickeyalackey89-max/Atlas-WNBA`

Canonical local root: `C:\Users\13142\Atlas\WNBA`

Branch: `builder-method-contract-v1`

Expected starting HEAD / direct remote SHA:

`6789f0a595bf3956f42146e8742005febd7cc080`

Expected active stop:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_GATE_R1`

If branch, HEAD, Builder stop, protected stash, or bound authorities differ, stop and report. Do not pull/rebase/reset/merge the WNBA repo automatically.

## Why this tier is justified

R1 established:

- strict prior-only causal regeneration works on sealed targets;
- no temporal leakage was detected;
- pointwise state can be regenerated independently;
- relational regeneration is currently too expensive for the runway (~5.1 hours projected for A/B/D);
- full pointwise causal regeneration is only 29 fits and was projected around 2.2 minutes from measured R1 rate.

Therefore pointwise is the correct low-cost causal benchmark before any further relational spend.

## Bound methodology

Use the existing frozen pointwise procedure/feature contract from the current pointwise learner. Do not redesign it.

Preserve exactly:

- existing pointwise feature basis;
- fixed `C=1` L2 logistic procedure;
- existing date/candidate weighting semantics;
- existing preprocessing semantics (medians, missing indicators, scaler, feature order);
- existing deterministic tie ordering;
- exact current-stack 3L legal candidate surface;
- frozen 2L exact-road depletion.

The **only scientific change from stored grouped-date OOF is temporal training authority**:

For target date `D`, all learned preprocessing/model state must be fit from settled discovery history strictly satisfying `t < D`.

No later-than-D row may enter any learned state for D.

## Historical as-of time arrow

For every one of the 30 applicable 3L dates, in chronological order:

1. construct `H_D` from settled applicable discovery information strictly before D;
2. if pointwise cold-start requirements are not met, freeze `KEEP_ATLAS_CONTROL_INSUFFICIENT_HISTORY` for D;
3. otherwise fit preprocessing + pointwise logistic using `H_D` only;
4. hash/freeze learned state before scoring D;
5. expose only D's sealed pretruth candidate/rank surface;
6. score D and select the pointwise top candidate using the frozen deterministic procedure;
7. freeze candidate ID, exact roads, score/order, state hash, training-date census/hash, and action before settlement;
8. only after that immutable selection seal may D settlement be opened for grading;
9. append D settlement to history for later targets;
10. advance to the next date.

No future backfill is allowed.

## Cold start

R0 established pointwise earliest legal target = `2026-06-19`.

Thus:

- `2026-06-17`: deterministic Atlas-control cold start, zero pointwise fit;
- every later eligible target: one prior-only pointwise fit when the frozen contract's class-support requirements are satisfied.

Expected full fit count: **29 pointwise fits**.

If the legal fit count differs, stop and explain before interpreting performance.

## Final-date parity requirement

`2026-08-13` is the chronologically final applicable target. For this date, the stored grouped-date LODO training set and strict `t < D` training set should contain the same dates.

Therefore the regenerated pointwise state/output must reproduce the stored pointwise legal LODO behavior under the same frozen algorithm.

Require at minimum:

- exact selected candidate identity parity;
- exact deterministic ranking/tie-order parity;
- prediction/score parity within a predeclared numerical tolerance justified by serialization precision;
- training-date-set parity.

If final-date pointwise parity fails, classify the run as implementation/parity failure and do not interpret aggregate causal performance.

## Explicitly prohibited

Do not:

- regenerate V2-A/B/C/D;
- run relational nested C selection;
- run G1 or G3;
- create a new learner;
- change pointwise features, C, preprocessing, weighting, or tie rules;
- add a confidence threshold or gate;
- tune any rule from target outcomes;
- use stored pointwise LODO predictions as causal predictions for dates where later-than-D training entered state;
- regenerate candidates;
- alter frozen 2L;
- begin 4L or FromDeep;
- read validation or lockbox outcomes;
- mutate RP24, RC1, calibration, minutes, allocator, QMC, dependence, rolling evidence, publication, or Live;
- promote the pointwise learner from this task.

## Runtime/resource bound

This is a low-cost R2 benchmark, not a long experiment.

Hard wall-clock budget for the causal sequence: **10 minutes**.

Requirements:

- checkpoint after every target date;
- record elapsed time and fit count after every target;
- safe stop before starting the next fit if the budget is exhausted;
- no silent continuation past the budget;
- resume must reuse exact sealed target packets/state caches rather than recomputing completed targets.

If runtime materially exceeds the R1 pointwise projection, stop and report the cause rather than broadening or optimizing methodology inside this task.

## Evidence language

The procedure family was designed after discovery evidence was already viewed. Therefore this result is:

`HISTORICAL_ASOF_PROCEDURAL_EVIDENCE`

It is stronger causally than grouped-date LODO for deployment simulation, but it is not pristine never-before-seen hypothesis evidence and has no direct promotion authority.

## Required outputs

Create a compact Stage 5 diagnostic directory for this R2 task, containing at minimum:

- `THREEL_HISTORICAL_ASOF_POINTWISE_R2_SUMMARY.json`
- `THREEL_HISTORICAL_ASOF_POINTWISE_R2_REVIEW.md`
- `three_leg_pointwise_asof_selection_ledger.csv`
- `three_leg_pointwise_asof_transition_ledger.csv`
- `three_leg_pointwise_asof_training_census.csv`
- `three_leg_pointwise_asof_state_hashes.csv`
- `three_leg_pointwise_asof_runtime.csv`
- `three_leg_pointwise_final_date_parity.json`
- per-target time-arrow / selection-seal receipts or an equivalent deterministic index
- artifact manifest / SHA256 hashes
- focused implementation/final test reports.

## Required result metrics

After all per-date selections have been frozen sequentially and graded according to the time arrow, report:

- Atlas control W/L/NB on the same 30-date applicable surface;
- causal pointwise W/L/NB;
- beneficial substitutions;
- harmful substitutions;
- neutral substitutions;
- nonbinary transitions;
- net beneficial minus harmful;
- exact repaired control-loss dates;
- exact broken control-win dates;
- selection churn;
- cold-start count/date;
- fit count;
- measured wall clock;
- final-date parity result.

Use one deterministic primary diagnostic label:

- `POINTWISE_ASOF_POSITIVE_NET` if beneficial - harmful > 0;
- `POINTWISE_ASOF_NEUTRAL_NET` if beneficial - harmful = 0;
- `POINTWISE_ASOF_NEGATIVE_NET` if beneficial - harmful < 0;
- `POINTWISE_ASOF_PARITY_OR_IMPLEMENTATION_FAILURE` if causal/parity requirements fail before scientific interpretation.

Also compare, as clearly labeled historical context only, with the stored grouped-date pointwise result `22-7-1`. Do not imply the two evidence designs are interchangeable.

## Required tests / controls

At minimum prove:

- every trained date for D is `< D`;
- no future settlement enters D-time state;
- `2026-06-17` is cold-start Atlas control;
- expected 29-fit topology is exact on complete execution;
- no relational fitting/import path is invoked;
- no gate/threshold/predicate selection occurs;
- selection seal precedes settlement append for every date;
- completed target caches are deterministic and resumable;
- final-date pointwise parity is exact within declared tolerance;
- validation reads = 0;
- lockbox reads = 0;
- sealed candidate/2L authorities remain unchanged;
- no Live/model mutation occurs.

## Git

Standing WNBA Git rules remain binding:

- exact-path staging only;
- never `git add .`, `git add -A`, `git add --all`;
- never `git clean`, `git reset --hard`, or force push;
- protected stash untouched.

After validators/tests pass, commit and push authorized WNBA changes and verify local HEAD == tracking ref == direct remote ref; leave worktree clean.

## Return

Return only the concise completion packet needed for SHA handoff, including:

1. final WNBA commit SHA;
2. equality/cleanliness proof;
3. primary diagnostic label;
4. causal pointwise W/L/NB and control W/L/NB;
5. repairs / damages / net;
6. final-date parity;
7. fit count and elapsed time;
8. validation reads;
9. lockbox reads;
10. final stop marker.

Final stop marker:

`BLOCKED_USER_REVIEW_WNBA_3L_HISTORICAL_ASOF_POINTWISE_R2`

After completion, do not begin relational profiling, G1/G3, R3, another learner, 4L, or FromDeep automatically.