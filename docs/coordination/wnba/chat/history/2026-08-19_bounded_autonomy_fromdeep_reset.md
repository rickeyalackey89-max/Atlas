# 2026-08-19 — Bounded Autonomy + FromDeep Reset

## User/Chat decision

The WNBA Builder workflow became over-governed at the command/test level and the prior FromDeep R1 drifted into an exhaustive/materialized combinatorial implementation that projected roughly 175 GB peak storage and about 183,037 seconds of runtime before opening scientific outcomes.

Accepted interpretation:

`R1_IMPLEMENTATION_TOPOLOGY_DESIGN_FAILURE_NOT_FROMDEEP_SCIENTIFIC_FAILURE`

The user rejects both:

1. the exhaustive/materialized R1 architecture as the path to FromDeep; and
2. the per-command/per-test governance ceremony that caused hours of low-value control work.

## New operating model

Prime now uses bounded autonomous missions.

User/Chat choose the scientific direction and mission envelope. Codex owns subordinate engineering execution inside that envelope, including multiple tasks, focused test/fix loops, and safe independent parallel work.

Review stops are decision boundaries, not command boundaries.

Mandatory review remains for scientific-method/scope changes, protected evidence, resource escalation, destructive/risky operations, new fitting/tuning authority, and Live/promotion/deployment changes.

Prime doctrine:

`docs/coordination/PRIME_BOUNDED_AUTONOMOUS_MISSIONS.md`

Publication commit:

`b90674b0c740a79e82ceae2493b9e52861187025`

## Authorized Codex mission

Work order:

`docs/coordination/wnba/codex/archive/2026-08-19_bounded_autonomy_governance_fromdeep_feature_inventory.md`

Publication commit:

`8f30ea13f27e8ed116f06c0dde40f113c764e668`

One authorization covers:

1. WNBA Builder governance/control reconciliation to bounded autonomous missions; then
2. automatic continuation into a compact FromDeep candidate-feature and historical-as-of inventory.

No intermediate user-review stop is required between those phases if governance validation passes.

The mission stops before final signal-discovery methodology is chosen or executed.

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_FEATURE_INVENTORY_COMPLETE`
