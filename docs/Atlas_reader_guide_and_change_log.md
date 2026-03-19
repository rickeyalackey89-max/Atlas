# Atlas Telemetry Reader Guide

## Purpose

`tools/telemetry_corpus_reader.py` is Atlas's standalone replay telemetry judge.

It is **not**:
- the replay generator
- Oracle
- the allocator
- the slip builder

Its job is to:
- read replay corpora
- summarize calibration + slip behavior
- compare a primary corpus to optional comparison corpora
- produce recommendations
- decide whether evidence is strong enough to justify promotion

Replay generation still comes from Backtest v2 or related replay runners. The reader consumes already-written run folders.

---

## What the reader expects

### Required per run
- `eval_legs.csv`
- `scored_legs_deduped.csv`

### Helpful but optional
- recommended slip CSVs
- `meta.json`

### Supported corpus layouts
- `root/runs/<run_id>/...`
- `root/<run_id>/...`
- zip input is also supported

### Incomplete runs
The reader is designed to skip incomplete runs rather than hard-fail the entire corpus.

---

## Where outputs are written

Reader outputs are written under:

- `.atlas_audit/diagnostics/telemetry_corpus/<timestamp>/`

Typical outputs include:

- `corpus_summary.json`
- `corpus_summary.md`
- `config_recommendations.json`
- `calibration_recommendations.json`
- `logic_recommendations.json`
- `candidate_scores.json`
- `per_run_metrics.csv`
- `corpus_metrics.csv`
- `drift_metrics.csv`
- `regime_tables.xlsx`
- `proposed_config_patch.yaml`
- `proposed_calibration.json`
- `patch_plan.json`

### New additive output added in this upgrade
- `runtime_identity.json`

This was added without changing the existing output family.

---

## Reader operating model

The reader now follows a clearer three-part contract.

### 1. Scorecard
This is the descriptive section.

It answers:
- what path ran
- what the corpus metrics are
- whether calibration improved
- how protected shorter-slip surfaces behaved
- which surfaces tilted positive or negative

### 2. Knob advisor
This is the advisory section.

It answers:
- what seam looks implicated
- whether the lead is calibration-only or broader
- what the smallest next test should be
- which candidate stood out most

### 3. Promotion guard
This is the policy section.

It answers:
- whether the candidate is promotable
- whether it is only informative
- what blockers prevented promotion
- whether the result should be quarantined, archived, or kept as the current standard

This separation is important because a candidate can improve calibration while still not being a promotable full variant.

---

## Phase changes made in this reader upgrade

## Phase 1
Goal: make the reader easier to trust without changing model math.

Changes:
- kept existing metrics and output files intact
- added `runtime_identity.json`
- added top-level summary sections in `corpus_summary.json`
- upgraded `corpus_summary.md` to surface:
  - runtime identity
  - scorecard
  - knob advisor
  - promotion guard

No changes were made to:
- probability math
- telemetry math
- schema
- timezone behavior
- run folder layout

## Phase 2
Goal: make explanation quality clearer.

Changes:
- made the knob advisor more explicit about:
  - top candidate
  - improvement vs current
  - gate clear status
  - pass share
  - severe regressions
- made the promotion guard less contradictory by separating:
  - "candidate improved"
  - "candidate is promotable"

This made it much easier to read telemetry leads as:
- real
- informative
- but not necessarily promotable

## Phase 3
Goal: make the reader more Atlas-specific.

Changes:
- surfaced protected surfaces directly in the scorecard:
  - `strict3`, `strict4`, `strict5`
  - `hit3`, `hit4`, `hit5`
  - dominant positive tilt
  - dominant negative tilt
- added `advisory_class` to the knob advisor
- added `blocker_hypotheses` to the promotion guard

This made the tool better at expressing:
- calibration-only leads
- variant breadth failures
- time-window or regime blockers
- protected-surface or policy blockers

---

## Runtime identity: what it means

The reader now tries to summarize what actually produced the corpus.

It looks for additive identity/proof fields such as:
- `prob_model_mode`
- `prob_active_experiments`
- `prob_experiment_flags`
- `telemetry_cal_key`
- `telemetry_k_shrink`
- `telemetry_under_penalty`
- `telemetry_mult`
- `telemetry_bucket_mult`
- `telemetry_cal_applied`
- `p_cal_src`
- `p_adj_pre_frag_under`
- `frag_under_mult`
- `frag_under_applied`

Important:
- these are additive diagnostics
- their presence helps prove what actually changed
- their absence is also informative and should not be silently ignored

