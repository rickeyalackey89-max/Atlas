# Codex Issue Routing

Use GitHub issues to hand work to either the primary Codex lane or the 5.3 Spark lane.

## Lanes

- `codex:primary`: production-sensitive Atlas work, model/runtime diagnosis, replay analysis, publishing behavior, or work that should stay with the main Codex session.
- `codex:5.3-spark`: isolated bugs, tests, docs, small UI/backend fixes, and work that should run independently from the main Codex session.

## Chat Invocation Examples

Ask Chat:

```text
Create a GitHub issue in rickeyalackey89-max/Atlas titled "[Codex Spark]: Fix X".
Use labels codex, codex:5.3-spark, assigned:codex-spark, needs-triage.
Assign it to rickeyalackey89-max.
Body: problem, reproduction steps, expected behavior, acceptance criteria.
```

For primary Codex:

```text
Create a GitHub issue in rickeyalackey89-max/Atlas titled "[Codex Primary]: Investigate X".
Use labels codex, codex:primary, assigned:codex-primary, needs-triage.
Assign it to rickeyalackey89-max.
```

## Required Issue Body

Every issue should include:

- Problem
- Reproduction steps or relevant files
- Expected behavior
- Acceptance criteria
- Target lane: `codex:primary` or `codex:5.3-spark`
- GitHub assignee, when a human owner should be notified

Do not use this routing for MLB work from this repo setup.
