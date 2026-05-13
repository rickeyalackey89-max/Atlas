# Atlas Single-Game Slate Script + Prop Translation Brief

**Date:** 2026-05-12
**Use case:** Hand this to Codex for repo-side implementation/testing.
**Slate type:** Single-game NBA playoff slate, Spurs vs Timberwolves Game 5.
**Primary goal:** Establish a baseline single-game mode before Conference Finals, where single-game slates become common and normal multi-game slip logic becomes dangerous.

---

## 1. Executive Summary

Single-game slates should not be treated like normal slates. The correct mode is not pure edge discovery; it is **risk containment plus script reachability**.

For this specific Game 5 context, the recommended baseline script is:

> **Close Spurs-efficiency / Wolves-glass counterpunch script**

Meaning:

```text
The game remains competitive into the 4th quarter.
San Antonio keeps the efficiency edge through eFG%, FT rate, Wembanyama gravity, Castle/Fox pressure, and spacing.
Minnesota keeps the game reachable through Anthony Edwards usage, offensive rebounding, second-chance points, and physicality.
Primary players and closers absorb most of the minutes.
Low-minute bench overs are treated as dangerous unless there is a very clear minutes/attempt path.
```

This should become a **prop-family preference layer** for Atlas, not just a narrative label.

The practical prop-family translation is:

```text
MIN: prefer REB / PR / rebound-led RA over pure scoring or assist-dependent props.
SAS: prefer primary-offense PA / PR / PRA / PTS / Wemby REB/BLK/PRA paths.
Slip construction: one MIN glass/counterpunch leg + one SAS efficiency/core leg + one stable star/closer leg.
Avoid forced 4-leg/5-leg builds, low-minute bench overs, and multi-shooter stacks.
```

---

## 2. Current Series Context Provided by User

Series context:

```text
Series: tied 2-2
Venue: Game 5 in San Antonio
Home/road split: each team has one home win and one home loss
Competitive profile: 3 of 4 games were within 7 points
Exception: one lopsided San Antonio win where Anthony Edwards was hurt
Anthony Edwards: back healthy
Only Minnesota player out: Donte DiVincenzo; Wolves have already adjusted to his absence
```

Team four-factor profile supplied by user:

| Team | Pace | eFG% | TOV% | ORB% | FT/FGA | ORtg | PTS |
|---|---:|---:|---:|---:|---:|---:|---:|
| MIN | 100.7 | .478 | 13.4 | 27.3 | .178 | 104.5 | 105.3 |
| SAS | 100.7 | .534 | 12.0 | 25.4 | .250 | 113.9 | 114.8 |

Primary read:

```text
Pace is neutral/even.
San Antonio owns the efficiency edge: eFG%, FT/FGA, ORtg, PTS.
Minnesota’s best stable counterpunch is the offensive glass and physicality.
Minnesota is not winning the series profile through clean shot-making.
```

---

## 3. Attached Sports Reference Exports: Series Player Context

The user attached four Sports Reference exports:

```text
sportsref_download (1).xls  -> Minnesota basic/totals/per-game table
sportsref_download.xls      -> Minnesota advanced table
sportsref_download (3).xls  -> San Antonio basic/totals/per-game table
sportsref_download (2).xls  -> San Antonio advanced table
```

These are HTML table exports saved as `.xls` files. Use them as current series context, not season priors.

### Minnesota key series per-game values

| Player | MPG | PPG | RPG | APG | Notes for props |
|---|---:|---:|---:|---:|---|
| Anthony Edwards | 32.5 | 24.5 | 6.5 | 2.8 | Primary usage anchor; PR/PRA preferred over assist-only |
| Jaden McDaniels | 34.1 | 14.8 | 5.3 | 2.0 | Stable minutes; REB/PR can fit glass-counterpunch script |
| Julius Randle | 34.4 | 14.3 | 7.3 | 1.8 | Inefficient scoring but rebound/PR path is script-compatible |
| Naz Reid | 28.4 | 14.0 | 8.5 | 2.5 | Bench but high-minute/stable enough to treat as core-adjacent |
| Terrence Shannon Jr. | 26.9 | 10.3 | 3.5 | 1.5 | Role/scoring volatility; use only with line/attempt support |
| Rudy Gobert | 29.8 | 9.0 | 10.0 | 2.5 | Strong MIN glass/counterpunch archetype |
| Mike Conley | 13.7 | 5.8 | 1.3 | 2.8 | Low-minute guard; should be guarded hard |
| Ayo Dosunmu | 24.3 | 7.0 | 4.0 | 2.7 | Role-dependent; minutes stability check required |

