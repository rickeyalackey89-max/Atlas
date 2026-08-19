# WNBA FromDeep — Market-Owned Signal Atlas R1

Execution tier: `R2_BOUNDED_PILOT`

User authorization in Chat on 2026-08-18:

> “Ok, lets do it”

This is the first real outcome-bearing FromDeep signal operation under the already-frozen V1 grammar. It is **development-consumed signal discovery**, not target-date FromDeep performance, market activation, freeze, protected validation, or Live authority.

The exact question is:

> Under the frozen one/two-predicate V1 language, does the admitted 38-date / 27-market Demon-OVER discovery corpus contain broad, reliable, temporally stable market-owned GREEN and/or RED road structure worth carrying into a later strict historical-as-of target-date evaluation?

A faithful result may contain many GREEN roads, only RED roads, or no decisive roads at all. Execution success is not conditioned on finding a winner.

## Authority and starting state

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA HEAD:

`51665c31090d51b727a3cedb0834ad7eb41ed0d2`

Expected current stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_SIGNAL_GRAMMAR_RELIABILITY_CONTRACT_R0`

Controller: `slip-builders` only. Do not invoke retired phase control.

Accepted predecessor success:

`PASS_FROMDEEP_SIGNAL_GRAMMAR_RELIABILITY_CONTRACT_R0`

## Frozen authorities — do not amend in R1

Prime strategy contract:

`docs/coordination/wnba/chat/FROMDEEP_SIGNAL_GRAMMAR_V1.md`

WNBA machine-readable contract:

`data/wnba/bap2_work/builder_stage_5/fromdeep_signal_grammar_reliability_contract_r0/FROMDEEP_SIGNAL_GRAMMAR_RELIABILITY_CONTRACT_R0.json`

SHA-256:

`1f4e9dddcbc03fa6c3a4b1cd6079ca3ec7ddbed8f3e37f27422dfdb9ccfd2574`

Outcome-blind field-permission manifest:

`data/wnba/bap2_work/builder_stage_5/fromdeep_signal_grammar_reliability_contract_r0/FROMDEEP_SIGNAL_FIELD_PERMISSION_MANIFEST_R0.json.gz`

SHA-256:

`ef525e245e60956cfefd0e6fc501774c01aa6cf1b5fb711a0ae7499d418d9088`

Accepted manifest facts:

- markets = `27`;
- market-field records = `25,218`;
- predicate-eligible market-field records = `8,040`;
- excluded market-field records = `17,178`.

Frozen discovery universe:

- R0B2 commit `73e6fb0ab1129086c81bbd7c547bc555d0e5517e`;
- 38 admitted provenance-valid dates;
- 20,626 exact Demon-OVER rows;
- 27 market owners;
- Aug. 13 excluded from contribution.

Frozen label surface:

`data/wnba/bap2_work/builder_stage_5/fromdeep_full_settlement_implementation_repair_and_complete/FROMDEEP_FULL_DIRECT_SETTLEMENT_LABELS.json.gz`

SHA-256:

`cb99773e91ce403adff3fb5171b28f2692dcbc039367909ba8ae0facb306db23`

Canonical state census:

- WIN = `4,305`;
- LOSS = `15,127`;
- WIN+LOSS = `19,432`;
- VOID = `499`;
- PUSH = `2`;
- unsupported = `622`;
- missing truth = `71`.

Only canonical WIN/LOSS may contribute to signal-performance statistics.

Reuse the already-sealed 38 source-scalar checkpoints and their cache manifest from the descriptive-anatomy lineage. Hash-verify them before use. Do not reopen the original retained Builder Cards when the accepted cache remains valid.

## Frozen V1 rules that R1 must execute literally

No methodological tuning is authorized.

- market-owned Demon-tier OVER roads only;
- one or two predicates only;
- conjunction only; no OR;
- no 3+ predicate interactions;
- probability/confidence/implied-probability/QMC fields prohibited from signal eligibility;
- identity/provenance/outcome/historical-hit-rate/missingness predicates prohibited;
- numeric predicates limited to `<=q10`, `<=q25`, `<=q50`, `>=q50`, `>=q75`, `>=q90`;
- boolean predicates exact true/false equality only;
- categorical predicates exact equality only, with historical-as-of nonmissing cardinality <= 12;
- Tier-B requires different fields and different semantic families;
- no two `OTHER_APPROVED_PREGAME` predicates in one Tier-B road;
- both Tier-A components must independently pass the frozen precursor before a Tier-B road can exist;
- breadth floor: support >= 24, unique dates >= 8, unique participants/combo tuples >= 6, top-1 date share <= 0.25, top-1 participant share <= 0.25;
- Wilson method: two-sided 95%, fixed `z = 1.959963984540054`;
- deterministic chronological early/late stability split, odd extra date to later half;
- GREEN requires breadth, strict WIN rate >= 0.90, date-balanced WIN rate >= 0.90, road Wilson lower > market Wilson upper, and both temporal halves above same-market period baselines;
- RED requires breadth, road date-balanced rate below same-market baseline, road Wilson upper < market Wilson lower, and both temporal halves below same-market period baselines;
- everything else is GRAY;
- behavioral duplicate resolution: simpler road first, then lexical canonical identity at equal complexity;
- no probability-based road ranking or state authority.

## Phase A — outcome-blind primitive surface and cost seal

This phase must complete **before settlement labels are opened by the R1 runner**.

### A1. Reconcile control and bind inputs

1. Sync Prime and reconcile the exact active Builder lane under `slip-builders`.
2. Verify WNBA starts from the expected review stop and accepted grammar PASS.
3. Hash-verify the frozen V1 contract, permission manifest, R0B universe bindings, and 38 source-scalar checkpoint/cache bindings.
4. Produce an R1 requirement-to-code matrix covering every governing grammar rule, outcome boundary, as-of rule, dedup rule, resource rule, and protected-data prohibition before performance execution.

Any missing or weakened requirement is `implementation_divergence` and blocks outcome work.

### A2. Canonical Tier-A symbolic road universe

Build the complete Tier-A primitive template universe for all 27 market owners from the predicate-eligible manifest. No top-N, outcome statistic, descriptive-anatomy lift, or performance ranking may determine inclusion.

Numeric road identity is symbolic (`field >= q75`, etc.), not a full-corpus literal cutpoint.

Boolean road identity is field + exact boolean value.

Categorical road identity is field + exact factual category value. Category/value discovery may use the sealed pregame source checkpoints because it is outcome-blind, but target/evidence-date matching remains constrained by the as-of rules below.

### A3. Historical-as-of primitive matching — no future threshold leakage

For each admitted discovery row on date `D`, primitive matching must be computed from pregame information only.

Numeric fields:

- compute the relevant market-local quantile from nonmissing rows with `game_date < D` only;
- all rows on date `D` are simultaneous for this purpose and may not contribute to one another's threshold;
- rows on later dates may never influence the match status of an earlier row;
- if no valid prior nonmissing market values exist, the numeric primitive is unavailable for that row and does not match;
- tied quantile predicates collapse deterministically under the frozen V1 rule.

Categorical fields:

- V1 cardinality is computed from nonmissing rows with `game_date < D` only;
- if prior nonmissing cardinality exceeds 12, that categorical field is unavailable for that row;
- a categorical road value must have been observed in the same market/field on a prior date before it may be considered historically available for row `D`; a first-seen category on `D` is a cold category and does not match an already-knowable road on `D`;
- no complement predicates.

Boolean fields use their literal pregame value and require no learned threshold.

Persist a compact deterministic outcome-blind primitive match surface, preferably bitset/hash-bound or another low-footprint repository-native representation. Every admitted row must be accounted for; unavailable/missing predicate states must remain explicit rather than imputed.

### A4. Outcome-blind dedup and topology

Before labels:

- collapse tied numeric duplicates;
- behaviorally deduplicate Tier-A primitives using their outcome-blind match membership over the sealed 20,626-row universe; simpler identity first, lexical identity at equal complexity;
- retain a raw-to-canonical dedup map;
- compute the complete semantic-family-compatible Tier-B **upper-bound topology** without grading or constructing outcome-selected pairs;
- report counts by market, semantic family, primitive type, raw road count, deduped road count, and pregame support breadth.

Do not prune by support rate, hit rate, anatomy separation, or expected performance before the frozen precursor is evaluated.

### A5. Resource runway gate

R1 is an `R2_BOUNDED_PILOT` with a target total wall-clock ceiling of approximately 60 minutes.

Before labels are opened, write a resource/cost seal with at least:

- exact raw and deduped Tier-A counts;
- primitive match-evaluation count;
- exact per-market upper-bound Tier-B topology counts;
- measured primitive-build runtime;
- projected remaining wall clock;
- memory/pagefile/disk-growth estimate;
- free-space measurement;
- checkpoint/resume plan.

Use low-footprint streaming/vectorized/bitset implementation where helpful, provided it is exact and proven by fidelity tests. Implementation optimization is allowed; scientific truncation is not.

If the complete frozen surface cannot safely fit the declared R2 resource contract, stop **before outcome access** with the exact cost/topology evidence. Do not select a top-N subset, weaken the grammar, or auto-escalate to R3.

## Phase B — canonical Tier-A grading

Only after Phase A and its resource seal pass may the runner bind/open the accepted discovery labels.

1. Join labels to the exact sealed row identities with exact accounting.
2. Use only `settlement_state in {WIN, LOSS}` for performance statistics.
3. Keep VOID/PUSH/unsupported/missing as separate matching/coverage counts only; never coerce them into losses.
4. Grade **every canonical Tier-A road** under the frozen V1 rules.
5. For each road report at minimum:
   - market owner;
   - canonical road identity;
   - semantic family;
   - predicate type/operator/value or symbolic quantile;
   - binary support, WIN, LOSS, strict WIN rate;
   - unique dates and unique participants/combo tuples;
   - top-1 date and participant support share;
   - date-balanced WIN rate;
   - same-market binary and date-balanced baselines;
   - road and market Wilson intervals;
   - chronological early/later support and road date-balanced rates;
   - corresponding period market baselines;
   - precursor pass/fail plus explicit failure reasons;
   - GREEN/RED/GRAY state under the frozen rules plus explicit failure reasons;
   - VOID/PUSH/unsupported/missing match counts as nonperformance coverage facts;
   - outcome-blind match-signature hash.
6. Keep the Tier-A artifact complete and lexical/unranked.

## Phase C — exact Tier-B precursor surface

After Tier-A grading:

1. identify the exact Tier-A primitives that pass the frozen precursor;
2. within each market, generate **all** legal unordered Tier-B pairs from precursor-pass primitives;
3. enforce different fields, different semantic families, and the no-two-`OTHER_APPROVED_PREGAME` rule;
4. construct pair match membership as the exact AND/intersection of the already-sealed primitive match sets;
5. behaviorally deduplicate Tier-B roads outcome-blind after construction, retaining raw-to-canonical mapping and preferring simpler/lexical identity exactly as frozen;
6. seal the exact Tier-B candidate list and cost projection **before Tier-B outcome grading**.

No Tier-B pair may be admitted because its own result looks good. The only outcome-bearing admission mechanism is the already-frozen Tier-A precursor.

If the exact complete Tier-B surface exceeds the remaining declared R2 resource contract, checkpoint/seal Tier-A and the exact Tier-B candidate topology and stop for user/Chat review. Do not truncate or rank candidate pairs.

## Phase D — complete Tier-B grading

If the Phase-C resource gate passes, grade every canonical Tier-B road under the same frozen breadth, concentration, market-baseline, Wilson, temporal, and GREEN/RED/GRAY rules.

Tier-B output must be complete, lexical/unranked, and include the same evidence fields required for Tier A.

## Phase E — market-owned atlas and scientific disposition

Write a compact review surface for all 27 markets with at least:

- raw/deduped Tier-A road count;
- Tier-A precursor-pass count;
- Tier-A GREEN / RED / GRAY counts;
- raw/deduped Tier-B road count;
- Tier-B GREEN / RED / GRAY counts;
- support/date/participant breadth of decisive roads;
- concentration diagnostics;
- quarter-threshold truth-coverage limitations explicitly separated;
- total runtime/resource accounting;
- zero-protected-read accounting.

Do not rank markets or roads by hit rate. Lexical market/road order is canonical for review.

Required scientific disposition must be exactly one of:

- `V1_SUPPORTED_GREEN_STRUCTURE_PRESENT` — at least one canonical GREEN road exists;
- `V1_NO_GREEN_SUPPORTED_RED_STRUCTURE_PRESENT` — zero GREEN and at least one canonical RED road exists;
- `V1_NO_SUPPORTED_DECISIVE_ROAD_STRUCTURE` — zero GREEN and zero RED roads; all canonical roads are GRAY.

These are **scientific findings**, not execution PASS/FAIL markers.

## Required evidence artifacts

At minimum bind under a new immutable R1 evidence root:

- `FROMDEEP_SIGNAL_ATLAS_R1_REQUIREMENT_TO_CODE_MATRIX.json`;
- `FROMDEEP_SIGNAL_ATLAS_R1_PREOUTCOME_PRIMITIVE_SURFACE_SEAL.json`;
- compact/hash-bound primitive match surface or deterministic equivalent;
- `FROMDEEP_SIGNAL_ATLAS_R1_RESOURCE_PREFLIGHT.json`;
- `FROMDEEP_SIGNAL_ATLAS_R1_TIER_A_ROADS.json.gz`;
- `FROMDEEP_SIGNAL_ATLAS_R1_TIER_B_CANDIDATE_SEAL.json`;
- `FROMDEEP_SIGNAL_ATLAS_R1_TIER_B_ROADS.json.gz` when Phase D executes;
- raw-to-canonical dedup maps;
- `FROMDEEP_SIGNAL_ATLAS_R1_MARKET_SUMMARY.json`;
- resource summary;
- focused tests;
- final receipt.

Checkpoint at least after Phase A, Tier-A completion, and exact Tier-B candidate sealing so a resource stop does not require repeating already-completed deterministic phases.

## Required tests / fidelity

Before real outcome grading, positive and adversarial tests must prove at least:

- exact binding of V1 grammar/permission manifest;
- future rows cannot alter an earlier row's numeric quantile match;
- same-date rows do not contribute to one another's quantiles/cardinality;
- no-prior numeric state remains unavailable rather than imputed;
- categorical >12 prior cardinality is unavailable;
- cold first-seen categorical values do not create hindsight-match authority;
- probability/identity/outcome/provenance/missingness fields cannot enter the road surface;
- VOID/PUSH/unsupported/missing are excluded from signal performance;
- all breadth and concentration inequalities are exact;
- Wilson strict inequalities are exact;
- odd temporal split sends the extra date to the later half;
- Tier-B requires precursor-pass Tier-A primitives, distinct fields and families, and no forbidden OTHER+OTHER pair;
- Tier-B generation is complete and has no outcome-based top-N path;
- behavioral dedup is deterministic and simpler/lexical;
- lexical ordering is deterministic;
- restart/checkpoint reuse yields identical hashes;
- validation/lockbox/Aug. 13 truth access remains zero;
- Builder lane validation passes before and after control mutation.

Run the required focused tests plus repository Builder regression/control validation. Record exact counts in the receipt.

## Protected and product boundaries

Throughout R1:

- validation reads = `0`;
- lockbox reads = `0`;
- Aug. 13 reads/contribution = `0`;
- core 2L/3L/4L work = `0`;
- depletion/redistribution work = `0`;
- probability/model/minutes/calibration/allocator/QMC/dependence changes = `0`;
- Live/publication/promotion mutation = `0`.

FromDeep remains independent of the core depleted pool.

## Explicitly prohibited in R1

Do **not**:

- alter the V1 grammar because R1 results are sparse or disappointing;
- introduce arbitrary literal cutpoints or new transforms;
- use full-corpus/future rows to define an earlier row's numeric threshold or categorical availability;
- use probability to admit or classify a signal;
- rank/prune Tier-A or Tier-B roads by outcome;
- select target-date FromDeep legs;
- calculate a final FromDeep selected-leg hit rate;
- use GREEN/RED roads as Live/runtime authority;
- activate or freeze a market;
- perform per-slate FromDeep ranking, caps, or slip assembly;
- start strict historical-as-of target-date selection/evaluation;
- open protected validation or lockbox;
- reopen 2L/3L/4L redistribution;
- auto-start any follow-on task.

## Required execution success disposition

A faithful complete R1 execution emits:

`PASS_FROMDEEP_MARKET_OWNED_SIGNAL_ATLAS_R1`

This PASS means the frozen procedure executed completely and faithfully. It does **not** require any GREEN road.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_MARKET_OWNED_SIGNAL_ATLAS_R1`

## Next if this passes — NOT AUTHORIZED

After user/Chat review of the complete atlas and scientific disposition, a separate task may be authorized to rebuild the frozen registry strictly `t < D`, apply it to each target date's pregame Demon-OVER surface, seal target-date eligibility/selections before settlement, and evaluate per-market activation-floor evidence.

Do not auto-start that historical-as-of target-date evaluation.