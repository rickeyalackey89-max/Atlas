# Prime Experiment Runway Protocol

Status: **MANDATORY PRIME RESEARCH DOCTRINE**

Prime research follows one rule:

> **Cheap runway before long takeoff.**

No expensive or multi-hour experiment may be authorized merely because an architecture is scientifically interesting. The experiment must first pass a bounded, inexpensive runway that proves the long run is necessary, executable, and capable of answering the intended question.

This protocol governs Prime Delegation research work across sports unless a stricter sport-specific authority applies.

It does not supersede sport/model repository authority, protected-data rules, or workflow controllers.

## Why this exists

A long experiment is a research expense, not evidence by itself.

The V2 WNBA relational sweep demonstrated one failure mode this protocol is designed to prevent: four expensive architectures were run through a shared gate that selected `INF` / forced incumbent control on 90-100% of target dates. The final action result therefore mostly measured the gate rather than the learners. A cheap pre-run decomposition/actionability check could have exposed that before a multi-hour sweep.

The 2026-08-19 WNBA FromDeep R1 resource stop demonstrated another failure mode: a combinatorial signal-atlas implementation was substantially engineered before the cheapest topology calculation established that the naive complete Tier-B execution surface was millions of roads and far outside the declared R2 budget. Prime must prevent that ordering error as aggressively as it prevents statistical leakage.

Prime therefore optimizes for **information gained per unit wall-clock time**, while preserving statistical rigor.

## Two-key authorization model

Expensive research requires two separate user/Chat decisions.

### Key 1 — Runway authorization

Authorizes only bounded diagnostics, implementation fidelity checks, runtime measurement, and a small scientific canary where legally appropriate.

The runway must stop at user review.

It **cannot auto-escalate** into the expensive experiment.

### Key 2 — Full-run authorization

May be issued only after Chat/user review the runway receipt and decide the long run is still warranted.

A full run requires its own Prime work order / commit identity.

## Mandatory topology-before-implementation rule

For any experiment with a multiplicative dimension — candidate pairs, combinations, folds, hyperparameters, regenerated slates, replay members, policy cross-products, or any other potentially explosive surface — **topology feasibility must be measured before substantial experiment implementation**.

The first runway must use existing sealed artifacts and simple read-only counting/algebra wherever possible. Target: seconds to a few minutes.

Before new runner architecture, checkpoint machinery, storage cleanup, large synthetic suites, or control-path engineering, report at minimum:

- input row/member/date count;
- primitive/candidate count by owner or partition;
- exact or bounded combinatorial count;
- structural-impossibility count where frozen support/breadth rules make a candidate incapable of qualifying;
- estimated operations/intersections/fits;
- compact-representation memory estimate;
- streamed-output estimate;
- wall-clock estimate from a tiny measured kernel when needed;
- whether the proposed execution can fit the declared R1/R2/R3 class.

If this topology receipt says the proposed implementation cannot fit the authorized resource class, **stop before building the full implementation**.

Do not spend hours creating crash recovery for a computation that a one-minute count proves should not be run in that form.

## Structural pruning is not scientific truncation

Outcome-blind structural impossibility may be removed before performance evidence without violating a complete scientific surface.

Examples include a road that cannot possibly achieve the frozen minimum support, minimum unique dates, minimum unique participants, required semantic-family pairing, or other immutable eligibility condition.

This is different from top-N, hit-rate, lift, or outcome-based pruning.

When a later candidate class is defined by a prior evidence gate, cost the stages in the same order as the frozen method. A worst-case combinatorial ceiling is useful as a guardrail, but it must not automatically be treated as the actual execution surface when the method itself permits Tier-B construction only after Tier-A precursor admission.

For staged signal systems, the preferred sequence is:

`outcome-blind Tier-A topology -> structural impossibility pruning -> Tier-A grading -> frozen precursor admission -> actual Tier-B topology/cost -> exact Tier-B grading if feasible`.

No outcome-based top-N shortcut is authorized by this rule.

## Compact/streamed representation requirement

A large candidate count does not by itself justify a large materialized candidate-by-row artifact.

Before declaring a resource failure, ask whether the same complete computation can be expressed with compact bitsets, sparse identities, vectorized intersections, streaming aggregation, chunked output, or other scientifically equivalent bounded-memory machinery.

Peak storage/RAM estimates must distinguish:

- intrinsic information required by the scientific question; and
- accidental cost caused by the chosen materialization strategy.

