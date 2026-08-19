# Prime Bounded Autonomous Missions

Status: **MANDATORY PRIME COORDINATION DOCTRINE**

## Governing principle

Prime governs scientific decisions strongly and implementation mechanics proportionally.

The normal Codex unit of work is a **bounded autonomous mission**, not a shell command, individual test, file edit, subagent, or microscopic workflow row.

Chat/user decide the scientific direction and the mission envelope. Codex owns the engineering path inside that envelope.

The purpose is to let Codex use its strengths — repository inspection, implementation, focused testing, debugging, parallel independent work, profiling, artifact generation, and exact-path Git work — without forcing repeated governance reasoning or user/Chat review for subordinate operations.

This doctrine does not weaken protected-data, validation, lockbox, Live, promotion, destructive-operation, or scientific-method boundaries.

## Required mission envelope

Every substantial Prime delegation states six things:

1. **Objective** — the concrete question/result Codex is responsible for delivering.
2. **Authority** — the repositories, artifacts, evidence classes, and outcome visibility it may use.
3. **Freedom** — implementation, inspection, testing, debugging, refactoring, parallelization, profiling, and artifact work Codex may perform autonomously.
4. **Hard boundaries** — scientific, protected-data, resource, deployment, destructive-operation, and scope changes that require a return to user/Chat.
5. **Resource envelope** — the expected/allowed runtime, storage, RAM, and multiplicative topology before escalation is required.
6. **Completion condition** — the evidence/artifacts/commits/report that end the mission.

If these six fields are clear, Codex should work the mission rather than repeatedly re-derive permission for subordinate mechanics.

## One mission preamble — inherited by all subagents

A full mission preamble is encouraged and should be emitted **once** at mission/active-row activation. It binds the stage/row, machine class, evidence class, input hashes, outcome visibility, fitting/code/resource/Live permissions, stop conditions, and final review requirement.

That single preamble belongs to the **parent mission**, not to each command and not to each subagent.

Every subagent created inside the mission inherits the already-bound mission envelope. Creating a `control`, `topology`, `engine-design`, `semantics`, `testing`, or other subagent does **not** create a new activation and does not justify another full preamble or a full governance reread.

A subagent may report its technical assignment and progress. It must not independently re-open the entire governance stack merely because it started work.

After the opening preamble, use only:

`BUILDER CONTROL DELTA: <changed governing fact>`

when a governing fact actually changes. If no governing fact changed, no control delta is required.

## Closed definition of a governing-fact change

For Prime bounded missions, a governing fact changes only when one or more of these changes:

1. scientific objective or method;
2. candidate/evidence population or evidence partition;
3. authorized outcome-evidence class, validation, lockbox, or protected-data visibility;
4. fitting/training/tuning authority;
5. feature, predicate, threshold, interaction, ranking, selection, output-policy, or routing semantics;
6. repository/workspace/branch authority;
7. resource envelope or destructive-operation authority;
8. Live/runtime/publication/promotion authority;
9. required stop/completion condition;
10. a previously bound authority hash actually changes in a way relevant to the active mission.

The following are **not** governing-fact changes when scientific meaning and the mission envelope remain unchanged:

- syntax, unit, fixture, or adversarial test failures;
- parser or representation repairs;
- exact row-identity fixes;
- serialization or metadata fixes;
- implementation seam changes;
- ordinary refactoring;
- another file inspection;
- `rg`, `Get-Content`, Git status/diff, or similar inspection commands;
- small utilities or inspectors;
- profiling and resource measurement;
- read-only topology/census work;
- focused test reruns;
- deterministic hash/existence/schema checks on already-authorized non-outcome inputs;
- creation/completion of a subordinate engineering subtask;
- a subagent starting, stopping, compacting context, or handing work back to the parent;
- representation/performance improvements that preserve exact scientific semantics.

Do not convert these engineering events into control cycles.

## Control-validation cadence

Full control validation is required only at meaningful mission boundaries:

1. once at mission activation;
2. once immediately before the first transition into a **newly authorized evidence class** when that class was not already open at activation;
3. after an actual governing-fact change from the closed list above;
4. at mission completion or a declared hard boundary.

Do **not** repeat full control validation:

- before every command;
- before every test;
- for every target date;
- for every file in one already-authorized evidence population;
- because a subagent began work;
- because an implementation bug was repaired;
- because a context window compacted.

If a mission preauthorizes a development outcome population under a strict causal schedule, opening successive members/dates of that same authorized population according to the frozen schedule is scientific execution, not a sequence of new governance activations.

## Outcome-bearing file bytes and hash checks

Before an outcome-bearing evidence class is authorized/open, do not read the bytes of its files merely to recompute hashes. Use already-bound manifest/seal hashes and metadata for preflight when available.

A SHA read of an outcome-bearing file is still file-byte access even when the file is not decompressed or parsed.

After the mission has crossed the authorized evidence boundary, ordinary reads/hash verification within that exact authorized population do not create a new governance boundary for each file/date.

