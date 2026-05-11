# 2026-05-09 Playoff Adjustment Session

**Date:** May 9, 2026
**Slate:** 2-game playoff (OKC vs LAL, CLE vs DET)
**Run verified:** `20260509_125038` — Built 3 marketed slips (5-leg, 4-leg, 3-leg) ✅

---

## Root Cause

The playoff isotonic calibration (active since late April) compresses `p_cal` into a tighter range (~0.55–0.87) compared to the regular-season scale (~0.50–0.98). The old `min_raw_thresholds` were calibrated against the pre-isotonic scale, so they were cutting out 90%+ of the legitimate GOBLIN pool on playoff slates. This left only 3 unique GOBLIN players in the marketed pool, which caused the 5-leg and 4-leg slips to fail to build.

**Diagnostic finding:** The playoff OVER isotonic curve has hard step breakpoints from sparse training data (~9 playoff dates). Many players cluster at the same `p_cal` value (e.g., 12 GOBLIN players at 0.7219, 6 at 0.6481) regardless of their raw `p_adj` spread. This is expected and will smooth as the playoff corpus grows.

---

## Change 1 — `config.yaml`: `telemetry.active_calibration`

| Setting | Before | After |
|---|---|---|
| `active_calibration` | `isotonic_direction_split` | `playoff_isotonic` |
| `apply_active_calibration` | `true` | `true` (no change) |
| `active_calibration_path` | `data/model/telemetry_calibration.isotonic_direction_split.json` | `data/model/telemetry_calibration.playoff_isotonic.json` |

**What it does:** Switches the telemetry isotonic overlay to the playoff-specific calibration file. The playoff isotonic was trained on ~9 playoff dates of `eval_legs.csv` data and applies separate OVER/UNDER correction curves from `p_adj`. The regular-season isotonic (`isotonic_direction_split.json`) was overcorrecting playoff legs because playoff pace, role distribution, and line calibration differ from regular season.

**Retrain plan:** Tuesday May 13, after May 9–12 eval legs are available:
```powershell
python tools/train_playoff_isotonic.py
```

---

## Change 2 — `config.yaml`: `marketed_slips.min_raw_thresholds`

These are the hard `p_cal` floors (post-isotonic, pre-haircut) that any leg must clear to enter the marketed pool. They gate real quality, not just marketed appearance.

| Tier | Before | After | Reason |
|---|---|---|---|
| GOBLIN | `0.77` | `0.71` | Old floor killed 100+ GOBLIN legs on playoff isotonic scale. At 0.71, 18 unique players qualify. |
| STANDARD | `0.57` | `0.50` | Broadens STANDARD pool on compressed scale; still above the isotonic UNDER window floor. |
| DEMON | `0.62` | `0.55` | Isotonic compresses DEMON legs to 0.55–0.77 range. Old floor wiped the tier entirely. |

**Config location:** `config.yaml` → `marketed_slips.min_raw_thresholds`

```yaml
# BEFORE
min_raw_thresholds:
  GOBLIN: 0.77
  STANDARD: 0.57
  DEMON: 0.62

# AFTER
min_raw_thresholds:
  GOBLIN: 0.71
  STANDARD: 0.50
  DEMON: 0.55
```

---

## Change 3 — `config.yaml`: `marketed_slips.min_thresholds`

These are the `p_cal_marketed` gates (after haircut multiplier applied: GOBLIN×0.95, STANDARD×0.85, DEMON×0.75). They ensure the leg still clears a minimum bar on the customer-facing probability.

| Tier | Before | After | Reason |
|---|---|---|---|
| GOBLIN | `0.57` | `0.57` | Unchanged — already correct for the isotonic scale. |
| STANDARD | `0.30` | `0.54` | Old floor was far too loose, letting in near-coin-flip legs. Tightened to enforce real edge. |
| DEMON | `0.28` | `0.49` | Same — old floor was vestigial. Tightened to match DEMON haircut-adjusted reality. |

