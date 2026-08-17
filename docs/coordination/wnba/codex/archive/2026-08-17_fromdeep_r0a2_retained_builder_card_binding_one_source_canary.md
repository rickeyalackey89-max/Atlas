# WNBA FromDeep R0A2 — Retained Builder-Card Binding Audit + One-Source Canary

Status: **USER AUTHORIZED**

User authorization in Chat: **“Agreed”**

## Purpose

The prior FromDeep R0A1 resource canary failed faithfully because the full-chain capsule scanner exceeded the 300-second gate on the smallest ~7.35 MB compressed capsule before producing one accepted measurement.

That failure is resource/extraction-path evidence only. It is not evidence against the FromDeep architecture.

The repository already contains low-footprint corpus machinery intended to retain reusable, outcome-blind Builder base artifacts. This row asks whether those existing retained artifacts can become the efficient, provenance-safe source surface for FromDeep R0B.

## Scientific question

> Across the exact 38 usable FromDeep discovery dates, how many canonical sealed members already expose an immutable direct retained Builder-card artifact with explicit hash lineage to the authoritative member/capsule freeze, and can the FromDeep outcome-blind projector process one such direct retained card quickly and deterministically without scanning the full-chain capsule?

## Starting authority

Expected WNBA starting HEAD:

`8e3f9d9e9d18fc814c30e232fc3d07411143deb9`

