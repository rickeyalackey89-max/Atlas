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
| WNBA-3L-011 | Historical as-of gate R1 actionability canary | COMPLETE | Completed at WNBA commit `6789f0a595bf3956f42146e8742005febd7cc080` | Causal machinery passed on first three targets, but final relational probe hit 900s watchdog; A/B/D full topology projects ~5.1h while pointwise-only is cheap |
| WNBA-3L-012 | Full causal pointwise historical-as-of benchmark | COMPLETE | Completed at WNBA commit `5eb96d83996e3f65c2ce021a5a3897b43f63da04` | Strict `t<D` pointwise produced 24-6-0 versus 20-9-1 control; four repairs, one harm, one NB->WIN, exact final-date parity, 29 fits in ~10.1s |
| WNBA-3L-015 | Causal pointwise freeze-readiness / residual forensic R0 | NEXT_AUTHORIZED | Codex completes authorized R0 and returns final WNBA SHA | Verify freeze-contract completeness, anatomize Jul07/Jul28/Aug01/Aug08/Aug13 plus Jul08 supply-impossible, and inventory exact already-generated 4L residual after pointwise exact-road depletion |
| WNBA-3L-014 | Causal pointwise 3L research freeze decision | CANDIDATE_NEXT | Freeze-readiness R0 passes and user/Chat review recommendation | 24-6-0 procedural evidence is strong enough to consider pointwise the working 3L backbone, but actual freeze remains a separate user decision |
| WNBA-3L-013 | Relational execution-cost audit | PARKED | Only if pointwise backbone still needs a witness layer after freeze decision | Current A/B/D full causal topology projects ~5.1h; do not spend that compute unless incremental value over 24-6-0 pointwise is clearly necessary |
| WNBA-3L-007 | Cross-arm agreement gate | PARKED | Pointwise freeze decision plus relational cost audit justify further spend | G1 remains scientifically plausible but current full prior-only A/B/D topology is too expensive under runway doctrine |
| WNBA-3L-010 | Pointwise proposal + relational witness gate | PARKED | Pointwise backbone is accepted but residual failure analysis shows a witness layer is still warranted | Hybrid remains conceptually valid, but relational compute must earn its incremental value over causal pointwise 24-6-0 |
| WNBA-3L-008 | Honest gate evaluation authority | ACTIVE | Ongoing while adaptive historical evidence is used | All adaptive historical decisions must use only settled `t<D` state and seal selection before D settlement is opened |
| WNBA-3L-004 | Selective use of prior pointwise logistic substitutions | COMPLETE | Superseded by causal pointwise R2 | Stored grouped-date OOF was 22-7+1; strict historical-as-of pointwise is stronger at 24-6-0 and is the relevant current procedure evidence |
| WNBA-3L-005 | Further relational learner research | PARKED | Pointwise/gate route resolved or fails | Existing relational architecture is enough for current gate research; do not launch another broad learner sweep first |
| WNBA-3L-006 | Nonlinear/GBM local learner | REVISIT_ON_TRIGGER | Simpler causal pointwise/gate methods fail with evidence | High overfit risk on small WNBA date count; do not jump here casually |
| WNBA-4L-001 | Retest context interaction on final post-3L residual surface | PARKED | 3L method actually frozen and exact depletion established | Prior covered-control context diagnostic was 14-1 but incomplete; actual 4L research waits for the separate 3L freeze decision |
| WNBA-COMBO-001 | Combo-prop probability/math adjustments review | LATER | Core Builder work stabilizes or model-quality review is opened | Important previously discussed model-quality agenda; preserve so it is not forgotten |
| WNBA-FD-001 | Current-stack FromDeep research | LATER | Core 2L/3L/4L reaches FromDeep boundary | Separate Demon-OVER specialist family; current context overlap insufficient |
| WNBA-ROLL-001 | Chronological rolling/adaptive Builder learner | REVISIT_ON_TRIGGER | New temporal/regime evidence shows static ranking degradation not explained by difficulty/supply | Sophisticated but tedious; current 2L evidence did not justify reopening for rolling adaptation |
| WNBA-OPS-001 | Passive long-run heartbeat/watchdog observability | LATER | Before next multi-hour expensive learner | Future long work must expose passive progress/heartbeat/checkpoint/completion observability under Prime runway doctrine |
| PRIME-001 | Prime Delegation adoption and maintenance | ACTIVE | Ongoing | Keep Chat strategy and Codex execution separate while preserving thread recovery and long-term agenda memory |