**Config location:** `config.yaml` → `marketed_slips.min_thresholds`

```yaml
# BEFORE
min_thresholds:
  GOBLIN: 0.57
  STANDARD: 0.30
  DEMON: 0.28

# AFTER
min_thresholds:
  GOBLIN: 0.57
  STANDARD: 0.54
  DEMON: 0.49
```

---

## Change 4 — `config.yaml`: `marketed_slips.max_players_per_team`

| Setting | Before | After |
|---|---|---|
| `max_players_per_team` | (not set — hardcoded to 2 in code for multi-game slates) | `2` (explicit config key) |

**What changed:** The cap was hardcoded logic in `marketed_slip_builder.py` with no config override path. The key was added to `config.yaml` so it can be tuned without code changes.

```yaml
# AFTER (new explicit key)
marketed_slips:
  max_players_per_team: 2
```

---

## Change 5 — `marketed_slip_builder.py`: Template Build Order

**File:** `src/Atlas/core/marketed_slip_builder.py`

| Before | After |
|---|---|
| 3-leg built first, then 4-leg, then 5-leg | **5-leg built first**, then 4-leg, then 3-leg |

**Why:** All templates share `used_players_global` — once a player appears in any slip, they are blocked from all subsequent slips. The old order meant the 3-leg (easiest to fill) consumed the top GOBLIN and DEMON players first, leaving nothing for the 5-leg (hardest to fill — requires a DEMON). Reversing the order ensures the most constrained template gets first pick.

```python
# BEFORE
self.templates = [
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
]

# AFTER
self.templates = [
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
]
```

---

## Change 6 — `marketed_slip_builder.py`: `max_players_per_team` Config-Driven

**File:** `src/Atlas/core/marketed_slip_builder.py`, line ~268

```python
# BEFORE (hardcoded)
max_per_team = 4 if single_game_slate else 2

# AFTER (config-driven with same default behavior)
max_per_team = int(self.config.get("max_players_per_team", 4 if single_game_slate else 2))
```

---

## Verification — `20260509_125038`

Run output confirmed all 3 slips built with no player overlap:

| Slip | Legs | Players | hit_prob | EV |
|---|---|---|---|---|
| 5-leg | Jaylin Williams (GOB), Isaiah Joe (GOB), Jaxson Hayes (STD), Jarrett Allen (STD), Dean Wade (DEM) | 5 unique | 18.5% | 0.396 |
| 4-leg | Evan Mobley (GOB), Jared McCain (GOB), Tobias Harris (STD), Daniss Jenkins (STD) | 4 unique | 21.0% | 0.398 |
| 3-leg | Duncan Robinson (GOB), Luke Kennard (STD), Rui Hachimura (STD) | 3 unique | 33.3% | 0.643 |

All legs OVER only (expected on thin 2-game playoff slate — UNDER pool is near-empty after applying the 0.50–0.70 window).

---

## Known Ongoing Concerns

1. **Isotonic sparse breakpoints:** Many players cluster at the same `p_cal` (e.g., 12 players at 0.7219) due to only 9 playoff dates of training data. Will smooth as corpus grows. Retrain Tuesday May 13.
2. **Thin DEMON pool:** On 2-game slates, only 2–3 players qualify as DEMON. If both DEMONs also dominate the GOBLIN pool, the 5-leg's `used_players_global` constraint may occasionally block a full build. Accepted behavior — correct product to not force a bad DEMON leg.
3. **STANDARD min_thresholds at 0.54:** On extra-thin slates, this may further constrain the pool. Monitor — lower to 0.50 if 4-leg or 3-leg fails to build on a future slate.

---

## Files Changed

| File | Type |
|---|---|
| `config.yaml` | `marketed_slips.min_raw_thresholds`, `min_thresholds`, `max_players_per_team` |
| `config.yaml` | `telemetry.active_calibration` → `playoff_isotonic` |
| `src/Atlas/core/marketed_slip_builder.py` | Template build order (5→4→3), `max_players_per_team` config-driven |