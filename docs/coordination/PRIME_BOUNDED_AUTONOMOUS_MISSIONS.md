# Prime Bounded Autonomous Missions

Status: **MANDATORY PRIME COORDINATION DOCTRINE**

## Governing principle

Prime governs scientific decisions strongly and implementation mechanics proportionally.

The normal Codex unit of work is a **bounded autonomous mission**, not a shell command, individual test, file edit, or microscopic workflow row.

Chat/user decide the scientific direction and the mission envelope. Codex owns the engineering path inside that envelope.

The purpose is to let Codex use its strengths — repository inspection, implementation, focused testing, debugging, parallel independent work, profiling, artifact generation, and exact-path Git work — without forcing a user/Chat review after every subordinate operation.

This doctrine does not weaken protected-data, validation, lockbox, Live, promotion, destructive-operation, or scientific-method boundaries.

## Required mission envelope

Every substantial Prime delegation should state six things:

1. **Objective** — the concrete question/result Codex is responsible for delivering.
2. **Authority** — the repositories, artifacts, evidence classes, and outcome visibility it may use.
3. **Freedom** — implementation, inspection, testing, debugging, refactoring, parallelization, profiling, and artifact work Codex may perform autonomously.
4. **Hard boundaries** — scientific, protected-data, resource, deployment, destructive-operation, and scope changes that require a return to user/Chat.
5. **Resource envelope** — the expected/allowed runtime, storage, RAM, and multiplicative topology before escalation is required.
6. **Completion condition** — the evidence/artifacts/commits/report that end the mission.

If these six fields are clear, Codex should work the mission rather than repeatedly ask permission for subordinate mechanics.

## Autonomous execution inside the envelope

Unless the mission explicitly says otherwise, Codex may autonomously:

- inspect multiple repository files/artifacts;
- run multiple focused tests;
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

Codex does **not** need a user/Chat review merely because:

- a syntax/unit/fixture test failed;
- a parser or representation adapter needs repair;
- another file must be inspected;
- a small utility script is needed;
- serialization or metadata needs correction;
- a focused test must be rerun;
- a hash/existence/schema check is needed;
- a read-only count or profiling pass is useful;
- a logically subordinate implementation step completed successfully.

Those are engineering events inside one mission, not new scientific decisions.

## One mission preamble, delta only afterward

A mission binds its governing facts once at activation.

Do not repeat a long governance/preamble block before every `rg`, `Get-Content`, test, Python command, or Git command.

After activation, report only a concise control delta when a governing fact actually changes.

Unchanged hash-bound governance should be reused for the continuous mission. Re-read only when:

- a governing hash changed;
- new authority entered the mission;
- the current state cannot be reconciled from bound receipts;
- the target repository explicitly requires a fresh read at a true boundary.

Static governance rereads are not scientific progress.

## Mandatory return-to-user/Chat boundaries

Codex must stop and return when continuing would require any of the following beyond the authorized mission envelope:

- changing the scientific question, methodology, candidate population, feature definition, threshold definition, interaction grammar, ranking rule, selection rule, or evidence partition;
- opening validation or lockbox evidence;
- opening a new outcome population not already authorized;
- beginning new fitting/tuning/training authority not already authorized;
- mutating Live/runtime/publication/promotion state;
- crossing the declared resource envelope after a cheap topology/cost check and competent compact/streamed alternatives;
- performing a destructive or materially risky repository/storage operation not already authorized;
- discovering evidence that invalidates the mission premise such that the authorized objective no longer makes sense.

These are decision boundaries. Individual commands and tests are not.

## Resource behavior

`docs/coordination/PRIME_EXPERIMENT_RUNWAY.md` remains governing.

Topology/cost feasibility comes before large implementation for multiplicative work.

If a cheap count shows the proposed architecture is pathological, Codex may redesign **implementation mechanics** within the same scientific method when an equivalent bounded representation is obvious and inside the mission envelope. It may not silently redesign the science.

Do not spend hours building checkpoint/restart/control machinery for a computation whose basic topology has not been shown worth running.

Long runtime is acceptable only when the mission is already scientifically decided, computationally feasible, observable, and the remaining work is bounded engineering/execution. Hours of unresolved autonomous scientific decision-making are not an acceptable use of Codex.

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
- resource/runtime summary;
- protected-data/Live visibility accounting;
- unresolved issues that materially affect the next scientific decision;
- the next decision required from user/Chat.

Intermediate logs may remain available for audit, but they should not become mandatory user-review gates.