---

## How to operate the tool

## 1. Single corpus read
Use this when you want the reader to judge one replay corpus by itself.

Example:
`py .\tools\telemetry_corpus_reader.py --corpus-input "C:\Users\rick\projects\Atlas\outputtelem\restructure_single_replay" --primary-label "restructure_single_replay" --config-path "C:\Users\rick\projects\Atlas\config.yaml" --output-root "C:\Users\rick\projects\Atlas"`

Use this for:
- single replay inspection
- sanity checks
- baseline summary
- checking whether runtime identity fields appear

## 2. Control vs challenger comparison
Use this when you want to compare a control corpus to a challenger corpus.

Example:
`py .\tools\telemetry_corpus_reader.py --corpus-input "C:\Users\rick\projects\Atlas\outputtelem\telemetry_ab_control_shrink_0.88_single" --comparison-corpus-input "C:\Users\rick\projects\Atlas\outputtelem\telemetry_ab_challenger_shrink_0.88_single" --primary-label "telemetry_ab_control_shrink_0.88_single" --config-path "C:\Users\rick\projects\Atlas\config.yaml" --output-root "C:\Users\rick\projects\Atlas"`

Use this for:
- telemetry control/challenger A/B
- comparing a standard branch against an experimental branch
- checking whether a calibration lead is real but non-promotable

## 3. Zip input
The reader can also consume a zip corpus directly.

This is useful when:
- results were bundled and uploaded
- you want to inspect a historical corpus without unpacking it yourself

---

## How to read the outputs

## `corpus_summary.md`
This is the best human-readable starting point.

Read it in this order:
1. runtime identity
2. scorecard
3. knob advisor
4. promotion guard

That order tells you:
- what actually ran
- what happened
- what seam looks implicated
- whether anything should be promoted

## `runtime_identity.json`
Read this when you want proof of:
- standard vs experiment mode
- telemetry application state
- whether proof fields were present
- whether the corpus identity is fully proven or only partially visible

## `candidate_scores.json`
Read this when you want:
- top calibration candidates
- relative rank among candidates
- the strongest telemetry or calibration lead

## `logic_recommendations.json`
Read this when you want:
- which target file or seam the reader believes deserves attention

## `drift_metrics.csv`
Read this when you want:
- stability and drift behavior across runs

## `regime_tables.xlsx`
Read this when you want:
- regime or slice behavior that is harder to read in JSON alone

---

## Specific telemetry workflow rules

Telemetry testing is a safe A/B surface only when:
- the baseline stays fixed
- the corpus stays fixed
- the truth file stays fixed
- allocator logic stays fixed
- `calibration_map.json` stays neutral / identity
- only `data/model/telemetry_calibration.json` changes

### Control
- remove or rename `telemetry_calibration.json`

### Challenger
- copy the challenger artifact into `data/model/telemetry_calibration.json`

### Then
- replay the same corpus
- run the reader
- compare the outputs

This is safe because it changes an artifact, not core probability math.

---

## What this tool is good at

The reader is good at:
- identifying real calibration leads
- rejecting weak promotions
- surfacing calibration-only wins
- protecting against shallow metric wins that do not generalize
- giving an auditable summary of what happened

It is especially useful for:
- telemetry A/B evaluation
- replay corpus summaries
- deciding whether a candidate is informative vs promotable

---

## What this tool is not for

The reader is not the place to:
- change probability math directly
- rewrite `new_probability.py`
- generate replay corpora
- replace slip-building logic
- force promotion because one metric improved slightly

It should guide decisions, not silently make them.

---

## Common interpretation patterns

### Pattern: calibration candidate improved, but no promotion
Meaning:
- the challenger is real
- the effect is measurable
- the improvement may be too narrow or too unstable for promotion

### Pattern: calibration-only lead
Meaning:
- the seam is likely a late calibration surface
- the result is informative
- it does not justify replacing the full standard branch

### Pattern: variant breadth failure
Meaning:
- a lead exists
- but it did not carry broadly enough across slices / windows / regimes

### Pattern: runtime identity incomplete
Meaning:
- the metrics may still be useful
- but path proof is incomplete
- caution is warranted before treating the result as a clean A/B

---

## Recommended operating habits

- always read `corpus_summary.md` first
- use `runtime_identity.json` to verify what actually ran
- treat proof-column presence as part of validity
- separate:
  - calibration lead
  - full-variant promotion
- do not treat telemetry wins as permission to change core probability math
- bank non-promoted branches as informative rather than pretending they failed

---

## Current practical stopping point

