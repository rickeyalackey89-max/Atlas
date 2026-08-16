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
- repaired four control losses
- damaged two control wins
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

Commit reviewed: `879c1c4455821094f7ffc754a557a6097a2988ba`

Official V2 settlement output:

- V2-A: 20-9-1
- V2-B: 20-9-1
- V2-C: 20-9-1
- V2-D: 20-9-1

Official code labeled the comparative conclusion `NO_RELATIONAL_SIGNAL_FOUND`.

### Chat strategic correction

Do **not** treat that label as proof that relational signal is absent.

The experiment coupled two questions:

1. can the learner identify a stronger challenger?
2. will a nested override-threshold policy permit the challenger to replace Atlas rank #1?

The threshold layer frequently selected `INF` / KEEP-ALL, collapsing the action result back to control.

Concrete evidence:

- 2026-07-06: V2-A and V2-D selected challenger `wnba_candidate_44e71fdfd5fab086425b647a`, which the earlier forensic identifies as the best-ranked winning candidate, but the threshold was `INF`, so the losing incumbent remained selected.
- 2026-07-31: V2-A/V2-B/V2-D selected challenger `wnba_candidate_b2798bab67a1c202c9f7a4ac`, which the earlier forensic identifies as the best-ranked winning candidate, but the threshold was `INF`, so the losing incumbent remained selected.

V2-A/D also showed date-balanced relational AUC above 0.55 on multiple surfaces. V2-A full residual AUC was ~0.558 and top-20 ~0.573; V2-D full residual ~0.559.

The V2 comparative classifier itself required both a discrimination signal and at least one **acted beneficial override** to emit `RELATIONAL_SIGNAL_EXISTS_BUT_UNSTABLE`. Because the gate suppressed beneficial actions, the code fell through to `NO_RELATIONAL_SIGNAL_FOUND` even when its own AUC condition identified relational discrimination.

Current Chat disposition:

`RELATIONAL_SIGNAL_WEAK_OR_UNSTABLE_AND_OVERRIDE_GATE_CONFOUNDED`

This is a strategic interpretation only, not a new statistical authority or promotion.

V2-C is the weakest arm and is more directly negative: beneficial-override ROC AUC ~0.314 and PR AUC ~0.054 versus prevalence ~0.077.

## Immediate research question

Before another expensive learner run, decompose V2 learner quality from override-gate quality using the already-sealed OOS candidate scores and already-open discovery settlement.

No refit is required for the first diagnostic.

The next useful question is:

**How often did each V2 architecture identify a winning challenger on control-loss dates before the threshold gate, and what was the counterfactual beneficial/harmful substitution frontier of the already-sealed OOS challenger scores?**

This diagnostic may guide a future predeclared gate or learner experiment but cannot itself promote a threshold selected after settlement.

## 4L

Do not begin final 4L research until final 3L methodology and exact post-3L residual surface are established.

A prior context diagnostic produced a large result on only a covered subset (14-1 versus 9-6 control on 15/23 covered controls), but eight controls were uncovered. Preserve as a later hypothesis only.

## FromDeep

Separate specialist lane. Current-stack context sweep lacked sufficient graded canonical overlap. Leave untouched until core 2L/3L/4L work reaches the appropriate boundary.

## Live

Live remains RC1 with RP24 and must remain independent of Builder discovery research.

No current Chat strategy authorizes a Live/model/minutes/allocator/calibration/QMC/dependence change.