### Minnesota advanced notes

| Player | eFG% | USG% | ORB% | TRB% | AST% | ORtg | Prop implication |
|---|---:|---:|---:|---:|---:|---:|---|
| Anthony Edwards | .574 | 28.4 | 2.3 | 9.8 | 16.4 | 114 | Strongest Wolves offensive anchor |
| Jaden McDaniels | .418 | 20.7 | 6.3 | 7.7 | 11.4 | 101 | Poor shooting but minutes + rebounds matter |
| Julius Randle | .407 | 23.5 | 10.2 | 10.7 | 7.6 | 86 | Avoid blind PTS; PR/REB more script-aligned |
| Naz Reid | .638 | 17.0 | 4.4 | 15.0 | 13.7 | 127 | Strong efficiency + rebounding; core single-game candidate if line reasonable |
| Rudy Gobert | .560 | 13.3 | 13.4 | 17.0 | 11.9 | 113 | Best pure MIN glass leg type |
| Ayo Dosunmu | .321 | 19.3 | 1.2 | 8.2 | 15.6 | 77 | Efficiency concern; do not blindly chase scoring |

### San Antonio key series per-game values

| Player | MPG | PPG | RPG | APG | Notes for props |
|---|---:|---:|---:|---:|---|
| Victor Wembanyama | 28.8 | 18.3 | 12.3 | 2.3 | Minutes depressed by Game 4 ejection; close-game projection should be higher |
| Stephon Castle | 32.2 | 17.8 | 4.8 | 6.3 | Primary creator; PA/PRA/AST paths fit SAS efficiency script |
| De'Aaron Fox | 32.6 | 16.8 | 2.5 | 4.0 | Health gate required; questionable ankle context must be checked pre-lock |
| Dylan Harper | 24.6 | 15.3 | 5.5 | 2.8 | Productive bench role; check knee/availability and minutes path |
| Devin Vassell | 31.9 | 12.8 | 4.3 | 3.3 | Stable spacing/scoring role, but do not stack multiple shooter overs |
| Julian Champagnie | 28.1 | 10.8 | 6.8 | 2.0 | Spacing + rebounding; role-shooter cap still applies |
| Keldon Johnson | 19.5 | 8.8 | 4.3 | 1.0 | Borderline; guard by minutes and line |
| Luke Kornet | 14.5 | 3.8 | 3.5 | 0.5 | Low-minute big; not a primary single-game slip leg |

### San Antonio advanced notes

| Player | eFG% | USG% | ORB% | TRB% | AST% | ORtg | Prop implication |
|---|---:|---:|---:|---:|---:|---:|---|
| Victor Wembanyama | .536 | 26.2 | 7.3 | 21.1 | 12.1 | 113 | Wemby REB/PRA/BLK/PR paths remain core if minutes restored |
| Stephon Castle | .522 | 22.5 | 3.2 | 7.5 | 27.8 | 122 | Best SAS creation archetype |
| De'Aaron Fox | .409 | 27.6 | 0.8 | 3.9 | 18.9 | 92 | Usage high, efficiency poor, health gate critical |
| Dylan Harper | .588 | 22.5 | 4.2 | 11.3 | 17.5 | 130 | Strong but availability/minute risk should be checked |
| Devin Vassell | .545 | 16.2 | 4.1 | 6.6 | 14.5 | 121 | Stable role; one shooter/spacing leg max per slip |
| Julian Champagnie | .591 | 13.7 | 7.3 | 11.9 | 9.3 | 134 | Good spacing/rebounding support; cap stacks |
| Keldon Johnson | .448 | 21.6 | 4.1 | 10.9 | 7.4 | 99 | Volatile support role |