Prime should reject an implementation design that requires orders of magnitude more storage than the underlying sealed evidence unless that materialization is scientifically necessary.

## Governance/re-read economy

Static governance is not scientific work.

If the governing documents, skill files, control hashes, and repository authority were already read and hash-bound for the current continuous task, Prime must reuse that verified authority rather than repeatedly rereading the entire Atlas/league governance stack before every shell command.

Re-read only when:

- a governing hash changed;
- a new task/skill introduces genuinely new authority;
- the current state cannot be reconciled from already-bound receipts;
- the target repository explicitly requires a fresh read.

Mandatory target-repository preambles remain mandatory, but they should be concise and must not trigger redundant full-document archaeology by themselves.

The goal is one coherent research workflow, not a governance ceremony between every `rg`, `Get-Content`, test, or Git command.

## Runway stages

Not every task needs every stage. Use the cheapest stage capable of falsifying the need for the next one.

### R0 — Static feasibility / artifact audit

Target: minutes, not tens of minutes.

Use existing artifacts, code inspection, algebra, counts, manifests, sealed scores, or consumed-development evidence to answer questions that do not require fitting.

Required questions:

- Can the hypothesis already be answered from existing evidence?
- Is the proposed learner/action/gate mathematically capable of changing the output?
- Is a shared fallback, gate, threshold, or policy likely to dominate all variants?
- Are multiple proposed variants actually materially different at the action surface?
- Can an artifact-only decomposition replace a refit?
- What is the exact computational topology before implementation?

If R0 answers the scientific or feasibility question, stop. Do not fit a model or build an execution framework for ceremony.

### R1 — Implementation/actionability canary

Target: normally <= 15 minutes.

Use synthetic data, development-consumed data, or other legally permitted non-promoting inputs to prove:

- intended architecture is actually exercised;
- each arm can produce a different score/selection when expected;
- gate/fallback behavior does not mechanically suppress the learner;
- outcome blindness and protected-data boundaries hold;
- checkpoint/restart/stop behavior works when checkpointing is actually needed;
- output schema and evidence capture are sufficient to diagnose failure.

A canary that shows action collapse, shared-gate domination, architecture equivalence, inability to answer the intended question, or resource infeasibility is a **STOP**, not a reason to launch the full run.

Do not overbuild recovery/checkpoint infrastructure before the topology receipt proves the intended R1/R2 computation is feasible.

### R2 — Bounded scientific pilot

Target: normally <= 60 minutes total and substantially cheaper than the proposed full run.

Use only a predeclared, statistically legal pilot surface. Never consume validation or lockbox merely to save time.

The pilot must be large enough to expose obvious design/runtime failure but small enough that failure is cheap.

Before execution, predeclare:

- exact rows/dates/folds used;
- outcome visibility;
- whether the pilot is scientific evidence or implementation-only evidence;
- exact stop criteria;
- no serial tuning based on individual pilot fold outcomes unless the governing methodology explicitly permits it.

The pilot should answer whether a full run is likely to add material information, not attempt to manufacture a promotion result from a tiny sample.

### R3 — Full expensive experiment

Only after a separate user-authorized Prime work order.

The work order must cite the runway receipt and state exactly what information the full run is expected to add beyond R0-R2.

If that sentence cannot be written concretely, do not launch.

## Mandatory pre-run cost receipt

Before any R2 or R3 execution, Codex must calculate and report the expected computational topology before launching:

- architecture/arm count;
- candidate/primitive/pair count where applicable;
- outer folds;
- inner folds;
- hyperparameter values;
- approximate fit/intersection count;
- expected output/checkpoint count;
- measured pilot time per unit;
- projected wall-clock range;
- expected peak CPU/RAM/storage class;
- compact/streamed alternative if a naive materialization is large;
- checkpoint/restart plan only after the computation is shown worth running.

For nested learners, show the fit-count arithmetic explicitly.

For pairwise/combinatorial searches, show the pair-count arithmetic explicitly.

Do not discover after launch that one "fold" contains hundreds of fits or one signal tier contains millions of pairs.

## Mandatory information-gain receipt

Before R3, answer all of these:

1. What exact scientific question remains unresolved after the runway?
2. What full-run evidence could change the current decision?
3. What result would cause us to reject the hypothesis?
4. What result would merely reproduce a known control/fallback and therefore add little information?
5. Why can existing sealed/consumed artifacts not answer the question more cheaply?

