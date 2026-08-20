# WNBA FromDeep Targeted Refinement — FTM + Turnovers R0

Status: **USER/CHAT AUTHORIZED — ACTIVE CODEX EXECUTION MISSION**

Date: 2026-08-19

Mission ID: `WNBA_FROMDEEP_TARGETED_REFINEMENT_FTM_TOV_R0`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Starting pushed target SHA:

`6ae67805e2112f09f16f40f9daf0d5f7676af300`

## Objective

Perform one deliberately small development-consumed refinement pass on only the two unresolved FromDeep markets that still have meaningful current traction but no clean freeze-candidate surface:

- `free_throws_made`
- `turnovers`

The goal is not to reopen FromDeep discovery. The goal is to answer:

> **Can either unresolved market be narrowed from its existing mixed road(s) into a current, causal, specialist-grade road by appending a very small number of already-known pregame commons, without changing the rest of the accepted FromDeep registry?**

If not, the market abstains and we move on.

## Accepted predecessor

Causal Lane Reconciliation R0 is accepted complete at target commit:

`6ae67805e2112f09f16f40f9daf0d5f7676af300`

Accepted reconciliation facts:

- 14 high-precision roads reconciled;
- 12 road identities recommended `FREEZE_CANDIDATE`;
- 7 road identities recommended `TARGETED_REFINEMENT_CANDIDATE`;
- 8 road identities recommended `DO_NOT_CARRY_FORWARD`;
- proposed deduplicated freeze registry: 10 representatives;
- selector not frozen or promoted;
- protected / validation / lockbox / heldout / Aug.13 / Live / fitting activity all zero.

The proposed 10-representative freeze registry is **held unchanged** during this mission. Do not tune, delete, add gates to, or otherwise alter those registry entries.

## Reconciliation decision on the seven targeted-refinement roads

Two targeted roads do not justify another research branch because their only unique same-market marginal candidate was a loss while sibling high-precision roads already cover the market:

- `ROAD:2aa51fc63ab02cd63dabe666f2ed4668c9f969cdf9b5670a584281d13a7488f4` — `blks_stls`
- `ROAD:2cd2b2ad62679304944eb9087a6d02e565e9b1290b243b25e0fcd251b5cb3059` — `steals`

Do not refine those two roads. Do not carry them into the proposed freeze registry. Their sibling freeze-candidate surfaces remain authoritative for those markets.

The only five base roads authorized for targeted refinement are:

### Free throws made

- `ROAD:374bcccb194d9fb5144f45a9759b37637082c59b82d62220617dcaba493e7ba8`
- `ROAD:6e42214971a4b68b8a0448170d7d4df19234866611e120e66c7bff7705da4a07`
- `ROAD:b73c755652c3a18ec1973d4a02a4ce2615b77dfaa6e3f5ae0e05cc70fbf0e78b`

### Turnovers

- `ROAD:4ea99f678027c66f4f3e66b7a35bf7dfe315b82602428c6c7b32cda6b1546b0a`
- `ROAD:ba243d0c0982534bb2b30112d09ae9197eeef49ae6cdec59ad5c8ff0a992afba`

The decayed turnover road `ROAD:5c811f529fca236828fb87df5e0a21af494adf7423c554e7c36dc186f43dd774` may be used only as existing loss/subset context. It is not a base road and cannot itself be promoted by this mission.

## Binding product doctrine

Bind:

- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_DOCTRINE.md`
- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_NAMES.md`
- `docs/coordination/wnba/chat/FROMDEEP_PRODUCT_INTEGRATION_CONTRACT.md`

FromDeep remains signal-driven and uncapped. This mission is about whether a road is good enough, never about forcing a desired number of outputs.

## Allowed development evidence

Development-consumed evidence only.

Allowed sources are limited to already accepted FromDeep development artifacts and their canonical pregame feature values:

- Win/Loss Commons R0;
- Recent Precision Roads R0;
- 27-road Causal Audit R1;
- Causal Lane Reconciliation R0;
- the same July/August unprotected development candidate corpus already consumed by those stages.

June remains background only and has no threshold, selection, or ranking authority.

Protected, validation, lockbox, heldout, Aug.13, and Live evidence remain prohibited.

## Predicate pool — no new feature discovery

Do **not** reopen the full feature inventory or 14,615-road search.

For each market, the only predicates eligible to be appended are exact pregame predicate identities already surfaced for that same market in either:

1. Win/Loss Commons R0 favorable/veto evidence; or
2. Recent Precision Roads R0 finalist/top-three road definitions.

No new feature identity, semantic family, operator family, quantile symbol, categorical value, or probability gate may be invented.

If the union contains more than 12 distinct appendable predicates for a market, cap it deterministically without outcome re-ranking using this precedence:

1. Commons primary favorable;
2. Commons primary veto;
3. predicates appearing most frequently across the market's existing R0 finalist/top-three roads;
4. canonical predicate string ascending.

