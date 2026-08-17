# WNBA 4L Precision-First Challenger R2 — Sealed Performance Grade

Status: **USER AUTHORIZED**

Execution tier: `R2_SEALED_PERFORMANCE_GRADE`

Preferred machine class: `SEALED_ARTIFACT_FORENSIC`

User authorization: **“Let's do it”**

## Scientific question

What is the development-consumed performance of the already-sealed R1 4L precision-first selection ledger, and did its sole pretruth consensus override improve, harm, or leave unchanged the canonical Atlas `14-8-1` control?

This task grades an already-frozen selection surface. It does not create or modify a method.

## Starting authority

Expected WNBA HEAD:

`c9b8ce32fc2557475d3d2f75af9e4feab3c7fe7b`

Expected Builder stop:

`BLOCKED_USER_REVIEW_WNBA_4L_PRECISION_FIRST_CHALLENGER_R1`

Accepted R1 facts:

- 23 target dates;
- 96 sealed candidates/date;
- 22 `KEEP_ATLAS` selections;
- exactly 1 `CONSENSUS_OVERRIDE`;
- sole override is `2026-08-07`, candidate `wnba_candidate_06038f743829e7965ed64acb`, frozen Atlas rank 16;
- all 23 R1 selections were sealed before target-date performance was opened;
- same-date target outcome reads before selection = 0;
- R1 performance authority = false;
- validation reads = 0;
- lockbox reads = 0.

Accepted canonical Atlas control:

`14 WIN / 8 LOSS / 1 NONBINARY` across the same 23 dates.

## Evidence class

`DEVELOPMENT_CONSUMED_SEALED_SELECTION_PERFORMANCE`

This is development evidence only. It is not validation, lockbox, prospective, Live, publication, or promotion authority.

## Required bindings

Bind and hash-check the existing immutable R1 artifacts, including at minimum:

- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_precision_first_challenger_r1/selected_candidate_seal.json`
- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_precision_first_challenger_r1/selection_ledger.csv`
- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_precision_first_challenger_r1/pretruth_selection_receipts.jsonl`
- `data/wnba/bap2_work/builder_stage_5/current_atlas_4l_precision_first_challenger_r1/R1_ACTIONABILITY_SUMMARY.json`
- the accepted uniform R2 candidate/annotation/score surface needed to recover each selected candidate's exact selected-leg identities without regeneration;
- the accepted discovery truth exposure/consumption authority proving these 23 dates are development-consumed;
- the immutable discovery leg-truth stream used by the accepted exact-selected-leg settlement adapter;
- the accepted 23-date Atlas control forensic artifacts.

Use the repository's canonical exact selected-leg identity/equality contract. Do not substitute candidate-ID-only settlement when the immutable exact-leg adapter is the accepted authority.

## Required procedure

1. Validate current Builder control and all bound artifact hashes.
2. Assert the R1 selected-candidate seal contains exactly 23 selections and exactly one `CONSENSUS_OVERRIDE`.
3. Assert the selection ledger and pretruth receipt chain match the sealed R1 identities exactly.
4. Confirm all 23 target dates are `DEVELOPMENT_CONSUMED_ALLOWED` before opening performance.
5. Join each sealed selected candidate to immutable development truth using the accepted exact selected-leg settlement adapter.
6. Grade the 23 sealed R1 selections exactly once.
7. Compare the R1 record against canonical Atlas `14-8-1` on the identical 23-date population.
8. For the one changed date only, report:
   - game date;
   - Atlas control candidate ID/result;
   - sealed R1 selected candidate ID/result;
   - selected Atlas rank;
   - exact transition (`WIN->WIN`, `WIN->LOSS`, etc.);
   - effect classification.
9. Write one compact R2 performance packet and return to user review.

## Effect classification

Use a simple predeclared win-count effect, not a new policy rule:

- `BENEFICIAL_OVERRIDE`: R1 selection adds one WIN relative to Atlas on the changed date.
- `HARMFUL_OVERRIDE`: R1 selection removes one WIN relative to Atlas on the changed date.
- `NEUTRAL_OVERRIDE`: R1 and Atlas have the same WIN/non-WIN status on the changed date.

Also report the raw exact result transition so NONBINARY behavior is never hidden by the classification.

## Required report

Report at minimum:

- target date count;
- R1 `WIN / LOSS / NONBINARY` record;
- R1 binary win rate;
- Atlas control `14 / 8 / 1` and binary win rate;
- net WIN delta versus Atlas;
- changed-selection count (must be 1);
- beneficial override count;
- harmful override count;
- neutral override count;
- exact one-date transition and selected Atlas rank;
- all target selections truth-supported or explicit fail-closed stop;
- validation reads = 0;
- lockbox reads = 0;
- fitting calls = 0;
- candidate generation/rescoring/reranking calls = 0;
- threshold/feature/hyperparameter search calls = 0;
- FromDeep calls = 0;
- Live/model/policy/publication mutations = 0;
- artifact paths and hashes;
- final WNBA SHA, local/tracking/direct-remote equality, clean worktree, protected stash status.

## Fast-path / implementation boundary

This is a read-only sealed-artifact forensic and should use the streamlined workflow:

`AUTHORIZED -> CONTROL_AND_EVIDENCE_PREFLIGHT -> SEALED_ARTIFACT_FORENSIC -> BLOCKED_USER_REVIEW`

- one full preamble at active-row start;
- only `BUILDER CONTROL DELTA` if a governing fact changes;
- no task-specific `control_builder_<task>.py` controller;
- use the shared sealed-forensic executor where expressible;
- if a small reusable shared-executor extension is required for sealed-selection grading, it may be implemented once with focused tests, but must not change the scientific population, settlement semantics, or R1 selections.

## Hard prohibitions

Do **not**:

- refit either R1 learner;
- regenerate or alter the R1 selection ledger;
- modify the selected candidate seal or pretruth receipts;
- rerank, rescore, prune, expand, or regenerate candidates;
- change feature contracts;
- search thresholds, features, weights, margins, confidence gates, signal roads, or hyperparameters;
- design another challenger;
- run FromDeep;
- freeze, install, promote, or publish 4L;
- access protected validation or lockbox evidence;
- mutate Live, model, minutes, calibration, allocator, QMC, dependence, policy, or publication state;
- automatically start any follow-on task.

Any mismatch in R1 sealed selection identity, truth support, evidence partition, or protected boundary fails closed.

## Decision boundary after R2

R2 itself does not freeze 4L.

After Chat/user review:

- if the sole override is beneficial, review whether the challenger has earned research-freeze status;
- if harmful or non-improving, the default strategic disposition is to reject the challenger and freeze canonical Atlas at `14-8-1`, unless the user explicitly authorizes additional 4L research.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_PRECISION_FIRST_CHALLENGER_R2`

No follow-on auto-start.
