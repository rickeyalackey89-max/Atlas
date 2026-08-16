# WNBA 3L — V2 Learner-vs-Gate Decomposition

Status: **USER AUTHORIZED / EXECUTION-READY DELEGATION**

Prime Delegation is not WNBA workflow authority. Codex must reconcile this user-authorized task into the existing `slip-builders` lane and obey WNBA `AGENTS.md`, the active Builder pointer, work order, state, evidence registry, and process manifest. Do not create a second controller.

## User decision

The user accepts the official V2 action results as faithful outputs, but does **not** accept `NO_RELATIONAL_SIGNAL_FOUND` as a scientific conclusion because the learner and override gate were confounded.

The user authorizes one cheap, post-settlement diagnostic that decomposes learner challenger quality from override-threshold behavior using only already-sealed V2 OOS outputs and already-open discovery settlement.

## Starting WNBA authority

Repository: `rickeyalackey89-max/Atlas-WNBA`

Canonical local root: `C:\Users\13142\Atlas\WNBA`

Branch: `builder-method-contract-v1`

Expected starting HEAD / direct remote SHA:

`879c1c4455821094f7ffc754a557a6097a2988ba`

Expected active stop:

`BLOCKED_USER_REVIEW_WNBA_3L_RELATIONAL_ARCHITECTURE_SWEEP_V2`

Expected active step:

`builder_s5_3l_relational_sweep_v2_user_review`

If branch, HEAD, active Builder state, or bound authorities have changed, stop and report the mismatch. Do not pull/rebase/reset/merge automatically.

## Statistical authority

Current-stack corpus only:

- 39 discovery dates
- 30 applicable legal 3L dates
- 1,609 residual 3L candidates
- zero BAP-1 statistical rows
- validation reads = 0
- lockbox reads = 0

Do not use BAP-1/BAP-2 rows for fitting, evaluation, threshold selection, or counterfactual scoring.

## Bound V2 evidence

Pin the diagnostic to V2 commit:

`879c1c4455821094f7ffc754a557a6097a2988ba`

Required sealed inputs include:

- `THREEL_RELATIONAL_SWEEP_GLOBAL_SELECTION_SEAL_V2.json`
  - SHA256 `5c7e949b540916bede75f4cac7ab6f6b43cb1769d6eaaa31e3bab8b95e88812c`
- `three_leg_relational_candidate_scores_pre_settlement.csv.gz`
  - SHA256 `8e4d8439bb9b5cdf507c279263bae413eae808ea56f3e3da53893bed2aa1f250`
- `three_leg_relational_substitution_ledger.csv`
  - SHA256 `64c7744215936517c9994039713ea7e7929d08cf41e9ebcf19296a7e3a19b5d7`
- `THREEL_RELATIONAL_SWEEP_DIAGNOSTICS_V2.json`
  - SHA256 `fcc70d6091e82ce92e3542fe0d65919d89cfa119fb4b3010063762b99ad6cc80`
- `THREEL_RELATIONAL_SWEEP_SUMMARY_V2.json`
  - SHA256 `185f959ddab8617ce2e5c0ba31da3837f0f802beb56a3d4db35e495579207190`

Also use the already-sealed 3L forensic loss packet and stored pointwise-logistic transition evidence as comparison-only inputs. Resolve and record their exact current hashes before analysis.

If any required V2 artifact differs from the committed manifest, stop.

## Purpose

Answer one question:

**What did each V2 learner identify before the override gate, and how much of the final 20-9-1 collapse was caused by the gate rather than by the learner?**

This is a diagnostic only. It may guide a later predeclared experiment. It cannot promote a model, learner, or threshold.

## Explicitly prohibited

Do not:

- refit V2-A/B/C/D;
- rerun nested LODO;
- rerun the 30 outer folds;
- change the V2 feature basis;
- change C values;
- tune or install a threshold;
- create a fifth architecture;
- regenerate candidates;
- alter frozen 2L;
- alter 3L control;
- begin 4L;
- begin FromDeep;
- read validation or lockbox outcomes;
- mutate RP24, minutes, allocator, calibration, QMC, dependence, RC1, rolling evidence, maintenance, publication, or Live;
- claim a post-hoc threshold as OOS authority.

