# STATE_CURRENT (updated v12)

## Where we are now
- **Standard baseline is locked to Variant 01** from the earlier replay baseline work:
  - `pp_kernel.coeffs.DEFAULT.STANDARD.a = 0.3164`
  - `pp_kernel.coeffs.DEFAULT.STANDARD.b = -0.2880`
- **Calibration map stays neutral / identity**.
- **Telemetry calibration is now wired into replay correctly**:
  - `telemetry_calibration.json` is consumed by the replay/runtime path that writes `p_cal`
  - proof columns now exist in artifacts:
    - `telemetry_cal_key`
    - `telemetry_k_shrink`
    - `telemetry_under_penalty`
    - `telemetry_mult`
    - `telemetry_bucket_mult` (when bucket rules are used)
    - `telemetry_cal_applied`
    - `p_cal_src` appends `+telemetry` when applied
- **Legacy eval reconstruction path exists and works**:
  - `tools/create_eval_leg_backtestv2.py`
  - builds missing `eval_legs.csv` from legacy `scored_legs_deduped.csv` + `data/gamelogs/nba_gamelogs.csv`
- **Telemetry corpus reader exists and is now usable**:
  - reads full replay corpora
  - supports both `root/runs/<run_id>` and `root/<run_id>` layouts
  - skips non-run folders and incomplete runs
  - can compare challenger corpora against control
  - has hardened ranking, regime gates, and time-window gates

## Current blocker
- We now have a working telemetry A/B loop, but **most challenger artifacts have failed to improve the full corpus cleanly enough to promote**.
- The first telemetry challengers failed because they were too blunt:
  - mixed stat-direction challenger failed
  - under-only challenger failed
  - penalty-only UNDER challenger failed
  - upper-bucket cooling challenger failed
- The **first challenger family that actually improved corpus-level calibration metrics** was:
  - `telemetry_calibration_targeted_lift_v1.json`
- But the reader still did **not** auto-promote v1 because promotion gates remained strict and the improvement did not clear enough slices/windows broadly enough.
- We built `targeted_lift_v2` as a **softened version** of that same family.
- `targeted_lift_v2` has passed the single-raw A/B sanity test and is currently the **most promising challenger**.
- The next unresolved question is:
  - **Does `targeted_lift_v2` earn promotion on the full replay corpus?**

## Core goal right now
- Finish telemetry calibration tuning in a disciplined way:
  1. keep Standard coeffs fixed at Variant 01
  2. keep identity calibration map fixed
  3. use telemetry calibration as the optional late overlay
  4. evaluate challengers via:
     - single-raw A/B
     - then full fixed-corpus A/B
     - then telemetry reader / diagnostic pass
  5. promote only if the challenger clearly improves corpus-level calibration and does not meaningfully damage protected slip surfaces

## What NOT to do
- Do **not** touch Standard coeffs again right now.
- Do **not** touch allocator logic.
- Do **not** replace `calibration_map.json` with telemetry artifacts.
- Do **not** re-open Oracle as the main decision tool.
- Do **not** guess at new challengers without using the diagnostics.

---

## 2026-03-13 — Telemetry integration state

### Telemetry integration patch status
- Telemetry calibration support was integrated into the replay path because control and challenger corpora were initially coming out **identical**.
- Root cause:
  - `src/Atlas/runtime/telemetry_calibration.py` existed
  - but replay was **not consuming it**
- Integration patch changed:
  - `src/Atlas/runtime/telemetry_calibration.py`
  - `src/Atlas/engine/new_engine.py`
  - `src/Atlas/engine/main.py`
  - `src/Atlas/runtime/orchestrator.py`
- Result:
  - single-raw A/B proved telemetry overlays now fire correctly
  - `p_cal` changes in challenger runs
  - proof columns appear in `scored_legs_deduped.csv`

### Legacy corpus readiness
- Many older telemetry folders lacked `eval_legs.csv`.
- Read-side reconstruction script was built:
  - `tools/create_eval_leg_backtestv2.py`
- Inputs:
  - legacy `scored_legs_deduped.csv`
  - `data/gamelogs/nba_gamelogs.csv`
- Outcome:
  - enough legacy runs can now be used by the telemetry reader
  - old telemetry can participate in corpus analysis

### Reader hardening status
The telemetry corpus reader was hardened through several iterations:
- supports both:
  - `root/runs/<run_id>`
  - `root/<run_id>`
- skips:
  - structural folders like `dashboard`, `runs`
  - incomplete runs
- handles legacy `source_projection_id` shapes:
  - numeric ids
  - compound ids with numeric prefix
