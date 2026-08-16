# WNBA Chat Agenda

This file preserves strategic topics that should not disappear when attention shifts.

Statuses:

- `ACTIVE`
- `NEXT_AUTHORIZED`
- `CANDIDATE_NEXT`
- `LATER`
- `PARKED`
- `REVISIT_ON_TRIGGER`
- `REJECTED`
- `COMPLETE`

`CANDIDATE_NEXT` is strategy only. It is **not** Codex authorization.

| ID | Topic | Status | Revisit trigger | Why retained |
|---|---|---|---|---|
| WNBA-3L-003 | V2 learner-vs-gate decomposition audit | COMPLETE | Completed at WNBA commit `bc71d9442580fe69812d6dbad87545006aabdd4e` | Confirmed gate domination: A/D each had 2 beneficial challenger repairs and 1 harm pre-gate while `INF` blocked both beneficial actions |
| WNBA-3L-009 | Historical as-of gate R0 audit | NEXT_AUTHORIZED | Codex completes R0 and returns final WNBA SHA | Formalize the causal t<D learning procedure, audit temporal legality of base signals, cold start, and projected replay cost before any fitting/replay is authorized |
| WNBA-3L-007 | Cross-arm agreement gate | PARKED | R0 determines legal historical-as-of signal construction | Post-hoc A/B/D same-challenger + all-positive-margin pattern had 2 beneficial, 0 harmful, 13 neutral on 17 dates; promising but development-consumed and not independently OOS |
| WNBA-3L-010 | Pointwise proposal + relational witness gate | CANDIDATE_NEXT | R0 determines temporal legality/feasibility | Preferred strategic architecture if causal construction is possible: pointwise proposes who, relational evidence informs whether Atlas #1 should be challenged |
| WNBA-3L-008 | Honest gate evaluation authority | ACTIVE | R0 establishes causal evidence contract | Historical as-of procedure must use only settled t<D state; stored LODO outputs are not automatically time-causal because other folds may include future dates |
| WNBA-3L-004 | Selective use of prior pointwise logistic substitutions | PARKED | R0 determines legal historical-as-of pointwise reconstruction | Prior pointwise logistic remains best stored honest grouped-date OOF result at 22-7+1; broad rerank repaired four but damaged two and may deserve a selective/confidence gate |
| WNBA-3L-005 | Further relational learner research | PARKED | Gate/as-of approach resolved or fails | Existing A/D learner information is useful locally; do not spend another multi-hour learner sweep before testing confidence/gating logic |
| WNBA-3L-006 | Nonlinear/GBM local learner | REVISIT_ON_TRIGGER | Linear/relational and gate approaches exhausted with evidence and sample design supports honest OOS | High overfit risk on small WNBA date count; do not jump here casually |
| WNBA-4L-001 | Retest context interaction on final post-3L residual surface | PARKED | 3L method frozen and exact depletion established | Prior covered-control context diagnostic was 14-1 but incomplete; actual 4L surface changes with final 3L |
| WNBA-COMBO-001 | Combo-prop probability/math adjustments review | LATER | Core Builder work stabilizes or model-quality review is opened | Important previously discussed model-quality agenda; preserve so it is not forgotten |
| WNBA-FD-001 | Current-stack FromDeep research | LATER | Core 2L/3L/4L reaches FromDeep boundary | Separate Demon-OVER specialist family; current context overlap insufficient |
| WNBA-ROLL-001 | Chronological rolling/adaptive Builder learner | REVISIT_ON_TRIGGER | New temporal/regime evidence shows static ranking degradation not explained by difficulty/supply | Sophisticated but tedious; current 2L evidence did not justify reopening for rolling adaptation |
| WNBA-OPS-001 | Passive long-run heartbeat/watchdog observability | LATER | Before next multi-hour expensive learner | Future long work must expose passive progress/heartbeat/checkpoint/completion observability under Prime runway doctrine |
| PRIME-001 | Prime Delegation adoption and maintenance | ACTIVE | Ongoing | Keep Chat strategy and Codex execution separate while preserving thread recovery and long-term agenda memory |
