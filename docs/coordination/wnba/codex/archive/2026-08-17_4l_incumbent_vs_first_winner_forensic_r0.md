# WNBA 4L Atlas Incumbent vs First-Winner Forensic R0

Execution tier: **R0_ARTIFACT_FORENSIC**

Machine class: **SEALED_ARTIFACT_FORENSIC**

User authorization: 2026-08-17 — user explicitly said they are ready to move forward and requested that the pending governance cleanup be committed and pushed before the next research work.

## Purpose

Answer one scientific question:

> Do the eight canonical Atlas rank-1 4L losses exhibit recurring **outcome-free** distinctions from (a) the fourteen canonical Atlas rank-1 4L wins and (b) their exact first winning alternative on the same loss date, strong enough to justify a later conservative incumbent/challenger R1?

This task is diagnostic only. It must not learn a repair rule.

## Authority and starting state

Target repo: `rickeyalackey89-max/Atlas-WNBA`

Branch: `builder-method-contract-v1`

Known pushed WNBA baseline before the pending governance-text cleanup:

`2d2f78e1ee9cb59f3c6687c1cad38ba1621272bf`

Accepted 4L control forensic commit:

`2d2b4f4db497ce6626d7ae30e6b0eeabc394863f`

Accepted control result:

- 23 development-consumed eligible dates;
- Atlas rank-1 = `14 WIN / 8 LOSS / 1 NONBINARY`;
- binary win rate = `63.64%`;
- winner available on `23/23` dates;
- all eight losses are ranking failures;
- exact first winning ranks on the eight losses = `2, 3, 4, 4, 6, 6, 23, 74` (date order remains artifact-owned, not re-sorted into method logic);
- no-winner dates = 0;
- validation reads = 0;
- lockbox reads = 0.

The accepted R2 candidate surface remains immutable:

- 23 dates;
- 2,208 candidates;
- 96 candidates/date;
- pretruth-sealed uniform post-depletion lineage.

## Mandatory Git prerequisite — finish the pending governance cleanup first

Before activating this scientific forensic, inspect the canonical WNBA worktree.

The user has already authorized a narrow governance-consistency cleanup immediately after `2d2f78e1...`.

Expected pending cleanup paths are only:

- `AGENTS.md`
- `docs/model_development/builder_method_contract/SLIP_BUILDERS_SKILL_AMENDMENT_WNBA_V1.md`

If the worktree contains exactly those authorized cleanup changes and no unrelated/unexpected task changes:

1. review the diff;
2. run only the governing-document/control tests required by that cleanup;
3. exact-path stage those files only;
4. commit with a narrow governance message;
5. push;
6. verify local HEAD == tracking ref == direct remote;
7. record that new commit as `governance_baseline_sha` for this forensic;
8. require a clean worktree before scientific activation.

If any additional dirty path exists, fail closed and report it. Do not sweep extra paths into the governance commit.

The governance cleanup commit and the scientific forensic commit must remain separate Git commits.

## Fast-path governance

After the governance prerequisite is clean and pushed, use:

`docs/model_development/builder_method_contract/WNBA_BUILDER_WORKFLOW_EFFICIENCY_AMENDMENT_V1.md`

and the shared sealed-forensic machinery.

Do **not** create a new `control_builder_<task>.py` controller.

Normal fast-path lifecycle:

`AUTHORIZED -> CONTROL_AND_EVIDENCE_PREFLIGHT -> SEALED_ARTIFACT_FORENSIC -> BLOCKED_USER_REVIEW`

One full Builder preamble at active-row start only. Thereafter emit only `BUILDER CONTROL DELTA: ...` if a governing fact actually changes.

## Bound evidence

Use only sealed/development-consumed artifacts already created before this work:

1. R2 annotated candidate surface and score lineage from `current_atlas_4l_uniform_stateful_candidate_surface_r2`.
2. R2 pretruth seal and artifact manifest.
3. `current_atlas_4l_uniform_control_forensic_r0/atlas_4l_uniform_control_by_date.csv`.
4. `current_atlas_4l_uniform_control_forensic_r0/atlas_4l_first_winning_candidate_by_date.csv`.
5. The accepted control-forensic summary/manifest required to prove the `14-8-1` baseline and exact first-winning identities/ranks.

Do not reopen raw mutable season truth when the accepted sealed forensic artifacts already answer identity/outcome membership.

All 23 dates are development-consumed under the accepted discovery exposure registry. Validation and lockbox remain inaccessible.

## Population

Primary binary contrast:

- 14 dates where Atlas rank-1 = WIN;
- 8 dates where Atlas rank-1 = LOSS.

The single NONBINARY date is report-only and excluded from binary win/loss discrimination.

For each of the 8 LOSS dates, compare:

- frozen Atlas rank-1 incumbent;
- exact first winning alternative already identified by the accepted control forensic.

Do not search for a different or “better” winner.

## Feature surface