- hardened ranking:
  - protected composite
  - System strict win rate primacy
  - shorter-slip protection
  - per-run stability penalty
  - sample-depth hygiene penalty
- hardened promotion gates:
  - all-runs
  - older/recent windows
  - regime gates
  - calibration gates

---

## Full telemetry experiment sequence completed so far

### 1. Mixed stat-direction challenger
- Reader originally recommended a `stat_direction_light` style challenger after diagnosing broad under/over patterns.
- Runtime wiring was not in place at first, so early control/challenger corpora were identical.
- After integration was fixed, the mixed challenger was retested.
- Result:
  - failed full-corpus A/B
  - worse aggregate calibration / weaker consistency
- Decision:
  - reject

### 2. UNDER-only challenger
- Built as a narrower artifact than the mixed challenger.
- Result:
  - failed single-raw
  - not promoted to corpus
- Decision:
  - reject

### 3. Penalty-only UNDER challenger
- Very small `standard_under_penalty` only, no stat multipliers.
- Result:
  - slight positive on a single raw
  - failed on full corpus (flat to slightly worse)
- Decision:
  - reject

### 4. Upper-bucket cooling challenger
- Added `bucket_rules` support to telemetry calibration runtime.
- Tested narrow cooling in hot upper probability buckets.
- Result:
  - structurally clean on a single raw
  - failed on full corpus
- Decision:
  - reject

### 5. Diagnostic pass
Because the earlier challengers failed, a standalone diagnostic was built:
- `tools/telemetry_calibration_diagnostic.py`

It produced:
- bucket diagnostics
- stat/direction slice diagnostics
- games-used diagnostics
- role-context diagnostics
- questionable status diagnostics
- p_cal source diagnostics

### Diagnostic conclusion
The diagnostic changed the direction:
- biggest recurring errors were **not** broad overheating
- strongest signals were **underconfident slices**, especially:
  - `FG3M UNDER`
  - `RA UNDER`
  - `PRA UNDER`
  - `REB UNDER`
  - `PA UNDER`
  - `PR UNDER`
- additional useful underconfidence on:
  - `PR OVER`
  - `PRA OVER`
  - `PTS OVER`
  - `PA OVER`

So the correct next family became:
- **targeted lift**
- not broad cooling
- not broad UNDER penalty

### 6. Targeted lift v1
Artifact built:
- `telemetry_calibration_targeted_lift_v1.json`

Single-raw result:
- clean pass
- exact intended keys fired
- mild targeted lifts only

Full corpus result:
- **first challenger with real corpus-level improvement**
  - Brier improved
  - log loss improved
- but **reader still did not auto-promote**
  - gates did not clear broadly enough
- Decision:
  - do not promote yet
  - soften into v2

### 7. Targeted lift v2
Artifact built:
- `telemetry_calibration_targeted_lift_v2.json`

Changes vs v1:
- same diagnostic target family
- slightly smaller multipliers:
  - `FG3M|UNDER = 1.028`
  - `RA|UNDER = 1.012`
  - `PRA|UNDER = 1.012`
  - `REB|UNDER = 1.012`
  - `PA|UNDER = 1.008`
  - `PR|UNDER = 1.008`
  - `PR|OVER = 1.008`
  - `PRA|OVER = 1.008`
  - `PTS|OVER = 1.006`
  - `PA|OVER = 1.006`

Single-raw result:
- clean pass
- targeted keys fired
- mild behavior preserved
- no broad board distortion

### Current position
- `targeted_lift_v2` is the current best active challenger.
- The next step is the **full fixed-corpus A/B** for `targeted_lift_v2`, followed by the telemetry reader on control and challenger, then compare whether v2:
  - beats control on Brier and log loss
  - avoids damaging protected slip surfaces
  - clears more gates than v1
  - becomes promotable

---

## Canonical commands / tooling state

### Standard baseline (locked)
- `a = 0.3164`
- `b = -0.2880`

### Active files that matter
- `config.yaml`
- `data/model/calibration_map.json`  ← identity / neutral
- `data/model/telemetry_calibration.json`  ← active telemetry challenger file
- `src/Atlas/runtime/telemetry_calibration.py`
- `tools/telemetry_corpus_reader.py`
- `tools/telemetry_calibration_diagnostic.py`
- `tools/create_eval_leg_backtestv2.py`

### Live corpus methodology
1. control = rename/remove `telemetry_calibration.json`
2. challenger = copy challenger artifact into `telemetry_calibration.json`
3. replay same corpus
4. run reader on both
5. compare bundles
6. only promote on evidence

### Current most important unresolved question
- **Does `targeted_lift_v2` beat control on the full fixed replay corpus strongly enough to promote?**
