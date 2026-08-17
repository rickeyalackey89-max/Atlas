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
- Preserve **market ownership**. Every canonical factual eligible Demon-OVER market present in the physically sealed discovery universe receives its own owner/policy lane unless repository-canonical normalization proves two source labels are aliases of the same market.
- The legacy RP37 21-market list is historical structure only. It is neither a minimum nor a cap and cannot silently exclude factual current-stack markets.
- Do not merge distinct markets merely because their statistics are related. For example, a combo market is not automatically owned by either component market, and quarter-specific markets are not automatically owned by full-game points.
- The final owner count is derived only from the complete outcome-blind sealed discovery universe. Partial-date evidence may identify candidate additional owners but may not freeze the final count.
- No minimum slate output count.
- Honest abstention is a successful result when no supported signal exists.
- Probability is not the primary eligibility mechanism. It may be used only after evidence-based signal eligibility as a secondary ranking, sanity, or tie-break input.
- Public/live output is not development, validation, or lockbox authority.

## Development universe

Start from the **full eligible scored Demon-OVER leg universe** on development/discovery dates.

FromDeep is architecturally independent of core selected-leg depletion. Frozen 2L, 3L, and 4L gate sequencing but do not remove legs from the FromDeep research universe.

Do not start from:

- prior FromDeep releases;
- public picks;
- legs selected by a historical FromDeep policy;
- core-family leftovers;
- only high-probability rows;
- historically winning rows;
- the legacy RP37 active/inactive market decisions.

For each development date, reconstruct the factual pregame eligible Demon-OVER surface with all available pregame fields, physically seal that surface, and only then append settlement.

Conceptually each leg record is:

`market + line/depth + player/context + projection + edge + probability + Atlas components + fragility + role/minutes/usage/context + outcome`

Outcome must never define the candidate universe.

## Market namespace derivation

Before signal research, derive the market-owner namespace from the complete physically sealed outcome-blind Demon-OVER discovery surface.

Rules:

1. Start from the canonical market label actually carried by each factual eligible row.
2. Build the union across the complete discovery surface.
3. A source label may be normalized into another owner only when an existing repository-canonical market alias/equality contract proves that equivalence. Do not invent aliases for convenience.
4. Any previously unknown or legacy-unlisted factual market remains a separate candidate owner until adjudicated.
5. Emit zero-support owners only when they are part of a previously frozen canonical namespace being compared for lineage; the final FromDeep namespace itself is the factual sealed-universe union.
6. Preserve the derived namespace and normalization mapping as a pretruth artifact before outcomes or signal statistics are opened.

The Aug. 13 R0 preflight observed `blks_stls`, `quarters_with_3_points`, `quarters_with_4_points`, and `quarters_with_5_points` outside the legacy 21-market list. Those observations justify deriving the final namespace from the complete sealed universe; they do not by themselves prove that the final count is 25.

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

For each target date `D`:

1. use only settled Demon-OVER development evidence from `t < D`;
2. update the market-owned GREEN/GRAY/RED registry under the frozen procedure;
3. freeze registry state;
4. expose date `D` pregame Demon-OVER surface;
5. select qualified FromDeep legs or abstain;
6. seal selections;
7. reveal `D` settlement;
8. append `D` to history.

Nothing originating on or after `D` may influence `D`.

## Development/validation boundary

FromDeep development is **discovery-only**.

Do not reuse the legacy `builder_from_deep_research.py` candidate-development gate as-is because it mixes discovery and validation evidence when declaring candidate signals.

Legacy `rp37_from_deep_registry.py` may provide neutral implementation patterns or historical market labels, but its fixed 21-market namespace and activation logic are not statistical or namespace authority for the current FromDeep method.

Protected validation remains sealed until 2L, 3L, 4L, and FromDeep are frozen. After frozen-stack validation, the lockbox may be opened only if no post-validation method changes occur.

## Expected outcome

FromDeep is allowed to be sparse.

A valid final method may support only a subset of the derived factual market-owner namespace and may populate on only a minority of slates. Unsupported markets remain inactive. A slate with zero qualified FromDeep legs is an honest abstention, not a failure.

## Planned runway

`source/provenance repair -> full Demon-OVER scored-leg census -> market namespace + pretruth seal -> win/loss forensic -> market-specific signal atlas -> GREEN/RED/GRAY procedure -> historical-as-of registry evaluation -> freeze decision`

Use the Prime cheap-runway doctrine before any expensive full-surface projection or learning operation.
