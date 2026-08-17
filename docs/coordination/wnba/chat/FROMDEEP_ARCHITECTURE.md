# WNBA FromDeep Agreed Architecture

Status: **AGREED ARCHITECTURE — EXECUTION NOT YET AUTHORIZED**

This document records the user/Chat-agreed strategic architecture for the future WNBA FromDeep family. It is not Builder execution authority and does not supersede the WNBA `slip-builders` controller.

## Purpose

FromDeep is not another probability-ranked leftovers family.

Normal Builder families answer:

> Which combination of qualified legs is strongest?

FromDeep answers:

> Which types of aggressive OVER roads repeatedly win, under what conditions, and which roads should be excluded before ranking?

The family is a sparse specialist. Precision matters more than coverage.

## Core family contract

- Demon-tier **OVER** roads only.
- Preserve market ownership. The existing 21-market separation remains the architectural skeleton; do not collapse all markets into one generic signal pool.
- No minimum slate output count.
- Honest abstention is a successful result when no supported signal exists.
- Probability is not the primary eligibility mechanism. It may be used only after evidence-based signal eligibility as a secondary ranking, sanity, or tie-break input.
- Public/live output is not development, validation, or lockbox authority.

## Development universe

Start from the **full eligible scored Demon-OVER leg universe** on development/discovery dates.

Do not start from:

- prior FromDeep releases;
- public picks;
- legs selected by a historical FromDeep policy;
- only high-probability rows.

For each development date, reconstruct the pregame eligible Demon-OVER surface with all available pregame fields, physically seal that surface, and only then append settlement.

Conceptually each leg record is:

`market + line/depth + player/context + projection + edge + probability + Atlas components + fragility + role/minutes/usage/context + outcome`

Outcome must never define the candidate universe.

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

Protected validation remains sealed until 2L, 3L, 4L, and FromDeep are all frozen. After frozen-stack validation, the lockbox may be opened only if no post-validation method changes occur.

## Expected outcome

FromDeep is allowed to be sparse.

A valid final method may support only a subset of the 21 markets and may populate on only a minority of slates. Unsupported markets remain inactive. A slate with zero qualified FromDeep legs is an honest abstention, not a failure.

## Planned runway after 4L is frozen

`full Demon-OVER scored-leg census -> pretruth seal -> win/loss forensic -> market-specific signal atlas -> GREEN/RED/GRAY procedure -> historical-as-of registry evaluation -> freeze decision`

Do not begin this runway until 4L is resolved and a separate user-authorized Prime delegation is published.
