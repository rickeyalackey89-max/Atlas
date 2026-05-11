# Share Allocator + Share Matrix Review — 2026-05-10

Audit conducted while the post-kernel-tune corpus replay was running. This is a structural/architectural review of `team_share_allocator_v2.py`, `share_matrix_builder_v2.py`, and the runtime path in `new_probability.py::compute_role_multiplier`. The goal is to find concrete ways to make the role-context layer more accurate and stable so it correctly captures the philosophy in `Team share allocator philosophy.txt`.

## TL;DR — The Biggest Stability Issues

1. **The CraftedNBA columns the allocator is built to consume are mostly empty.** The `team_share_allocator_v2.py` has explicit ramps on `copm`, `drip_offense`, `usage_projection`, `depth_role`, `rotation_tier`, `starter_flag`, `role_awareness` — every one of those returns `None` from the live snapshot. The advanced-metric branches are effectively dead.
2. **The runtime never sees the allocator's classification.** The allocator stores `transfer_fraction` and `depth_multiplier` internally then collapses them into a single `weight`. The engine then re-uses that `weight` with a *different* dampening scheme (`star_beneficiary_damp`, `core_beneficiary_damp`, `demon_tier_damp`, `over_direction_damp`, `multi_injury_boost`). Two parallel dampening systems is the structural problem — they need to be unified.
3. **Beneficiary minutes are static.** The allocator uses gamelog `avg_min` over 140 days, which does not adapt when a player has just been promoted into a bigger role. Forward-looking minutes (which would handle promotion-on-injury) are not used even though `minutes_projection` is available.
4. **No held-out test exists for the matrix itself.** The matrix is built each run from the current IAEL — there is no validation set of (team, out-player, beneficiary, stat) → (actual production swing) that grades whether the matrix is right.
5. **Multi-out logic is linear and global.** Penalty is `0.12 * max(0, n_outs - 1)` capped at 0.55. There is no notion of overlap (do two outs serve the same beneficiary?) or stat-family interaction (e.g., two PG outs both push AST to one teammate, which the model should *amplify* not penalize).

## CraftedNBA Field Coverage (2026-05-10 snapshot, 518 players)

Source: `https://craftednba.com/api/player-stats` via [tools/fetch_role_metrics.py](../../tools/fetch_role_metrics.py)

| Field | Populated | Status | Used By Allocator |
|---|---|---|---|
| `darko` / `odarko` | 95% / 95% | ✅ available | yes (boost) |
| `drip_total` | 95% | ✅ available | no |
| `vorp` | 83% | ✅ available | no |
| `bpm` / `obpm` / `dbpm` | 96% / 95% / 94% | ✅ available | no |
| `usg_pct` (seasonal) | 97% | ✅ available | no |
| `crafted_warp` | 95% | ✅ available | no |
| `crafted_opm` / `crafted_dpm` | 97% / 95% | ✅ available | no |
| `minutes_projection` (seasonal total) | 100% | ✅ available | no |
| `ts_pct` / `tov_pct` | 99% / — | ✅ available | no |
| **`copm`** | **0%** | ❌ empty in API | YES (classify_outgoing_player) |
| **`drip_offense`** / `drip_defense` | **0%** | ❌ empty in API | YES (_candidate_score) |
| **`usage_projection`** (per-game) | **0%** | ❌ empty in API | engine uses it |
| **`depth_role`** | **0%** | ❌ empty in API | not yet |
| **`rotation_tier`** | **0%** | ❌ empty in API | not yet |
| **`starter_flag`** | **0%** | ❌ empty in API | not yet |
| **`role_awareness`** | **0%** | ❌ empty in API | engine references |
| `load` / `pr` | 0% | ❌ empty in API | no |

The API endpoint exposes box-score + impact ratings but **not** the projection/role columns. Those probably live on a different CraftedNBA endpoint (the HTML projection table). The parser already handles those headers — it's the upstream data that's missing.

### Concrete Action Item A — Fix the upstream fetch

Either (1) find the projection endpoint and add a second call to enrich the snapshot, or (2) drop the dead code branches and stop pretending they're contributing. Option 1 is better — those fields are exactly what the philosophy needs.

## Code-Level Findings

### 1. `classify_outgoing_player` — bucket boundaries are ad-hoc

```python
if usage >= 0.28 or minutes >= 30.0 or role_index >= 0.75: → "star" (transfer 0.72)
elif usage >= 0.16 or minutes >= 24.0 or role_index >= 0.50: → "core" (transfer 0.54)
elif usage >= 0.08 or minutes >= 14.0 or role_index >= 0.25: → "role" (transfer 0.32)
else: → "bench" (transfer 0.12)
```

