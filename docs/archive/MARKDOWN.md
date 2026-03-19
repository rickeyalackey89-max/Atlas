# Atlas Math Contract (Leg → Slip) — Formula + Column Truth

This document defines the **authoritative formulas** and probability sources used by Atlas, independent of UI/publishing.

It is written to match the system’s actual artifacts:
- Leg ledger: `scored_legs.csv`, `scored_legs_deduped.csv`
- Slip portfolios: `recommended_{3,4,5}leg.csv` + `System/` and `Windfall/` variants

---

## 1) Probability pipeline per leg

Each leg row carries a probability “story”:

### 1.1 Baseline probability: `p`
- **Definition:** baseline probability of hitting the prop threshold based on historical distribution + line.
- **No role redistribution** and no “heater bump” is implied by the *definition* of baseline.

### 1.2 Role-adjusted probability: `p_role`
- **Definition:** probability after **role-context redistribution** + **heater bump**.
- Role-context redistribution means: teammates being out changes expected rate/share for the player.
- Heater bump means: if player has hit the target line ≥ **8/10**, apply a bump (your `role_ctx_bump` flag tracks this).

> In short: `p_role` is designed to be the “correct output” when injuries/outs matter, *and* includes the heater behavior.

### 1.3 Post-adjust probability: `p_adj`
- **Definition:** probability after additional stabilizers (fragility / blowout / other smoothing rules).
- This is designed to be the “correct output” when role redistribution is not the dominant driver (healthy teams).

### 1.4 Close-line variants
These exist to stabilize behavior near threshold lines:
- `p_close_raw`: close-line probability before role context
- `p_close_role`: close-line probability after role context
- `p_close`: blended close-line probability used downstream where applicable

---

## 2) Calibration mapping: `p_cal`

### 2.1 Calibration map definition
Calibration uses a monotone grid map:

- Input grid: `grid_p_in` (non-decreasing)
- Output grid: `grid_p_out`

For each row:

1) `p_in = clip(p_source, 0, 1)`
2) `p_cal = interp(p_in, grid_p_in, grid_p_out)`

This is deterministic and stable.

### 2.2 Calibration policy (row-wise source selection)
**Policy:**
- If outs/redistribution is engaged → calibrate **`p_role`**
- Otherwise → calibrate **`p_adj`**

Formally:

- `outs_engaged := (role_ctx_outs_used is non-empty)`  
  (fallback: `role_ctx_outs` if `_used` not available)

- `p_for_cal = p_role` if `outs_engaged` else `p_adj`
- `p_cal = CalMap(p_for_cal)`

**Debug columns (recommended):**
- `p_for_cal`: numeric probability used as map input
- `p_cal_src`: `"p_role"` or `"p_adj"`

---

## 3) Slip-level math (recommended slips)

Each slip row is a set of N legs (N ∈ {3,4,5}) drawn from the deduped leg ledger.

### 3.1 Probability source for slips
Current implementation (as observed in the 2026-02-24 shadow run):
- Slip probabilities are computed from `p_adj` (until `p_cal` is integrated into slip building).

Once `p_cal` exists, you can move to:
- `hit_prob = Π p_cal_i` (recommended later), or export both (`hit_prob` and `hit_prob_cal`) during transition.

### 3.2 `hit_prob`
For an N-leg slip:

- **Current contract (observed):**
  \[
  hit\_prob = \prod_{i=1}^{N} p_{adj,i}
  \]

### 3.3 `avg_p`
\[
avg\_p = \frac{1}{N}\sum_{i=1}^{N} p_{adj,i}
\]

### 3.4 `avg_fragility`
\[
avg\_fragility = \frac{1}{N}\sum_{i=1}^{N} fragility_i
\]

### 3.5 `payout_mult`
`payout_mult` is determined by the pricing engine for the slip.
In POWER-style modeling, payout behaves like:

\[
payout\_mult \approx base\_mult \times \prod_{i=1}^{N} leg\_factor_i
\]

Typical bases:
- 3-leg: 5x
- 4-leg: 10x
- 5-leg: 20x

> Note: payout can vary even with the same tier mix if `leg_factor` depends on tier+line or other PP kernel metadata.

### 3.6 `ev_mult`
Observed contract:
\[
ev\_mult = hit\_prob \times payout\_mult
\]

---

## 4) What must be true for the system to be interpretable
- `scored_legs_deduped.csv` is the canonical “leg ledger.”
- Any slip metric must be explainable from its legs’ probabilities + payout logic.
- Calibration must be auditable:
  - include `p_for_cal`, `p_cal_src`, `p_cal`

---

## 5) Implementation note (p_cal)
To enforce the calibration policy without ambiguity:
- Add `p_cal` to both `scored_legs.csv` and `scored_legs_deduped.csv`
- Use `role_ctx_outs_used` to decide whether to calibrate from `p_role` or `p_adj`
- Add debug columns (`p_for_cal`, `p_cal_src`) so telemetry can segment:
  - “healthy” vs “outs-engaged” calibration performance

---

# Patch: Add p_cal to scored_legs.csv + scored_legs_deduped.csv (row-wise p_role vs p_adj)

I made a patch that adds:
- `p_for_cal` (numeric)
- `p_cal_src` (`p_adj` or `p_role`)
- `p_cal` (calibrated)

to **both** `scored` and `scored_for_optimizer` right after the prep-for-optimizer stage, before outputs are written.

**Calibration source policy:**
- If `role_ctx_outs_used` (or fallback `role_ctx_outs`) is non-empty → calibrate `p_role`
- Else calibrate `p_adj`

**Map source:**
- Uses `ATLAS_CAL_MAP` (same as your existing calibration map loader)

## Download patch zip
[Download the patch zip](sandbox:/mnt/data/Atlas_patch_add_p_cal_to_scored_legs.zip)

### Included file
- `Atlas/src/Atlas/engine/main.py`
  - sha256: `030a72dbbea2205f11790f2b1f152b3ab66e540891801a2b817b3b557fad0a40`

Patch zip sha256:
- `78cbd61e929061596cf6c8300bb95ada9eda7342fa3b64c2f9b7c2b220cc019f`

## How to apply (zip-based replacement)
1) Unzip `Atlas_patch_add_p_cal_to_scored_legs.zip`
2) Copy the contained path into your Atlas repo root, overwriting:
   - `src\Atlas\engine\main.py`
3) Run a normal live run:
   - `.\run.ps1`
4) Verify in the new run folder:
   - `scored_legs.csv` contains `p_for_cal`, `p_cal_src`, `p_cal`
   - `scored_legs_deduped.csv` contains `p_for_cal`, `p_cal_src`, `p_cal`