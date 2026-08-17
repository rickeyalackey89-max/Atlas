# WNBA 4L Post-Depletion Stateful Generator R1 Canary

Execution tier: `R1_ACTIONABILITY_CANARY`

User authorization: 2026-08-16 — proceed with the post-depletion stateful 4L generator canary.

## Purpose

Prove that the canonical/current WNBA 4L candidate-construction machinery can be invoked **after** frozen 2L and frozen 3L exact-selected-leg depletion, producing deterministic legal pretruth 4L candidate surfaces on representative coverage-gap dates without changing the 4L family contract or scoring semantics.

This is a structural/actionability canary only. It is **not** a performance experiment and must not read target outcomes.

## Authority and starting state

Repository: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Expected starting WNBA commit:

`978cca95d3701737232dc8e507e9a6ba7f04c301`

Expected current WNBA stop:

`BLOCKED_USER_REVIEW_WNBA_4L_RESIDUAL_LEG_SUPPLY_COVERAGE_R0`

Bind and preserve:

- frozen 2L method and exact selected-leg identities;
- frozen pointwise 3L research/depletion backbone and exact selected-leg identities;
- R0 residual-supply evidence at `978cca95d3701737232dc8e507e9a6ba7f04c301`;
- sealed outcome-free current Builder discovery surfaces;
- validation and lockbox truth remain unopened.

## Terminology and depletion contract

Do not use `road` ambiguously.

- **exact selected leg identity** = player + market + tier + side + line; this is the only upstream-depletion unit.
- **signal road** = a conditional evidence bucket/rule such as probability + fragility + minutes/edge conditions; signal roads are never depleted by upstream selection.

Required stateful order:

`full outcome-free scored-leg pool -> remove frozen 2L exact selected-leg identities -> remove frozen 3L exact selected-leg identities -> invoke 4L candidate construction on the remaining leg pool`.

Never perform player-wide depletion or signal-road depletion.

## Canary dates

Use exactly four dates.

Coverage-gap canaries selected for structural/resource diversity only:

1. `2026-06-28` — 4-game slate, 229 residual structurally eligible legs in R0;
2. `2026-07-09` — 3-game slate, 702 residual legs;
3. `2026-08-07` — later 3-game slate, 775 residual legs.

Parity/control canary:

4. `2026-06-19` — earliest chronological 3-game date with an existing nonzero materialized 4L candidate surface. This choice is structural/chronological, not outcome-based.

No other dates may be generated in this R1.

## Unchanged 4L structural contract

Derive from current WNBA authority and assert before generation. R0 reported the active structural floor as:

- family size = 4;
- public 4L requires slate game count >= 3;
- minimum distinct games in a 4L = 2;
- player entities must be disjoint;
- exact row identities unique;
- minimum leg probability = 0.50;
- active option structures and same-market/standard-leg limits remain exactly current authority;
- no new signal-quality filters, thresholds, or ranker/pool caps may be invented for this canary.

If current governing authority conflicts with the R0 summary, fail closed and report the conflict rather than silently choosing a contract.

## Generator reuse requirement

Identify and reuse the canonical/current WNBA candidate-construction machinery if it can be invoked safely on a post-depletion residual pool.

Do **not** create a parallel 4L builder or a new candidate-generation philosophy.

If the canonical generator cannot be reused without architectural changes, stop with a precise blocker/lineage diagnosis. Do not invent a replacement implementation inside this R1.

## Required pretruth outputs

For each of the four canary dates, emit outcome-free evidence sufficient to prove:

- source residual leg count after exact upstream depletion;
- unique residual player entities, games, markets, tiers, and sides;
- generator implementation/path/version/contract identity used;
- deterministic candidate count;
- unique exact candidate identities;
- candidate structural legality;
- candidate scoring/features required by the canonical Atlas 4L scorer;
- generation runtime and bounded-search/resource topology;
- no target settlement/outcome field is present in candidate-generation inputs or outputs.

The three coverage-gap dates must produce a nonzero legal candidate surface for R1 to pass actionability. R0 already proved a legal witness exists on each date; failure to generate candidates therefore requires a generator/coverage diagnosis, not an abstention label.

## Parity/control requirements for 2026-06-19

The stateful generator may produce a broader candidate set than the old materialized surface. Exact set equality is **not** required.

However, for exact candidate identities common to both the old materialized surface and the regenerated stateful surface:

- unchanged pretruth candidate features/scoring inputs must agree;
- Atlas scorer semantics and deterministic score/order fields must agree within existing repository numeric tolerances;
- structural contract interpretation must agree;
- the prior canonical Atlas control candidate must remain representable if its four exact selected-leg identities remain in the post-depletion residual pool.

Any parity failure must be reported and blocks escalation.

## Determinism requirement

Run the canary generation twice or otherwise prove byte-/identity-level deterministic equivalence using the repository's accepted deterministic evidence pattern.

At minimum, candidate identity sets and canonical ordering/scoring outputs must be reproducible from the same sealed inputs.

## Resource topology

This is a cheap runway canary.

Before generation, report projected topology and implementation path.

Hard wall-clock cap: **15 minutes total** for the authorized four-date canary, excluding normal focused tests/lint/validator cleanup.

If generation work itself exceeds 2 minutes, emit progress/heartbeat evidence rather than appearing hung.

Do not auto-expand to all 23 dates even if the canary is fast.

## Explicit prohibitions

This R1 authorizes only candidate generation needed for the four canary dates.

Do not:

- read target outcomes or settlement truth;
- grade any generated candidate or slip;
- search for winning candidates;
- fit pointwise, context, relational, nonlinear, or any other learner;
- tune signal roads, thresholds, gates, features, hyperparameters, weights, or confidence rules;
- modify frozen 2L or frozen 3L methods/selections;
- generate the full 23-date 4L surface;
- patch the eight gap dates into the old surface as a final research surface;
- freeze or promote 4L;
- execute FromDeep;
- read validation truth;
- read lockbox truth;
- mutate Live, model, minutes, calibration, allocator, QMC, dependence, or promotion state;
- auto-start any follow-on work.

Required read counts:

- target outcome reads = 0;
- validation reads = 0;
- lockbox reads = 0.

## Required disposition

Emit one of:

- `STATEFUL_4L_GENERATOR_R1_PASS`
- `STATEFUL_4L_GENERATOR_R1_FAIL_GENERATION`
- `STATEFUL_4L_GENERATOR_R1_FAIL_PARITY`
- `STATEFUL_4L_GENERATOR_R1_BLOCKED_CANONICAL_GENERATOR_REUSE`
- `STATEFUL_4L_GENERATOR_R1_BLOCKED_AUTHORITY_CONFLICT`
- `STATEFUL_4L_GENERATOR_R1_BLOCKED_RESOURCE`

A PASS means only that stateful post-depletion candidate generation is technically and methodologically ready for a separately authorized uniform 23-date pretruth regeneration. It does not authorize that regeneration.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_POST_DEPLETION_STATEFUL_GENERATOR_R1`

After permanent authorized evidence/code changes: exact-path stage only, commit, push, verify local HEAD == tracking ref == direct remote ref, leave clean, preserve the protected stash, report final WNBA SHA + stop marker, and stop.