- The thresholds were picked by intuition, not fit to data. There is no audit showing star outs actually transfer ~72% of their value in observed games.
- `usage` here is the **mean of pts/reb/ast shares** which is *not* true usage% — a high-AST low-scoring PG will look like a non-star even if they're irreplaceable.
- The advanced-metric "bump" only kicks in for `core_adv` and `role_adv` brackets — it can never *create* a star classification, only nudge between role and core. So Westbrook-on-Lakers-2024-style players (mid-usage, huge impact) stay miscategorized.

### 2. `_team_depth_score` is HHI of minutes — useful but coarse

```python
hhi = sum(share_i^2)  # minute concentration
depth = clamp(1.0 - hhi, 0, 1)
```

- Teams with a single dominant minute consumer score *less* depth — correct direction.
- But two-star teams (Den, Bos, OKC during regular season) have *more* minute concentration than one-star teams. A team like LAL with high LeBron concentration scores as *shallower* than DEN with Jokic-Murray split. That gives LAL more transfer when LeBron is out (good) but DEN less transfer when Jokic is out (wrong — DEN gets devastated without Jokic).
- Need a **star-aware depth** signal: HHI excluding the out player, or a "next-N rotation strength" feature.

### 3. `_candidate_score` heavily favors role players who already played a lot

```python
raw = (0.70 * stat_share + 0.30 * min_share) * role_headroom * adv_mult
```

- Top role-headroom is `0.40 + 0.60 * role_index` — so a starter (role_index=1) gets 1.0, bench gets 0.40.
- This *correctly* sends bumps to starters > bench, but means the model can never project a deep-bench player to a breakout night, even when that's what actually happens after a star injury (the next-man-up frequently outperforms his season averages).
- No "ceiling" feature — a player with 4 ppg-but-25-min role gets less than a player with 8 ppg-but-15-min role, even though minutes capacity is what actually matters for absorption.

### 4. Multi-out penalty is structurally backward in some scenarios

```python
multi_out_penalty = min(0.55, 0.12 * max(0, n_outs - 1))
# applied as transfer *= max(0.60, 1.0 - multi_out_penalty)
```

- Says: more outs → less transfer per out. **But the philosophy says the opposite** for stat families where two outs both contribute to the same metric. If both PGs are out, AST should *concentrate* on the remaining ball-handler, not dilute.
- Correct shape: penalty depends on **whether the outs are stat-redundant** (two scorers) vs **stat-independent** (a scorer + a defender).

### 5. The runtime adds a second dampening layer

In `new_probability.py::simulate_leg_probability_new` around line 2245:

```python
_bump_pre = role_mult_raw - 1.0
if ben_min_mean >= 33: _bump_pre *= star_beneficiary_damp  # 0.25
elif ben_min_mean >= 28: _bump_pre *= core_beneficiary_damp  # 0.60
if pp_tier == "DEMON": _bump_pre *= demon_tier_damp  # 0.0
if direction == "OVER": _bump_pre *= over_direction_damp  # 0.50
if outs_used >= 3: _bump_pre *= multi_injury_boost  # 1.0
```