Expected Builder stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A1_EXCLUSION_RESOURCE_CANARY`

Accepted upstream FromDeep evidence:

- R0: `c5d3886363d8cce9afceeb2cd5e94a43af6ab3fb`
- R0A: `9d752a99700c5311fa71f325883e162829b0381a`
- R0A1: `8e3f9d9e9d18fc814c30e232fc3d07411143deb9`
- usable FromDeep discovery dates: `38`
- provenance-excluded date: `2026-08-13`
- Aug. 13 exclusion reason: `PROVENANCE_UNAVAILABLE_REQUIRED_PREGAME_FULL_ROW_BYTES`
- Aug. 13 statistical/evaluation contribution: `0`
- semantic regeneration: forbidden
- outcomes/truth/settlement/validation/lockbox reads so far: `0`

## Execution tier

`R0A2_RETAINED_BUILDER_CARD_BINDING_AND_ONE_SOURCE_CANARY`

This is a bounded actionability/resource audit. It has no performance or method authority.

Target wall time: `<=15 minutes`.

## Required operation

### 1. Freeze the exact 38-date audit census before any row-level card read

Use the already-accepted 38 usable FromDeep discovery members from R0/R0A1.

Do not add Aug. 13. Do not substitute a different date. Do not infer an unbound source.

Serialize the exact member/date census and its source authority before opening any retained Builder Card.

### 2. Audit direct retained Builder-card bindings for all 38 members

For each member, inspect only sealed/member-level metadata and manifests sufficient to determine whether an immutable direct retained Builder-card artifact exists.

Candidate repository-owned artifacts may include, where actually bound:

- `low_footprint_v1/builder_card.json.gz`
- `low_footprint_v1/retained_builder_card_manifest.json`
- member-level `builder_card_manifest.json`
- member-level `retained_base_manifest.json`
- member/surface freeze or audit artifacts that bind the retained base to the authoritative capsule/member identity

A direct retained Builder Card is **VALID** only when the repository proves the complete chain:

`canonical discovery member -> authoritative member/surface freeze -> retained base/Builder-card manifest -> exact Builder-card path + bytes + SHA-256`

Requirements:

- artifact physically exists;
- bytes match the bound size;
- SHA-256 matches the bound hash;
- member/date identity matches the audited discovery member;
- the retained artifact is explicitly outcome blind / pre-settlement under its governing contract;
- no source path is invented or inferred from naming convention alone.

If a date lacks that complete lineage, classify it precisely. Do not regenerate or repair it in this task.

### 3. Report retained-card coverage before canary execution

Produce a 38-date census with at least:

- game date;
- canonical member id;
- retained-card status;
- direct retained-card path if valid;
- bytes;
- SHA-256;
- governing manifest/freeze path(s) and hash(es);
- storage/provider location classification;
- exact failure reason when invalid/unavailable.

Report:

- valid direct-binding count;
- invalid/missing count;
- dates lacking a valid direct binding;
- total bound retained-card bytes across valid members;
- whether coverage is complete, partial, or zero.

### 4. One-source direct-card projector canary

Only if at least one valid direct retained Builder-card binding exists:

- sort valid direct retained cards by bound artifact bytes ascending;
- tie-break by game date then canonical member id;
- select exactly the smallest valid retained Builder Card;
- serialize that selection before opening the card rows.

Run only the intended outcome-blind FromDeep row projector over that direct retained Builder-card artifact.

Do **not** scan the full-chain capsule to rediscover the card.

Measure separately where applicable:

1. source hydration/copy/open latency from storage provider into task-local scratch;
2. projector CPU/wall time after the exact artifact is locally readable;
3. total elapsed wall time.

Report:

- Builder-card bytes;
- rows streamed;
- eligible Demon-OVER rows;
- canonical markets observed;
- feature-field count / availability-topology hash;
- projector-output hash;
- peak Python allocation estimate where practical;
- hydration seconds;
- projector seconds;
- total seconds.

### 5. Deterministic repeat

If the first direct-card canary completes within `60 seconds` total and no resource boundary is crossed, immediately run the exact same retained card once more from the same bound artifact.

Require exact parity for:

- row count;
- eligible Demon-OVER row count;
- canonical market set;
- feature topology hash;
- projector output hash.

Runtime itself need not be byte-identical.

If the first direct-card canary exceeds `60 seconds`, stop after preserving the faithful measurement. Do not retry.

## Resource boundaries

- target total row wall time: `<=15 minutes`
- one direct retained-card canary hard stop: `60 seconds`
- no full-chain capsule parser retry
- no full 38-date row projection
- no R0B
- no bulk hydration of all retained cards

If metadata audit itself cannot finish inside the target wall time, fail closed and report the exact bottleneck.

## Outcome and scientific boundaries

Required counters throughout:

- outcome reads = `0`
- truth reads = `0`
- settlement reads = `0`
- validation reads = `0`
- lockbox reads = `0`

Forbidden:

- hit-rate or performance computation;
- signal-road mining;
- GREEN/RED/GRAY classification;
- support/reliability/threshold selection;
- feature selection;
- fitting or ML;
- FromDeep selection;
- final market-owner-count freeze;
- changing the Aug. 13 exclusion;
- semantic regeneration or imputation;
- candidate generation for 2L/3L/4L;
- any 2L/3L/4L method mutation;
- Live/model/minutes/calibration/allocator/QMC/dependence/policy/publication mutation;
- protected evidence access;
- automatic R0B start.

## Implementation rule

Prefer existing repository-owned low-footprint/member-binding utilities and neutral reusable helpers. Do not create a new scientific source authority.

A minimal reusable reader/projector adaptation is allowed only if required to read an already-proven direct retained Builder Card without reopening the full-chain capsule. It may not change row eligibility semantics, market normalization, feature values, or FromDeep architecture.

## Required artifacts

At minimum produce/bind:

- exact 38-date audit census;
- retained Builder-card binding coverage ledger;
- retained-binding provenance summary;
- one-source canary selection receipt, if a valid direct card exists;
- one-source projector measurement, if executed;
- deterministic repeat/parity receipt, if executed;
- resource summary;
- final receipt with all protected/mutation counters.

## Git completion

Commit/push only authorized WNBA evidence and minimal reusable infrastructure with exact-path staging.

Verify:

- local HEAD == tracking branch == direct remote;
- worktree clean;
- protected stash unchanged.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A2_RETAINED_CARD_CANARY`

No follow-on auto-start. R0B remains separately user-authorized only.