No model fitting is authorized.

## Required diagnostic A — pre-gate challenger ledger

For every one of the 30 applicable dates and each of V2-A/B/C/D, report from the already-sealed OOS selection/candidate-score artifacts:

- control candidate/result;
- learner-preferred top-5 challenger;
- challenger Atlas rank;
- native score or incumbent-relative margin;
- training-derived threshold actually used;
- whether threshold was finite or `INF`;
- official KEEP/OVERRIDE decision;
- challenger settlement result;
- counterfactual classification if the challenger had been used:
  - `BENEFICIAL_CHALLENGER`
  - `HARMFUL_CHALLENGER`
  - `NEUTRAL_CHALLENGER`
  - `NONBINARY`
  - `SUPPLY_IMPOSSIBLE` where applicable.

Do not alter any sealed V2 decision.

## Required diagnostic B — eight rank-failure dates

For these exact dates:

- 2026-06-20
- 2026-07-03
- 2026-07-06
- 2026-07-07
- 2026-07-28
- 2026-07-31
- 2026-08-08
- 2026-08-13

report for A/B/C/D:

- learner challenger ID and exact roads;
- challenger rank;
- challenger WIN/LOSS;
- whether it equals the forensic best-ranked winner;
- whether another legal top-5 winner existed;
- learner margin over incumbent;
- actual threshold;
- whether a beneficial repair was blocked by `INF` or by a finite threshold;
- whether the learner chose a loser even before the gate.

Explicitly verify the known examples:

- 2026-07-06: V2-A and V2-D challenger `wnba_candidate_44e71fdfd5fab086425b647a`;
- 2026-07-31: V2-A/V2-B/V2-D challenger `wnba_candidate_b2798bab67a1c202c9f7a4ac`.

If either known example does not reproduce exactly, stop and report parity failure.

## Required diagnostic C — ungated challenger counterfactual

For each architecture independently, compute the purely diagnostic result of always taking the learner's already-sealed top-5 challenger instead of the incumbent.

Report:

- wins/losses/nonbinary;
- beneficial substitutions;
- harmful substitutions;
- neutral substitutions;
- net beneficial minus harmful;
- the exact repaired control-loss dates;
- the exact broken control-win dates;
- challenger success on winner-supplied dates.

This is **not** a proposed production policy. It is decomposition evidence only.

## Required diagnostic D — gate effect

For each architecture report:

- count of target dates with `INF` threshold;
- count with finite threshold;
- beneficial challengers blocked by `INF`;
- beneficial challengers blocked by finite threshold;
- harmful challengers blocked by `INF`;
- harmful challengers blocked by finite threshold;
- neutral challengers blocked;
- beneficial/harmful/neutral actions actually allowed;
- percentage of dates on which the final result was mechanically forced to control by `INF`.

Then answer:

**Was the final action result primarily learner-limited, gate-limited, or both?**

## Required diagnostic E — score/margin separation frontier

Using the already-sealed OOS challenger scores and already-open discovery settlement, build a **post-hoc diagnostic frontier only**.

For each architecture:

- distribution of challenger score/margin for beneficial, harmful, and neutral substitutions;
- medians and quantiles;
- rank-biserial/AUC or equivalent separation where identifiable;
- every unique/meaningful score threshold frontier, or a compact deterministic set if uniqueness is excessive;
- at each diagnostic threshold: override count, beneficial, harmful, neutral, net, control-win preservation, churn.

This frontier has **zero promotion authority** because outcomes are already visible. Its only purpose is to determine whether a future predeclared gate experiment is worth running.

Do not choose a 'best' threshold and install it.

## Required diagnostic F — A/D and multi-arm consensus

Because A and D showed the strongest relational AUC, report:

- dates where A and D select the same challenger;
- outcome distribution of those consensus challengers;
- beneficial/harmful/neutral counts when both have positive incumbent-relative margin;
- same analysis for A/B/D three-way consensus where available;
- rank-failure dates repaired by consensus challenger selection.

