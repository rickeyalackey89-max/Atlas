# WNBA FromDeep — Signal Grammar and Reliability Contract R0

Execution tier: `R0_ARTIFACT_AUDIT`

Evidence intent: **method predeclaration / implementation fidelity only; no statistical signal search**.

User authorization in Chat on 2026-08-18:

> “I agree with this”

Chat has accepted the completed descriptive anatomy at WNBA `06317138e247412a56a4c31cf10bac2f8e4975c8` and frozen the strategic method document:

`docs/coordination/wnba/chat/FROMDEEP_SIGNAL_GRAMMAR_V1.md`

Prime publication commit for that strategy document:

`f6d68165658b65da7d4428a3af2817c7f5cafa98`

This delegation is deliberately **pre-performance**. Codex must materialize the exact agreed grammar/reliability contract and an outcome-blind field-permission manifest, prove implementation fidelity with synthetic/control tests, and stop. It must not construct or grade a single real FromDeep signal road.

## Authority and starting state

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`06317138e247412a56a4c31cf10bac2f8e4975c8`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_ANATOMY_PARTITION_CORRECTION_AND_COMPLETE`

Controller: `slip-builders` only. Do not invoke retired phase control.

Current accepted anatomy facts are context only for this delegation:

- 20,626 sealed FromDeep rows;
- 27 market owners;
- 19,432 canonical WIN/LOSS rows;
- 4,305 WIN / 15,127 LOSS;
- 499 VOID / 2 PUSH / 622 unsupported / 71 missing truth;
- 19,845 unranked market-field descriptive records;
- validation reads = 0;
- lockbox reads = 0;
- Aug. 13 contribution = 0.

Do not reopen the completed anatomy to choose thresholds or fields.

## Governing method contract

Implement the strategy in `FROMDEEP_SIGNAL_GRAMMAR_V1.md` exactly.

The target-repo machine contract must preserve at minimum:

### Fixed signal language

- market-owned Demon-OVER only;
- one- or two-predicate roads only;
- no OR clauses;
- no 3+ predicate interactions;
- no arbitrary arithmetic or newly invented transforms;
- numeric grid only: `<=q10`, `<=q25`, `<=q50`, `>=q50`, `>=q75`, `>=q90`;
- boolean equality only;
- categorical equality only with as-of nonmissing cardinality <= 12;
- numeric thresholds computed market-locally and historical-as-of from prior nonmissing feature values only;
- tied/duplicate quantile predicates collapse deterministically.

### Predicate prohibitions

Never permit as signal predicates:

- settlement/outcome/postgame fields;
- player identity;
- team/opponent identity;
- date/calendar identity, timestamps used as identity, run/source/provenance/hash/row/card IDs;
- prior selections/publication labels;
- historical hit rates/streaks/outcome-derived summaries;
- direct probability/confidence/implied-probability fields;
- missingness itself;
- newly synthesized transforms.

Probability remains strictly downstream/secondary after signal eligibility and is not part of this R0 implementation.

### Outcome-blind semantic families

Every permitted field must be deterministically assigned to one of:

- `LINE_DEPTH`
- `PROJECTION_EDGE`
- `ROLE_OPPORTUNITY`
- `FRAGILITY_UNCERTAINTY`
- `AVAILABILITY_CONTEXT`
- `ATLAS_COMPONENT`
- `OTHER_APPROVED_PREGAME`

Use existing repository-native field metadata/ownership when available. Do not use outcome statistics to classify fields. If a field cannot be classified confidently from pregame semantics, exclude it from V1 and emit an explicit ambiguity reason.

### Pairwise precursor gate

Tier-B conjunctions may later be generated only when both atomic predicates independently satisfy, on prior evidence:

- binary support >= 24;
- unique support dates >= 8;
- unique participants/combo tuples >= 6;
- top-1 date support share <= 0.25;
- top-1 participant support share <= 0.25;
- strict WIN rate > same-market binary baseline;
- date-balanced WIN rate > same-market date-balanced baseline;
- 95% Wilson lower bound >= same-market binary baseline point estimate.

The two predicates must use different fields and different semantic families. Two `OTHER_APPROVED_PREGAME` predicates may not be paired.

This precursor state is not GREEN authority.

### Breadth / reliability floor

GREEN or RED state later requires:

- binary support >= 24;
- unique dates >= 8;
- unique participants/combo tuples >= 6;
- top-1 date support share <= 0.25;
- top-1 participant support share <= 0.25.

Use canonical participant/combo tuple identity only for support/concentration diagnostics, never as a predicate.

### Reliability method

- strict WIN rate = WIN / (WIN + LOSS);
- date-balanced WIN rate = unweighted mean of per-date road WIN rates;
- market baseline = same-market prior WIN/(WIN+LOSS);
- market date-balanced baseline = unweighted mean of prior per-date market WIN rates;
- confidence interval = two-sided 95% Wilson score interval with `z = 1.959963984540054`;
- no substitute posterior/confidence method inside V1.

### Temporal stability

For a road meeting the breadth floor, sort unique support dates and split into early/late chronological halves; later half receives the extra date when odd. Both halves compare against the same-market date-balanced baseline on those same dates.

No outcome-selected date boundary is legal.

### GREEN

All required:

- breadth/concentration floor passes;
- strict WIN rate >= 0.90;
- date-balanced WIN rate >= 0.90;
- road Wilson lower bound > same-market baseline Wilson upper bound;
- early-half road date-balanced rate > early-half market date-balanced baseline;
- late-half road date-balanced rate > late-half market date-balanced baseline.

### RED

V1 RED is intentionally conservative. All required:

- breadth/concentration floor passes;
- road date-balanced WIN rate < same-market date-balanced baseline;
- road Wilson upper bound < same-market baseline Wilson lower bound;
- early-half road date-balanced rate < early-half market date-balanced baseline;
- late-half road date-balanced rate < late-half market date-balanced baseline.

### GRAY

Everything else is GRAY/inactive. In V1, instability without reliable negative evidence remains GRAY rather than being forced RED.

### Eligibility semantics

Future runtime concept only:

`eligible = matches >=1 GREEN AND matches 0 RED`

RED veto wins. GRAY has no authority. No fallback/manufactured eligibility.

### Final market activation floor

Preserve the current target-repo FromDeep product contract without weakening:

- 90% strict/run rate;
- 90% date-balanced rate;
- >=24 historical-as-of selections;
- >=8 target dates;
- per activated market;
- zero minimum active markets;
- sparse output/abstention legal.

This R0 does not evaluate that floor.

## Exact allowed reads

Codex may read:

- current WNBA governing Builder control/state/work-order files needed for a legal `slip-builders` transition;
- current target `builder_goal.json` to preserve the existing FromDeep product contract;
- Prime `FROMDEEP_ARCHITECTURE.md` and `FROMDEEP_SIGNAL_GRAMMAR_V1.md`;
- the already-sealed outcome-blind FromDeep market namespace/scope artifacts;
- `FROMDEEP_ANATOMY_FIELD_TYPE_SEAL.json.gz` and other pre-outcome field metadata needed to build a field-permission manifest;
- repository source/schema metadata needed to classify field semantics outcome-blind;
- synthetic fixture data created solely for unit/fidelity tests.

## Forbidden reads in this R0

Do **not** open or parse:

- the 20,626-row settlement label surface;
- WIN/LOSS descriptive anatomy values;
- market baseline performance artifacts;
- field outcome descriptives;
- any historical signal-road performance output;
- validation truth;
- lockbox truth;
- Aug. 13 truth;
- Live/public performance as statistical authority.

The completed anatomy has already motivated the user/Chat methodology decision. Codex may not use its outcome values to optimize or reinterpret the frozen contract.

## Required implementation artifacts

Use repository-native locations/naming, but the final receipt must bind exact paths and hashes for at least:

1. a machine-readable FromDeep signal grammar/reliability contract V1;
2. a requirement-to-code/fidelity matrix covering every governing rule in this work order;
3. an outcome-blind field-permission manifest containing for every field considered:
   - canonical field identity/path;
   - sealed type;
   - semantic family or `EXCLUDED`;
   - predicate eligibility true/false;
   - exact exclusion reason when false;
   - whether Tier-B pairing is permitted;
4. a compact field-permission review summary:
   - total fields considered;
   - permitted numeric / boolean / categorical counts;
   - excluded identity/provenance/outcome/probability/historical-performance/ambiguous counts;
   - semantic-family counts;
   - no performance ranking;
5. synthetic positive/adversarial fidelity tests;
6. final receipt.

Do not rank fields by anatomy separation, hit rate, or any outcome statistic.

## Required adversarial tests

At minimum prove that the implementation rejects:

- player-name and player-ID predicates;
- team/opponent identity predicates;
- date/run/hash/source IDs;
- settlement/result fields;
- historical hit-rate fields;
- probability/confidence fields as eligibility predicates;
- missingness-as-signal predicates;
- arbitrary literal numeric thresholds;
- numeric thresholds outside the six-symbol quantile grid;
- categorical `!=` complements;
- categorical cardinality > 12;
- same-field two-threshold roads;
- same-semantic-family Tier-B conjunctions;
- two `OTHER_APPROVED_PREGAME` fields in one Tier-B road;
- three-predicate or OR roads;
- a GREEN state below any required support/breadth/concentration/90-90/Wilson/temporal gate;
- a RED state without the conservative negative/Wilson/temporal gates;
- any non-GREEN/non-RED state being coerced out of GRAY;
- any use of future feature values to compute a target-date quantile.

Synthetic tests must also prove exact deterministic repeat parity.

## Control/evidence class

This is pre-statistical contract implementation/fidelity work.

- no real candidate road generation;
- no real GREEN/RED/GRAY assignment;
- no outcome statistics;
- no fitting;
- no threshold search;
- no market activation;
- no FromDeep selection;
- no historical-as-of performance run;
- no validation/lockbox/Aug. 13;
- no 2L/3L/4L or redistribution work;
- no Live/model/policy/publication mutation.

Use the target repository's legal singular Builder-row transition. Prefer `FIDELITY` for synthetic contract tests if consistent with current `slip-builders` authority; if the controller requires a process-only `CONTROL_AUDIT` transition to install the predeclaration, preserve that authority and report the exact machine-test mapping. Do not invent a second controller.

## Resource boundary

This should be cheap.

- no retained-card source pass;
- no settlement-label pass;
- no full descriptive anatomy pass;
- no corpus replay;
- no fitting;
- no expensive execution.

Target wall clock: <= 10 minutes excluding routine tests/Git hygiene.

## Required success disposition

`PASS_FROMDEEP_SIGNAL_GRAMMAR_RELIABILITY_CONTRACT_R0`

Success means only that the frozen method language and field permissions were faithfully materialized and tested outcome-blind.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_SIGNAL_GRAMMAR_RELIABILITY_CONTRACT_R0`

## Next if this passes — NOT AUTHORIZED

Chat/user may review the exact field-permission manifest and implementation receipt. Only after that review may a separate bounded signal-road discovery/actionability task be authorized.

Do not auto-start real road construction, GREEN/RED/GRAY assignment, historical-as-of performance evaluation, FromDeep freeze, core redistribution, protected validation, lockbox, or Live work.