---

## 4. Current External Pre-Lock Notes to Verify

Codex should treat these as **pre-lock verification items**, not static truth. The current web checks found:

```text
Series is tied 2-2 entering Game 5.
Game 5 is in San Antonio.
Wembanyama avoided suspension after Game 4 ejection and is expected available.
De'Aaron Fox is listed as questionable / game-time decision with ankle soreness.
Dylan Harper has been reported questionable with knee soreness.
San Antonio has recently allowed 15 offensive rebounds in each of the last two games according to local preview coverage.
```

Sources checked:

- Reuters/Field Level Media, “Spurs' Dylan Harper (knee) questionable for Game 5 vs. Wolves,” 2026-05-12.
- San Antonio Express-News, “Latest on Spurs guard De'Aaron Fox's status for Game 5,” 2026-05-12.
- MySanAntonio, “Spurs' Victor Wembanyama will play Game 5 vs. Timberwolves,” 2026-05-11.
- Pounding The Rock, “Game Five Preview: San Antonio Spurs vs. Minnesota Timberwolves,” 2026-05-12.
- Canis Hoopus, “Game 5 Preview: Timberwolves at Spurs,” 2026-05-12.

Implementation request:

```text
Make the single-game mode consume the live IAEL/Rotowire/injury source and branch if Fox or Harper is limited/out.
Do not hardcode either as active.
```

---

## 5. Why Single-Game Slates Need a Separate Mode

Normal slates:

```text
Edge discovery across many games.
Diversification is possible.
One bad game does not destroy the whole board.
```

Single-game slates:

```text
No game diversification.
Same-game correlation is unavoidable.
One blowout script affects every leg.
One injury, foul issue, rotation decision, or bench shift can kill the slate.
The builder can overuse marginal edges because the pool is thin.
Parlay construction matters more than raw leg ranking.
```

Therefore:

```text
Normal slate mode = edge discovery.
Single-game mode = risk containment + script reachability.
```

---

## 6. Recommended Baseline Script

Recommended primary script:

```yaml
single_game_script:
  primary_script: close_spurs_efficiency_wolves_glass
  confidence: medium_high

  possession_band: [97, 103]
  expected_margin_band: [1, 8]

  san_antonio_path:
    - efg_advantage
    - ft_rate_advantage
    - wembanyama_full_minutes
    - castle_creation
    - fox_creation_if_healthy
    - vassell_champagnie_spacing

  minnesota_path:
    - anthony_edwards_primary_usage
    - offensive_rebounding
    - second_chance_points
    - gobert_naz_randle_glass
    - physical_close_game

  downweighted_evidence:
    - lopsided_spurs_win_with_edwards_hurt
    - wembanyama_game4_ejection_minutes

  hard_avoid:
    - low_minute_bench_overs
    - forced_slip_output
    - slips_requiring_blowout
    - contradictory_game_scripts
```

This script is reachable because it does not require a weird event. It only requires:

```text
Ant healthy.
Wemby plays normal close-game minutes.
Spurs efficiency continues.
Wolves offensive glass remains a real counterpunch.
The game remains within striking distance.
```

---

## 7. Prop-Family Translation

The narrative should affect **prop families** and **slip composition**, not just text labels.

### 7.1 Minnesota glass counterpunch

Minnesota’s series profile shows poor eFG/ORtg but a real offensive rebounding path.

Upgrade:

```text
MIN REB
MIN PR
MIN rebound-led RA
MIN PRA only when rebound/usage support is real
```

Candidate player archetypes:

```text
Rudy Gobert REB / RA / PR
Naz Reid REB / RA / PR
Julius Randle REB / PR, not blind PTS
Jaden McDaniels REB / PR if line is soft
Anthony Edwards PR / PRA more than AST-only
```

Downgrade / be careful:

```text
MIN pure PTS from inefficient non-stars
MIN AST-only props
MIN assist-dependent RA where assists carry the line
Low-minute Minnesota bench overs
```

Specific logic:

```text
If RA is rebound-driven, script-positive.
If RA is assist-driven, script-neutral or negative because MIN eFG is weak.
```

