# WNBA FromDeep Causal Lane Reconciliation R0

Status: **USER/CHAT AUTHORIZED — ACTIVE CODEX EXECUTION MISSION**

Date: 2026-08-19

Mission ID: `WNBA_FROMDEEP_CAUSAL_LANE_RECONCILIATION_R0`

Target repository: `rickeyalackey89-max/Atlas-WNBA`

Target branch: `builder-method-contract-v1`

Starting pushed target SHA:

`749589392d8faa58f438ddcd601607bf5a35c68b`

## Objective

Use the completed 27-road causal-audit artifacts only to reconcile the surviving WNBA FromDeep lanes before any freeze or protected validation decision.

The question is:

> **Among the roads that already showed causal high-precision support or sparse high-precision evidence, which road identities are redundant, which broader roads add genuinely useful candidates, which narrower roads protect precision, and which lanes should be carried forward as freeze candidates versus targeted-refinement candidates?**

This is an artifact-only reconciliation mission. It is **not** a new replay, threshold search, road search, model fit, validation pass, or Live action.

## Binding product doctrine

Read and bind:

- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_DOCTRINE.md`
- `docs/coordination/ATLAS_DEMON_SPECIALIST_PRODUCT_NAMES.md`
- `docs/coordination/wnba/chat/FROMDEEP_PRODUCT_INTEGRATION_CONTRACT.md`

FromDeep remains signal-driven and uncapped. Output count is never a pass/fail criterion. A road may be retained even if it fires rarely. Distinct genuine qualifiers must not be eliminated merely because another candidate also fires on the same run.

## Accepted predecessor

The 27-road causal audit is accepted complete at target commit:

`749589392d8faa58f438ddcd601607bf5a35c68b`

Accepted facts:

- exactly 27 frozen R0 roads causally audited once;
- 142 distinct uncapped Demon candidates;
- active union: 85 WIN / 54 LOSS / 3 nonbinary, strict 61.1511%, +32.3161 pp strict baseline lift;
- latest-10 union: 45 WIN / 16 LOSS / 1 nonbinary, strict 73.7705%;
- 3 `CAUSAL_HIGH_PRECISION_SUPPORTED` roads;
- 11 `CAUSAL_HIGH_PRECISION_SPARSE` roads;
- 8 `CAUSAL_MIXED` roads;
- 3 `CAUSAL_DECAYED` roads;
- 2 `CAUSAL_INACTIVE_INSUFFICIENT_FIRE` roads;
- protected, validation, lockbox, Aug.13, heldout, fitting, Live, and automatic follow-on counts all zero.

## Sole scientific inputs

Use only the already-produced causal-audit artifacts at the accepted target commit:

- `data/wnba/bap2_work/builder_stage_5/fromdeep_27_candidate_roads_causal_audit_r1/FROMDEEP_27_CANDIDATE_ROADS_CAUSAL_AUDIT_R1_ROAD_AUDIT.csv`
- `data/wnba/bap2_work/builder_stage_5/fromdeep_27_candidate_roads_causal_audit_r1/FROMDEEP_27_CANDIDATE_ROADS_CAUSAL_AUDIT_R1_EQUIVALENCE_OVERLAP.json`
- `data/wnba/bap2_work/builder_stage_5/fromdeep_27_candidate_roads_causal_audit_r1/FROMDEEP_27_CANDIDATE_ROADS_CAUSAL_AUDIT_R1_UNION_DIAGNOSTICS.json`
- `data/wnba/bap2_work/builder_stage_5/fromdeep_27_candidate_roads_causal_audit_r1/FROMDEEP_27_CANDIDATE_ROADS_CAUSAL_AUDIT_R1.json.gz`
- `data/wnba/bap2_work/builder_stage_5/fromdeep_27_candidate_roads_causal_audit_r1/final_receipt.json`

Do not regenerate the causal selections. Do not reread protected or heldout sources.

## Primary road authority — exactly 14 high-precision roads

Perform marginal reconciliation on exactly these 14 roads that the causal audit classified as `CAUSAL_HIGH_PRECISION_SUPPORTED` or `CAUSAL_HIGH_PRECISION_SPARSE`.

### BLKS+STLS

- `ROAD:06913b6f82e57c5d332986716ff189be6f38ed2a41eb0d44877bec052849a250`
- `ROAD:2aa51fc63ab02cd63dabe666f2ed4668c9f969cdf9b5670a584281d13a7488f4`
- `ROAD:95b6347af3248a1d830c615f250bf2b4c6e0f903493847705c6b0cceb749a58f`

### Blocks

- `ROAD:619110bd383b954a23228bf4167ff8a09433ff81b6eae7ba89123cb622b25b67`
- `ROAD:7ed69228aa36b21c9f2081c91299aee16a54252a33977c546c64939872cbef96`
- `ROAD:a9ab4ae58a67cef2a52ee4ef6126decd5fe5beef53f193985136a02105624b03`

### Offensive rebounds

- `ROAD:7b10cb7f1b60945ab82506cb85becab8e0663abdb400de194cea21ffef477e4e`

### Steals

- `ROAD:26d2a30bfb30f1364eab20eaa04039c45ea482d9ec070da291c9cc82e272fdd7`
- `ROAD:2cd2b2ad62679304944eb9087a6d02e565e9b1290b243b25e0fcd251b5cb3059`
- `ROAD:64476c4f2de09b4a8b637c3c4fa4c3a5aee97150ca9adb1d38fe42f492b6baff`

### Three-pointers made

- `ROAD:aedaa6dc3625d9ff78f0248470297578add2e86ae208d4515e24d3598cd4a8c2`

### Free throws attempted

- `ROAD:653545eeb14ceac07a037a21b4f741dd85ccefadc135552cdec4b872563525e0`
- `ROAD:e48eadf48debc7ea01bb1479d6d03cd1084650e0010aa46d35bd2d29311a5c0a`
- `ROAD:ed5a34a3ea390f4059a39a37642320bfe90940c278112fd141c283f8ec3a599a`

The unique authoritative road count must equal **14**, and every ID must be present in the accepted causal `ROAD_AUDIT.csv` with one of the two high-precision causal classifications. Any mismatch fails closed.

## Required marginal analysis

For every same-market group among the 14 roads:

1. preserve the exact causal selection set already sealed for each road;
2. identify exact selection-surface equivalence;
3. identify strict subset/superset relationships;
4. for each road, compute candidates unique to that road versus the union of its same-market peers;
5. for each broader road, compute candidates added beyond each narrower/subset road;
6. for each narrower road, compute candidates excluded relative to the broader road;
7. grade each marginal/added/excluded candidate set W/L/NB, strict precision, date-balanced precision where meaningful, selected dates, most recent date, and latest-10 W/L/NB;
8. report whether the marginal candidates improve, preserve, or damage current-regime precision;
9. report overlap counts so corroborating roads are not mistaken for additional picks.

For single-road markets among the 14 (`offensive_rebounds`, `three_pointers_made`), simply preserve their causal evidence and carry them into the decision packet without inventing a comparison road.

## Existing mixed-road context

Do **not** perform new road discovery or threshold work on the 8 `CAUSAL_MIXED` roads. However, summarize their already-known causal evidence from the audit so Chat/user can decide whether a later **targeted current-regime refinement** is warranted.

Do not silently discard a mixed road merely because its full active-regime precision is lower if its latest-window trajectory materially improved. Recency remains decision-relevant.

The 3 `CAUSAL_DECAYED` and 2 `CAUSAL_INACTIVE_INSUFFICIENT_FIRE` roads should be carried only as context and not included in marginal high-precision reconciliation.

## Decision packet

Return a concise lane-level packet with three **recommendation** classes only; this mission does not itself freeze anything:

- `FREEZE_CANDIDATE` — the existing causal road/surface is coherent enough to carry unchanged into a freeze/validation decision;
- `TARGETED_REFINEMENT_CANDIDATE` — current evidence is interesting, especially recently, but the existing road is not clean enough to freeze unchanged;
- `DO_NOT_CARRY_FORWARD` — current causal evidence is mixed/decayed/inactive enough that the lane should not advance in its present form.

For every recommendation state:

- cite the exact road IDs involved;
- distinguish road identity from equivalence cluster identity;
- explain the marginal evidence supporting the recommendation;
- preserve low-support high-precision roads as legitimate evidence;
- never use candidate count as a rejection reason.

Also return a proposed **deduplicated freeze-candidate road registry** for user/Chat review only. It should collapse operationally equivalent selection surfaces while preserving all corroborating source road IDs in provenance.

## No new science

Prohibited:

- any new causal replay;
- any new target-date evaluation;
- road generation;
- adding/removing gates;
- threshold search;
- quantile recomputation;
- model probability filtering;
- fitting/training/tuning/calibration;
- validation/lockbox/protected/heldout/Aug.13 access;
- Live/model/publication/promotion mutation;
- core 2L/3L/4L changes;
- count-based suppression or density pass/fail rules.

A tiny artifact-only parser/report generator and focused tests for reconciliation arithmetic are allowed.

## Workflow/resource envelope

Execution tier: `R0_ARTIFACT_ONLY_RECONCILIATION`.

One parent Builder preamble. Subagents inherit it.

Target parent mission <=20 minutes. Hard workflow boundary 30 minutes.

No broad governance rereads, no generalized engine, no new checkpoint framework.

## Completion

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_CAUSAL_LANE_RECONCILIATION_R0_COMPLETE`

Return:

- the 14-road marginal reconciliation table;
- equivalence/subset/superset incremental evidence;
- mixed-road current-trajectory context;
- the three-class lane recommendation packet;
- proposed deduplicated freeze-candidate registry for review;
- artifact IDs/receipts;
- focused test result;
- parent mission wall-clock versus analyzer/report runtime.

Do not freeze a selector and do not open protected validation automatically.
