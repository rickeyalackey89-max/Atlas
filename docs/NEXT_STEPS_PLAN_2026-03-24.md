# Next Steps Plan

Date: 2026-03-24
Repo: Atlas
Primary source notes: `AtlasGoalsDoc.txt`, `docs/ATLAS_MODEL_CONTEXT.md`, `docs/REPLAY_BACKTEST_EVALUATION_PLAN.md`, `docs/ROLE_CONTEXT_STRENGTH_PLAN.md`, `docs/FUTURE_CHAT_REFERENCE_2026-03-24.md`

## 1. Objective

The goal is not just to make Atlas different. The goal is to make it materially better.

For this repo, materially better means:

1. Improve hit quality while pushing Brier below `0.20`.
2. Improve log loss, not only one-off hit rate.
3. Preserve stability across replay and backtest evaluation.
4. Avoid recommendation drift that comes from unapproved optimizer behavior changes rather than better math.
5. Preserve strict historical fidelity in replay.

## 2. Current State

### 2.1 What is already true

1. Live slip target is restored to `10`.
2. Engine fallback default for `top_n_slips` is restored to `10`.
3. `slip_build.beam_width` is currently `250` by explicit approval.
4. Replay run completes successfully.
5. Replay truth coverage is unchanged versus the prior comparison replay:
   - `scored_legs_deduped.csv`: `4469` rows in both runs
   - `matched_rows`: `3957`
   - `unmatched_rows`: `512`
   - `match_rate`: `0.8854329827701947`
   - hits: `1682`
   - misses: `2275`

### 2.2 What is not settled

1. Replay recommendation sets changed materially.
2. Recommendation overlap versus the prior replay is `0` across all compared recommendation files.
3. That means optimizer behavior changed materially even though replay infrastructure is working.
4. Because slip count was restored from `25` to `10`, some recommendation metric improvements are not directly apples-to-apples.

### 2.3 Remaining behavior-changing optimizer edits still present

1. Beam window defaults in `src/Atlas/core/slip_builders.py` are decoupled from `target_pool_mult`.
2. Greedy top-off fallback exists after beam stall in `src/Atlas/core/slip_builders.py`.

These two changes may be helping runtime and completion, but they are also plausible sources of recommendation drift.

## 3. Working Principles For The Next Phase

1. One meaningful change at a time.
2. Replay first, then small corpus, then broader backtest.
3. No broad optimizer behavior changes without explicit approval.
4. Separate operational fixes from model-quality improvements.
5. Use `scored_legs_deduped.csv` as the primary math lens.
6. Treat replay fidelity as mandatory and non-negotiable.

## 4. What Needs To Be Answered Before We Chase New Math

We need to answer four questions in order.

### Question 1

Is recommendation drift coming mostly from:

1. restored slip count from `25` to `10`
2. beam window decoupling
3. greedy top-off fallback
4. beam width increase from `200` to `250`

### Question 2

After isolating optimizer drift, what is the clean baseline candidate for probability work?

### Question 3

Which probability-layer candidate has the best chance to improve Brier and log loss materially without destabilizing slip selection?

### Question 4

Once a candidate looks good on replay, does it survive a small corpus and then a broader reader-backed comparison?

## 5. Plan Overview

The work should proceed in six phases.

1. Freeze a trustworthy control baseline.
2. Isolate optimizer drift.
3. Lock the approved selection path.
4. Resume probability and calibration work.
5. Validate on a small replay corpus.
6. Promote only if the wider evidence holds.

## 6. Phase 1: Freeze The Control Baseline

### Goal

Create a clean, named control point so every later replay comparison is interpretable.

### Actions

1. Treat the most recent prior replay comparison run as the behavioral control reference:
   - `data/telemetry/replay_runs/roleblend_current_vs_baseline_20260317_bundle/20260324_140826/runs/20260324_092632`
2. Treat the latest completed replay as the current candidate state:
   - `data/telemetry/replay_runs/roleblend_current_vs_baseline_20260317_bundle/20260324_225732/runs/20260324_175821`
3. Capture a compact baseline summary table for:
   - eval rows
   - match rate
   - hits and misses
   - recommendation counts
   - top hit_prob for each output family
   - overlap between control and candidate recommendation sets
4. Do not modify probability math during this phase.

### Deliverable

One control-versus-current comparison snapshot that future tests can reference.

## 7. Phase 2: Isolate Optimizer Drift

### Goal

Determine exactly which remaining optimizer edit is responsible for the replay recommendation turnover.

### Why this must come first

Right now replay truth coverage is stable but selection changed completely. If we start tuning under-relief, role strength, or telemetry on top of an unstable selector, we will not know what actually improved the model.

### Ordered experiment ladder

Run these as separate replay experiments, one at a time.

#### Experiment A

Control the count effect only.

1. Compare prior replay top `10` vs current replay top `10` only.
2. Determine whether the zero overlap remains even after removing the `25 -> 10` truncation distortion.

#### Experiment B

Test beam width sensitivity.

1. Keep all current logic.
2. Replay with `beam_width: 200` versus `250`.
3. Measure runtime, completion stability, overlap, and top-slip metric deltas.

#### Experiment C

Test the greedy top-off fallback.

1. Keep beam width fixed.
2. Disable only greedy top-off fallback.
3. Replay and compare:
   - completion
   - runtime
   - recommendation overlap
   - whether failure returns under exposure caps