This is diagnostic only.

## Required diagnostic G — pointwise logistic comparison

Compare the stored prior pointwise-logistic result (22-7+1; four repairs, two damages) against sealed V2 pre-gate challenger behavior.

Report:

- overlap in repaired dates;
- overlap in damaged dates;
- candidate identity overlap where available;
- whether V2 A/D identify any correct substitutions the pointwise learner misses;
- whether pointwise identifies correct substitutions A/D miss.

Do not refit the pointwise learner.

## Required dispositions

Return one primary diagnosis:

- `V2_GATE_DOMINATED_USEFUL_CHALLENGER_SIGNAL`
- `V2_RELATIONAL_CHALLENGER_SIGNAL_WEAK_OR_UNSTABLE`
- `V2_RELATIONAL_CHALLENGER_SIGNAL_NOT_SUPPORTED`
- `V2_DECOMPOSITION_INCONCLUSIVE`

Also separately classify each arm A-D.

Do **not** reuse `NO_RELATIONAL_SIGNAL_FOUND` merely because no official gated beneficial override occurred.

## Expected runtime/resource class

This should be a cheap artifact-analysis diagnostic, not a multi-hour learner run.

No nested fitting or outer-fold recomputation is authorized.

If implementation attempts to launch expensive fitting, stop.

## Outputs

Create a compact diagnostic directory under the existing Builder Stage 5 development area, with at minimum:

- `THREEL_V2_LEARNER_GATE_DECOMPOSITION_SUMMARY.json`
- `THREEL_V2_LEARNER_GATE_DECOMPOSITION_REVIEW.md`
- `three_leg_v2_pregate_challenger_ledger.csv`
- `three_leg_v2_rank_failure_decomposition.csv`
- `three_leg_v2_ungated_counterfactual.csv`
- `three_leg_v2_gate_effect.csv`
- `three_leg_v2_score_frontier.csv`
- `three_leg_v2_consensus_diagnostic.csv`
- `three_leg_v2_pointwise_comparison.csv`
- artifact manifest / hashes

Preserve existing V2 artifacts byte-for-byte.

## Control / validation

Before execution:

- canonical WNBA guard must pass;
- reconcile this user authorization through `slip-builders` as the sole controller;
- use the narrowest existing approved machine test class permitted by the lane; do not invent a new machine test class;
- mark evidence as diagnostic / development-consumed, never promotion authority;
- bind exact authorized paths before mutation.

After execution:

- governing Builder lane validator passes;
- method-contract validator passes;
- focused positive tests pass;
- adversarial test proves no fitting path is invoked;
- adversarial test proves V2 sealed selections/artifacts are unmodified;
- validation reads = 0;
- lockbox reads = 0.

## Git

WNBA standing Git rules remain binding:

- exact-path staging only;
- never `git add .`, `git add -A`, `git add --all`;
- never `git clean`, `git reset --hard`, or force push;
- protected stash untouched.

After validators pass, commit and push authorized WNBA changes and verify local HEAD == tracking ref == direct remote ref.

## Return

Return:

1. starting authority proof;
2. exact bound input hashes;
3. proof no refit/rerun occurred;
4. 30-date pre-gate challenger census;
5. exact eight-loss decomposition;
6. ungated counterfactual result A-D;
7. gate effect A-D;
8. count/list of beneficial repairs blocked by `INF`;
9. count/list blocked by finite thresholds;
10. score/margin separation diagnostics;
11. A/D and A/B/D consensus results;
12. comparison with stored 22-7+1 pointwise logistic;
13. arm-specific dispositions;
14. primary decomposition diagnosis;
15. whether a future predeclared gate experiment is warranted;
16. validation reads;
17. lockbox reads;
18. tests/validators;
19. changed paths;
20. commit SHA and local/remote equality.

Final stop marker:

`BLOCKED_USER_REVIEW_WNBA_3L_V2_LEARNER_GATE_DECOMPOSITION`
