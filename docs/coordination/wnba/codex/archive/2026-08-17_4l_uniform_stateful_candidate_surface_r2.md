# WNBA 4L Uniform Stateful Candidate Surface R2

Execution tier: `R2_BOUNDED_PILOT`

User authorization: 2026-08-17 — proceed with the uniform 23-date outcome-blind stateful 4L candidate-surface regeneration.

## Purpose

Build and pretruth-seal one **uniform current 4L research surface** across all structurally eligible WNBA discovery slates using the stateful order proven by R1/R1A:

`sealed pregame scored-leg / Builder-Card surface -> frozen 2L exact-selected-leg depletion -> frozen pointwise-3L exact-selected-leg depletion -> canonical fresh 4L generation -> canonical context annotation -> canonical Atlas 4L scoring -> pretruth seal`.

This task corrects the incomplete old 481-candidate / 15-nonzero-date materialized surface. It is **candidate-surface construction only**. It must remain outcome-blind and must stop before discovery grading.

## Authority and starting state

Repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA commit:

`1f71ec936e7b23a7f537336056eaf4ae4209e9c7`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_STATEFUL_GENERATOR_PARITY_REPAIR_R1A`

Bind and preserve at minimum:

- frozen 2L method and selected exact-leg identities;
- frozen pointwise 3L research/depletion backbone and selected exact-leg identities;
- residual supply R0 commit `978cca95d3701737232dc8e507e9a6ba7f04c301`;
- stateful generator R1 commit `1e9930253ca3113842a687e188210321424c2d8a`;
- parity repair R1A commit `1f71ec936e7b23a7f537336056eaf4ae4209e9c7`;
- R0 `four_leg_residual_leg_supply_by_date.csv` and its sealed hashes;
- R1 candidate/determinism evidence and per-date hashes;
- R1A symmetric parity receipts;
- active Builder policy, canonical `fresh_four_leg_frontier`, canonical context annotation semantics, and canonical `score_family_candidates` implementation identities;
- validation and lockbox remain unopened.

Fail closed on authority/hash drift. Do not silently substitute newer generator/scorer/context behavior.

## Exact eligible-date census

Derive the target dates from the sealed residual-supply R0 ledger, not from memory.

Required rule:

- use **all and only** rows with `public_4l_family_eligible=true` / slate game count >= 3;
- assert exact eligible date count = **23**;
- assert the remaining seven audited dates are the already-established sub-three-game structural abstentions;
- do not generate 4L surfaces for those seven in this task.

The 23-date surface must include both the 15 dates that had old materialized candidates and the eight dates previously classified as `CANDIDATE_SURFACE_COVERAGE_GAP`.

Do **not** patch only the eight gaps. Every one of the 23 eligible dates must be generated under the same stateful lineage in this R2.

## Depletion contract

Terminology is binding:

- **exact selected leg identity** = player + market + tier + side + line; this is the only upstream depletion unit;
- **signal road** = a conditional evidence bucket/rule such as probability/fragility/minutes/edge conditions and is not a depletion unit.

Required order on each date:

1. load the sealed outcome-free pregame scored-leg / Builder-Card surface;
2. apply unchanged current 4L leg eligibility;
3. remove only the frozen 2L exact selected-leg identities;
4. remove only the frozen pointwise-3L exact selected-leg identities;
5. invoke canonical `fresh_four_leg_frontier` on the residual pool;
6. validate family-size/player/game/option-contract legality;
7. apply the same canonical context annotation semantics proven by R1A;
8. score the **complete generated date pool** with canonical `score_family_candidates(family=4, ...)` so within-pool percentile/midrank semantics are preserved;
9. seal the date surface before moving on.

Never perform player-wide depletion or signal-road depletion.

## Unchanged 4L structural contract

Bind the active contract from current authority and R0. At minimum R0 established:

- family size = 4;
- public 4L requires slate game count >= 3;
- minimum distinct games in a 4L = 2;
- player entities disjoint;
- exact row identities unique;
- minimum leg probability = 0.50;
- active option structures / same-market / standard-leg rules remain unchanged;
- no new signal-quality filters, thresholds, ranker caps, or pool caps may be invented.

If governing authority conflicts with the sealed R0/R1/R1A bindings, fail closed and report the conflict.

## Required candidate surface

For every one of the 23 dates, emit outcome-free evidence including at minimum:

- game date and slate game count;
- Builder-Card/scored-leg source hash;
- structurally eligible leg count before depletion;
- frozen 2L exact-leg count and identities removed;
- frozen 3L exact-leg count and identities removed;
- residual eligible leg count;
- residual unique players, games, markets, tiers, and sides;
- generator implementation/path/hash;
- generated candidate count;
- unique exact candidate identities and ordered identity hash;
- complete raw Atlas scorer primitives needed by `score_family_candidates`;
- complete fixed canonical context annotation fields;
- canonical Atlas components, score, final scorer rank, and final ordered score-ledger hash;
- structural legality receipt;
- target outcome reads = 0.

Do not impose a public-slip fill quota. Candidate count must be nonzero on a structurally eligible date unless the canonical generator itself produces a precise contract/coverage blocker. Do not call generator scarcity a public abstention in this pretruth construction step.

## Determinism / continuity without redundant full rerun

R1 already proved two-pass determinism on four dates and R1A proved semantic parity. Therefore do **not** rerun all 23 dates twice merely for ceremony.

Generate each target date once in the uniform R2.

For the four sealed R1 canary dates:

- `2026-06-19`
- `2026-06-28`
- `2026-07-09`
- `2026-08-07`

require exact reproduction, under the same bound inputs, of the prior R1 candidate identity/order/scorer hashes available in the sealed R1 determinism/by-date evidence. Fail closed on unexplained mismatch.

For all 23 dates, write deterministic canonical hashes for input membership, raw generated candidate surface, annotated candidate surface, and complete Atlas score ledger. These hashes become the uniform-surface authority for the later separately authorized forensic.

## Uniform pretruth seal

Before any outcome access, emit a final surface seal that binds:

- exact 23-date census and ordered date list;
- per-date input/source hashes;
- per-date upstream depletion identities;
- per-date candidate counts and candidate identity/order hashes;
- per-date annotation/scorer hashes;
- complete uniform candidate ledger / compressed candidate surface hash;
- complete score-ledger hash;
- generator/scorer/context source hashes;
- structural contract identity;
- explicit `outcomes_opened=false`;
- target outcome reads = 0;
- validation reads = 0;
- lockbox reads = 0;
- no Live/model mutation.

The seal must make later discovery grading possible without regenerating or changing the candidate surface.

## Resource topology / cheap-runway requirement

R1 measured four dates × two generation passes at about 43.17 seconds of generation time, approximately 5.4 seconds per canonical generator call. A one-pass 23-date surface therefore projects to roughly 2–3 minutes of pure generation under similar conditions. Allow additional time for annotation, scoring, evidence, tests, and compression.

Before execution, emit resource/storage preflight and the exact call topology.

Expected topology:

- generator calls: 23 one-pass calls;
- learner fits: 0;
- target outcome reads: 0;
- one date in memory at a time; release/GC between dates;
- resource class: bounded sequential CPU;
- expected wall clock: approximately 5–10 minutes including evidence overhead;
- hard generation/surface-construction cap: **20 minutes** excluding focused tests/lint/validator cleanup.

Emit heartbeat/progress at least every 3 completed dates or every 2 minutes, whichever comes first.

If the cap is exceeded because the implementation is broad-regenerating unrelated state, refitting, or reconstructing the whole corpus, stop rather than silently escalating.

## Explicit prohibitions

This R2 authorizes only construction and sealing of the uniform 23-date pretruth 4L candidate surface.

Do not:

- read target settlement/outcome truth;
- grade any candidate or slip;
- search for winners or best historical outcomes;
- establish a W/L/NB record;
- fit pointwise, context, relational, nonlinear, or any other learner;
- run the parked context-consensus challenger;
- tune signal roads, thresholds, gates, features, hyperparameters, weights, confidence rules, or candidate depth;
- change frozen 2L or frozen 3L methods/selections;
- use player-wide depletion;
- use signal-road depletion;
- patch old and new candidate surfaces together as final authority;
- freeze, install, promote, or publish 4L;
- execute FromDeep;
- read protected validation truth;
- read lockbox truth;
- use public/live slips as scientific evaluation;
- mutate Live, model, minutes, calibration, allocator, QMC, dependence, scorer, context semantics, or promotion state;
- auto-start discovery grading or any follow-on work.

Required read counts:

- target outcome reads = 0;
- validation reads = 0;
- lockbox reads = 0.

## Required dispositions

Emit one of:

- `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_PASS`
- `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_FAIL_GENERATION`
- `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_FAIL_CANARY_CONTINUITY`
- `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_BLOCKED_AUTHORITY_CONFLICT`
- `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_BLOCKED_RESOURCE`

A PASS means only that one uniform outcome-blind 23-date 4L research surface has been generated and pretruth-sealed. It creates **no performance claim and no freeze/promotion authority**.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`

After permanent authorized evidence/code changes: exact-path stage only, commit, push, verify local HEAD == tracking ref == direct remote ref, leave clean, preserve the protected stash, report final WNBA SHA + artifact paths + candidate/date census + canary-continuity result + target/validation/lockbox reads + stop marker, and stop.

## Next if R2 passes — NOT AUTHORIZED BY THIS TASK

A separate user-authorized artifact-only forensic may then open **already-consumed discovery truth only** against the sealed uniform surface to establish the new canonical Atlas 4L baseline and supply/ranking anatomy.

That later forensic must not open protected validation or lockbox and must not automatically launch any learner. Context-consensus remains parked until the new uniform baseline proves that ranking research is warranted.
