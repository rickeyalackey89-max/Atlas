# Prime Pre-Outcome Implementation Retry Rule

Status: **MANDATORY PRIME COORDINATION CLARIFICATION**

This document clarifies and operationalizes `docs/coordination/PRIME_BOUNDED_AUTONOMOUS_MISSIONS.md` across all Atlas model repositories.

## Rule

A bounded Codex mission is authorized to repair and retry **implementation-only failures** without returning to user/Chat when the failure occurs before outcome-bearing scientific evaluation and the repair preserves the already-bound scientific meaning.

Examples include:

- parser/representation defects;
- canonical key/name mismatches;
- outcome-free date/calendar topology construction bugs;
- serialization/schema mistakes;
- implementation seam defects;
- test/fixture defects;
- deterministic hash/receipt synchronization needed after such a repair.

These are subordinate engineering events, not new scientific missions.

## Scientific-run accounting

A controller may record every execution attempt for audit, but controller attempt count is not the same thing as scientific evaluation count.

Unless a user/Chat mission explicitly states otherwise for a scientific reason:

- a failed attempt that stops **before settlement/outcome consultation, variant grading, fitting, or result-bearing scientific output** consumes zero scientific evaluations;
- Codex may fix the implementation defect, rerun focused tests/invariants, and retry inside the same mission envelope;
- the mission's scientific-run limit applies to successful/result-bearing scientific evaluations, not to pre-outcome engineering attempts.

Do not require a new Prime amendment solely because a pre-outcome implementation attempt counter incremented.

## Conditions for autonomous retry

All must hold:

1. no new outcome/protected evidence was consulted beyond what the mission already authorizes;
2. no scientific result/recommendation artifact was produced from the failed attempt;
3. the repair does not change objective, population, feature/predicate/threshold semantics, ranking/selection/output policy, evidence partition, fitting authority, repository authority, resource/destructive authority, Live authority, or completion condition;
4. focused tests and relevant invariants are rerun after repair;
5. the retry remains within the authorized resource envelope.

If these conditions hold, Codex should continue autonomously rather than stop for user/Chat.

## Required return boundary

Return to user/Chat if the repair would change a governing fact, if a new evidence class must be opened, if protected/validation/lockbox authority is needed, if result-bearing scientific evaluation has already occurred and another scientifically distinct evaluation would be required, or if the mission resource envelope is genuinely exceeded.

## Intent

Fail-closed controls protect scientific validity. They are not intended to turn ordinary debugging into repeated human permission cycles.

Prime is mission control, not remote control.