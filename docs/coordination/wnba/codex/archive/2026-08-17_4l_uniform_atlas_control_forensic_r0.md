# WNBA 4L Uniform Atlas Control Forensic R0

Status: **USER AUTHORIZED**

User authorization: `go` on 2026-08-17 after Chat proposed the sealed uniform-surface Atlas 4L control forensic.

Execution tier: **R0_ARTIFACT_FORENSIC**

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`fd0df85a70559d830cd2ae5e76a711453a9f4dca`

Expected Builder stop before execution:

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`

## Purpose

Establish the canonical Atlas 4L control baseline and loss/rank anatomy on the accepted uniform post-depletion R2 candidate surface **without regenerating candidates or fitting any learner**.

This task answers one question:

> On the correctly constructed, pretruth-sealed stateful 4L surface, how often does the frozen canonical Atlas rank-1 candidate win, and when it loses is the failure primarily ranking or absence of any winning candidate on the sealed 96-candidate/date surface?

## Binding authority

Bind exactly to the accepted R2 evidence from WNBA commit:

`fd0df85a70559d830cd2ae5e76a711453a9f4dca`

Required accepted R2 invariants:

- disposition `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_PASS`;
- 23 structurally eligible 3+ game dates;
- exactly 2,208 candidates;
- exactly 96 candidates per eligible date;
- one uniform post-depletion stateful lineage;
- four R1 canary continuity checks passed;
- pretruth seal status `UNIFORM_OUTCOME_BLIND_23_DATE_4L_SURFACE_SEALED`;
- sealed R2 candidate/context/score artifacts and hashes are immutable inputs for this forensic.

Primary R2 authority artifacts include the sealed manifest/summary, exact ordered date census, candidate surface, annotated surface, score ledger, depletion ledger, and `UNIFORM_4L_PRETRUTH_SEAL.json` under the current Builder Stage-5 R2 artifact directory.

Do not substitute the historical 481-candidate / 15-date materialized surface.

## Prime / Builder control reconciliation

The paused Builder control may still be bound to an older Prime coordination hash because Prime advanced during the operational eval-recovery detour.

Before any Builder outcome read:

1. validate canonical WNBA workspace and current builder lane;
2. classify any current Prime-hash mismatch as `control_divergence` if the governing controller requires it;
3. reconcile current Prime authority **only through the existing governed Builder controller/process-only rebind mechanism** if such a legal mechanism exists;
4. do not manually edit hash-bound Builder controls to make validation pass;
5. do not change Builder method, candidate surface, ranking, depletion, folds, thresholds, or evidence semantics during reconciliation;
6. if no existing governed control-only reconciliation path exists, fail closed and report the exact blocker rather than inventing one.

Any required control-only reconciliation is subordinate to this authorized forensic and creates no methodological change.

## Outcome-consumption boundary — critical

This task may open **only Builder-development-consumed discovery outcomes**.

Operational prior-day eval creation does not itself make an outcome Builder-development-consumed.

Before grading any candidate:

1. inspect the current Builder evidence registry / outcome-consumption authority for each of the 23 sealed R2 dates;
2. classify each date as exactly one of:
   - `DEVELOPMENT_CONSUMED_ALLOWED`,
   - `UNCONSUMED_WITHHELD`,
   - `PROTECTED_VALIDATION_WITHHELD`,
   - `PROTECTED_LOCKBOX_WITHHELD`,
   - `AUTHORITY_UNCLEAR_FAIL_CLOSED`;
3. grade only `DEVELOPMENT_CONSUMED_ALLOWED` dates;
4. do not open candidate/leg outcomes for any withheld date;
5. if authority is unclear for any date, withhold it and report the blocker.

Expected strategic caution: `2026-08-13` was outcome-unconsumed at R2 seal time and its later operational eval does **not** automatically authorize Builder development use. Do not consume it unless current governing evidence explicitly proves it was already development-consumed independently of this task.

Validation reads must remain `0`.

Lockbox reads must remain `0`.

## Canonical control definition

For each graded date:

- use the exact sealed 96-candidate R2 population;
- preserve the sealed canonical Atlas ordering from the R2 score ledger;
- canonical control selection = the exact Atlas rank-1 candidate under that sealed ordering;
- do not recompute scores using a different candidate population;
- do not rerank, refit, tune, filter, gate, or apply a challenger;
- use the repository's canonical candidate identity and canonical settlement/slip-result semantics.

If the rank-1 candidate is not fully gradable under canonical settlement semantics, classify it faithfully (for example `NONBINARY`) rather than forcing a binary result.

## Required forensic outputs

Write a compact, hash-bound artifact set under a new Stage-5 forensic directory without mutating the sealed R2 artifacts.

At minimum produce:

1. `ATLAS_4L_UNIFORM_CONTROL_FORENSIC_R0_SUMMARY.json`
2. `ATLAS_4L_UNIFORM_CONTROL_FORENSIC_R0_REVIEW.md`
3. `atlas_4l_uniform_control_by_date.csv`
4. `atlas_4l_first_winning_candidate_by_date.csv`
5. `atlas_4l_winning_rank_distribution.json`
6. `atlas_4l_outcome_consumption_census.csv`
7. `artifact_manifest.json`

### Per-date control ledger

For every one of the 23 sealed dates include:

- game date;
- R2 candidate count (must equal 96);
- outcome-consumption classification;
- whether outcome was opened by this task;
- canonical control candidate id;
- canonical Atlas rank;
- control result if graded;
- all four canonical leg identities for the control candidate;
- candidate Atlas score / QMC / other already-sealed control diagnostics needed to identify the selection;
- number of fully winning candidates on the sealed 96-candidate surface if graded;
- first winning candidate Atlas rank if one exists;
- first winning candidate id if one exists;
- failure class if control did not win.

### Loss classification

For every graded canonical control non-win, classify exactly:

- `RANKING_FAILURE_WINNER_EXISTS` — at least one fully winning candidate exists among the sealed 96 candidates;
- `NO_WINNING_CANDIDATE_ON_SEALED_SURFACE` — no fully winning candidate exists among the sealed 96;
- `CONTROL_NONBINARY` — control itself is nonbinary under canonical settlement semantics;
- `OUTCOME_INCOMPLETE_OR_UNSUPPORTED` — canonical truth cannot fully grade the required candidate set without inventing settlement;
- `OTHER_FAIL_CLOSED` — unexpected condition requiring review.

Do not call `NO_WINNING_CANDIDATE_ON_SEALED_SURFACE` a structural supply failure. R0 already proved structural legal supply. This label concerns realized winner availability on the fixed sealed 96-candidate surface.

## Required aggregate statistics

For `DEVELOPMENT_CONSUMED_ALLOWED` graded dates report:

- graded date count;
- canonical Atlas control WIN / LOSS / NONBINARY record;
- binary win rate where appropriate;
- count of control losses with at least one winning alternative;
- count of dates with no fully winning candidate on the sealed surface;
- count of nonbinary controls;
- winner-available date count;
- sealed-surface winner-availability ceiling (dates with >=1 winning candidate), clearly labeled as an availability ceiling, not a learned-method performance claim;
- first-winning-rank minimum / median / maximum;
- count of winner-available dates with first winner at rank 1, <=3, <=5, <=10, <=25, <=50, <=96;
- distribution of total winning-candidate counts/date;
- control-score/rank diagnostics sufficient to understand whether failures are concentrated near the top or far down the sealed ordering.

Also report the full 23-date consumption census separately so withheld dates are visible without being graded.

## Historical comparison

The old incomplete-surface 7-7-1 Atlas control may be shown only as clearly scoped historical context.

Do not combine it statistically with the new uniform-surface forensic.

Do not revive the old 9-5-1 ceiling.

Do not score or rerun the rejected full pointwise 4L learner.

## Explicit prohibitions

Do **not**:

- regenerate any R2 candidate;
- mutate or rewrite any sealed R2 artifact;
- change exact selected-leg depletion;
- use player-wide depletion;
- use signal-road depletion;
- fit any pointwise, context, relational, tree, linear, or other learner;
- run context-consensus;
- tune thresholds, gates, weights, confidence levels, features, roads, support rules, or candidate depth;
- search for a rule that repairs observed losses;
- freeze/install/promote 4L;
- execute FromDeep;
- mutate Live/model/minutes/allocator/calibration/QMC/dependence;
- read protected validation outcomes;
- read protected lockbox outcomes;
- use public/live slip results as validation authority;
- auto-start any follow-on ranking experiment.

## Evidence class

`DEVELOPMENT_CONSUMED_SEALED_SURFACE_CONTROL_FORENSIC`

This is development evidence only. It is not protected validation, lockbox, prospective proof, or promotion authority.

Any unconsumed withheld date retains its pre-task Builder-consumption status.

## Resource contract

- learner fits: `0`;
- candidate-generation calls: `0`;
- candidate rescoring calls that alter population semantics: `0`;
- expected operation: artifact joins + canonical grading only;
- expected runtime: minutes, not hours;
- no expensive execution is justified.

## Required tests / checks

Before finalizing evidence prove:

- exact R2 surface hash bindings match accepted seal;
- 23-date ordered census matches R2;
- 96 candidates/date and 2,208 total candidates unchanged;
- no sealed R2 file changed bytes/hash;
- canonical control selection is exactly rank 1 from the sealed score ledger;
- outcome-consumption classifications were applied before outcome reads;
- withheld dates had no Builder candidate/leg outcome reads;
- validation reads = 0;
- lockbox reads = 0;
- no learner fit/generation/tuning occurred;
- canonical workspace and protected stash remain intact.

## Required dispositions

Use one of:

- `ATLAS_4L_UNIFORM_CONTROL_FORENSIC_R0_COMPLETE`
- `BLOCKED_OUTCOME_CONSUMPTION_AUTHORITY_UNCLEAR`
- `BLOCKED_R2_SEAL_HASH_MISMATCH`
- `BLOCKED_CANONICAL_CONTROL_IDENTITY_MISMATCH`
- `BLOCKED_BUILDER_CONTROL_RECONCILIATION`
- `BLOCKED_UNEXPECTED_FORENSIC_FAILURE`

Completion itself does not mean the 4L method passes or fails. It establishes the correct baseline anatomy for user/Chat review.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_CONTROL_FORENSIC_R0`

Commit and push only authorized permanent source/control/evidence paths if the target repo's governing Git contract permits them; exact-path staging only; verify local HEAD == tracking == direct remote; leave clean; preserve protected stash.

Report final WNBA SHA, evidence artifact paths, graded/withheld date counts, Atlas control record, ranking-failure count, no-winner count, first-winning-rank summary, validation/lockbox reads, and final stop marker.

## Next if this completes — NOT AUTHORIZED

Chat/Rick will review whether the complete-surface control anatomy justifies any ranking research.

Possible later decisions include:

- freeze canonical Atlas 4L if performance/anatomy is sufficient;
- test a predeclared conservative challenger if ranking failures justify it;
- keep context-consensus parked if incremental opportunity is weak;
- proceed to FromDeep only after the 4L method is resolved/frozen.

No follow-on is authorized by this work order.
