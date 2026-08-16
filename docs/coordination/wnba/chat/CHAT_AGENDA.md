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
| WNBA-3L-009 | Historical as-of gate R0 audit | COMPLETE | Completed at WNBA commit `f2e40be6d1beff5db0e6ed1dc178a68d21f9b512` | Established strict `t<D` legality: stored pointwise/V2 LODO outputs require prior-only regeneration on 29/30 targets; pretruth candidate/rank and frozen 2L surfaces remain reusable |
| WNBA-3L-011 | Historical as-of gate R1 actionability canary | CANDIDATE_NEXT | User authorizes next runway tier after R0 review | Cheap canary should prove prior-only regeneration, cold start, time-arrow sealing, signal/action variation, caching, and measured runtime before any replay-scale spend |
| WNBA-3L-007 | Cross-arm agreement gate | PARKED | R1 proves A/B/D prior-only regeneration and actionability | G1 is feasible but requires prior-only A/B/D regeneration; no fixed agreement predicate has been selected yet |
| WNBA-3L-010 | Pointwise proposal + relational witness gate | CANDIDATE_NEXT | R1 proves both pointwise and A/B/D prior-only regeneration | Preferred strategic architecture: pointwise proposes who, relational evidence informs whether Atlas #1 should be challenged; G3 projected full causal regeneration 15-45 minutes with shared caches |
| WNBA-3L-008 | Honest gate evaluation authority | ACTIVE | R1/R2 establish causal implementation evidence | Historical as-of procedure must use only settled `t<D` state; stored grouped-date OOF/LODO outputs are not causal inputs when later-than-D training entered state |
| WNBA-3L-004 | Selective use of prior pointwise logistic substitutions | PARKED | R1 proves prior-only pointwise regeneration | G2 is feasible and low-cost; stored 22-7+1 remains grouped-date OOF evidence, not direct historical-as-of sequence |
| WNBA-3L-005 | Further relational learner research | PARKED | Gate/as-of approach resolved or fails | Existing relational architecture is enough for current gate research; do not launch another broad learner sweep first |
| WNBA-3L-006 | Nonlinear/GBM local learner | REVISIT_ON_TRIGGER | Linear/relational and gate approaches exhausted with evidence and sample design supports honest OOS | High overfit risk on small WNBA date count; do not jump here casually |
| WNBA-4L-001 | Retest context interaction on final post-3L residual surface | PARKED | 3L method frozen and exact depletion established | Prior covered-control context diagnostic was 14-1 but incomplete; actual 4L surface changes with final 3L |
| WNBA-COMBO-001 | Combo-prop probability/math adjustments review | LATER | Core Builder work stabilizes or model-quality review is opened | Important previously discussed model-quality agenda; preserve so it is not forgotten |
| WNBA-FD-001 | Current-stack FromDeep research | LATER | Core 2L/3L/4L reaches FromDeep boundary | Separate Demon-OVER specialist family; current context overlap insufficient |
| WNBA-ROLL-001 | Chronological rolling/adaptive Builder learner | REVISIT_ON_TRIGGER | New temporal/regime evidence shows static ranking degradation not explained by difficulty/supply | Sophisticated but tedious; current 2L evidence did not justify reopening for rolling adaptation |
| WNBA-OPS-001 | Passive long-run heartbeat/watchdog observability | LATER | Before next multi-hour expensive learner | Future long work must expose passive progress/heartbeat/checkpoint/completion observability under Prime runway doctrine |
| PRIME-001 | Prime Delegation adoption and maintenance | ACTIVE | Ongoing | Keep Chat strategy and Codex execution separate while preserving thread recovery and long-term agenda memory |