The reader is now in a strong state for:
- identity
- explanation clarity
- Atlas-specific blocker framing

That means the next major work area should be math discussion, not more reader rewrites, unless a specific new reporting gap appears.

# CHANGELOG (ordered, updated v15, 2026-03-18)

## 1) Replay/backtest fidelity work moved from theory to implementation

### 1.1 Live Rotowire archival was implemented
- The correct live write seam was identified as `fetch_rotowire_lines.py`.
- The final working implementation was additive and self-contained in that file.
- Live still writes the latest Rotowire JSON where it always did.
- Live now also archives the live-used Rotowire JSON into the IAEL archive family for later replay fidelity.

### 1.2 External-priors debug artifact routing was fixed
- `external_priors.py` was confirmed to own the debug CSV write behavior.
- Output routing was fixed so live and backtest no longer share the same debug artifact destination.
- The most important runtime bug turned out to be bad repo-root resolution, not only output-dir logic.
- Using `find_repo_root(Path(__file__))` restored correct live output behavior.

### 1.3 Historical Rotowire / external-priors injection was wired into replay
- `backtest_v2.py` was extended to stage replay-side historical artifacts into engine publish.
- `matchup_enricher.py` was patched to honor a replay Rotowire path override.
- `external_priors.py` was patched to honor a replay external-priors source override.

### 1.4 Started-game replay parity was implemented
- Replay was initially rebuilding a wider playable universe than the live run on a late slate.
- The extra replay rows were eventually traced to games that had already started at live time.
- A replay-only started-game gate was added to `backtest_v2.py`.
- The first version did not bind because the cutoff timestamp was interpreted in the wrong timezone.
- After fixing the cutoff interpretation, replay and live `today.csv` matched on the tested slate.

### 1.5 Fidelity conclusion
- Replay/backtest is now behaving much closer to live on the corrected path.
- The earlier replay-thinness excuse is no longer the main blocker for judging the branch.

## 2) `new_probability.py` reshape continued and narrowed

### 2.1 UNDER weakness was identified as real
- The branch was not failing because fragility was being applied to UNDERS directly.
- Fragility remained effectively OVER-side.
- UNDERS were weak because the downstream `p_role -> p_adj` haircut/blowout path was still penalizing them too much.

### 2.2 UNDER giveback / relief was tested
- The original UNDER relief was too small to matter materially.
- The user tested larger giveback levels.
- A 50% giveback pass improved metrics but did not yet clear the reader’s full promotion rules.

### 2.3 Directional UNDER blowout sensitivity seam was added
- A cleaner seam was introduced so qualifying UNDERS use reduced blowout sensitivity before the haircut is applied.
- This matched the intended basketball logic better than “full haircut then tiny refund.”

### 2.4 Role-context carve-out was the key surgical seam
- As reader regressions narrowed, `role_ctx_on` became the remaining hard slice.
- The final strong surgical move was to weaken UNDER-side relief when `role_ctx_outs_used > 0` while keeping stronger relief when role context was off.
- This produced the strongest reader turn of the chat.

## 3) Reader outputs evolved materially during this chat

### 3.1 Early corrected replay runs
- `keep_current_standard`
- repeated small improvements but not enough

### 3.2 Mid-run improvement phase
- 50% UNDER giveback improved the branch
- directional UNDER blowout sensitivity improved again
- role-context carve-out improved again
- severe regressions narrowed

### 3.3 Late run breakthrough
- reader began surfacing a real calibration-only lead instead of flat rejection
- strongest recurring candidate became `telemetry_key_role_off_light`
- candidate improvements turned positive
- pass share became high
- severe regressions dropped to zero

### 3.4 Final label state reached in this chat
- `keep_current_standard_with_calibration_only_lead`
- calibration-only lead is real
- full variant promotion still blocked by the reader’s more conservative policy gates

## 4) Calibration-map gate work was added
- `calibration_map.py` was patched, not `calibration.py`
- tiny helper functions were added to support env-based role-off gating
- `apply_calibration_column(...)` was modified
- the gate allows calibration to apply only when role context is off
- activation path uses env flags / profile naming plus an explicit map file path

## 5) Strategic conclusion reached at the end of the chat
- The user’s judgment is that the reshaped model is now practically better than the locked standard.
- The reader still refuses full promotion because it is acting as a conservative diagnostic/promotion guard.
- Therefore the key unresolved question is no longer replay plumbing or simple model weakness.
- The key unresolved question is whether the reader’s promotion policy is aligned with Atlas’s true operating objective.