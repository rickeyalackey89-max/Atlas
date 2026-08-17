# WNBA FromDeep R0A.1 — provenance exclusion + three-capsule streaming canary

Status: **USER AUTHORIZED — BOUNDED RESOURCE CANARY ONLY**

User authorization in Chat:

> “Let's go”

## Purpose

Accept the completed R0/R0A finding that the exact Aug. 13 full-row pregame sources cannot be recovered without semantic regeneration, formally classify Aug. 13 as a FromDeep **provenance-unavailable development exclusion**, and measure the real streaming extraction cost on exactly three deterministic physically available discovery capsules before any full 38-date R0B projection.

This is not signal research and is not a performance experiment.

## Starting authority

Expected WNBA HEAD:

`9d752a99700c5311fa71f325883e162829b0381a`

Expected Builder stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A_PROVENANCE_NAMESPACE_CANARY`

Accepted R0:

`c5d3886363d8cce9afceeb2cd5e94a43af6ab3fb`

Accepted R0A:

`9d752a99700c5311fa71f325883e162829b0381a`

Amended FromDeep architecture commit:

`4bd330e04a0ef36e55857f794b043e583317a844`

Read and obey current WNBA `AGENTS.md`, active `slip-builders` controls, Builder governance, `PRIME_EXPERIMENT_RUNWAY.md`, and the amended `FROMDEEP_ARCHITECTURE.md`.

## Fixed scientific decisions

### Aug. 13 exclusion

Declare `2026-08-13` excluded from **FromDeep development only** with reason:

`PROVENANCE_UNAVAILABLE_REQUIRED_PREGAME_FULL_ROW_BYTES`

Bind the exclusion to:

- canonical run `live_20260813_173116`;
- expected Builder Card SHA-256 `ce09ff65e08999de2be19a08108de9d3f60992a08944cd52a026d16be6d05f15`;
- expected scored-leg SHA-256 `c7cacd93256f1de8865194367423e2a0b772aca63a3446ec6812662240a1089e`;
- R0/R0A source-search evidence showing the exact bytes were not recovered;
- explicit counters proving outcome/truth/settlement/validation/lockbox reads were zero when the exclusion was decided.

The exclusion contributes zero rows, support, wins, losses, market baselines, temporal evidence, training evidence, or historical-as-of target evidence.

Do not semantically regenerate, replay-substitute, impute, or infer Aug. 13 pregame rows.

If exact bytes are recovered in the future, they are not silently added; incorporation would be a method/universe change requiring user/Chat reauthorization and downstream FromDeep re-adjudication.

### Market namespace

Preserve the R0A namespace derivation contract.

The four canonically distinct Aug. 13 markets:

- `blks_stls`
- `quarters_with_3_points`
- `quarters_with_4_points`
- `quarters_with_5_points`

remain known canonical owner identities. They receive **zero support from Aug. 13**. If they appear on usable full-row dates, those usable rows may later provide support. Final owner count is not frozen in this task.

## Usable source universe for this canary

Exactly the 38 physically present full-row discovery capsules already bound by R0.

Do not add newer dates, operational evals, public/live slips, validation dates, lockbox dates, or alternate replay reconstructions.

## Deterministic three-capsule selection

From the 38 usable capsules, sort ascending by the exact compressed source byte count already bound in the R0 source census, with deterministic tie-break by `target_game_date` ascending then canonical member id lexical.

Select exactly:

1. smallest = first item;
2. lower median = item 19 in 1-based order (index 18 zero-based) because `n=38`;
3. largest = final item.

Serialize the selected dates/member IDs/source paths/source hashes/source byte counts before reading capsule row contents.

## Streaming canary operation

Use the same intended streaming/projector logic that a later R0B would use to recover **outcome-free factual eligible Demon-tier OVER pregame rows and feature-availability metadata**.

For each of the three selected capsules report at minimum:

- source compressed bytes;
- wall seconds;
- rows inspected or streamed;
- factual eligible Demon-OVER rows emitted/countable;
- canonical markets observed;
- feature-field count / availability-summary topology needed by R0B;
- peak-memory estimate if cheaply measurable without adding intrusive instrumentation;
- deterministic output/hash parity on one immediate repeat of the smallest capsule only, if that repeat keeps the total task under the resource cap.

Do not write a full 38-date projected universe.

Do not open outcomes or settlement.

## Resource gate

Target total wall time: `<=15 minutes`.

Fail closed and stop for user review if:

- any one canary capsule requires more than 300 seconds;
- total canary execution would exceed 900 seconds;
- the intended streaming/projector cannot operate without reading prohibited outcome/truth/settlement fields;
- source/hash drift is found;
- the canary reveals memory/resource topology materially larger than expected.

After the three canaries, produce a conservative full-R0B projection over the 38 usable capsules. Base the projection on measured throughput and actual bound source bytes; include a conservative overhead factor rather than a best-case estimate. Report projected wall time and whether the full run appears suitable for R2 bounded pilot / R3 full under Prime runway doctrine.

The projection is advisory only. **Do not start R0B.**

## Required outputs

Produce compact bound artifacts equivalent to:

- `FROMDEEP_R0A1_PROVENANCE_EXCLUSION.json`
- `fromdeep_r0a1_canary_source_selection.csv`
- `fromdeep_r0a1_streaming_canary.csv`
- `FROMDEEP_R0A1_RESOURCE_PROJECTION.json`
- `FROMDEEP_R0A1_SUMMARY.json`
- `final_receipt.json`

The exact repository-owned names may differ if existing generic Builder machinery has a canonical naming pattern, but the evidence content must be equivalent and hash-bound.

## Hard boundaries

- outcome reads = 0
- truth reads = 0
- settlement reads = 0
- validation reads = 0
- lockbox reads = 0
- no signal-road mining
- no GREEN/RED/GRAY classification
- no hit-rate or performance computation
- no support/reliability threshold selection
- no feature selection
- no fitting or ML
- no FromDeep selection/output construction
- no final owner-count freeze
- no full 38-date projection
- no R0B auto-start
- no 2L/3L/4L research or mutation
- no Live/model/minutes/calibration/allocator/QMC/dependence/policy/publication mutation

## Completion

Commit/push only authorized WNBA changes with exact-path staging. Verify local HEAD == tracking == direct remote, leave worktree clean, preserve the protected stash unchanged, and report the WNBA result SHA plus artifact hashes and measured canary topology.

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A1_EXCLUSION_RESOURCE_CANARY`
