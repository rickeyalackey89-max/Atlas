# WNBA FromDeep R0A3 — Native Retained-Card Parser Parity Canary

Status: **USER AUTHORIZED**

Execution tier: `R0A3_NATIVE_RETAINED_CARD_PARSER_PARITY_CANARY`

Expected WNBA starting HEAD:

`433bd153c11463493a7bd1b0e50687d356bdf345`

Expected current Builder stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A2_RETAINED_CARD_CANARY`

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0A3_NATIVE_RETAINED_CARD_PARITY_CANARY`

## Scientific / engineering question

Can the already provenance-proven retained Builder Card selected by R0A2 be decoded and projected with a native compact-card JSON path while reproducing the exact sealed R0A2 deterministic projection, eliminating the custom character-scanner bottleneck without changing any FromDeep eligibility, market, feature, or outcome-boundary semantics?

This is implementation actionability only. It has no performance, signal, selection, promotion, or validation authority.

## Bound R0A2 reference

WNBA R0A2 commit:

`433bd153c11463493a7bd1b0e50687d356bdf345`

Use exactly the R0A2 selected retained card:

- date: `2026-06-18`
- member: `live_20260618_182656__2026-06-18`
- retained-card bytes: `5108222`
- retained-card SHA-256: `0bb694a5e511d34bcddc32104686252e26b0495694476f6cec3a99766a548456`

Sealed R0A2 expected deterministic result:

- rows streamed: `684`
- eligible Demon-OVER rows: `187`
- feature field count: `933`
- availability-summary SHA-256: `2b6b596ef9b8be19b76cfedacde5f096010d59c3ceb8740e821a0a683f2b58b2`
- projector-output SHA-256: `61e284e6fd0ff42e1f9476f5c4b0c8243f940d0fe03e7616213f8318395b2ced`
- canonical markets exactly as sealed in `FROMDEEP_R0A2_ONE_SOURCE_MEASUREMENT.json`

Do not recompute or reinterpret the R0A2 baseline with the slow scanner. Bind it from the sealed artifact.

## Required operation

1. Verify canonical root/branch, Prime delegation, starting WNBA HEAD, R0A2 final receipt, selected-card binding, source bytes/SHA, and zero protected-read state.
2. Hydrate/copy only the exact same selected retained card if needed; verify bytes and SHA before parsing. Report hydration/open time separately.
3. Parse the compact retained Builder Card using native `gzip` + standard JSON decoding. **Do not use the R0A1/R0A2 character-by-character `_CharStream` / `_capture_value` scanner.**
4. Require the decoded payload to be the expected retained-card object with a `rows` list.
5. Before adopting the fast outcome-boundary scan, prove every decoded row is a mapping and every row value is JSON-scalar (`null`, boolean, number, string). If any nested mapping/list/tuple value exists, fail closed and stop; do not weaken the existing recursive outcome contract.
6. For the proven-flat card only, enforce the same explicit prohibited outcome/settlement field set by scanning every row key through the repository-canonical outcome-field normalization/membership contract. No heuristic substring matching.
7. Apply the exact existing Demon-OVER factual eligibility semantics and market handling used by R0A2. Do not change `is_playable_tier_side`, tier/side normalization, market identity, missingness semantics, or field-value typing.
8. Build the exact same deterministic projection payload as R0A2: rows, eligible rows, canonical markets, feature-field count, per-field present/non-missing/type topology.
9. Require exact parity against the sealed R0A2 reference for:
   - rows streamed;
   - eligible Demon-OVER rows;
   - canonical market list;
   - feature field count;
   - availability-summary SHA-256;
   - projector-output SHA-256.
10. Record separate timings for:
   - hydration/open;
   - gzip/native JSON decode;
   - flatness + outcome-boundary scan;
   - eligibility + topology aggregation;
   - deterministic serialization/hash;
   - total projector and total operation.
11. If the first native-parser pass has exact R0A2 parity and total projector time `<=30s`, immediately repeat exactly once from the same verified retained-card bytes and require exact output/hash parity plus identical counts/markets/topology.
12. Stop for user/Chat review. Do not start R0B.

## Resource / actionability gate

Target wall time: `<=15 minutes` total.

Actionability PASS requires:

- exact R0A2 deterministic parity;
- flat-row proof for the selected card;
- zero prohibited outcome fields;
- first native projector `<=30s`;
- deterministic repeat exact parity when first pass is within gate.

If the native pass is slower than 30s, parity fails, row flatness is false, source/hash drift occurs, or any protected/outcome dependency appears: fail closed and stop without widening scope.

## Hard boundaries

- outcome reads = `0`
- truth reads = `0`
- settlement reads = `0`
- validation reads = `0`
- lockbox reads = `0`
- no full-chain capsule scan
- no R0A2 slow-parser rerun
- no second source/date
- no bulk hydration
- no full 38-date projection
- no R0B
- no final owner-count freeze
- no signal-road mining
- no GREEN/RED/GRAY classification
- no hit-rate/performance computation
- no support/reliability/threshold selection
- no feature selection
- no fitting/ML
- no FromDeep selections
- no 2L/3L/4L work
- no Live/model/minutes/calibration/allocator/QMC/dependence/policy/publication mutation
- no Aug. 13 change or synthesis
- no follow-on auto-start

Minimal reusable parser/projector infrastructure changes are allowed only when they preserve the exact R0A2 deterministic projection and explicit outcome boundary demonstrated above.

Commit/push only exact authorized WNBA paths. Verify local HEAD == tracking == direct remote, leave worktree clean, and preserve the protected stash unchanged.

## Required final report

Return:

- final WNBA SHA;
- exact final stop marker;
- exact selected retained-card bytes/SHA/date/member;
- flatness proof result;
- native decode/outcome scan/topology/hash timings;
- first total projector time;
- exact R0A2 parity booleans and both expected/observed hashes;
- repeat parity result/timing if executed;
- protected read counters all zero;
- R0B not started;
- ref equality / clean worktree / stash unchanged.