### 7.2 San Antonio efficiency edge

San Antonio owns the cleaner offensive profile in eFG, FT/FGA, ORtg, and PTS.

Upgrade:

```text
SAS primary creator PA / PRA / PR / PTS
Wembanyama REB / PR / PRA / BLK depending line
Castle PA / PRA / AST
Vassell / Champagnie spacing props as one-per-slip candidates
Fox PA / PTS only if health gate passes
Dylan Harper PR / PRA only if knee/minutes gate passes
```

Downgrade / be careful:

```text
Random SAS bench overs
Multiple role-shooter overs in the same slip
Fox aggressive overs if ankle status/minutes are uncertain
Harper overs if knee status/minutes are uncertain
```

### 7.3 Wembanyama full-minute return

Raw Wemby series MPG is depressed by Game 4 ejection. Do not blindly treat 28.8 MPG as tonight’s close-game projection.

Recommended adjustment:

```text
Wembanyama close-game minutes: 34–38 range, unless foul/injury/ejection risk branch triggers.
```

Prop effect:

```text
Wemby REB / PR / PRA / BLK become more live than raw series MPG suggests.
Minnesota missed-shot rebound paths can remain live because Wemby may suppress efficiency but increase missed-shot volume.
```

This does **not** automatically kill Minnesota REB props.

### 7.4 Close game / rotation compression

Upgrade:

```text
High-minute starters and closers.
Primary creators.
Stable bench players with true 24+ minute roles.
```

Downgrade:

```text
Thin bench roles.
Low-minute low-line overs.
Props requiring garbage time.
Props requiring random bench spikes.
```

### 7.5 Role shooters

Allow one role-shooter over if it has strong attempt support.

Do not allow multiple shooter overs in a primary slip unless the slip is explicitly tagged as a high-variance “Spurs shooting heater” script.

Rule:

```text
max_role_shooter_overs_per_slip = 1
```

---

## 8. Slip Construction Template

Recommended primary slip structure:

```text
1 MIN glass/counterpunch leg
+ 1 SAS efficiency/core leg
+ 1 stable star/closer leg
```

Valid structural examples, not picks:

```text
Gobert/Naz/Randle REB or PR
+ Wemby PR/PRA/REB/BLK
+ Ant PR/PRA or Castle PA/PRA
```

Or:

```text
MIN rebound-led RA/PR
+ SAS primary creator PA/PRA
+ one stable shooter/spacing leg
```

Bad structures:

```text
Three Spurs scoring overs.
Three Minnesota scoring overs.
Two role-shooter threes plus one bench over.
MIN AST over + MIN shooter over + Spurs blowout script.
Wemby blowout script + Minnesota starter volume overs.
```

---

## 9. Single-Game Mode Config Draft

Starting config for testing:

```yaml
single_game_mode:
  enabled: auto
  trigger_max_games: 1

  build_slip_sizes: [3, 4, 5]
  primary_slip_size: 3
  do_not_block_slip_sizes: true
  do_not_force_output: true
  allow_4_leg_if_quality_passes: true
  allow_5_leg_if_quality_passes: true

  primary_script: close_spurs_efficiency_wolves_glass
  require_script_label: true
  reject_contradictory_scripts: true

  max_players_per_team:
    3_leg: 2
    4_leg: 3
    5_leg: 3

  max_same_stat: 1
  max_low_minute_bench_legs: 0
  max_injury_uncertainty_legs: 1
  max_role_shooter_overs: 1
  max_cat_boosted_legs: 1

  require_one_stable_anchor: true
  require_one_cross_team_or_glass_counterweight: true

  downweight_games:
    - reason: edwards_injury_blowout
    - reason: wembanyama_ejection

  no_play_thresholds:
    min_qualified_stable_legs: 5
    min_unique_players: 4
    max_avg_minute_risk: 0.18
```

Important: single-game mode should be allowed to output:

```text
No full card.
One lean only.
One conservative 3-leg only.
One qualified 4-leg or 5-leg if Atlas actually finds a script-compatible slip.
```