Analyze only fields already present in the sealed R2 annotated candidate surface and already outcome-free under the R2 generator/context/scorer bindings.

Include, where present:

- Atlas components `P/Q/G/V/M/W/S/A`;
- `atlas_slip_score`;
- `joint_qmc_probability`;
- `independent_strict_probability`;
- minimum/mean leg probability;
- minimum/mean probability edge;
- minimum/mean projection edge;
- expected net value estimate/floor;
- minutes/stat fragility;
- slate context;
- original/Atlas rank percentiles;
- canonical R2 context fields;
- existing outcome-free candidate composition / market-tier makeup fields.

Identifiers, names, dates, and exact selected-leg identities may be retained for joins/reporting but may not become inferred “signals.”

Exclude all outcome, settlement, realized-performance, postgame, or later-mutated truth fields from the analytic feature set.

## Required descriptive analyses

No model fitting and no threshold search.

For every eligible outcome-free feature, report:

1. **Atlas incumbent WIN vs LOSS contrast**
   - WIN-incumbent median and IQR / categorical frequency;
   - LOSS-incumbent median and IQR / categorical frequency;
   - raw median difference or categorical frequency difference;
   - no learned cutoff.

2. **LOSS-date incumbent vs first-winner paired contrast**
   - per-date incumbent value;
   - first-winner value;
   - signed delta where numeric;
   - direction recurrence count across the eight loss dates;
   - categorical transition counts where applicable.

3. **Rank/score geometry**
   - first-winner Atlas rank;
   - incumbent-vs-winner Atlas-score gap;
   - QMC gap;
   - probability/EV/fragility gaps where available;
   - distribution of those gaps across the eight losses.

4. **Descriptive recurrence packet**
   - surface fields whose LOSS-incumbent vs WIN-incumbent direction and paired incumbent-vs-first-winner direction are repeatedly aligned;
   - report raw recurrence counts and effect magnitudes only;
   - explicitly state that this is outcome-informed diagnostic ranking of fields, not an admitted signal road and not a runtime rule.

Do not manufacture a binary `stable_signal=true/false` gate from post-hoc thresholds. Chat/user will interpret the packet.

## Shared executor rule

Prefer the generic `scripts/run_builder_sealed_artifact_forensic.py` fast path.

If the current declarative executor cannot express incumbent-vs-comparator feature contrasts, Codex may make a **minimal reusable extension to the shared generic sealed-forensic executor/spec schema** within this same scientific question, provided that extension:

- is generic rather than task-specific;
- does not alter the scientific population, outcome membership, candidate ordering, or feature values;
- does not add a task-specific controller;
- receives focused positive/adversarial tests;
- is recorded as implementation-only shared infrastructure in the final receipt.

Any change to scientific semantics requires fail-closed user review instead.

## Explicit prohibitions

Do not:

- regenerate candidates;
- rescore or rerank the R2 surface;
- fit any learner;
- search thresholds;
- create signal-road gates;
- tune features, weights, support, depth, or hyperparameters;
- run pointwise/relational/context-consensus challengers;
- evaluate a hypothetical override policy;
- optimize historical wins;
- freeze/install/promote 4L;
- run FromDeep;
- open validation or lockbox;
- mutate Live/model/minutes/calibration/allocator/QMC/dependence/publication state;
- auto-start any follow-on experiment.

## Required outputs

Write a compact sealed forensic packet containing at least:

- exact governance baseline SHA;
- exact R2 input hashes;
- exact control-forensic input hashes;
- binary date census = 14 WIN / 8 LOSS, plus 1 NONBINARY report-only;
- one row per LOSS date with incumbent + exact first winner + feature deltas;
- WIN-incumbent vs LOSS-incumbent descriptive feature summary;
- paired LOSS incumbent-vs-first-winner descriptive summary;
- categorical composition comparison;
- rank/score/QMC/EV/fragility gap summary;
- recurrence packet with no runtime/admission authority;
- validation reads = 0;
- lockbox reads = 0;
- learner fits = 0;
- candidate generation/rescoring/reranking = 0;
- final scientific stop marker.

## Git completion

If the forensic produces permanent repo evidence or a reusable generic fast-path extension:

- exact-path stage only;
- commit separately from the governance cleanup commit;
- push;
- verify local HEAD == tracking == direct remote;
- leave clean;
- preserve protected stash.

Report both:

1. `governance_baseline_sha`;
2. final forensic WNBA SHA.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_4L_INCUMBENT_VS_FIRST_WINNER_FORENSIC_R0`

## Next if this shows coherent repair structure — NOT AUTHORIZED

A separately user-authorized conservative incumbent/challenger R1 may test whether a fixed historical-as-of challenger can repair selected Atlas losses while preserving the 14 existing control wins.

If the forensic does not show coherent recurring structure, seriously consider freezing 4L at the canonical Atlas baseline rather than manufacturing a repair method.
