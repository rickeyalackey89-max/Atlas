# WNBA FromDeep Recent Precision Roads R0

Status: **USER/CHAT AUTHORIZED — ACTIVE CODEX EXECUTION MISSION**

Date: 2026-08-19

Mission ID: `WNBA_FROMDEEP_RECENT_PRECISION_ROADS_R0`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Starting pushed target SHA: `dabd1d0b20e0aa07138c15ba28df9f37fc7d65af`

## Accepted predecessors

Accept the WIN-vs-LOSS Commons R0 and Commons Selector V1 development replay as completed development evidence.

Commons R0:

- target commit `02f8b7143012c879df55078fb7017ed9635382ea`;
- 19 markets with `POSITIVE_COMMONS_PRESENT`;
- 8 markets with `INSUFFICIENT_EVIDENCE`.

Commons Selector V1 replay:

- target commit `dabd1d0b20e0aa07138c15ba28df9f37fc7d65af`;
- 498 qualified singles;
- 250 WIN / 238 LOSS / 10 nonbinary;
- strict binary rate `51.2295%`;
- date-balanced rate `49.9820%`;
- exact selected market-date baseline `22.3278%`;
- 29 selected dates / 83 participants;
- no validation, lockbox, Aug.13, heldout, Live, or fitting evidence consumed.

Interpretation:

The broad one-positive-plus-one-veto selector demonstrated large information lift over the Demon baseline but emitted far too much volume and is not the intended FromDeep product. It is discovery/procedural evidence, not a product candidate to ship as-is.

## Binding cross-sport product doctrine

Read and bind:

- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_DOCTRINE.md`
- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_NAMES.md`

FromDeep is the WNBA/NBA/CBB name for the same Atlas Demon-specialist product concept represented by BigSwings in MLB and HailMarys in NFL.

The product objective is **not broad Demon coverage**. It is the narrowest, strongest, highest-conviction Demon single-leg flex/add-on surface, normally about `0-3-ish` fires per run/slate, with zero a valid successful output.

## Scientific question

**Using only already-admitted pregame features and already-settled development evidence, what narrow multi-gate, market-owned Demon roads are strongest in the current WNBA regime closest to 2026-08-19, while June is retained only as background/stress context?**

This is a road-discovery packet. It does not freeze or validate a final selector.

## Recency authority

The market is treated as a moving target.

### Active discovery regime

Use only usable settled development dates from:

`2026-07-01` through `2026-08-09`

for road discovery, road support, road ranking, and current-regime pass/fail diagnostics.

### Current traction window

Within that active regime, define the **current traction window** as the latest **10 usable development dates** ending at the newest available development date (`2026-08-09`). Derive the exact ten dates from the sealed corpus rather than hard-coding assumptions about missing dates.

Current-traction performance is more decision-relevant than older active-regime performance.

### June

June remains background/stress evidence only.

June rows may be reported *after* current-regime roads are identified, but June may not:

- contribute to road discovery;
- contribute to support minima;
- change active/current road ranking;
- reject a road that is strongly supported in the current regime;
- be used to add or remove a gate.

Do not delete or invalidate June evidence. Keep it as historical context only.

## Candidate-gate authority

Do **not** reopen the full 52,488-condition universe and do not build another atlas.

For each market, use only the already-produced Commons R0 shortlist evidence:

- up to the five strongest favorable commons;
- up to the five strongest negative/veto commons;
- the exact pregame field/operator/quantile-or-category identity already recorded in Commons R0.

Collapse exact duplicate/equivalent alias conditions before combination.

Hard leakage/postgame/future/identity-provenance exclusions remain binding.

Direct model probability may be reported as context but is not a gate unless it already appears as an admitted Commons condition under the existing evidence contract. Do not invent a probability threshold in this mission.

## Narrow road construction

A road is a deterministic conjunction of admitted gates.

Examples:

`A AND B AND C`

or

`A AND B AND NOT VETO_C AND D AND NOT VETO_E`

Rules:

1. A road must contain at least one favorable gate.
2. A road may contain from 1 through 8 total gates.
3. Negative/veto commons enter as `NOT <veto condition>`.
4. Only fixed Commons landmarks/categories are allowed; no free numerical threshold search.
5. For numeric conditions, retain the quantile symbol (`q10/q25/q50/q75/q90`) rather than inventing a literal cutpoint.
6. Contradictory roads are invalid.
7. Do not add a gate merely to manufacture 100% history.

Because each market has at most ten collapsed shortlist gates, an exhaustive enumeration of the resulting bounded shortlist combinations is acceptable. Do **not** expand beyond that shortlist.

## Specialist-grade evidence screen

This mission is allowed to be extremely selective.

A road may be labeled `SPECIALIST_GRADE_CURRENT_CANDIDATE` only if, on the July/August active regime:

- at least 8 binary selections;
- at least 5 unique selected dates;
- at least 5 unique participants/combo identities;
- active-regime strict binary WIN rate >= `0.60`;
- active-regime lift versus the exact contemporaneous same-market/date Demon baseline >= `+0.20` absolute;
- and, in the latest-10-date current traction window, where the road has at least 5 binary selections across at least 4 dates:
  - strict binary WIN rate >= `0.70`;
  - date-balanced WIN rate >= `0.70`.

If current-window support is below 5 binary selections or 4 dates but the road is at least 80% strict and has at least 5 active-regime binary selections, classify it `SPARSE_HIGH_PRECISION_WATCHLIST`, not specialist-grade.

These are discovery screens, not promotion thresholds.

Do not force every market to produce a road.

## Minimality / anti-overfit rule

Among roads that clear the same precision class, prefer a road that is not gratuitously complex.

For every reported finalist, perform leave-one-gate-out diagnostics.

A gate is justified when removing it materially degrades current-regime/current-window precision, materially increases losing fires, or causes the road to fail the stated specialist-grade screen.

Report any gate that appears unnecessary. Do not silently keep ornamental gates.

Also Pareto-prune a road when a strict subset of its gates has equal-or-better current-window precision, equal-or-better active-regime precision, and at least as much support.

## Required temporal diagnostics

For every reported finalist, show:

- July/August active-regime W-L-NB, strict rate and date-balanced rate;
- latest-10-date current-window W-L-NB, strict rate and date-balanced rate;
- exact-date market baseline and lift for both windows;
- selected dates and participants;
- zero-inclusive fires per usable date;
- gate count and full gate expression;
- leave-one-gate-out effect;
- June background W-L-NB and rate, clearly marked `BACKGROUND_ONLY`;
- trajectory classification:
  - `STABLE_STRONG`
  - `EMERGING_STRONG`
  - `DECAYING`
  - `SPARSE_HIGH_PRECISION_WATCHLIST`
  - `NO_CURRENT_PRECISION_ROAD`.

An improving late road is not to be penalized merely because older history was weaker.

## Output-density diagnostic

The product target is sparse.

After ranking roads per market, form a **diagnostic-only union** of each market's best non-decaying candidate road and report the zero-inclusive number of fires per usable active-regime date and per latest-10 current date.

This does not freeze a selector or create a hard output cap.

Report:

- median fires/date;
- 90th percentile fires/date;
- max fires/date;
- percentage of dates with 0, 1, 2, 3, and >3 fires.

If the diagnostic union routinely produces >3 fires, say so plainly: the road set is still too broad for FromDeep.

Do not fix excess volume by adding an arbitrary probability top-N cap in this mission.

## Road ranking

Within each market, return at most the top 3 Pareto-valid roads.

Rank in this order:

1. current-window strict precision;
2. current-window date-balanced precision;
3. active-regime strict precision;
4. active-regime lift over contemporaneous baseline;
5. active-regime support;
6. fewer gates when otherwise tied.

A market may return zero roads.

## Workflow / implementation

This is one bounded mission.

One full Builder preamble at parent activation. Subagents inherit it.

No repeated control cycles for ordinary aggregation, shortlist enumeration, reporting, focused testing, or implementation fixes that preserve the mission.

Prefer direct analysis of the already-produced Commons R0 and Commons Selector V1 artifacts plus their existing admitted row sources.

Do not build a new generalized research engine.

A small mission-specific analyzer/utility is allowed if needed.

Do not create a checkpoint framework.

Do not rerun the old SAFE Tier A/Tier B signal atlas.

Do not rerun Commons R0 across the full field universe.

Target parent mission <=45 minutes. Hard workflow boundary 60 minutes. If the required road packet is not essentially complete by 60 minutes, stop and return the actual blocker rather than expanding infrastructure.

## Hard boundaries

Prohibited:

- protected validation or lockbox access;
- Aug.13 contribution;
- heldout outcome access;
- Live/model/publication/promotion mutation;
- model fitting/training/tuning;
- new probability calibration;
- core 2L/3L/4L method changes;
- final FromDeep selector freeze;
- final product ranking/cap policy;
- core-slip attachment/routing changes;
- numerical threshold search outside fixed Commons landmarks;
- expanding beyond the bounded Commons shortlist gates.

## Required deliverables

Return:

1. one concise human-readable market report;
2. one compact machine-readable road artifact;
3. a per-market top-3 road table;
4. the diagnostic sparse-union firing distribution;
5. explicit list of markets with no current precision road;
6. explicit list of `SPECIALIST_GRADE_CURRENT_CANDIDATE` and `SPARSE_HIGH_PRECISION_WATCHLIST` roads;
7. total mission wall time versus actual analyzer runtime.

Do **not** auto-start a historical-as-of road replay or validation after this packet.

## Completion

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_RECENT_PRECISION_ROADS_R0_COMPLETE`

At that stop, Chat/user will choose the narrow road set to freeze for one causal replay / protected-validation decision path.
