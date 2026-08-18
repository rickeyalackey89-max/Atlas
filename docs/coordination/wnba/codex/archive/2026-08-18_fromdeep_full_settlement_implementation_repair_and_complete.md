# WNBA FromDeep — Full Settlement Implementation Repair and Complete

Execution tier: `R1_ACTIONABILITY_REPAIR`

User authorization in Chat on 2026-08-18:

> “ok”

This authorizes an **implementation-only repair and completion of the already-authorized full FromDeep settlement task**. It does not reopen the FromDeep scientific question, change the frozen R0B universe, or authorize any core-family, redistribution, validation, lockbox, signal, fitting, or Live work.

## Purpose

Finish the exact same scientific task that was blocked at WNBA `4787d9a1ce55a1ab8252d601a15bb4719895972e` because of two runner-design defects:

1. exact-date truth-source resolution selected the latest snapshot before checking that its complete game-status set was final;
2. completed date labels were held only in memory, so the first 22 dates / 9,796 deterministic evaluator calls were not checkpointed before the July 16 implementation stop.

The historical games are not being re-adjudicated. The frozen candidate universe and canonical settlement semantics are unchanged.

## Authority and starting state

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`4787d9a1ce55a1ab8252d601a15bb4719895972e`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_FULL_38_DATE_DIRECT_SETTLEMENT_LABEL_SURFACE`

Controller: `slip-builders` only. Do not invoke the retired phase controller.

Bind before execution:

- frozen R0B2 pretruth universe at `73e6fb0ab1129086c81bbd7c547bc555d0e5517e`;
- exact R0B membership SHA `9a908f1f34802e473885df67eb0dbe130a90e77d1daec94cef581a3bae6201d2`;
- 38 provenance-valid source members;
- 20,626 eligible Demon-OVER rows;
- 27 factual market owners;
- R0C1 canonical direct-settlement actionability evidence at `48d1d04b2027ef3ca7b6cd6446b4c1de1d95176b`;
- failed full-settlement implementation receipt at `4787d9a1ce55a1ab8252d601a15bb4719895972e`;
- unchanged canonical `wnba.evaluation.live_prior_day._TruthIndex + _evaluate_leg` semantics.

Fixed FromDeep contract:

- FromDeep is independent of 2L/3L/4L depletion;
- core selected-leg depletion is not applied to FromDeep;
- no core redistribution/depletion work is allowed while FromDeep is being finished.

## Protected boundary

Validation dates remain protected and unread:

- `2026-08-04`
- `2026-08-10`

Lockbox dates remain protected and unread:

- `2026-08-11`
- `2026-08-12`

`2026-08-13` remains provenance-excluded from FromDeep.

Required throughout:

- validation reads = `0`;
- lockbox reads = `0`;
- Aug. 13 reads/contribution = `0`;
- monolithic protected truth opens = `0`;
- old GOBLIN/STANDARD discovery-label package opens = `0`.

## Phase A — Repair source selection before any evaluator call

Before evaluating a single R0B row in the repair run:

1. Inventory **all physically exact-date candidate ESPN sources** already present for each of the 38 admitted discovery dates.
2. For source-selection purposes, status-only reads are allowed on those 38 already-consumed discovery dates.
3. For every candidate source, verify physical date isolation and inspect the complete game-status row set.
4. A candidate is settlement-eligible only if its complete exact-date game-status set is final under repository-canonical finality semantics. Do not select a source merely because its pull timestamp is newest.
5. For each admitted date, select the latest **fully-final** physically exact-date source, deterministically breaking ties by repository path if required.
6. Serialize a pre-settlement source-resolution artifact listing every selected source, hashes, status counts/types, and the rejected newer/nonfinal candidates where applicable.
7. Require all 38 admitted dates to have a fully-final physically date-scoped source **before the first evaluator call**.

### Bounded discovery-only refresh authority

If and only if the complete existing-source inventory proves that an admitted discovery date has no fully-final physically exact-date source:

- a bounded ESPN refresh is authorized for **that exact admitted discovery date only**;
- do not refresh a validation date, lockbox date, or Aug. 13;
- record the missing date and failed existing-source inventory before refresh;
- fetch/normalize only that exact date using existing repository-owned ESPN tooling;
- require the refreshed source to be physically exact-date and fully final before proceeding;
- if a safe exact-date final refresh cannot be produced, fail closed **before any evaluator call for the 38-date run**.

This refresh authority is operational truth-source recovery for already-consumed discovery dates, not a new scientific surface or candidate regeneration.

## Phase B — Resumable per-date deterministic settlement

After all 38 selected sources pass Phase A:

1. Reverify the immutable 20,626-row R0B membership and 38 source-card bindings.
2. Preserve unchanged row preparation and unchanged `_TruthIndex + _evaluate_leg` behavior.
3. Evaluate dates in deterministic chronological order.
4. Immediately after each date finishes, atomically write a **per-date checkpoint shard** containing:
   - game date;
   - selected truth/status source paths and SHA-256 hashes;
   - exact R0B member/card binding and row identities;
   - complete settlement labels for that date;
   - per-date evaluator-call count;
   - settlement census;
   - checkpoint content hash/id.
5. A checkpoint is valid only when it contains exactly one label for every frozen R0B row on that date, with no duplicate identities or silent drops.
6. On any later interruption, resume only from hash-verified complete checkpoints. Never partially trust an incomplete date shard.
7. Preserve canonical statuses exactly: binary win/loss, push/nonbinary, `unsupported_market`, `missing_player_game_truth`, or any other existing evaluator status. Never manufacture binary truth.
8. Quarter-threshold rows remain `unsupported_market` whenever canonical quarter event truth is incomplete.

### Corrected exact-once contract

For final scientific evidence, **exactly once means exactly one unique final sealed label record per frozen R0B row**.

The prior failed attempt's 9,796 evaluator calls are process-history evidence only. They were not checkpointed into the final label surface and do not prohibit deterministic re-evaluation of those already-consumed discovery rows.

Required reporting must distinguish:

- prior failed-attempt evaluator calls: `9,796`;
- repair-run evaluator calls executed from scratch or resumed from new checkpoints;
- final unique sealed label records: exactly `20,626`;
- final duplicate label records: `0`;
- final silent drops: `0`.

Do not count a deterministic rerun after an aborted implementation attempt as a duplicate scientific observation.

## Phase C — Final merge and seal

After all 38 checkpoint shards pass:

1. Merge only the hash-verified per-date checkpoints.
2. Require exactly 38 unique admitted dates.
3. Require exactly 20,626 unique final label identities, one per frozen R0B membership row.
4. Require all 27 factual market owners to be represented according to the frozen membership census.
5. Produce overall, by-date, and by-market settlement/gradability census.
6. Seal the merged label surface against:
   - the R0B pretruth seal;
   - the exact R0B membership SHA;
   - the selected exact-date truth-source hashes;
   - the unchanged canonical evaluator binding;
   - all 38 per-date checkpoint hashes.
7. Preserve previous failed-attempt evidence unchanged; do not rewrite or delete it.

## Required outputs

Use a **new repair evidence root** under Builder Stage 5 so the failed attempt remains immutable. At minimum produce:

- `FROMDEEP_FULL_REPAIR_SOURCE_FINALITY_PREFLIGHT.json`;
- `FROMDEEP_FULL_REPAIR_PREOUTCOME_SCOPE_SEAL.json`;
- one atomic checkpoint directory/file per admitted date;
- `FROMDEEP_FULL_DIRECT_SETTLEMENT_LABELS.json.gz`;
- `FROMDEEP_FULL_DIRECT_SETTLEMENT_CENSUS.json`;
- `FROMDEEP_FULL_MARKET_SETTLEMENT_CENSUS.json`;
- `FROMDEEP_FULL_PROTECTED_READ_ACCOUNTING.json`;
- `FROMDEEP_FULL_LABEL_SURFACE_SEAL.json`;
- `FROMDEEP_FULL_REPAIR_ATTEMPT_ACCOUNTING.json`;
- `FROMDEEP_FULL_RESOURCE_SUMMARY.json`;
- focused-test evidence;
- `final_receipt.json`.

Exact file naming may follow repository conventions, but the final receipt must bind every required artifact and every per-date checkpoint by exact path + SHA-256.

## Required tests / adversarial cases

At minimum prove:

- a newer nonfinal exact-date source loses to an older fully-final exact-date source;
- source finality for all 38 dates is resolved before evaluator call 1;
- mixed/protected/Aug13 sources fail closed;
- a checkpoint cannot be accepted if row count/hash/identity/source binding drifts;
- resume skips a valid completed date checkpoint without re-evaluating it;
- incomplete/corrupt checkpoint is rejected and that date is recomputed from scratch;
- final merge rejects duplicate identities, missing rows, extra rows, missing dates, or source-hash drift;
- prior failed-attempt 9,796 calls are reported separately and do not alter final unique-label accounting.

## Explicitly unauthorized

Do not:

- change the R0B universe, membership, market namespace, tier, side, or line semantics;
- change `_TruthIndex`, `_evaluate_leg`, or market settlement semantics except implementation plumbing necessary to invoke the unchanged evaluator;
- add another scientific canary;
- run descriptive feature anatomy;
- rank fields or choose features;
- mine thresholds/cutpoints;
- construct signal roads;
- assign GREEN/RED/GRAY;
- fit/train;
- rank/select FromDeep legs;
- freeze/activate FromDeep markets;
- mutate 2L/3L/4L;
- perform core depletion or redistribution research;
- access validation or lockbox;
- mutate Live/model/minutes/allocator/calibration/QMC/dependence/policy/publication;
- auto-start the next FromDeep step.

## Required success disposition

Scientific surface success:

`PASS_FROMDEEP_FULL_38_DATE_DIRECT_SETTLEMENT_LABEL_SURFACE`

Implementation repair completion:

`PASS_FROMDEEP_FULL_SETTLEMENT_IMPLEMENTATION_REPAIR_AND_COMPLETE`

A pass requires the complete 20,626-row label surface and all 38 hash-bound checkpoints. A partial run is not a pass.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_FULL_SETTLEMENT_IMPLEMENTATION_REPAIR_AND_COMPLETE`

## Next if this passes — NOT AUTHORIZED

The next FromDeep step is descriptive market-owned win/loss anatomy using the completed sealed label surface. No signal-road mining, fitting, core redistribution, validation, or lockbox work is authorized by this repair.
