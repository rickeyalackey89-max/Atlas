# WNBA FromDeep Full Scored-Leg Universe R0

Status: **USER-AUTHORIZED PRIME WORK ORDER**

Execution tier: `R0_ARTIFACT_AUDIT_AND_PRETRUTH_SEAL`

## Starting authority

Canonical WNBA repository:

`C:\Users\13142\Atlas\WNBA`

Expected WNBA starting HEAD:

`24c5e29c965f5e808d84470c16146bb18a0b0148`

Expected Builder stop:

`BLOCKED_USER_REVIEW_WNBA_4L_CANONICAL_ATLAS_FREEZE`

Accepted frozen core:

- 2L: `WNBA_2L_ORIGINAL_FROZEN_RANK_V1_1`
- 3L: `WNBA_3L_CAUSAL_POINTWISE_RESEARCH_DEPLETION_V1`
- 4L: `WNBA_4L_CANONICAL_ATLAS_RANK1_RESEARCH_DEPLETION_V1`
- 4L freeze ID: `ba6c1d31387759ba0da2d504e01c3029b2693d54a5c680e7b71972e807bd1133`
- 4L freeze contract SHA-256: `ca4199cc369e155621320a16df44a8ecc4c00925ebf372e269479a6d1da9dc13`
- 4L freeze control receipt SHA-256: `9219b44b99d6756969cce14fc79ed0c8e8d62620c60442f45fa72f002c335516`

The 4L lane is scientifically closed. Do not reopen 4L learner/reranker research.

## Governing FromDeep architecture

Read parent Prime architecture:

`docs/coordination/wnba/chat/FROMDEEP_ARCHITECTURE.md`

FromDeep is a sparse market-owned Demon-OVER specialist. It is **not** a probability-ranked leftovers family.

This R0 answers only:

> Can the current frozen-stack WNBA discovery corpus reconstruct and physically seal the complete eligible scored Demon-OVER pregame leg universe, preserving all 21 market owners and the pregame fields required for the later win/loss signal atlas, without opening any outcome evidence?

## Critical universe semantics

The FromDeep universe is **independent of core selected-leg depletion**.

Start from the full eligible scored Demon-tier OVER leg surface on development/discovery dates.

Do **not** remove legs merely because the same exact selected leg identity was used by frozen 2L, 3L, or 4L. Core freezes gate sequencing; they do not turn FromDeep into a downstream leftover pool.

Do not start from:

- prior FromDeep releases;
- public/live FromDeep picks;
- old signal-match outputs;
- legs selected by an older FromDeep policy;
- probability-cut rows;
- only historically winning rows;
- old RP33/RP34/RP37 active/inactive policy decisions.

Eligibility for the R0 census is factual/pregame only:

- WNBA discovery/development member/date;
- scored leg row from the canonical pregame Builder/leg surface;
- tier = `DEMON`;
- side = `over` under repository canonical side semantics;
- otherwise factually eligible/playable under the canonical scored-leg surface contract.

If the repo has a canonical field stronger/more precise than shorthand `builder_eligible_side`, use that existing contract. Do not invent a new eligibility tuple.

## 21 market owners

Preserve exactly the existing canonical market skeleton:

1. points
2. rebounds
3. assists
4. three_pointers_made
5. 3_pt_attempted
6. blocks
7. steals
8. turnovers
9. fg_made
10. fg_attempted
11. free_throws_made
12. free_throws_attempted
13. offensive_rebounds
14. defensive_rebounds
15. two_pointers_made
16. two_pointers_attempted
17. fantasy_score
18. points_rebounds_assists
19. points_rebounds
20. points_assists
21. rebounds_assists

R0 must emit all 21 owners even when support is zero.

Any eligible Demon-OVER market encountered outside this list must be reported as an unmapped-market audit item and must block authoritative sealing until reviewed; do not silently drop or coerce it.

## Outcome boundary

This R0 is **strictly outcome-blind**.

Outcome/truth/settlement reads = `0`.

Do not open discovery labels, candidate truth, leg truth, validation, lockbox, prior FromDeep performance, public performance, or historical signal hit-rate artifacts.

Use only pregame/sealed source artifacts and process/control metadata required to prove provenance.

If a candidate source file physically contains outcome-like columns, use the repository canonical prohibited-outcome contract to prove the fields are absent/blank for the source rows used. Do not inspect nonblank outcome values. If safe outcome-free reconstruction cannot be proven without opening truth, stop.

## Required R0 work

### A. Canonical discovery-source census

Locate the canonical current Builder discovery source registry/manifests that underlie the accepted current-stack research corpus.

Report:

- discovery member count;
- unique discovery dates;
- source artifact path/hash per member/date;
- whether each source was physically sealed/pregame before outcome exposure according to repository authority;
- any duplicate or ambiguous member/date source.

Expected strategic corpus is the current discovery corpus, previously known as 39 dates; do not hard-code 39 if current repository authority proves a different exact census. Any discrepancy must be surfaced and reviewed, not normalized away.

### B. Full Demon-OVER leg census

Project every factual eligible Demon-OVER row from those pregame sources into one deterministic row-level surface.

