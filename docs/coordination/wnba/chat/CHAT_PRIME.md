# WNBA Chat Prime

Status: **strategic continuity snapshot; not operational authority**

Last strategic reconciliation: 2026-08-16

## Current strategic objective

Stabilize the stateful WNBA Builder families on the newest current-stack discovery corpus while preserving honest abstention and exact-road depletion.

Stateful core order remains:

`2L -> exact selected-road depletion -> 3L -> exact selected-road depletion -> 4L`

FromDeep remains separate.

## Statistical authority

Current Builder research uses the newest current-stack discovery corpus only:

- 39 discovery dates
- 30 applicable legal 3L dates after frozen 2L exact-road depletion
- 1,609 residual 3L candidates
- validation reads: 0
- lockbox reads: 0

BAP-1/BAP-2 may inform historical methodology only. They must not contribute current training/evaluation rows unless explicitly reauthorized in a future governed task.

## 2L

Frozen and unchanged.

- control/frozen performance: 32 WIN / 7 LOSS
- exact-road depletion only
- no player-wide depletion
- timing/context/allocator investigations did not justify reopening 2L
- current disposition: keep frozen

## 3L control and forensic

Current exact control:

- 20 WIN / 9 LOSS / 1 NONBINARY
- 8 true within-date ranking failures
- 1 supply-impossible loss: 2026-07-08

The primary problem is top-of-rank discrimination, not broad candidate supply.

Six of the eight repairable loss dates had a legal winner inside the current Atlas top five.

## Prior 3L pointwise logistic

Stored grouped-date OOF result:

- 22 WIN / 7 LOSS / 1 NONBINARY
- repaired 2026-07-03, 2026-07-06, 2026-07-07, 2026-07-31
- damaged 2026-07-02 and 2026-08-01
- candidate-wide within-date AUC approximately 0.492
- date-constant `slate_game_count` has zero within-date ordering contribution

Interpretation: some multivariate substitution signal exists, but broad reranking is unstable.

## Pairwise V1

V1 protected pairwise result:

- 19 WIN / 10 LOSS / 1 NONBINARY
- 0/8 repairs
- one harmful override

V1 trained only from top-five mixed WIN/LOSS contexts, reducing the useful pair-training surface to 10 contributing dates and 48 unordered pairs.

Accepted interpretation: V1 failed one narrow architecture; it did not prove pairwise learning generally useless.

## Relational Sweep V2

Original V2 commit:

`879c1c4455821094f7ffc754a557a6097a2988ba`

Official gated action output was 20-9-1 for all four arms and emitted `NO_RELATIONAL_SIGNAL_FOUND`.

That phrase is superseded for Chat strategy by the completed learner-vs-gate decomposition at:

`bc71d9442580fe69812d6dbad87545006aabdd4e`

Primary diagnostic conclusion:

`V2_GATE_DOMINATED_USEFUL_CHALLENGER_SIGNAL`

This is development-consumed post-settlement diagnostic evidence only. It does not promote a learner or gate.

### Arm-level decomposition

- V2-A ungated challenger counterfactual: 22-8-0; 2 beneficial substitutions, 1 harmful, net +1. Repairs: 2026-07-06 and 2026-07-31. Harm: 2026-08-01. `INF` gate on 27/30 dates; both beneficial challengers were blocked by `INF`.
- V2-B: 21-9-0; 2 beneficial, 2 harmful, net 0. `INF` on 28/30. Disposition remains weak/unstable.
- V2-C: 22-8-0; 3 beneficial, 2 harmful, net +1. Repairs: 2026-07-03, 2026-07-06, 2026-07-07. Harms: 2026-06-19 and 2026-07-02. `INF` on 30/30. Despite these local repairs, prior V2-C discrimination diagnostics were weak, so C remains weak/unstable rather than promoted.
- V2-D: 22-8-0; 2 beneficial, 1 harmful, net +1. Repairs: 2026-07-06 and 2026-07-31. Harm: 2026-08-01. `INF` on 29/30; both beneficial challengers were blocked by `INF`.

No finite threshold blocked a beneficial challenger in any arm. The dominant action failure was the nested `INF` / never-override gate.

### Consensus signal

A and D selected the same challenger on 26/30 dates. On the 19 A/D-consensus dates where both incumbent-relative margins were positive, the challenger classifications were:

- 2 beneficial
- 1 harmful
- 14 neutral
- 1 nonbinary
- 1 supply-impossible

The two repaired ranking failures were 2026-07-06 and 2026-07-31; the harmful date was 2026-08-01.

A/B/D selected the same challenger on 23/30 dates. On the 17 three-way-consensus dates where all three incumbent-relative margins were positive:

- 2 beneficial
- 0 harmful
- 13 neutral
- 1 nonbinary
- 1 supply-impossible

Those two beneficial dates were again 2026-07-06 and 2026-07-31.

This three-way positive-consensus pattern is strategically important because, if it had been a predeclared rule, those two repairs with no damaged control wins would move the 20-9-1 control to 22-7-1 while changing far fewer decisions than the prior pointwise logistic. **However, the rule was identified after discovery settlement was visible, so that 22-7-1 implication is post-hoc diagnostic only and must not be represented as OOS performance.**

### Relationship to pointwise logistic

The prior pointwise learner repaired four dates and damaged two. V2-A/D correctly identify only the 2026-07-06 and 2026-07-31 subset and share the 2026-08-01 damage; they do not identify a correct substitution that the pointwise learner missed. The pointwise learner additionally repairs 2026-07-03 and 2026-07-07.

V2-C captures 2026-07-03, 2026-07-06, and 2026-07-07 but misses 2026-07-31 and introduces different damage on 2026-06-19 and 2026-07-02.

Interpretation: the relational arms contain useful local challenger information, but no current arm is independently strong enough for promotion. The most promising new information is **cross-arm agreement/disagreement as a potential confidence signal**, not a claim that one relational learner has become the champion.

## Immediate research question

The decomposition is complete. Do not run another expensive learner automatically.

The next strategic problem is to design an **honest predeclared selective gate experiment** that tests whether model agreement can convert relational challenger signal without damaging strong control wins.

Primary candidate hypothesis for discussion:

`A/B/D same challenger + all three incumbent-relative margins positive -> candidate override condition`

Secondary comparison hypothesis:

selectively gate the stored pointwise logistic rather than using its broad rerank.

Important methodological boundary: these exact gate ideas were informed by already-open discovery outcomes. Their retrospective discovery results have zero promotion authority. A future claim requires an honest evaluation route chosen before outcomes are read: prospective evidence, explicitly authorized unopened validation/lockbox use, or a newly generated leakage-safe cross-fit architecture. Validation and lockbox remain unopened pending explicit user authorization.

## 4L

Do not begin final 4L research until final 3L methodology and exact post-3L residual surface are established.

A prior context diagnostic produced a large result on only a covered subset (14-1 versus 9-6 control on 15/23 covered controls), but eight controls were uncovered. Preserve as a later hypothesis only.

## FromDeep

Separate specialist lane. Current-stack context sweep lacked sufficient graded canonical overlap. Leave untouched until core 2L/3L/4L work reaches the appropriate boundary.

## Live

Live remains RC1 with RP24 and must remain independent of Builder discovery research.

No current Chat strategy authorizes a Live/model/minutes/allocator/calibration/QMC/dependence change.
