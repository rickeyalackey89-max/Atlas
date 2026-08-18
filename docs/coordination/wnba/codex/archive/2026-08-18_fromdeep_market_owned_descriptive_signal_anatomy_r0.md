# WNBA FromDeep — Market-Owned Descriptive Signal Anatomy R0

Execution tier: `R2_FULL_SURFACE_DESCRIPTIVE_ANATOMY`

User authorization in Chat on 2026-08-18:

> “lets go”

This authorization continues **forward within FromDeep only**. FromDeep remains independent of 2L/3L/4L depletion. Core redistribution/depletion, protected validation, lockbox, Live, model, and publication work remain out of scope.

## Purpose

Use the completed sealed FromDeep discovery label surface to answer one descriptive question:

> Within each factual Demon-OVER market owner, what pregame anatomy distinguishes canonical WIN rows from canonical LOSS rows, and how much support/concentration/coverage sits behind those differences?

This is anatomy, not signal construction. No field, value, range, condition, or market may be promoted, vetoed, ranked, or frozen in this task.

## Authority and starting state

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`dfd55223fbb8ed9b0d7ef4af544ecf911adc78f5`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_FULL_SETTLEMENT_IMPLEMENTATION_REPAIR_AND_COMPLETE`

Controller: `slip-builders` only.

Bind before execution to:

- immutable R0B pretruth universe: 38 source dates / 20,626 exact Demon-OVER rows / 27 factual market owners;
- R0B membership and retained-card source bindings;
- `FROMDEEP_R0B_FEATURE_AVAILABILITY_BY_MARKET.json`;
- completed direct-settlement label file:
  `data/wnba/bap2_work/builder_stage_5/fromdeep_full_settlement_implementation_repair_and_complete/FROMDEEP_FULL_DIRECT_SETTLEMENT_LABELS.json.gz`
  with final-receipt SHA-256 `cb99773e91ce403adff3fb5171b28f2692dcbc039367909ba8ae0facb306db23`;
- completed label-surface seal:
  `FROMDEEP_FULL_LABEL_SURFACE_SEAL.json`
  with final-receipt SHA-256 `f9b7fe63a9897a0b1c5b6cb62987565b59133d27eaa1c5cd87d8bb308ce35e47`;
- canonical settlement-state semantics in `src/wnba/evaluation/builder_discovery_labels_v1_1.py::_settlement_state`;
- existing descriptive/exclusion patterns in `src/wnba/evaluation/builder_fromdeep_r0c_discovery_settlement_forensic.py` as implementation reference only.

Do not regenerate candidates, R0B, or settlement labels.

## Critical settlement-class semantics audit

Before any win/loss anatomy, audit the sealed label surface by **canonical `settlement_state`**, not by the existing full-settlement census helper's raw-result classification.

Repository-canonical precedence is:

- `VOID` before raw win/loss when DNP/void semantics apply;
- then `WIN`;
- then `LOSS`;
- then `PUSH`;
- then `UNGRADABLE_UNSUPPORTED_MARKET` / `UNGRADABLE_MISSING_TRUTH`.

The completed label surface is sound, but the current aggregate census helper classified `result` before `settlement_state`. Its reported `19,919` binary rows therefore includes the `499` rows whose canonical settlement state is `VOID`/`void_dnp`.

For this R0 anatomy, the only outcome-bearing rows allowed in winner-versus-loser descriptives are:

`settlement_state == WIN` or `settlement_state == LOSS`.

Predeclared canonical partition consistency gate:

- total sealed rows = `20,626`;
- canonical WIN + LOSS rows = `19,420`;
- canonical VOID rows = `499`;
- canonical PUSH rows = `14`;
- canonical unsupported-market rows = `622`;
- canonical missing-player-game-truth rows = `71`;
- these classes must account for all `20,626` rows with no overlap or silent drop.

Do **not** mutate the sealed label file to repair the old summary. Write a separate state-audit artifact and use canonical state eligibility downstream.

## Pregame field grammar — freeze before label outcomes are used

Field admission and typing must be determined **outcome-blind from the frozen R0B pregame rows before reading winner/loss labels for the anatomy**.

### Exclude from predictive/descriptive field comparison

Exclude:

- outcome, settlement, actual-value, result, binary-label, or result-derived fields;
- player/name/canonical-player identity fields;
- game/date/timestamp identity fields;
- run/member/game/row/source ids;
- source paths, SHA/hash fields, receipts, provenance identifiers;
- team/opponent identity fields as field predicates;
- historical hit-rate/win-rate/loss-rate/result-derived fields;
- any field prohibited by the current Builder outcome/field contract;
- nonscalar object/array fields unless an already-canonical scalar representation exists;
- market/tier/side universe-definition constants as candidate explanatory fields.

Identity fields may be used only to compute **concentration diagnostics** described below; their literal values must not become signal candidates.

### Outcome-blind type seal

For every remaining field within every factual market owner, classify source representation before outcome access:

1. `line` uses the already-proven repository-canonical numeric semantics.
2. Native finite integer/float fields are numeric.
3. String fields may be treated as numeric **only when every nonmissing value on that entire market's sealed pregame lane parses strictly as a finite decimal number**. This is representation-only adaptation; record the proof and original source type. No outcome may influence typing.
4. Exact native booleans and exact `true`/`false` string representations may be treated as boolean.
5. Everything else remains categorical source representation.
6. Numeric-looking strings that fail the all-values strict parse remain categorical; do not selectively coerce values.

Serialize this complete field/type/exclusion map as a pre-outcome type seal before opening the label file for WIN/LOSS comparison.

## Required descriptive anatomy

Run independently for **all 27 factual market owners**. Do not merge market owners.

### Market baseline and coverage

For each market report:

- sealed source rows;
- canonical WIN count;
- canonical LOSS count;
- canonical binary support = WIN + LOSS;
- market binary win rate;
- unique usable dates represented;
- VOID/PUSH/unsupported/missing-truth counts separately;
- field availability/missingness.

The three quarter-threshold markets must remain in the atlas, but their low canonical event-truth coverage must be explicit. Unsupported rows are coverage evidence only and cannot be treated as losses.

### Numeric fields

For each admitted numeric field, report for overall canonical-binary rows, WIN rows, and LOSS rows:

- nonmissing support;
- missing count/rate;
- min, Q1, median, Q3, max;
- mean and standard deviation where finite;
- WIN-minus-LOSS median difference;
- WIN-minus-LOSS mean difference.

Do not sort or rank fields by any difference statistic.

### Boolean fields

For WIN and LOSS separately report:

- support;
- true/false counts;
- true/false rates;
- WIN-minus-LOSS true-rate difference.

No state becomes a rule in R0.

### Categorical fields

For every factual scalar value report:

- total binary support;
- WIN count;
- LOSS count;
- within-value binary win rate;
- difference from that market's binary baseline;
- unique-date support where deterministically available.

Order categorical output by canonical lexical value, not by outcome rate/lift. Do not suppress low-support values in a way that could masquerade as a support threshold; preserve support counts so later Chat review can judge reliability.

### Concentration diagnostics

Using identities only for diagnostic aggregation, report per market and, where applicable, separately for WIN/LOSS:

- unique dates;
- unique canonical participants (combo tuple counts as the participant identity);
- unique teams where available;
- top-1 and top-5 participant support share;
- top-1 and top-5 date support share;
- participant HHI and date HHI or an equivalent predeclared concentration measure;
- winner concentration by participant/date.

Do not emit player/team identities as candidate conditions. Concentration tells us whether an apparent anatomy is broad or cluster-dependent; it does not define a signal.

## Required outputs

Use a dedicated Builder Stage-5 evidence root for this task. At minimum produce:

- `FROMDEEP_ANATOMY_PREOUTCOME_SCOPE_SEAL.json`;
- `FROMDEEP_ANATOMY_FIELD_TYPE_SEAL.json.gz`;
- `FROMDEEP_ANATOMY_CANONICAL_SETTLEMENT_STATE_AUDIT.json`;
- `FROMDEEP_ANATOMY_MARKET_BASELINES.json`;
- `FROMDEEP_ANATOMY_MARKET_CONCENTRATION.json`;
- `FROMDEEP_ANATOMY_FIELD_DESCRIPTIVES.json.gz`;
- `FROMDEEP_ANATOMY_REVIEW_SUMMARY.json`;
- `FROMDEEP_ANATOMY_RESOURCE_SUMMARY.json`;
- focused-test evidence;
- `final_receipt.json`.

The compact review summary must remain **unranked**. It should provide market support/coverage and artifact pointers, not a "best fields" list.

## Resource / execution discipline

This is a deterministic descriptive pass, not fitting or candidate generation.

- use the already-proven native retained-card parser / exact R0B membership bindings;
- process source cards one at a time; do not hydrate all 605.9 MB simultaneously;
- bind labels to raw rows using exact same-lineage R0B identity/source hashes, not legacy cross-lineage ids;
- perform an output-size/runtime preflight before full serialization; compression or per-market chunking is allowed as representation-only engineering if necessary, but scientific content may not be dropped;
- no full-chain capsule scan;
- no replay generation;
- no model execution;
- unexpected resource escalation fails closed.

## Evidence boundary

Allowed:

- the already-consumed 38-date R0B pregame rows;
- the already-sealed 20,626-row FromDeep direct-settlement label surface;
- canonical state/result metadata required for descriptive WIN/LOSS grouping.

Must remain zero:

- validation reads = `0`;
- lockbox reads = `0`;
- Aug. 13 reads/contribution = `0`;
- new/prospective protected-date reads = `0`.

## Hard prohibitions

Do **not**:

- rank fields by separation, lift, effect size, or hit rate;
- choose "best" features;
- search/select line, probability, edge, minutes, usage, fragility, or any other cutpoints;
- create bins/intervals optimized from outcome;
- construct AND/OR signal roads;
- assign GREEN/RED/GRAY;
- set minimum support/confidence thresholds for signal eligibility;
- fit/train/regularize a model;
- run historical-as-of FromDeep selection;
- rank/select FromDeep legs or slips;
- activate/freeze any FromDeep market;
- mutate 2L/3L/4L, depletion, or redistribution;
- access validation or lockbox;
- mutate Live/model/minutes/allocator/calibration/QMC/dependence/policy/publication;
- use public/live slips as evidence;
- auto-start a follow-on task.

## Required success disposition

`PASS_FROMDEEP_MARKET_OWNED_DESCRIPTIVE_SIGNAL_ANATOMY_R0`

A pass means the complete unranked market-owned winner/loss anatomy is available for Chat/user interpretation. It does **not** accept a signal, field, cutoff, market, or FromDeep selector.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_MARKET_OWNED_DESCRIPTIVE_SIGNAL_ANATOMY_R0`

## Next if this passes — NOT AUTHORIZED

Chat/user may use the sealed anatomy to design and predeclare a bounded market-owned signal-road grammar and reliability procedure. No signal-road mining, GREEN/RED/GRAY assignment, historical-as-of selection, FromDeep freeze, core redistribution, protected validation, or lockbox work is authorized by this R0.