This is a feature, not a failure.

Important implementation rule:

```text
Do not hard-disable 4-leg or 5-leg output solely because the slate is single-game.
Atlas should attempt every configured slip size and only reject a slip when the actual
quality, script-coherence, injury, minutes, or exposure rules fail.
```

---

## 10. p_select vs p_cal

Do not let raw CatBoost `p_cal` alone control single-game slip selection.

Use CatBoost for broad-board calibration, but use a guarded single-game selection surface.

Recommended:

```yaml
p_select_single_game:
  p_for_cal_w: 0.50
  p_cal_w: 0.25
  series_fit_w: 0.15
  minute_stability_w: 0.10
  max_positive_cat_boost_for_selection: 0.02
```

Formula concept:

```python
p_select_single_game = (
    0.50 * p_for_cal
  + 0.25 * p_cal
  + 0.15 * series_script_fit
  + 0.10 * minute_stability_score
  - minute_risk_penalty
  - injury_uncertainty_penalty
  - script_contradiction_penalty
)
```

Why:

```text
Cat D may be a strong broad-board calibrator.
But selected-tail diagnostics showed p_cal/CAT made selected-leg Brier worse while positively boosting 87.5% of selected legs.
Single-game mode is exactly where selected-tail overboost is dangerous.
```

---

## 11. CatBoost Context From Current Trainer

The uploaded Cat trainer file is:

```text
catboost_playoff_v5cD_full_corpus.py
```

Important details:

```text
It trains a single full-corpus CatBoost residual regressor.
Training cache: _v1_playoff_resim_cache.pkl.
Original trainer comment: 10 playoff dates, no holdout.
Architecture: 19 features.
Model: CatBoostRegressor.
Target: hit - p_for_cal.
Residual apply function: p + RESIDUAL_SCALE * clipped residual.
RESIDUAL_SCALE = 0.50.
RESIDUAL_CLIP = 0.20.
P_LO/P_HI = 0.03 / 0.97.
PARAMS: iterations=600, depth=5, learning_rate=0.075, l2_leaf_reg=6.0, min_data_in_leaf=50.
```

Implementation principle:

```text
Use Cat D as one calibration signal.
Do not let Cat D be the sole slip-selection surface for single-game slates.
```

---

## 12. Guard Audit Context

### 12.1 Minutes risk guard passed audit

Current guard:

```yaml
minute_risk_guard:
  enabled: true
  min_modeled_minutes: 16.0
  bench_minutes_threshold: 18.0
  max_minutes_cv: 0.35
  low_modeled_minutes_penalty: 0.10
  bench_under_18_min_penalty: 0.10
  minutes_cv_penalty: 0.08
  injury_uncertainty_penalty: 0.12
  max_total_penalty: 0.25
```

Single-game override suggestion:

```yaml
minute_risk_guard_single_game:
  min_modeled_minutes: 18.0
  bench_minutes_threshold: 20.0
  max_minutes_cv: 0.30
  low_modeled_minutes_penalty: 0.12
  bench_under_18_min_penalty: 0.14
  minutes_cv_penalty: 0.08
  injury_uncertainty_penalty: 0.15
  max_total_penalty: 0.30
```

Reason:

```text
Single-game slates punish bench-minute misses harder because there is no game diversification.
```

### 12.2 Standalone volatility guard failed audit

Current failed guard:

```yaml
volatility_guard:
  enabled: true
  max_total_penalty: 0.12
  low_line_zero_rate_penalty: 0.06
  low_line_minutes_cv_penalty: 0.04
  fg3m_low_line_penalty: 0.04
  min_zero_rate: 0.25
```

Audit result:

```text
Even sweeping configs, it threw away almost 60% more good legs than bad.
```

Recommendation:

```yaml
volatility_guard:
  enabled: false
  report_only: true
```

Do not use blunt volatility as a production selection penalty.

If revisiting later, use excess fragility instead of raw zero-rate:

```python
expected_miss_rate = 1.0 - p_for_cal
excess_zero_rate = zero_rate_l10 - expected_miss_rate

if low_line and zero_rate_l10 >= 0.35 and excess_zero_rate >= 0.12:
    penalty += 0.03
```

