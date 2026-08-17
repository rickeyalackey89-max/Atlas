# WNBA FromDeep Agreed Architecture

Status: **AGREED ARCHITECTURE — EXECUTION ONLY THROUGH EXPLICIT PRIME DELEGATION**

This document records the user/Chat-agreed strategic architecture for WNBA FromDeep. It is not Builder execution authority and does not supersede the WNBA `slip-builders` controller.

## Purpose

FromDeep is not another probability-ranked leftovers family.

Normal Builder families answer:

> Which combination of qualified legs is strongest?

FromDeep answers:

> Which types of aggressive OVER roads repeatedly win, under what conditions, and which roads should be excluded before ranking?

The family is a sparse specialist. Precision matters more than coverage.

## Core family contract

- Demon-tier **OVER** roads only.
- Preserve **market ownership**. Every canonical factual eligible Demon-OVER market admitted by the outcome-blind discovery authority receives its own owner/policy lane unless repository-canonical normalization proves two source labels are aliases of the same market.
- The legacy RP37 21-market list is historical structure only. It is neither a minimum nor a cap and cannot silently exclude factual current-stack markets.
- Do not merge distinct markets merely because their statistics are related. For example, a combo market is not automatically owned by either component market, and quarter-specific markets are not automatically owned by full-game points.
- No minimum slate output count.
- Honest abstention is a successful result when no supported signal exists.
- Probability is not the primary eligibility mechanism. It may be used only after evidence-based signal eligibility as a secondary ranking, sanity, or tie-break input.
- Public/live output is not development, validation, or lockbox authority.

## Development universe

Start from the **full eligible scored Demon-OVER leg universe** on usable development/discovery dates.

FromDeep is architecturally independent of core selected-leg depletion. Frozen 2L, 3L, and 4L gate sequencing but do not remove legs from the FromDeep research universe.

Do not start from:

- prior FromDeep releases;
- public picks;
- legs selected by a historical FromDeep policy;
- core-family leftovers;
- only high-probability rows;
- historically winning rows;
- the legacy RP37 active/inactive market decisions.

For each usable development date, reconstruct the factual pregame eligible Demon-OVER surface with all available pregame fields, physically seal that surface, and only then append settlement.

Conceptually each supported leg record is:

`market + line/depth + player/context + projection + edge + probability + Atlas components + fragility + role/minutes/usage/context + outcome`

Outcome must never define the candidate universe.

## Provenance-unavailable development exclusions

A discovery date may be excluded from FromDeep development only when the required pregame full-row source bytes cannot be recovered under a bounded, documented, outcome-blind provenance search.

Rules:

1. The exclusion decision must be made before any FromDeep outcome, settlement, hit-rate, signal-road, or performance use for that date.
2. The missing source must be bound by whatever exact canonical provenance remains available, including expected path/hash/run identity when known.
3. Semantic regeneration, replay substitution, imputation, or reconstruction of missing pregame rows is forbidden unless a later separate method change explicitly reopens the universe and invalidates downstream FromDeep evidence.
4. A provenance-excluded date contributes **zero** support, wins, losses, feature observations, market baselines, temporal evidence, historical-as-of training evidence, or target-date evaluation evidence.
5. The exclusion and its reason must remain explicit in every universe/registry seal derived from that development corpus.
6. The exclusion must never be justified by or revisited because of the realized result on that date.
7. If the exact missing pregame bytes are later recovered after FromDeep research has consumed the reduced universe, they are not silently added. Incorporating them is a method/universe change requiring invalidation and re-adjudication of downstream FromDeep evidence.

For the current WNBA runway, Aug. 13 may be declared a provenance-unavailable development exclusion only under the already-completed R0/R0A evidence that its exact full-row pregame sources could not be recovered without semantic regeneration.

## Market namespace derivation

Before signal research, derive and seal the market-owner namespace outcome-blind.

The final namespace is the union of:

1. canonical market identities carried by factual eligible Demon-OVER rows in the physically sealed **usable full-row** discovery universe; and
2. canonical market identities independently proven by sealed outcome-blind identity/provenance artifacts on any formally provenance-excluded discovery date.

The second class is retained as explicit **zero-support owner lanes** unless the same canonical market also appears on a usable full-row date.

Rules:

1. Start from the canonical market label actually carried by each factual eligible row or independently sealed factual eligible identity.
2. Build the union across the admitted outcome-blind discovery authority.
3. A source label may be normalized into another owner only when an existing repository-canonical market alias/equality contract proves that equivalence. Do not invent aliases for convenience.
4. Any previously unknown or legacy-unlisted factual market remains a separate owner until repository-canonical equality proves otherwise.
5. Zero-support owner lanes may not receive wins, losses, hit rates, reliability, GREEN/RED state, or selection authority merely because their identity is known. They remain GRAY/inactive until supported full-row evidence exists under the frozen procedure.
6. Preserve the derived namespace, support class, normalization mapping, and provenance exclusions as pretruth artifacts before outcomes or signal statistics are opened.