#### Experiment D

Test beam window decoupling.

1. Keep beam width fixed.
2. Revert only the beam-window default logic.
3. Replay and compare:
   - runtime
   - completion
   - recommendation overlap

### Deliverable

An attribution table that says which optimizer change causes which portion of the drift.

## 8. Phase 3: Lock The Approved Selection Path

### Goal

Choose the selection path we trust enough to use as the baseline for math improvements.

### Decision rule

Use this order of priority:

1. replay fidelity and completion
2. behavioral clarity
3. runtime reasonableness
4. recommendation quality metrics

### What we may end up approving

Possible approved endpoint examples:

1. Keep `beam_width = 250`, keep beam window decoupling, remove greedy top-off.
2. Keep `beam_width = 250`, keep greedy top-off, revise beam window defaults.
3. Revert both remaining optimizer edits and only retain explicit `top_n = 10` plus `beam_width = 250`.

### Deliverable

One explicit optimizer baseline with no ambiguity about what is and is not approved.

## 9. Phase 4: Resume Probability And Calibration Work

### Goal

Return to the actual model-improvement work with a stable selector underneath it.

### Primary model-improvement targets

Based on the current docs and prior work, the next candidate areas should be:

1. under-relief tuning refinement
2. continuous role-context strength for calibration
3. telemetry family comparison using current replay corpus discipline

### Priority order

#### Priority A: Under-relief refinement

Reason:

1. It already exists in the runtime.
2. It directly affects `p_adj` and under behavior.
3. It can move Brier and log loss without requiring a full allocator rewrite.

What to inspect in `scored_legs_deduped.csv`:

1. `p_adj_pre_under_relief`
2. `p_adj`
3. `under_relief_factor`
4. `under_relief_applied`
5. `q_blowout`

Candidate work:

1. validate whether current under-relief is too broad or too weak on under-heavy slices
2. run small replay checks with one knob change at a time
3. keep everything else fixed

#### Priority B: Role context strength candidate

Reason:

1. The existing plan in `docs/ROLE_CONTEXT_STRENGTH_PLAN.md` is already directionally sound.
2. It targets calibration quality rather than raw selection churn.
3. It uses existing fields such as `role_ctx_outs_used` and `role_ctx_mult`.

Candidate work:

1. implement a conservative continuous role-strength feature in the reader or comparison layer first
2. compare it against current role-on / role-off calibration families
3. promote only if Brier and log loss both improve without slice collapse

#### Priority C: Telemetry calibration candidate review

Reason:

1. The current note says the clean lead is calibration-only rather than full variant promotion.
2. That suggests there may still be low-risk gains in calibration before more structural modeling work.

Candidate work:

1. verify the current active calibration baseline
2. test whether the role-strength candidate improves beyond the current calibration-only lead
3. protect slices that already pass

## 10. Phase 5: Small Corpus Evaluation

### Goal

Promote only candidates that survive more than one replay.

### Corpus design

Start with a tight corpus of `3` to `5` slates, not a large sweep.

Include these slice types where possible:

1. injury-heavy
2. under-heavy
3. role-sensitive
4. questionable-heavy
5. mixed stat-family

### Evaluation metrics to record

1. Brier score
2. log loss
3. hit rate by leg count
4. average expected value distribution
5. under-heavy slice performance
6. role-sensitive slice performance
7. recommendation stability versus control

### Guardrails

Reject a candidate if it:

1. improves only one metric while hurting the others materially
2. regresses protected slices
3. relies on replay artifacts that are not fidelity-safe

## 11. Phase 6: Wider Corpus And Promotion Gate

### Goal

Use the reader to decide whether the candidate is real.

### Order

1. Single replay smoke test
2. Small corpus comparison
3. Reader pass
4. Wider corpus only if the small corpus is clean

### Promotion rule

A candidate should be considered promotable only if:

1. Brier improves or remains below `0.20`
2. log loss improves
3. no meaningful protected-slice collapse appears
4. replay fidelity remains intact
5. runtime remains acceptable for live use

## 12. Concrete Immediate Work Queue

This is the order I recommend for the next actual work sessions.

### Step 1

Build the optimizer drift attribution table.

Do this first because it is the blocker for trusting any replay recommendation change.

### Step 2

Decide the approved optimizer baseline.

Do not continue math tuning until this is settled.

### Step 3

Run the next under-relief replay candidate on the stabilized baseline.

Use one replay first.

### Step 4

If the replay looks good, run a `3` to `5` slate comparison.

### Step 5

Only after that, evaluate the role-context-strength candidate.

### Step 6

Use the reader and wider corpus only after a candidate survives the small replay ladder.

## 13. Definition Of Materially Better

For this project, a change should only be called materially better if most of the following are true:

1. Brier is lower and stays under `0.20`, or moves meaningfully closer without tradeoff collapse.
2. Log loss improves.
3. Hit quality improves on relevant outputs, not just one cherry-picked file.
4. Improvement survives more than one replay.
5. Protected slices do not regress materially.
6. Runtime remains practical for live operation.
7. The improvement comes from better model behavior, not accidental optimizer churn.

## 14. Immediate Recommendation

The next best step is:

1. finish the optimizer drift attribution work
2. lock the approved selector baseline
3. resume under-relief and calibration work only after that

That is the fastest path to a result that is both better and trustworthy.