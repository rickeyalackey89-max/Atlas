# WNBA 3L V2 Gate Decomposition — Strategic Checkpoint

Date: 2026-08-16

WNBA evidence commit:

`bc71d9442580fe69812d6dbad87545006aabdd4e`

## Why this checkpoint exists

The original four-arm V2 relational sweep returned the exact control result (20-9-1) for all arms and emitted `NO_RELATIONAL_SIGNAL_FOUND`. Chat/user review challenged that interpretation because the nested override layer frequently selected `INF`, mechanically preventing challenger action.

A user-authorized no-refit decomposition was then run on the already-sealed OOS challenger scores and already-open discovery settlement.

## Accepted result

Primary diagnosis:

`V2_GATE_DOMINATED_USEFUL_CHALLENGER_SIGNAL`

No learner was refit. No outer fold was rerun. Validation reads remained 0. Lockbox reads remained 0. Live/model authority was unchanged.

### A

Ungated challenger counterfactual: 22-8-0.

- beneficial: 2 — Jul06, Jul31
- harmful: 1 — Aug01
- net: +1
- `INF`: 27/30
- both beneficial challengers blocked by `INF`

### B

Ungated: 21-9-0.

- beneficial: 2
- harmful: 2
- net: 0
- `INF`: 28/30

Disposition: weak/unstable.

### C

Ungated: 22-8-0.

- beneficial: 3 — Jul03, Jul06, Jul07
- harmful: 2 — Jun19, Jul02
- net: +1
- `INF`: 30/30

Disposition remains weak/unstable because broader V2-C discrimination evidence was poor even though local challenger choices sometimes repaired losses.

### D

Ungated: 22-8-0.

- beneficial: 2 — Jul06, Jul31
- harmful: 1 — Aug01
- net: +1
- `INF`: 29/30
- both beneficial challengers blocked by `INF`

## Consensus discovery

A/D selected the same challenger on 26/30 dates. When both margins were positive: 2 beneficial, 1 harmful, 14 neutral, 1 nonbinary, 1 supply-impossible.

A/B/D selected the same challenger on 23/30 dates. When all three margins were positive: 2 beneficial, 0 harmful, 13 neutral, 1 nonbinary, 1 supply-impossible.

The two beneficial three-way-consensus dates were Jul06 and Jul31.

If the three-way positive-consensus condition had been predeclared, those two repairs with no damaged control wins would imply 22-7-1 from the 20-9-1 control. It was **not** predeclared, so this is post-hoc development evidence only and has zero promotion authority.

## Pointwise comparison

Stored pointwise logistic remains 22-7-1, repairing Jul03, Jul06, Jul07, Jul31 while damaging Jul02 and Aug01.

A/D capture the Jul06/Jul31 subset and the Aug01 damage, while missing Jul03/Jul07. They identify no correct substitution that pointwise misses.

The strategic opportunity is therefore not "replace pointwise with A/D." It is to investigate whether cross-arm agreement/disagreement can serve as a confidence gate that preserves strong control wins with fewer substitutions.

## Next unresolved decision

Choose an honest evaluation route before testing a gate informed by these outcomes.

Candidate hypotheses:

1. A/B/D same challenger + all three incumbent-relative margins positive.
2. A selective confidence gate around the stored pointwise logistic.
3. A predeclared comparison of the two if a leakage-safe evaluation design can be constructed.

Discovery outcomes have already informed these hypotheses. Their retrospective performance cannot be treated as OOS. Validation and lockbox remain unopened pending explicit user authorization.