The Aug. 13 R0/R0A evidence observed and canonically adjudicated `blks_stls`, `quarters_with_3_points`, `quarters_with_4_points`, and `quarters_with_5_points` as distinct canonical markets outside the legacy 21-market list. If Aug. 13 is formally excluded for provenance, those markets remain zero-support owner lanes unless they also appear in the usable full-row discovery universe.

## First research question: win/loss forensic

Before building a selector, audit what wins and what loses and why.

The market-specific signal atlas should examine, where supported by the actual corpus fields:

- market identity;
- line/depth characteristics;
- projection-edge ranges;
- probability bands as one explanatory variable, not the primary selector;
- player role, minutes, usage, opportunity and rotation context;
- fragility measures;
- Atlas component combinations;
- injury/availability/context features;
- temporal stability across dates;
- concentration by player/team/date so one cluster cannot masquerade as a durable signal.

Losses should receive a descriptive taxonomy derived from available evidence rather than a preconceived fixed list. Examples that may be distinguishable include minutes/role failure, insufficient opportunity, excessive line depth, market-specific weakness, adverse context, and ordinary outcome variance.

## Signal states

Candidate road conditions are classified into three conceptual states:

- **GREEN** — sufficiently supported winning road; eligible.
- **RED** — sufficiently supported losing or unstable road; veto.
- **GRAY** — insufficient evidence; inactive.

GRAY is intentional. Every road does not need a forced decision.

Exact support thresholds, confidence method, and state-transition rules are **not frozen by this architecture document**. They must be derived and predeclared through discovery-only runway work before performance-bearing historical-as-of evaluation.

## Reliability, not raw hit rate

Do not rank or activate signals from raw hit rate alone.

The registry should account for at least:

- support count;
- unique dates;
- unique players where relevant;
- market baseline;
- lift above market baseline;
- uncertainty / lower-confidence or posterior bound;
- temporal stability;
- failure concentration.

A Beta-binomial posterior, Wilson lower bound, or another predeclared reliability method may be evaluated, but the architecture does not preselect a numerical cutoff today.

## Eligibility and ranking

Conceptually:

`Eligible(leg) = matches >=1 GREEN signal AND matches no RED veto`

Only eligible legs enter FromDeep ranking.

Among eligible legs, ranking may use a simple reliability-oriented score based on supported-signal strength, market-relative lift, support, temporal stability, and fragility. Atlas probability may participate only as a secondary input after eligibility.

Signal determines **whether the leg is allowed into FromDeep**. Probability may help decide **between already-qualified legs**.

## Historical-as-of evaluation

Once the signal-learning procedure is fully specified, evaluate it causally.

For each usable target date `D`:

1. use only settled Demon-OVER development evidence from usable dates `t < D`;
2. update the market-owned GREEN/GRAY/RED registry under the frozen procedure;
3. freeze registry state;
4. expose date `D` pregame Demon-OVER surface;
5. select qualified FromDeep legs or abstain;
6. seal selections;
7. reveal `D` settlement;
8. append `D` to history.

Nothing originating on or after `D` may influence `D`. Formally provenance-excluded dates are skipped entirely and never appended to history.

## Development/validation boundary

FromDeep development is **discovery-only**.

Do not reuse the legacy `builder_from_deep_research.py` candidate-development gate as-is because it mixes discovery and validation evidence when declaring candidate signals.

Legacy `rp37_from_deep_registry.py` may provide neutral implementation patterns or historical market labels, but its fixed 21-market namespace and activation logic are not statistical or namespace authority for the current FromDeep method.

Protected validation remains sealed until 2L, 3L, 4L, and FromDeep are frozen. After frozen-stack validation, the lockbox may be opened only if no post-validation method changes occur.

## Expected outcome

FromDeep is allowed to be sparse.

A valid final method may support only a subset of the derived factual market-owner namespace and may populate on only a minority of slates. Unsupported and zero-support markets remain inactive. A slate with zero qualified FromDeep legs is an honest abstention, not a failure.

## Planned runway

`source/provenance adjudication -> usable Demon-OVER scored-leg census -> market namespace + pretruth seal -> win/loss forensic -> market-specific signal atlas -> GREEN/RED/GRAY procedure -> historical-as-of registry evaluation -> freeze decision`

Use the Prime cheap-runway doctrine before any expensive full-surface projection or learning operation.