Better yet, control fragility at slip level:

```yaml
fragility_exposure:
  enabled: true
  max_low_line_fragile_legs_per_slip: 1
  max_fg3m_overs_per_slip: 1
```

---

## 13. Script-Fit Scoring Draft

Codex should add a lightweight rule-based script engine first. Do not overbuild this as ML yet.

```python
def single_game_script_fit(leg):
    score = 0.0
    team = str(leg.team).upper()
    stat = str(leg.stat).upper()
    player = str(leg.player)

    # Minnesota glass counterpunch
    if team == "MIN" and stat in ["REB", "RA", "PR", "PRA"]:
        if player in ["Rudy Gobert", "Naz Reid", "Julius Randle", "Jaden McDaniels", "Anthony Edwards"]:
            score += 0.08

    # Rebound-led RA is better than assist-led RA
    if team == "MIN" and stat == "RA":
        if getattr(leg, "reb_share_of_ra", 0.0) >= 0.65:
            score += 0.04
        else:
            score -= 0.04

    # SAS efficiency/core path
    if team == "SAS" and stat in ["PTS", "PA", "PRA", "PR", "REB", "BLK"]:
        if player in ["Victor Wembanyama", "Stephon Castle", "De'Aaron Fox", "Dylan Harper", "Devin Vassell", "Julian Champagnie"]:
            score += 0.05

    # Close-game starters / closers
    if getattr(leg, "modeled_minutes", 0.0) >= 28:
        score += 0.05
    if getattr(leg, "modeled_minutes", 0.0) < 18:
        score -= 0.12

    # Role shooter: allow but cap at slip level
    if stat in ["FG3M", "PTS"] and getattr(leg, "role", "") == "role_shooter":
        score += 0.02

    return score
```

Slip-level checks:

```python
def single_game_slip_rules(slip):
    # Must include at least one stable anchor
    require_one_anchor = [
        "Anthony Edwards",
        "Victor Wembanyama",
        "Stephon Castle",
        "Rudy Gobert",
        "Julius Randle",
        "Naz Reid",
    ]

    # Prefer one MIN glass leg
    prefer_one_min_glass = dict(team="MIN", stat_family=["REB", "RA", "PR", "PRA"])

    # Prefer one SAS efficiency/core leg
    prefer_one_sas_core = dict(team="SAS", stat_family=["PTS", "PA", "PRA", "PR", "REB", "BLK"])

    max_role_shooter_overs = 1
    max_low_minute_bench_overs = 0
    build_slip_sizes = [3, 4, 5]
    primary_slip_size = 3
    allow_larger_slips_if_quality_passes = True
```

---

## 14. Contradiction Rules

Reject or heavily penalize slips that require contradictory stories.

Examples:

```text
Favorite blowout script + favorite star over minutes.
Underdog team total under + multiple underdog overs.
Pace-down script + three scoring overs from role players.
Close-game script + two bench overs needing extra minutes.
Same player points under + teammate assist over that depends on him scoring.
Star points over + same star assists over + teammate points under.
```

For tonight specifically:

```text
Reject: multiple Spurs role-shooter overs + Minnesota glass-heavy comeback legs.
Reject: Spurs blowout-dependent bench over + Edwards/Randle/Gobert volume overs.
Reject: Minnesota AST-heavy slip if Wolves eFG remains poor.
Allow: one MIN glass/PR leg + one SAS core-efficiency leg + one stable anchor.
```

---

## 15. Testing Plan Using Existing Single-Game Dates

Use these as initial single-game test dates:

```text
2026-05-02 single-game slate
Last night’s pre-second-game test run
Tonight’s Game 5 run, after truth arrives
```

Compare:

```text
normal_mode
vs
single_game_mode_v1
vs
single_game_mode_v1 + p_select_single_game
vs
single_game_mode_v1 + stricter minutes guard
```

Metrics:

```text
selected leg hit rate
selected Brier
slip win rate
minute_shortfall count
injury_uncertainty count
ordinary_miss count
same-script concentration
contradictory slip count
Cat positive boost rate
average modeled minutes of selected legs
bench-leg exposure
role-shooter stack count
MIN glass-leg count
SAS core-efficiency-leg count
```

