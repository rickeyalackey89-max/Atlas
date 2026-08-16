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
| WNBA-3L-011 | Historical as-of gate R1 actionability canary | COMPLETE | Completed at WNBA commit `6789f0a595bf3956f42146e8742005febd7cc080` | Causal machinery passed on first three targets, but final relational probe hit 900s watchdog; A/B/D full topology now projects ~5.1h while pointwise-only projects ~2.2m |
| WNBA-3L-012 | Full causal pointwise historical-as-of benchmark | NEXT_AUTHORIZED | Codex completes pointwise R2 and returns final WNBA SHA | Cheapest decisive benchmark: 30-date ledger, 29 strict prior-only pointwise fits, final-date parity, no relational work or gate tuning |
| WNBA-3L-013 | Relational execution-cost audit | CANDIDATE_NEXT | Causal pointwise survives R2 strongly enough to justify relational witnesses | Determine whether ~5.1h A/B/D cost is irreducible nested-selection cost or removable implementation overhead without changing statistical procedure |
| WNBA-3L-007 | Cross-arm agreement gate | PARKED | Pointwise R2 plus relational cost audit justify further spend | G1 remains scientifically plausible but current full prior-only A/B/D topology is too expensive to authorize under runway doctrine |
| WNBA-3L-010 | Pointwise proposal + relational witness gate | PARKED | Pointwise R2 survives and relational execution becomes acceptably efficient or user explicitly accepts long runtime | Preferred hybrid architecture conceptually, but not worth a ~5.1h run until the cheap pointwise causal benchmark is known |
| WNBA-3L-008 | Honest gate evaluation authority | ACTIVE | Historical-as-of pointwise/R1/R2 evidence establishes causal implementation basis | All adaptive historical decisions must use only settled `t<D` state and seal selection before D settlement is opened |
| WNBA-3L-004 | Selective use of prior pointwise logistic substitutions | ACTIVE | Pointwise R2 determines causal pointwise behavior | Stored grouped-date OOF was 22-7+1; R2 now tests whether that signal survives strict historical-as-of regeneration |
| WNBA-3L-005 | Further relational learner research | PARKED | Gate/as-of approach resolved or fails | Existing relational architecture is enough for current gate research; do not launch another broad learner sweep first |
| WNBA-3L-006 | Nonlinear/GBM local learner | REVISIT_ON_TRIGGER | Linear/relational and gate approaches exhausted with evidence and sample design supports honest OOS | High overfit risk on small WNBA date count; do not jump here casually |
| WNBA-4L-001 | Retest context interaction on final post-3L residual surface | PARKED | 3L method frozen and exact depletion established | Prior covered-control context diagnostic was 14-1 but incomplete; actual 4L surface changes with final 3L |
| WNBA-COMBO-001 | Combo-prop probability/math adjustments review | LATER | Core Builder work stabilizes or model-quality review is opened | Important previously discussed model-quality agenda; preserve so it is not forgotten |
| WNBA-FD-001 | Current-stack FromDeep research | LATER | Core 2L/3L/4L reaches FromDeep boundary | Separate Demon-OVER specialist family; current context overlap insufficient |
| WNBA-ROLL-001 | Chronological rolling/adaptive Builder learner | REVISIT_ON_TRIGGER | New temporal/regime evidence shows static ranking degradation not explained by difficulty/supply | Sophisticated but tedious; current 2L evidence did not justify reopening for rolling adaptation |
| WNBA-OPS-001 | Passive long-run heartbeat/watchdog observability | LATER | Before next multi-hour expensive learner | Future long work must expose passive progress/heartbeat/checkpoint/completion observability under Prime runway doctrine |
| PRIME-001 | Prime Delegation adoption and maintenance | ACTIVE | Ongoing | Keep Chat strategy and Codex execution separate while preserving thread recovery and long-term agenda memory |