Any accidental premature byte read must be recorded once, quarantined from scientific inputs, and adjudicated according to whether values/semantics actually entered the scientific process. Do not turn one implementation anomaly into repeated governance ceremony when the authorized mission can be repaired without changing science.

## Autonomous execution inside the envelope

Unless the mission explicitly says otherwise, Codex may autonomously:

- inspect multiple repository files/artifacts;
- run multiple focused/adversarial tests;
- fix implementation defects and rerun those tests;
- write small utilities/inspectors needed to answer the authorized question;
- profile runtime and memory;
- perform read-only censuses and schema/provenance inspection;
- generate compact diagnostic artifacts and receipts;
- perform ordinary exact-path Git inspection/staging/commits allowed by target-repository governance;
- split the mission into multiple engineering subtasks;
- execute independent read-only or non-conflicting subtasks in parallel;
- retry implementation-only failures that do not change scientific meaning;
- choose the engineering implementation needed to satisfy the objective.

Codex does **not** need a user/Chat review or a fresh governance cycle merely because a subordinate implementation event occurred.

## Governance reread economy

Unchanged hash-bound governance is reused for the continuous mission.

Do not reread the full Atlas/league/Builder governance stack for each subagent or subordinate action.

Re-read a governing document only when:

- its relevant bound hash changed;
- new authority entered the mission;
- the current state cannot be reconciled from already-bound receipts;
- the target repository explicitly requires a fresh read at a genuine boundary.

Where target governance currently demands unconditional repeated reads, the next user-authorized governance-reconciliation mission should replace that behavior with a hash-bound manifest/check so unchanged authority can be reused.

Static governance rereads are not scientific progress.

## Mandatory return-to-user/Chat boundaries

Codex must stop and return when continuing would require any of the following beyond the authorized mission envelope:

- changing the scientific question, methodology, candidate population, feature definition, threshold definition, interaction grammar, ranking rule, selection rule, output policy, routing rule, or evidence partition;
- opening validation or lockbox evidence;
- opening a new outcome population not already authorized;
- beginning new fitting/tuning/training authority not already authorized;
- mutating Live/runtime/publication/promotion state;
- crossing the declared resource envelope after a cheap topology/cost check and competent compact/streamed alternatives;
- performing a destructive or materially risky repository/storage operation not already authorized;
- discovering evidence that invalidates the mission premise such that the authorized objective no longer makes sense.

These are decision boundaries. Individual commands, tests, dates, files, and subagents are not.

## Resource behavior

`docs/coordination/PRIME_EXPERIMENT_RUNWAY.md` remains governing.

Topology/cost feasibility comes before large implementation for multiplicative work.

If a cheap count shows the proposed architecture is pathological, Codex may redesign **implementation mechanics** within the same scientific method when an equivalent bounded representation is obvious and inside the mission envelope. It may not silently redesign the science.

Do not spend hours building checkpoint/restart/control machinery for a computation whose basic topology has not been shown worth running.

Long runtime is acceptable only when the mission is already scientifically decided, computationally feasible, observable, and the remaining work is bounded engineering/execution. Hours of repeated governance/control work are not an acceptable substitute for progress.

## Mission elapsed-time accounting

Every substantial mission must distinguish **total Codex mission wall-clock time** from the runtime of an individual runner/kernel.

At activation, record a mission start timestamp. At completion, report at minimum:

- total mission elapsed wall-clock time;
- scientific runner/kernel wall-clock time;
- approximate governance/control time when measurable;
- approximate implementation/testing time when measurable;
- whether long elapsed time was dominated by useful bounded engineering/scientific execution or by repeated control/re-read ceremony.

Never present a 100-second runner as though a four-hour Codex mission took 100 seconds.

If the mission spends materially more wall time on repeated governance/control work than on implementing/testing/executing the authorized objective, treat that as a workflow defect to be reported, not normal rigor.

## Mission sizing

Prefer medium-sized goals with a clear endpoint.

Too small:

`run one test -> stop -> ask user -> fix one parser -> stop -> ask user`.

Too large:

`build the best possible FromDeep system and decide the methodology as you go`.

Preferred:

`within these evidence and resource boundaries, implement/verify this agreed method, solve subordinate engineering problems autonomously, and return when the defined result packet is complete`.

## Prime / Chat / Codex roles

- **User/Chat:** scientific objective, methodological choices, protected-evidence decisions, promotion/deployment decisions, mission boundaries.
- **Prime:** durable transport of those decisions and mission envelopes.
- **Codex:** autonomous engineering execution inside the envelope.
- **Target repository workflow controller:** remains authoritative for repository/model state and must be reconciled to the user-approved mission rather than duplicated by Prime.

Prime is mission control, not remote control.

## Completion report

A bounded autonomous mission should normally return one final mission receipt/report containing:

- objective completed or exact reason for boundary stop;
- commits and changed paths;
- tests/checks run and final status;
- evidence/artifacts produced;
- total mission elapsed time and scientific-run time separately;
- resource/runtime summary;
- protected-data/Live visibility accounting;
- unresolved issues that materially affect the next scientific decision;
- the next decision required from user/Chat.

Intermediate logs may remain available for audit, but they should not become mandatory user-review gates.