Main success metric:

```text
Did single_game_mode reduce avoidable misses without throwing away too many good legs?
```

Avoidable-miss categories:

```text
minute_shortfall
injury_uncertainty
over-correlated same-script failures
overboosted selected misses
low-minute bench overs
```

---

## 16. Specific Codex Tasks

### Task A — Add script classifier

Create something like:

```text
src/Atlas/core/single_game_script.py
```

Responsibilities:

```text
Detect single-game slate.
Classify primary script.
Compute leg script-fit score.
Compute slip script-coherence score.
Emit telemetry/debug reasons.
```

### Task B — Add p_select surface

Add a selection-only probability/score, separate from calibrated reporting probability.

```text
p_cal     -> broad-board calibration / Brier / reporting
p_select  -> slip candidate ranking
p_slip    -> final slip-level probability after correlation/script checks
```

### Task C — Add single-game slip constraints

Add constraints:

```text
build_slip_sizes = [3, 4, 5]
primary_slip_size = 3
do_not_block_slip_sizes = true
do_not_force_output = true
allow_4_leg_if_quality_passes = true
allow_5_leg_if_quality_passes = true
max_role_shooter_overs = 1
max_low_minute_bench_legs = 0
max_same_stat = 1
max_same_team_legs = 2
require_one_stable_anchor = true
require_one_min_glass_or_counterweight = true
```

### Task D — Integrate minutes-risk guard override

Use current audited minutes guard, with stricter single-game overrides.

### Task E — Disable standalone volatility guard

Set report-only or fully off. Do not use it for p_select until a new excess-fragility version passes audit.

### Task F — Add telemetry for single-game run

Output a report with:

```text
primary_script
script_confidence
selected_slip_script_label
per-leg script_fit_score
per-leg p_select
per-leg p_cal
per-leg p_for_cal
cat_delta
minute_risk_penalty
injury_uncertainty_penalty
role_shooter_flag
bench_flag
contradiction_flags
why_selected
why_rejected
```

---

## 17. Questions for Codex to Answer From Repo Tests

1. On 2026-05-02 single-game replay, does single-game mode improve selected-leg hit rate or slip win rate?
2. Does p_select_single_game reduce positive Cat overboost in selected tails?
3. Does stricter minute risk reduce minute-shortfall misses without over-pruning good legs?
4. Are MIN REB/PR/rebound-led RA legs actually outperforming pure MIN scoring/AST legs in this series corpus?
5. Are SAS core-efficiency legs outperforming random SAS support/bench legs?
6. How many candidate slips become invalid due to contradiction rules?
7. How many forced 4-leg/5-leg slips would normal mode create, and how bad are they?
8. Should single-game mode allow exactly one 4-leg upside slip, or should it hard-disable 4/5 until more evidence?
9. Does Wembanyama’s ejection-contaminated minutes cause underprojection in the current model?
10. Do Fox/Harper injury statuses require automatic branching in `p_select` or only in minute-risk guard?

---

## 18. Recommended Baseline for Tonight

Use this plain-English instruction inside any debug/run note:

```text
Baseline script: San Antonio remains the cleaner offense, but Minnesota keeps the game close through Edwards usage and offensive rebounding. Treat Wembanyama and Edwards as close-game minute restoration candidates. Avoid blowout-dependent bench overs. Treat 3-leg as the primary single-game slip size, but build 4-leg and 5-leg slips if the board produces enough script-compatible stable legs. Prioritize one MIN glass/counterpunch leg, one SAS core-efficiency leg, and one stable anchor. Do not force any slip size.
```

Codex should not interpret this as a manual pick list. It should become a script-fit and slip-construction layer.

---

## 19. Final Implementation Principle

The biggest edge is not picking every good-looking prop.

The biggest edge is allowing Atlas to say:

```text
Single-game slate quality is low.
No full card.
One lean only.
One conservative 3-leg only.
```

Most people force parlays on single-game slates because the board exists. Atlas should not.
