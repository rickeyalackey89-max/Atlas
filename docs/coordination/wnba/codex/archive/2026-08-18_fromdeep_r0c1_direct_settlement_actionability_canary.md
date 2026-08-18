# WNBA FromDeep R0C1 — Direct Settlement Actionability Canary

Execution tier: `R1_ACTIONABILITY_CANARY`

User authorization in Chat on 2026-08-18 at approximately 12:41 CT:

> “Ok, so lets do that”

## Purpose

Answer one small integration question:

> Can exact rows from the already-sealed `20,626`-row FromDeep R0B universe be settled directly through Atlas's unchanged repository-canonical `_TruthIndex + _evaluate_leg` machinery, without using `builder_card_row_id` as cross-lineage settlement authority and without reading protected validation or lockbox truth?

This is not signal research, not a full 38-date settlement pass, and not performance authority.

R0C already established that the old canonical discovery label package and R0B use different Builder Card row-ID lineages. R0C also established that the old label package is only a partial prior Builder-exposed surface, so it cannot be treated as full-universe FromDeep settlement authority.

R0C1 therefore tests the direct canonical evaluator itself on a tiny deterministic development-consumed slice.

## Authority and starting state

Prime parent repository: `rickeyalackey89-max/Atlas`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`50be4d1fa5e2289d065e2f9d1b21c1448a2d6921`