- `star_beneficiary_damp=0.25` means **75% of the bump is wiped** for high-minute beneficiaries. The philosophy says "the next man up *should* benefit," so this is doing the right thing for capacity reasons (a 36-min/g player can't add another 6 min), but the magnitude is heuristic.
- `demon_tier_damp=0.0` completely kills role context for DEMON legs. That's defensible (DEMON lines are market-efficient) but it means a star-out + demon-line scenario gets *no* role context boost at all.
- `over_direction_damp=0.5` means OVERs get half the bump UNDERs get. The philosophy is symmetric (a star out should push beneficiary OVERs and pull star-line UNDERs equally) — there's no fundamental reason OVER should be dampened more.

These knobs may have been tuned for Brier, but they're tuning *against the philosophy* rather than refining it.

## Stability Issue: Why The Allocator Drifts Across Runs

1. The matrix is rebuilt every run from the current IAEL. If IAEL changes (a player downgrades from Q→OUT), the matrix changes, and **the same leg gets a different `p_role`** without anything else changing.
2. Gamelog windowing is `recent_days=140`. As new games land, old games drop off — the share calculation drifts even when nothing about the team has changed.
3. There is no version pin between the allocator config and the calibration. Re-tuning the allocator silently invalidates GBM training data because `p_for_cal` changes.

## Proposed Stabilization Plan

### Phase 1 — Quick Fixes (config + small code)

**1.1 Strip dead branches.** Remove the `copm`/`drip_offense` boosts from `classify_outgoing_player` and `_candidate_score` until those fields come back. They add nothing today and obscure what the allocator is actually using.

**1.2 Use seasonal `darko` + `usg_pct` instead.** These have 95%+ coverage and are reliable stand-ins for the role classification the philosophy asks for:
- `is_star = (darko >= 3.0) OR (usg_pct >= 26) OR (avg_min >= 32)`
- `is_core = (darko >= 1.0) OR (usg_pct >= 18) OR (avg_min >= 24)`

**1.3 Compute star-aware depth.** Replace HHI-of-all-minutes with HHI excluding the out player. This single change correctly punishes single-star teams (LAL without LeBron) more than depth-equal teams (DEN without Jokic — but Murray still produces).

**1.4 Reverse multi-out penalty for redundant stats.** If two outs both have `pts_share >= 0.20`, the PTS pool should *concentrate* on the next scorer, not dilute. Implement as: `multi_out_stat_concentration[stat] = 1.0 + 0.10 * (n_outs_with_strong_stat - 1)` for the same stat family.

### Phase 2 — Unification (code refactor)

**2.1 Move all dampening into the allocator.** Today the engine adds star/core/demon/over dampers after the fact. Move those into the matrix `weight` itself so:
- weights become already-dampened
- engine just reads + clamps
- no parallel knobs

The engine would lose the `_bump_pre` block; the allocator would output a single calibrated weight per (team, out, beneficiary, stat).

**2.2 Add beneficiary-capacity ceiling.** Each beneficiary gets a hard ceiling = `(48 - current_avg_min) / current_avg_min` — a 36-min player can only gain ~33% more minutes, period. This is mechanical, not heuristic.

### Phase 3 — Trainer / Validation (biggest leverage)

**3.1 Build a held-out injury panel.** For every game in the gamelog where a starter was OUT, compute the actual stat swing for each teammate. This produces a labeled dataset:
- features: `(out_player_star_class, team_depth, beneficiary_minutes, beneficiary_usg, stat)`
- target: `actual_stat - season_avg_stat` for that beneficiary in that game

You already have all the data. The panel is computable in minutes.

**3.2 Fit weights to the panel.** Either:
- isotonic regression on `predicted_bump → actual_bump` per (stat, role) bucket
- or a small GBM with the allocator outputs as features and actual bump as target

This is a focused trainer, not a global LOSO. It produces an honest calibration of "given allocator says +0.30 PTS bump for beneficiary X, what's the actual mean swing in observed games?"

**3.3 Stability constraint in matrix build.** When the matrix is rebuilt, weight changes vs the previous matrix should be bounded (e.g., max 20% per-row change unless gamelog rows for that pattern changed by >20%). This stops the day-over-day drift.

### Phase 4 — Forward-looking inputs (after API fix)

If/when CraftedNBA `usage_projection` and `depth_role` come back populated:
- replace seasonal `usg_pct` with `usage_projection` (forward forecast)
- use `depth_role` directly as the bucket label, ground-truthed by CraftedNBA's own model

## Recommended Order Of Operations

1. **Finish current corpus replay + cache rebuild + CatBoost retrain.** Do not touch the allocator yet. Establish baseline Brier with current config.
2. **Build the injury panel (Phase 3.1).** Read-only, can run in parallel with other work. Produces the dataset that grades the matrix.
3. **Compute "current allocator predicted bump vs panel actual bump" calibration plots.** This tells us *where* the matrix is wrong (e.g., overshooting on star outs? undershooting on multi-out scenarios?).
4. **Phase 1 quick fixes.** Each one is small, in-config or single-file. Test in replay-1 mode against panel before scaling.
5. **Phase 2 unification.** Behind a config flag; A/B-able vs current.
6. **Phase 3.2 trainer.** Once panel + Phase 1 are in place, fit the bumps to actuals.

## Why This Approach (vs A Dedicated LOSO)

A LOSO trainer for the matrix would be:
- expensive (each LOSO leaf is a per-date matrix rebuild + full replay)
- noisy (Brier on a full slate is dominated by ~thousands of legs that have no role context at all — only ~10-30 legs per slate have meaningful role_ctx_outs_used)
- self-referential (matrix → p_role → p_adj → p_cal → slip score; LOSO Brier rewards the whole pipeline, not the matrix specifically)

A **panel-based regression** is the right tool because:
- target is observed (actual stat - mean), not derived from probabilities
- N per row is small but per-bucket aggregation gives clean groups (star out / core out / role out × stat)
- doesn't require rerunning the engine — pure pandas on gamelogs + IAEL history
- gives a direct answer: "is the +0.30 PTS bump for beneficiary X correct?"

## Open Questions For Discussion

1. Should we kill the `over_direction_damp=0.5` knob? The philosophy says role context is symmetric direction-wise.
2. Should `demon_tier_damp=0.0` move to `0.3` or so? Demons are market-efficient, but star-out scenarios *are* often where Demon lines miss.
3. Where do you want the "stability budget" enforced — in the matrix builder (cap row-level change) or downstream (smooth `p_role` against EMA of past few runs)?