Use the repository-canonical exact selected-leg identity/equality representation for identity fields where available; do not invent a new identity contract.

Required census:

- total rows;
- unique exact leg identities;
- rows and unique identities by date;
- rows, unique identities, dates, players, teams by each of 21 markets;
- duplicate exact leg identities within the same source/date;
- line/depth availability and min/median/max where numeric and meaningful;
- source-member lineage for every row.

Do not deduplicate legitimate distinct source members/runs silently. Report member multiplicity and use the canonical current-corpus member semantics.

### C. Pregame feature availability matrix

Inventory the complete outcome-free pregame field surface actually available to FromDeep, without deciding which fields are good signals.

At minimum classify actual available fields into these conceptual groups where supported:

- market / line / depth;
- projection and projection edge;
- probability / market edge;
- Atlas/scorer components if present at leg level;
- fragility / uncertainty;
- minutes / role / rotation / starter context;
- usage / opportunity context;
- injury / team-out / availability context;
- team/game/slate context;
- any additional deterministic pregame fields already present.

For every field report:

- canonical field name;
- source namespace/artifact;
- dtype/category;
- row support count and missing rate overall;
- support/missing rate by market;
- whether the field is deterministic pregame authority;
- whether it is identity-only, descriptive-only, or potentially admissible later for signal research.

R0 does **not** choose features, thresholds, interactions, GREEN/RED roads, reliability cutoffs, or ranking weights.

### D. Physical pretruth seal

Write a deterministic outcome-free compressed row-level surface plus manifest/seal binding:

- exact source hashes;
- row ordering rule;
- row count;
- market-owner count = 21;
- field schema/order;
- surface SHA-256;
- per-market row/date/player counts;
- prohibited-outcome-field audit;
- core freeze IDs/hashes as sequencing authority only;
- explicit statement that core exact-selected-leg depletion was **not** applied to FromDeep universe.

Suggested artifact names (sport-owned code may use equivalent clear names):

- `fromdeep_demon_over_pregame_surface.jsonl.gz`
- `FROMDEEP_DEMON_OVER_PRETRUTH_SEAL.json`
- `fromdeep_market_census.csv`
- `fromdeep_feature_availability.csv`
- `FROMDEEP_R0_SUMMARY.json`

Use a compact repo-local Builder research directory under current Builder Stage 5 / FromDeep work. Do not create a large replay/corpus archive unless required by existing storage policy.

## Legacy code disposition

`src/wnba/evaluation/builder_from_deep_research.py` is **not statistical authority for this runway** because its existing method explicitly combines discovery and validation evidence.

`src/wnba/evaluation/rp37_from_deep_registry.py` may be reused only for neutral constants/market-owner structure or generic fail-closed patterns. Its old RP37 support/activation logic is not the new signal-atlas method and must not be treated as authority.

Do not delete or rewrite legacy evidence in R0.

## Execution / resource doctrine

Cheap runway before long takeoff.

This is an artifact audit and deterministic projection only:

- no fitting;
- no historical-as-of replay;
- no signal enumeration;
- no performance grading;
- no expensive execution.

Before execution, compute expected source rows/files and projected runtime. If projected runtime exceeds 15 minutes or requires a major corpus rebuild, stop for user/Chat review rather than silently broadening R0.

Use `SEALED_ARTIFACT_FORENSIC` fast-path governance if and only if the exact operation qualifies under the active efficiency amendment. Otherwise use the narrowest existing Builder row/class that preserves the same scientific boundaries. Do not create a task-specific controller merely for R0.

## Hard prohibitions

- outcome/truth/settlement reads = 0;
- validation reads = 0;
- lockbox reads = 0;
- no public/live output as evidence;
- no signal-road mining;
- no GREEN/RED/GRAY classification;
- no thresholds/support/reliability method selection;
- no probability gate selection;
- no FromDeep leg selection;
- no historical performance computation;
- no fitting or ML;
- no 2L/3L/4L mutation;
- no Live/model/minutes/calibration/allocator/QMC/dependence/publication mutation;
- no automatic R1 start.

## Required report

Return:

1. exact discovery source/member/date census;
2. total Demon-OVER row and unique-leg counts;
3. exact 21-market census, including zero-support owners;
4. unmapped-market count/list;
5. per-market dates/players/rows;
6. feature-availability matrix summary;
7. pretruth surface path/hash and seal ID/hash;
8. provenance/source hashes;
9. outcome/protected-read counters, all zero;
10. runtime/resource class;
11. final WNBA SHA and local/tracking/direct-remote equality;
12. clean worktree and protected stash status.

## Pass / stop semantics

Pass only if the full factual eligible Demon-OVER discovery universe can be reconstructed deterministically, market ownership is exact and complete, provenance is authoritative, the pregame feature schema is usable for later signal forensics, and an outcome-free physical seal is produced.

If material provenance/market/schema gaps exist, report them precisely and stop. Do not repair scientifically meaningful gaps inside R0 without user/Chat review.

Required final stop:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_SCORED_LEG_UNIVERSE_R0`

No follow-on auto-start.