If the expected full-run output is structurally forced to equal an incumbent/control on most targets, stop and diagnose that mechanism first.

## Variant divergence / actionability checks

For multi-arm experiments, runway evidence must report:

- score divergence across arms;
- challenger/selection divergence across arms;
- gate/fallback rate per arm;
- percentage of pilot targets mechanically forced to incumbent/control;
- whether arm differences survive through the final action layer.

A study of four learners that all feed a common gate is not a four-learner action experiment if the gate suppresses nearly all actions.

When a shared layer dominates, decompose learner quality from shared-layer quality before long execution.

## Runtime observability

Long-running work must be observable without requiring the user to stare at VS Code.

R2/R3 work orders must specify:

- progress unit (fold/date/arm/etc.);
- completed / total counter;
- current unit;
- elapsed time;
- last-progress timestamp;
- checkpoint location;
- completion sentinel / stop marker;
- process exit status.

For work expected to run unattended, the execution wrapper/controller should emit a lightweight heartbeat frequently enough that a completed, failed, or stalled process can be recognized promptly. The heartbeat is observational only; it must not alter scientific behavior.

A process that has already completed or failed must not remain silently unattended for hours merely because Codex has not noticed the terminal state.

## Mandatory storage housekeeping before expensive work

Storage housekeeping is required only after topology/cost feasibility proves the experiment is worth running and storage is the actual blocker.

Do **not** start multi-step cleanup merely to make room for an implementation whose topology has not yet been shown feasible.

Before every genuinely expensive Builder, replay, corpus, model-training, or large evidence operation that passes topology feasibility, Codex must read and apply `docs/coordination/PRIME_STORAGE_HOUSEKEEPING.md`.

Where the Codex environment exposes an installed `keep-it-tidy` skill, Codex must resolve and read that skill and use it for the housekeeping operation. Do not invent a substitute destructive cleanup routine when the skill cannot be resolved.

Housekeeping occurs **before** the final storage/resource preflight but **after** the static topology receipt. It is operational maintenance, not scientific evidence.

A low-space measurement should not automatically force a multi-turn research interruption while safe stale non-authority material remains reclaimable under the housekeeping protocol. The scientific work order's hard resource gate remains unchanged and must still pass after housekeeping.

Prime work orders for expensive operations should bind the housekeeping protocol explicitly and state any task-specific protected keep-set additions.

## Stop-fast conditions

Stop before expensive execution when any of these is demonstrated:

- artifact-only evidence answers the question;
- proposed variants are action-equivalent;
- gate/fallback mechanically dominates the learner;
- combinatorial topology materially exceeds the authorized budget;
- compact/streamed execution cannot bring the complete scientific surface inside the authorized budget;
- canary cannot reproduce known parity/invariants;
- required outcome blindness cannot be preserved;
- protected authority has drifted;
- projected runtime materially exceeds the authorized budget;
- restart/checkpoint behavior is not proven for an expensive run that actually needs it;
- the full run cannot produce information that would change the decision;
- implementation starts an unauthorized fitting path.

Stopping early is a successful research outcome when it prevents low-information compute.

## Statistical rigor is not optional

Efficiency must not be obtained by weakening methodology.

Do not:

- peek at validation/lockbox;
- react serially to heldout outcomes when the experiment requires global sealing;
- tune on a pilot and then describe the same pilot as OOS confirmation;
- post-hoc select a winning threshold and promote it;
- shrink the surface until noise looks favorable;
- reuse consumed evidence as fresh confirmation;
- top-N prune a candidate family because the full outcome-bearing result is inconvenient.

The objective is **less unnecessary compute**, not less rigor.

## Prime work-order requirement

Every future Prime research delegation must classify its execution tier:

- `R0_ARTIFACT_AUDIT`
- `R1_ACTIONABILITY_CANARY`
- `R2_BOUNDED_PILOT`
- `R3_FULL_EXPERIMENT`

An `R3_FULL_EXPERIMENT` delegation must cite the accepted R0/R1/R2 evidence or explicitly explain why a lower-cost stage is impossible.

Absent that justification, fail closed and return for user review.

## Completion principle

The preferred research cadence is:

`theory -> static topology/cost receipt -> cheap falsification -> actionability canary -> bounded pilot -> user review -> full run only if necessary`

not:

`theory -> build maximum machinery -> discover topology/resource failure afterward`.
