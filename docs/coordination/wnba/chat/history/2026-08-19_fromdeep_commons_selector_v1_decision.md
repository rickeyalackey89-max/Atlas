# WNBA FromDeep Commons Selector V1 Decision

Date: 2026-08-19

User/Chat accept WIN-vs-LOSS Commons R0 at WNBA commit `02f8b7143012c879df55078fb7017ed9635382ea`.

## Accepted interpretation

The commons packet found 19 markets with `POSITIVE_COMMONS_PRESENT` and 8 with `INSUFFICIENT_EVIDENCE`. This supports moving directly to one simple deterministic selector replay rather than reopening exhaustive signal-road research.

The prior SAFE-only GREEN-road R1 failure remains valid for that exact method but does not control this commons selector.

## Frozen candidate method for development replay

- Use all 19 Commons R0 positive markets; do not cherry-pick a subset from discovery rates.
- Each market uses exactly its Commons R0 primary favorable qualifier plus primary veto.
- The eight insufficient-evidence markets abstain.
- Numeric rule identity is field + operator + quantile symbol; the literal threshold is recomputed from prior `t<D` pregame candidate values only.
- Categorical/boolean values are exact.
- Cold start requires 24 prior binary rows, 8 prior dates, 6 prior participants/combo identities.
- Qualification is `positive match AND no veto match`.
- Missing positive -> not qualified; missing veto -> no veto match.
- Preserve every qualified FromDeep single leg; no one-pick cap and no probability ranking/output rule.
- Do not apply the old 90/90 GREEN/Wilson road gate to qualification. Report the 90/90 + 24/8 product target only as a diagnostic reference.

## Evidence interpretation

Because the feature/operator identities were discovered on the full development corpus, the replay is development-consumed evidence, not untouched OOS confirmation. If promising, the frozen selector can later be tested on protected validation with the completed stack.

## Execution principle

No new engine, no road atlas, no Commons rerun, no model fit, no validation/lockbox/Live mutation. Prefer direct replay from sealed artifacts/checkpoints and a minimal selector adapter only if needed.

Active Prime work order:

`docs/coordination/wnba/codex/archive/2026-08-19_fromdeep_commons_selector_v1_development_replay.md`
