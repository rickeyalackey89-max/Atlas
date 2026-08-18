# WNBA FromDeep R0C — Discovery Settlement Binding + Market-Owned Win/Loss Forensic Canary

Execution tier: `R0C_DISCOVERY_SETTLEMENT_BINDING_AND_WIN_LOSS_FORENSIC_CANARY`

User authorization in Chat on 2026-08-18:

> “I agree”

This authorization intentionally opens **development-consumed discovery settlement only** for the already-sealed FromDeep R0B universe. Protected validation and lockbox remain sealed.

## Purpose

Answer three bounded questions before any signal-road mining or GREEN/RED/GRAY design:

1. Can the exact `20,626`-row R0B pretruth universe be deterministically bound one-to-one to repository-canonical discovery settlement without crossing into protected validation/lockbox evidence?
2. What is the repository-canonical numeric interpretation of the Builder Card `line` field, given R0B reported `numeric_line_count = 0` while preserving line values as factual source data?
3. On a small **predeclared** set of market owners, what descriptive win/loss separation exists across approved pregame fields, without selecting thresholds, features, policies, or FromDeep picks?

This is development-consumed forensic evidence only. It has no validation, lockbox, Live, promotion, activation, or selection authority.

## Authority and starting state

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`73e6fb0ab1129086c81bbd7c547bc555d0e5517e`

Expected active Builder row:

`builder_s5_fromdeep_r0b2_storage_recovered_resume_user_review`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0B_UNIVERSE_PRETRUTH_SEAL`

Bind and verify before outcome access:

- R0B final receipt and pretruth seal at WNBA `73e6fb0ab1129086c81bbd7c547bc555d0e5517e`;
- `FROMDEEP_R0B_SOURCE_CENSUS.json`;
- `FROMDEEP_R0B_ELIGIBLE_ROW_MEMBERSHIP.json.gz`;
- `FROMDEEP_R0B_MARKET_NAMESPACE.json`;
- `FROMDEEP_R0B_PER_MARKET_CENSUS.json`;
- `FROMDEEP_R0B_FEATURE_AVAILABILITY_OVERALL.json`;
- `FROMDEEP_R0B_FEATURE_AVAILABILITY_BY_MARKET.json`;
- current `BUILDER_DATE_PARTITION_V1_1.json`;
- current `discovery_label_join_contract_v1_1.json`;
- repository-owned discovery settlement semantics in `src/wnba/evaluation/builder_discovery_labels.py` and canonical leg settlement in `src/wnba/evaluation/live_prior_day.py`;
- `docs/coordination/PRIME_STORAGE_HOUSEKEEPING.md` and installed `keep-it-tidy` skill for operational housekeeping before the final resource gate.

Accepted R0B facts are fixed inputs, not to be regenerated or revised:

- usable member count `38`;
- sealed eligible Demon-OVER rows `20,626`;
- factual owner count `27`;
- every owner is `FULL_ROW_SUPPORTED`;
- `2026-08-13` is excluded from FromDeep development statistical contribution;
- R0A3 parity passed;
- core-family depletion is not applied to FromDeep.

## Protected date boundary

Current partition authority identifies:

- validation: `2026-08-04`, `2026-08-10`;
- lockbox: `2026-08-11`, `2026-08-12`.

R0C may not label, grade, aggregate, print, inspect, compare, or otherwise consume outcomes for those dates.

R0C settlement scope is **exactly the 38 R0B source dates**. `2026-08-13` must not enter the settlement or forensic contribution because it is absent from the sealed R0B full-row universe and remains provenance-excluded for FromDeep development.

If the available settlement path cannot preserve this exact role/date boundary, fail closed before opening outcomes.

## Required pre-outcome scope seal

Before the first discovery settlement read, write a deterministic R0C scope artifact containing:

- exact R0B pretruth seal SHA/id;
- exact 38 settlement-eligible dates derived from the R0B source census;
- explicit exclusion of `2026-08-13`;
- explicit protected validation/lockbox date lists;
- exact four forensic market owners below;
- exact field-permission/forbidden-field authority used for the forensic;
- confirmation that no outcome was read before this scope artifact was serialized.

### Predeclared forensic market owners

These owners are selected **outcome-blind from the R0B census**, solely to cover different factual market shapes while keeping the canary bounded:

1. `points` — dense base counting market, `3,581` sealed rows / `38` usable dates;
2. `three_pointers_made` — dense discrete shooting market, `1,736` rows / `38` dates;
3. `blks_stls` — specialized combined defensive market, `135` rows / `29` dates;
4. `quarters_with_3_points` — specialized quarter-threshold market, `347` rows / `24` dates.

Do not substitute markets after outcomes are opened. Do not add a fifth market because its result looks interesting.

## Phase A — Line semantics proof (before line-based forensic interpretation)

R0B's market census reported zero native numeric-line observations. Treat that as a typing/representation question, not a data defect.

Required proof:

1. Reconstruct the exact sealed R0B membership rows from the hash-bound retained Builder Cards, one member at a time, and require complete-row hash parity with the R0B membership ledger.
2. Report raw JSON/source type and missingness of `line` across all `20,626` sealed rows and by market owner.
3. Trace the repository-canonical settlement path used for line comparison. Prefer existing repository conversion/evaluation behavior; do not invent a new numeric contract merely for R0C.
4. Demonstrate deterministic parity between the raw Builder Card line representation and canonical settlement evaluation on a deterministic outcome-independent sample spanning every factual market owner with rows.
5. If line values are serialized as strings but the repository canonical evaluator safely interprets them numerically, document that exact contract. If any nonnumeric/ambiguous line representation cannot be handled by existing canonical semantics, report it and prohibit line-range forensic interpretation for that affected scope.

No line thresholds or line buckets may be selected in R0C.

## Phase B — Exact discovery settlement binding

Use only the frozen R0B universe.

For every sealed membership row:

- verify its source retained-card binding and complete source-row SHA;
- preserve `builder_card_row_id` as the source row identity;
- use the repository-canonical discovery settlement semantics (`builder_discovery_labels.py` / canonical `_evaluate_leg` behavior or a fidelity-equivalent repository-owned helper);
- do not invent a tuple identity as settlement authority;
- bind exactly zero or one settlement record and fail on duplicates;
- preserve result classes distinctly: binary win, binary loss, push/nonbinary, unsettled/unmatched, unsupported settlement status if any.

Produce exact counts overall, by date, and by each of the 27 market owners:

- sealed membership rows;
- matched settlement rows;
- binary wins;
- binary losses;
- pushes/nonbinary;
- unsettled;
- unmatched;
- duplicate/ambiguous joins;
- gradable rate;
- unique dates represented.

A successful binding does **not** require every row to be binary. It requires deterministic accounting with no silent drops and no protected-date leakage.

Fail closed if:

- any R0B row/hash/source binding drifts;
- any settlement record binds to more than one sealed row;
- any sealed row binds to multiple outcomes;
- any protected validation/lockbox date appears in the settlement output;
- any Aug. 13 row contributes;
- settlement semantics would require an invented market alias or invented identity tuple;
- the R0B pretruth seal is modified.

## Phase C — Bounded market-owned win/loss forensic canary

Run only after Phase B binding passes.

Use only **binary settled** rows from the four predeclared market owners.

Use the full approved outcome-free Builder field grammar/permissions already governing WNBA Builder research, but exclude all prohibited leakage/identity fields such as:

- player names or player identity as a predicate;
- target date/date identity;
- run/member ids;
- source paths/hashes/row ids as predictors;
- outcome/settlement fields;
- historical hit-rate/result-derived fields;
- any field forbidden by current Builder field permissions.

This canary is **descriptive only**.

For every allowed pregame field actually present in each selected market, report deterministic support/missingness plus win/loss descriptive summaries according to its repository/source type:

- numeric source fields: counts, missingness, win/loss median and IQR (and optionally mean/std if already standard repository practice);
- boolean fields: win/loss state counts and rates;
- categorical/string fields: support counts by value with winner/loss counts, subject to existing concentration/privacy/identity exclusions;
- numeric-looking strings must remain strings unless an existing repository-canonical numeric semantic is proven for that field. `line` follows Phase A's explicit contract.

Do **not**:

- rank fields by outcome separation;
- choose "best" features;
- search thresholds/cutpoints/intervals;
- construct signal roads;
- assign GREEN/RED/GRAY;
- calculate an activation decision;
- fit a model;
- create a selector;
- rank or select FromDeep legs.

The purpose is to expose the anatomy we will use to design a later predeclared signal-road grammar, not to optimize that grammar now.

## Required outputs

Use a dedicated R0C evidence root under Builder Stage 5. At minimum produce:

- `FROMDEEP_R0C_PREOUTCOME_SCOPE_SEAL.json`;
- `FROMDEEP_R0C_LINE_SEMANTICS_AUDIT.json`;
- `FROMDEEP_R0C_SETTLED_MEMBERSHIP.json.gz` (minimal identity + settlement label/metadata; do not duplicate full Builder Card rows unnecessarily);
- `FROMDEEP_R0C_SETTLEMENT_BINDING_SUMMARY.json`;
- `FROMDEEP_R0C_MARKET_SETTLEMENT_CENSUS.json`;
- `FROMDEEP_R0C_FORENSIC_FIELD_DESCRIPTIVES.json.gz`;
- `FROMDEEP_R0C_FORENSIC_SUMMARY.json`;
- `FROMDEEP_R0C_RESOURCE_SUMMARY.json`;
- focused-test evidence;
- `final_receipt.json`.

All outputs must bind back to the exact R0B pretruth seal and membership ledger.

## Resource topology

R0C is a bounded canary, not a long research sweep.

Target total wall time: `<=15 minutes` excluding any routine `keep-it-tidy` housekeeping time.

Requirements:

- use `keep-it-tidy` under `PRIME_STORAGE_HOUSEKEEPING.md` before the final resource preflight;
- keep current/immediate Live/replay/corpus data, R0B artifacts, source bindings, protected stash, protected validation/lockbox data, and current Builder evidence untouched;
- process retained cards one at a time where card re-read is required;
- no full-chain capsule scan;
- no old slow parser;
- emit progress/heartbeat if execution is long enough to benefit from it;
- unexpected resource escalation fails closed.

## Evidence/read authority

Allowed:

- outcome/truth/settlement reads: **development discovery only, exact 38 R0B dates**;
- descriptive win/loss forensic on the four predeclared owners only.

Required to remain zero:

- validation reads = `0`;
- lockbox reads = `0`;
- new/prospective protected-date reads = `0`.

The final receipt must report exact discovery truth/settlement access counts separately from protected read counts.

## Hard boundaries

- do not mutate or regenerate the R0B pretruth universe;
- do not apply core selected-leg depletion;
- do not include Aug. 13 settlement contribution;
- no validation or lockbox access;
- no new unevaluated/protected dates;
- no signal/bucket threshold mining;
- no GREEN/RED/GRAY state assignment;
- no feature selection;
- no fitting/ML;
- no FromDeep ranking or selection;
- no market activation/freeze;
- no probability/model calibration work;
- no 2L/3L/4L research or mutation;
- no Live/model/minutes/allocator/QMC/dependence/policy/publication mutation;
- no public slip use as evidence;
- no follow-on auto-start.

Use exact-path Git staging only and preserve the protected stash. Verify local HEAD == tracking == direct remote and leave the WNBA worktree clean.

## Required disposition

On success, report a process/development-forensic pass such as:

`PASS_R0C_DISCOVERY_SETTLEMENT_BINDING_AND_BOUNDED_FORENSIC_COMPLETE`

A pass means settlement/gradability and descriptive anatomy are available for Chat review. It does **not** mean any signal road or market is accepted.

On any boundary/parity/binding failure, fail closed and identify the exact class before any repair.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0C_DISCOVERY_SETTLEMENT_FORENSIC_CANARY`

## Next if this passes — NOT AUTHORIZED

After Chat/user review, a later R0D may predeclare a market-owned signal-road grammar and discovery-only GREEN/RED/GRAY derivation procedure. R0C does not authorize R0D, historical-as-of procedure evaluation, FromDeep selection, protected validation, lockbox, or Live installation.
