# WNBA Codex Prime

Status: **NO ACTIVE EXECUTION DELEGATION — FROMDEEP FULL SETTLEMENT BLOCKED ON IMPLEMENTATION REPAIR / USER REVIEW REQUIRED**

Use the clean Prime mirror at `C:\Users\13142\Atlas\PrimeDelegation` and canonical WNBA root `C:\Users\13142\Atlas\WNBA`. Target-repository authority and the active `slip-builders` lane remain governing.

## Fixed strategic sequence

- Finish FromDeep end-to-end first.
- FromDeep is independent of 2L/3L/4L depletion and uses the full eligible Demon-OVER universe.
- Do not reopen core redistribution/depletion while FromDeep is in progress.
- After FromDeep is frozen, separately revisit the 2L -> 3L redistribution/non-redistribution architecture.
- Protected validation comes only after both FromDeep and the core redistribution decision are complete.

## Accepted FromDeep universe

R0B2 pretruth seal:

`73e6fb0ab1129086c81bbd7c547bc555d0e5517e`

Fixed facts:

- 38 provenance-valid retained Builder Cards;
- 20,626 eligible Demon-OVER rows physically sealed outcome-blind;
- 27 factual market owners, all full-row supported;
- Aug. 13 excluded because exact full-row provenance is unavailable;
- core-family selected-leg depletion is not applied to FromDeep.

## Accepted direct settlement actionability

R0C1 result:

`48d1d04b2027ef3ca7b6cd6446b4c1de1d95176b`

The unchanged canonical evaluator `_TruthIndex + _evaluate_leg` is accepted as actionable for exact sealed FromDeep rows. The old GOBLIN/STANDARD label package is not a success gate for the Demon universe.

## Last attempted task — full 38-date direct settlement label surface

WNBA result commit:

`4787d9a1ce55a1ab8252d601a15bb4719895972e`

Repository stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_FULL_38_DATE_DIRECT_SETTLEMENT_LABEL_SURFACE`

Repository failure classification:

`implementation_divergence`

This is **not** evidence that historical game truth is unavailable and is **not** a FromDeep scientific failure.

Exact attempt facts:

- pre-outcome scope sealed all 38 admitted dates, 20,626 rows, and 27 markets;
- 22 dates through `2026-07-15` completed;
- 9,796 exact evaluator calls completed;
- validation reads = 0;
- lockbox reads = 0;
- Aug. 13 reads/contribution = 0;
- no old label package, monolithic protected truth, core-family, redistribution, validation, lockbox, or Live work occurred.

### Root cause

The new full-settlement source resolver collected exact-date ESPN snapshots, then selected the **latest** candidate by `raw_pulled_at_utc` / feature-manifest path **without checking game-status finality before selection**.

For `2026-07-16`, it selected:

`data/wnba/runtime_state/espn_gamelogs/g0716_terminal_retry_20260718_truth_refresh_espn_gamelogs_feature_manifest.json`

with two game-status rows. The execution loop only opened/validated those status rows when it reached July 16; the selected status source was not uniformly `STATUS_FINAL`, so the run correctly failed before evaluating that date.

The runner also accumulated completed labels only in memory and wrote the full label artifact after all 38 dates. Therefore the 9,796 completed labels were not checkpointed. A literal restart under the old process-level "exactly once" wording would repeat evaluator calls.

### Chat interpretation

The blocker is an implementation design problem:

1. source selection should choose a **fully-final exact-date** source, not merely the latest exact-date source;
2. all 38 selected sources should be finality-preflighted before the first evaluator call;
3. completed date labels should be checkpointed/hash-bound so a later failure can resume;
4. "exactly once" should govern **one final sealed label per R0B row**, not prohibit deterministic re-evaluation of already-consumed development rows after an aborted implementation attempt. Prior failed-attempt calls should be reported separately rather than treated as scientific contamination.

The fixed R0B universe, evaluator, market semantics, and protected-date boundary do not need to change.

## Candidate next — NOT AUTHORIZED

`FROMDEEP_FULL_SETTLEMENT_IMPLEMENTATION_REPAIR_AND_COMPLETE`

A future user-authorized repair should stay inside the same scientific task and must **not** add another scientific canary.

Required design:

1. Starting from WNBA `4787d9a1ce55a1ab8252d601a15bb4719895972e`, inventory every physically exact-date candidate source for all 38 admitted dates before any evaluator call.
2. Inspect exact-date game-status files only and select the latest candidate whose complete status set is `STATUS_FINAL`.
3. If an admitted discovery date has no existing fully-final exact-date source, fail before any evaluator call unless the same authorization explicitly permits one bounded exact-date discovery-only ESPN refresh for that date. Any refresh remains forbidden for validation, lockbox, or Aug. 13.
4. Require all 38 dates to have a fully-final physically date-scoped source before settlement starts.
5. Preserve the same frozen 20,626-row R0B membership and unchanged `_TruthIndex + _evaluate_leg` semantics.
6. Write one atomic per-date checkpoint immediately after each date, binding exact R0B row identities/source hashes, truth-source hashes, labels, and evaluator-call count.
7. Resume only from hash-verified checkpoints if a later implementation stop occurs.
8. Final success requires exactly 20,626 unique final label records, one per frozen R0B row, with no duplicates or silent drops. Report prior failed-attempt evaluator calls separately; they do not invalidate deterministic final labels.
9. Preserve canonical nonbinary/unsupported statuses; do not manufacture results.
10. validation reads = 0; lockbox reads = 0; Aug. 13 reads = 0.
11. No feature anatomy, thresholds, GREEN/RED/GRAY, fitting, ranking, selection, FromDeep freeze, core-family redistribution, protected validation, lockbox, or Live/model/policy/publication mutation.
12. Stop for user/Chat review after the complete label surface is sealed.

No Codex execution is currently authorized.
