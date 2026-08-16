# WNBA Chat Handoff

Use this file when a Chat thread becomes unstable, too large, or unavailable.

## Prime Delegation recovery prompt

A new Chat thread should be told:

> Read the WNBA Prime Delegation package under `docs/coordination/wnba/` in the parent Atlas repo. Reconstruct the current WNBA strategy, then verify the live Atlas-WNBA repository authority before making operational recommendations. Do not treat Prime Delegation as repository authority.

## Read order

1. `CHAT_PRIME.md`
2. `state/CURRENT_STATE.json`
3. `CHAT_AGENDA.md`
4. `CHAT_DECISIONS.md`
5. newest relevant `history/*.md`
6. actual Atlas-WNBA `AGENTS.md`
7. actual `docs/model_development/ACTIVE_BUILDER_LANE.json`
8. current builder state/work order/evidence/process controls as required
9. current model champion/Live pointers when relevant

## Role separation

- **Chat:** theory, strategy, interpretation, durable agenda, research design, user-facing judgment.
- **Codex:** exact execution of a user-authorized delegation.
- **slip-builders:** sole WNBA Builder workflow controller while the Builder lane is active.
- **Prime Delegation:** continuity/delegation layer only.

## Mandatory reconciliation

Before operational advice, compare `state/CURRENT_STATE.json` with the actual Atlas-WNBA branch/ref and active controls.

If they differ, treat the snapshot as stale and reconcile from the model repo. Never overwrite current authority with remembered Prime state.

## High-value continuity facts

- newest current-stack discovery corpus is the statistical research authority
- 39 discovery dates; 30 applicable 3L dates; 1,609 3L candidates
- 2L frozen 32-7
- 3L exact control 20-9+1
- 8 3L ranking failures; one supply-impossible date 2026-07-08
- prior pointwise logistic 22-7+1
- Pairwise V1 failed
- V2 official action results equaled control, but Chat review found the KEEP/INF threshold gate confounded the interpretation of learner signal
- 4L waits for final 3L depletion
- FromDeep stays separate
- validation/lockbox remain protected