## Refinement grammar

Each of the five authorized base roads remains intact.

A refined variant may **append only one or two additional predicates/vetoes** from the allowed same-market pool.

Do not remove, relax, rewrite, or invert a base-road gate.

Maximum final gate depth is six. This is sufficient for the current FTM and turnover bases while keeping the refinement interpretable and bounded.

Numeric gates preserve their frozen operator + quantile symbol identity; for target date `D`, any numeric cutoff must be realized strictly from authorized prior `t < D` current-regime pregame rows. Exact categorical/boolean values remain exact.

Missing positive gates fail qualification. Missing veto values do not invent a veto hit.

No model probability, EV, rank, top-N, or candidate-count rule may enter qualification.

## Search topology

This is a small bounded refinement, not a new atlas.

For each base road, enumerate only append sets of size 1 and 2 from the capped allowed predicate pool, rejecting contradictory or duplicate predicates before evaluation.

Before execution, report the exact variant count. If the total exceeds 400 variants across all five bases, stop and return to user/Chat rather than broadening the search.

No architecture framework, checkpoint lattice, generalized road engine, or multi-hour sweep is authorized.

## Evaluation and time arrow

Evaluate variants causally across the already-consumed July/August development regime.

For each target date:

1. realize numeric thresholds from prior pregame data only;
2. seal qualifying candidate identities before reading that target date's outcomes;
3. join settlements only after sealing;
4. deduplicate exact candidate identities when calculating market/union diagnostics.

This remains **development-consumed refinement evidence**, not OOS or protected validation.

Latest 10 usable dates remain the primary current-traction window; the earlier July portion remains support/stress context.

## Deterministic selection objective

At most one refined representative may be proposed per market.

A variant is eligible for `REFINED_FREEZE_CANDIDATE` only if all are true:

- active binary support >= 6;
- active selected dates >= 4;
- active participants >= 4;
- active strict precision >= 0.70;
- active date-balanced precision >= 0.70;
- latest-10 binary support >= 3;
- latest-10 selected dates >= 2;
- latest-10 strict precision >= 0.80;
- latest-10 date-balanced precision >= 0.80.

A variant with latest-10 100% precision but only 2 binary selections may be reported as `REFINED_SPARSE_WATCH`, never automatically elevated to freeze candidate.

Among eligible variants for a market, choose one deterministically by:

1. latest-10 strict precision descending;
2. latest-10 date-balanced precision descending;
3. active strict precision descending;
4. active date-balanced precision descending;
5. active binary support descending;
6. fewer appended predicates;
7. canonical expression ascending.

If no variant clears the fixed criteria, disposition the market `NO_REFINED_SPECIALIST_ROAD` and stop searching that market. Do not loosen criteria after seeing results.

## Required report

For each of the two markets return:

- every authorized base road and its unchanged expression;
- allowed append-predicate pool;
- exact bounded variant count;
- selected refined representative, if any;
- full refined expression and source provenance for every appended predicate;
- gate-by-gate candidate removal W/L/NB anatomy;
- active and latest-10 W/L/NB, strict, date-balanced, dates, participants, most recent fire date;
- contemporaneous exact-market baseline and lift;
- zero-inclusive fires by date for the selected refined road;
- disposition: `REFINED_FREEZE_CANDIDATE`, `REFINED_SPARSE_WATCH`, or `NO_REFINED_SPECIALIST_ROAD`.

Also return a **proposed final FromDeep development registry** that combines:

- the unchanged 10-representative reconciliation freeze registry;
- plus any `REFINED_FREEZE_CANDIDATE` representative(s) from this mission;

with exact duplicate/equivalent candidate surfaces collapsed operationally and all source road IDs retained as provenance.

Do not freeze or promote that registry in this mission.

## Hard boundaries

Prohibited:

- touching the 10 existing proposed freeze-registry road definitions;
- refining `blks_stls` or `steals` further in this mission;
- adding the eight `DO_NOT_CARRY_FORWARD` roads;
- promoting the decayed turnover road;
- new feature discovery;
- arbitrary numeric threshold search;
- more than two appended predicates;
- more than 400 total variants;
- fitting/training/calibration;
- protected / validation / lockbox / heldout / Aug.13 access;
- Live/model/publication/promotion mutation;
- core 2L/3L/4L changes;
- count-based output suppression.

## Workflow/resource envelope

Execution tier: `R1_BOUNDED_TARGETED_REFINEMENT`.

One parent Builder preamble; subagents inherit it.

Target parent mission <=25 minutes. Hard workflow boundary 40 minutes.

Use existing FromDeep code/artifacts wherever possible. Do not build another generalized research framework.

## Completion

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_TARGETED_REFINEMENT_FTM_TOV_R0_COMPLETE`

Return the two-market refinement packet, proposed final development registry, exact test/audit results, evidence/receipt IDs, and mission wall-clock versus scientific runner time.

Do not open protected validation automatically.