Expected current Builder stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0C_DISCOVERY_SETTLEMENT_FORENSIC_CANARY`

Expected active WNBA Builder row before activation:

`builder_s5_fromdeep_r0c_discovery_settlement_forensic_canary_user_review`

The WNBA `slip-builders` lane remains sole workflow controller. Reconcile and validate target-repo authority before any mutation or outcome access.

Bind at minimum:

- R0B pretruth seal and exact `20,626`-row membership from WNBA `73e6fb0ab1129086c81bbd7c547bc555d0e5517e`;
- R0C result commit `50be4d1fa5e2289d065e2f9d1b21c1448a2d6921`;
- current Builder date partition/protected-date authority;
- unchanged `src/wnba/evaluation/live_prior_day.py` canonical `_TruthIndex` and `_evaluate_leg` behavior;
- `src/wnba/evaluation/builder_discovery_labels.py` only as the existing discovery-only preparation/settlement pattern;
- old canonical discovery leg-truth package only for overlap parity, never as full R0B settlement authority.

## Fixed canary scope

The canary dates are predeclared now, before any new truth access:

1. `2026-06-18` — early discovery date; R0B has `187` sealed eligible Demon-OVER rows and the old canonical discovery leg-truth package is known to contain `24` canonical rows on this date.
2. `2026-07-15` — later discovery date; R0B has `241` sealed eligible Demon-OVER rows.

Total maximum R0B canary membership: `428` rows.

These dates were selected from already-development-consumed discovery evidence for small size and temporal separation, not from outcome quality.

Do not substitute dates after truth access.

## Protected evidence boundary

Protected validation dates remain:

- `2026-08-04`
- `2026-08-10`

Lockbox dates remain:

- `2026-08-11`
- `2026-08-12`

R0C1 must not read, deserialize, filter after reading, print, label, aggregate, or otherwise consume truth rows for any protected date.

Important: merely reading a monolithic all-season truth file and filtering protected dates afterward does **not** satisfy this boundary for R0C1.

Use a repository-native physically date-scoped discovery truth source or date-scoped underlying source bytes for the two canary dates only. If the available repository truth topology cannot make protected rows physically unread for this canary, fail closed and report that exact blocker. Do not weaken the boundary.

Aug. 13 remains excluded and contributes zero.

## Required procedure

### 1. Seal the canary membership before truth access

From the unchanged R0B membership ledger:

- select only `2026-06-18` and `2026-07-15`;
- require exact expected counts `187` and `241`;
- reverify source/member/row hashes exactly as R0C did;
- serialize a small pre-outcome scope receipt containing exact row identities/hashes, dates, protected exclusions, evaluator code SHA/hash, and confirmation that truth reads are still zero.

Do not regenerate or alter R0B.

### 2. Resolve safe date-scoped canonical truth

Use existing repository truth/provenance metadata to identify truth source bytes containing only the authorized canary dates, or safely materialize a date-scoped view from source artifacts **without opening protected-date truth rows**.

Do not use the old `1,052`-row discovery leg-truth package as settlement authority.

Do not invent new truth, aliases, player mappings, market mappings, or settlement semantics.

### 3. Directly settle the sealed R0B rows

Prepare each sealed R0B row exactly as the repository's discovery label path prepares a Builder row for evaluation, preserving the original factual fields and Demon-OVER side.

Then call the unchanged repository-canonical:

`_TruthIndex -> _evaluate_leg`

for every canary row.

Do not replace the evaluator with a new custom settlement implementation.

Report by date and overall:

- sealed rows;
- evaluator calls;
- binary wins;
- binary losses;
- pushes/nonbinary;
- `missing_player_game_truth`;
- unsupported-market/status counts;
- any other canonical settlement status;
- gradable count/rate.

The canary is actionable if the canonical evaluator produces real direct settlement on both dates and does not collapse systematically to missing/unsupported because of an integration mistake. No arbitrary hit-rate or performance threshold applies.

### 4. Old-package parity on overlap only

For canary roads that also exist in the old canonical discovery leg-truth package, compare by the repository-native identity:

`game_date + exact_road`

where `exact_road` uses canonical participant/combo identity + market + tier + direction + canonical line.

This is parity evidence only.

Require:

- at least one overlapping canonical road across the two-date canary;
- one-to-one overlap identity with no duplicate ambiguity;
- exact parity for canonical result class and settlement status;
- actual-value parity after repository-canonical numeric normalization where applicable.

Any parity mismatch fails closed and is reported before broader work.

## Success disposition

Return:

`PASS_R0C1_DIRECT_SETTLEMENT_ACTIONABILITY_CANARY`

only if all of the following are true:

- exact R0B canary membership/hash verification passes;
- both predeclared dates are directly evaluated through unchanged `_TruthIndex + _evaluate_leg`;
- direct settlement is nondegenerate/actionable on both dates;
- old-package overlap exists and parity is exact on all overlapping roads;
- validation reads = `0`;
- lockbox reads = `0`;
- Aug. 13 reads/contribution = `0`;
- no signal, threshold, fitting, ranking, selection, model, Live, or publication work occurs.

If safe date-scoped truth cannot be obtained without opening protected rows, return a specific blocked disposition rather than reading the monolithic truth store anyway.

## Required outputs

Keep this small. Produce only what is needed to prove the integration:

- pre-outcome canary scope/hash receipt;
- direct-settlement canary rows or compact labels;
- settlement census by date/status;
- exact-road overlap/parity report;
- protected-read accounting;
- focused tests;
- final receipt.

Do not create a full 38-date label universe in R0C1.

## Resource topology

This should be minutes, not hours.

- no fitting;
- no candidate generation;
- no replay/corpus rebuild;
- no full-chain capsule scan;
- no full 20,626-row settlement pass;
- no expensive execution;
- no need for `keep-it-tidy` unless ordinary Builder preflight requires it because this is a tiny read/settlement canary.

If the implementation begins expanding into a broad infrastructure project, stop and report why.

## Hard prohibitions

Do not:

- change the R0B universe;
- settle all 38 dates;
- use `builder_card_row_id` as cross-lineage settlement authority;
- treat the old 1,052-row label package as the full FromDeep truth universe;
- read protected validation/lockbox truth;
- include Aug. 13;
- mine features or thresholds;
- build signal roads;
- assign GREEN/RED/GRAY;
- fit/train a learner;
- rank/select FromDeep legs;
- activate a market;
- modify 2L/3L/4L;
- mutate Live/model/minutes/allocator/calibration/QMC/dependence/policies/publication;
- auto-start follow-on work.

Use exact-path Git governance and leave the target WNBA worktree clean with local HEAD == tracking == direct remote after any authorized permanent change.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0C1_DIRECT_SETTLEMENT_ACTIONABILITY_CANARY`

## Next if this passes — NOT AUTHORIZED

A separate user-authorized operation may settle the entire frozen 38-date / 20,626-row R0B development universe through the same proven canonical evaluator and produce the full labeled FromDeep discovery surface.

That full pass is not authorized by R0C1.