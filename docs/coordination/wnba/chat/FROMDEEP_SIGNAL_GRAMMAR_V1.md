# WNBA FromDeep Signal Grammar and Reliability Contract V1

Status: **USER/CHAT AGREED PREDECLARATION — EXECUTION ONLY THROUGH EXPLICIT PRIME DELEGATION**

User authorization in Chat on 2026-08-18:

> “I agree with this”

This document freezes the methodological language that the current WNBA FromDeep research lane is allowed to use when it later constructs market-owned signal roads. It is strategy/method authority for Prime coordination only. It does not supersede the WNBA `slip-builders` controller or create permission to run statistical evidence by itself.

## 1. Fixed purpose

FromDeep remains a sparse, market-owned, Demon-tier **OVER** specialist.

A FromDeep signal answers:

> Under what pregame condition does this specific market owner show sufficiently broad, reliable, temporally stable evidence to admit or veto an aggressive OVER road?

It does **not** answer:

> Which row has the highest model probability?

Signal eligibility comes first. Probability may only be used later as a secondary ranking/sanity/tie-break input among already-eligible rows.

## 2. Fixed evidence boundary

The signal procedure is bound to the already-accepted FromDeep discovery corpus:

- 38 provenance-valid discovery dates;
- 20,626 exact sealed Demon-OVER rows;
- 27 factual market owners;
- canonical WIN/LOSS anatomy population = 19,432 rows;
- WIN = 4,305;
- LOSS = 15,127;
- VOID = 499;
- PUSH = 2;
- unsupported = 622;
- missing truth = 71;
- Aug. 13 contribution = 0;
- validation reads = 0;
- lockbox reads = 0.

Only canonical `WIN` and `LOSS` rows may contribute to signal performance statistics. VOID, PUSH, unsupported, and missing-truth rows remain separate coverage facts.

Market ownership is immutable. Distinct markets are never pooled to manufacture support.

## 3. Predicate field permission

Only fields already present in the sealed outcome-blind pregame field/type grammar may become candidate predicates.

### Always prohibited as predicates

- settlement, result, WIN/LOSS, realized outcome, or postgame fields;
- player names or player IDs;
- team or opponent identity labels/IDs;
- target date, game date, timestamps used as calendar identity, run IDs, source paths, hashes, row IDs, card IDs, or provenance IDs;
- public-selection, publication, prior FromDeep selection, or release labels;
- historical hit rates, realized streaks, prior settlement-derived performance summaries, or any other outcome-derived pregame feature;
- direct model probability/confidence fields, implied probability fields, or probability-derived eligibility scores;
- missingness itself as a positive or negative basketball signal;
- newly invented ratios, transforms, synthetic embeddings, or semantic reconstructions not already present pregame.

Identity fields may still be used for concentration diagnostics only.

### Eligible semantic families

A permitted field should be assigned outcome-blind to one of:

- `LINE_DEPTH`
- `PROJECTION_EDGE`
- `ROLE_OPPORTUNITY`
- `FRAGILITY_UNCERTAINTY`
- `AVAILABILITY_CONTEXT`
- `ATLAS_COMPONENT`
- `OTHER_APPROVED_PREGAME`

Use repository-native field ownership/metadata where it exists. Do not infer semantic class from outcomes. Ambiguous fields are excluded from V1 and reported for review rather than guessed into a class.

## 4. Primitive signal grammar

A signal road is market-owned and contains at most **two** primitive predicates.

No OR clauses, no three-way interactions, no arbitrary arithmetic, no same-field double-threshold ranges, and no learned nonlinear boundary are permitted in V1.

### Numeric primitive

For a numeric field, thresholds are outcome-blind, market-local, historical-as-of empirical quantiles computed only from nonmissing prior rows.

Fixed quantile/operator grid:

- `x <= q10`
- `x <= q25`
- `x <= q50`
- `x >= q50`
- `x >= q75`
- `x >= q90`

where `q10/q25/q50/q75/q90` are computed from the same market owner using only evidence available before the target date. Inclusive comparison is canonical. Duplicate predicates created by tied quantiles collapse deterministically.

Literal numeric cutpoint search outside this grid is forbidden.

### Boolean primitive

Only exact equality is allowed:

- `x == true`
- `x == false`

### Categorical primitive

Only exact equality to one factual pregame category is allowed.

A categorical field is V1-eligible only when its nonmissing as-of cardinality is at most 12 after all identity/provenance prohibitions are applied. Complement predicates such as `x != category` are forbidden.

## 5. Complexity and pairwise construction

Tier A consists of one-primitive roads.

Tier B consists of a conjunction of exactly two Tier-A primitives and is allowed only when:

1. the two primitives use different fields;
2. the two fields belong to different semantic families;
3. neither primitive is prohibited by the probability/identity/outcome rules;
4. each primitive independently clears the V1 precursor gate on prior evidence;
5. the conjunction itself clears the full support/reliability state gate.

No pairwise candidate is formed from two `OTHER_APPROVED_PREGAME` fields. No higher-order interaction exists in V1.

### V1 precursor gate for pairwise construction

For an atomic primitive to be eligible to participate in a Tier-B conjunction, using prior canonical WIN/LOSS evidence only:

- binary support >= 24 rows;
- unique support dates >= 8;
- unique canonical participants/combo tuples >= 6;
- top-1 date support share <= 0.25;
- top-1 participant support share <= 0.25;
- primitive strict WIN rate > the same-market prior binary baseline;
- primitive date-balanced WIN rate > the same-market prior date-balanced baseline;
- primitive 95% Wilson lower bound >= the same-market prior binary baseline point estimate.

This precursor state is **not GREEN authority**. It exists only to bound the pairwise search surface.

## 6. Reliability definitions

All quantities are market-owned and historical-as-of.

### Strict WIN rate

`wins / (wins + losses)` over rows matching the road.

### Date-balanced WIN rate

For each unique support date, compute that date's road WIN rate. Then take the unweighted mean across support dates.

### Market baseline

The same-market canonical WIN rate over all prior WIN/LOSS rows, with no road predicate applied.

The market date-balanced baseline is defined analogously by equal-weighting prior market dates.

### Wilson interval

Use the standard two-sided 95% Wilson score interval with

`z = 1.959963984540054`.

No posterior prior or alternative confidence method may be substituted inside V1 without a new user-authorized method amendment.

### Breadth and concentration floor

A road may receive GREEN or RED state only if all are true:

- binary support >= 24 rows;
- unique support dates >= 8;
- unique canonical participants/combo tuples >= 6;
- top-1 date support share <= 0.25;
- top-1 participant support share <= 0.25.

Rows with missing predicate values do not match the road and are not imputed.

## 7. Temporal stability

For every road meeting the breadth floor, order its unique support dates chronologically and split them into an early half and a late half. With an odd number of dates, the later half receives the extra date.

For each half, compare the road's date-balanced WIN rate with the same-market date-balanced baseline computed on those same dates.

A road is temporally positive only when both halves are above their corresponding market baselines.

This split is deterministic and historical-as-of. No date boundary may be chosen from outcomes.

## 8. GREEN / RED / GRAY state rules

### GREEN — supported winning road

A road is GREEN only when all are true:

- breadth/concentration floor passes;
- strict WIN rate >= 0.90;
- date-balanced WIN rate >= 0.90;
- 95% Wilson lower bound for the road is strictly greater than the 95% Wilson upper bound of the same-market binary baseline;
- the road is temporally positive in both chronological halves.

GREEN means eligible signal evidence. It does not by itself activate a market for final FromDeep use.

### RED — supported negative veto

V1 RED is deliberately conservative. A road is RED only when all are true:

- breadth/concentration floor passes;
- road date-balanced WIN rate is below the same-market date-balanced baseline;
- 95% Wilson upper bound for the road is strictly below the 95% Wilson lower bound of the same-market binary baseline;
- both chronological halves are below their corresponding same-market date-balanced baselines.

A RED match vetoes the row even if another GREEN road also matches.

### GRAY — unresolved/inactive

Everything else is GRAY, including:

- insufficient support or date breadth;
- participant/date concentration failure;
- ambiguous field semantics;
- unstable positive evidence that fails the two-half temporal test;
- positive lift that does not meet the 90/90 GREEN contract;
- negative evidence that is not strong enough for conservative RED status.

In V1, instability without reliable negative evidence remains GRAY rather than being forced into RED.

## 9. Road identity and deterministic deduplication

A road's canonical identity is:

`market_owner + tier(A|B) + semantic predicate identity`

For numeric predicates, the identity stores the quantile/operator symbol (`>=q75`), not the target-date literal threshold value.

If two candidate roads are behaviorally identical on the same prior training rows, keep the simpler road; if complexity is equal, keep lexical canonical identity. No outcome-based tie-break is allowed for duplicate identity resolution.

## 10. Eligibility semantics

Conceptually:

`Eligible(leg) = matches >=1 GREEN road AND matches 0 RED roads`

GRAY roads have no runtime authority.

No fallback may manufacture eligibility when no GREEN road exists.

## 11. Historical-as-of requirement

For target date `D`:

1. use only settled admitted discovery evidence from dates `t < D`;
2. recompute market baselines, quantiles, precursor state, and GREEN/RED/GRAY registry from prior evidence only;
3. freeze registry state;
4. expose date `D` pregame Demon-OVER surface;
5. apply GREEN eligibility and RED vetoes;
6. only then may later ranking choose among eligible rows;
7. seal selections before revealing `D` settlement;
8. append `D` only after settlement.

No full-corpus feature quantile or future market baseline may be used on an earlier target date.

## 12. Market activation/freeze evidence floor

The current WNBA product contract remains unchanged:

- FromDeep target = 90% strict/run rate;
- 90% date-balanced rate;
- at least 24 historical-as-of selections;
- across at least 8 target dates;
- per activated market owner;
- zero minimum active markets/policies;
- sparse output and full abstention are legal.

A market with GREEN roads but insufficient historical-as-of selection evidence remains unactivated/GRAY at freeze review.

## 13. Explicitly deferred

This V1 contract does **not** freeze:

- probability-based ranking among already-eligible rows;
- slip assembly or per-slate output caps;
- cross-market portfolio interaction;
- final FromDeep freeze/promotion;
- validation or lockbox use.

Those remain later decisions after causal historical-as-of signal evaluation.

## 14. Scientific interpretation rule

A V1 failure means only that this bounded one/two-predicate, market-owned, reliability-gated signal language failed to produce sufficient causal evidence.

It does not prove that FromDeep as a concept is impossible, and it does not authorize silently expanding thresholds, adding third-order interactions, introducing probability as an eligibility gate, weakening breadth, or mining protected evidence.
