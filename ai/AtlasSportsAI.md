# Atlas Sports AI — Product & Brand Reference

> **Last updated:** 2026-05-10
> **Purpose:** Brand identity, product architecture, subscriber tiers, delivery infrastructure, and positioning for all current and planned Atlas Sports AI products.

---

## What Atlas Sports AI Is

Atlas Sports AI is a multi-sport, AI-driven player-prop prediction engine designed for daily fantasy and props platforms — primarily PrizePicks. The core mission is to surface high-confidence, calibrated player prop picks at the right time, in the right format, for subscribers who want a quantitative edge without having to build models themselves.

Atlas is **not** a tipster service. It is a probability pipeline. Every pick is the output of a full decision chain: live data ingestion → injury-adjusted Monte Carlo simulation → May 10 kernel transforms → CatBoost playoff calibration → slip builder optimization. Every probability is tracked, evaluated against truth labels, and continuously improved.

---

## Brand Architecture

```text
Atlas Sports AI
├── Atlas NBA          (Production — live)
├── Atlas MLB          (Development — launching end of 2026 NBA Playoffs)
├── Atlas NFL          (Planned — September 2026 kickoff)
└── Atlas App          (Planned — mobile subscriber interface)
```

---

## Current Product — Atlas NBA

### What Runs Daily

Current Windows automation includes four full live runs plus a graphics/free-pick job:

- **8:00 AM ET** — early full live run
- **11:00 AM ET** — morning full live run
- **2:30 PM ET** — afternoon/evening refresh
- **4:30 PM ET** — free slip / graphics job
- **5:30 PM ET** — evening / playoff-window full live run

Each run ingests the live PrizePicks board, freezes the injury state, scores every available leg through the full probability chain, and produces optimized multi-leg slips. Outputs are published to the Cloudflare dashboard within ~5 minutes of run completion.

### Subscriber Tiers

| Tier | Confidence Range | Brand Voice | Multiplier Target | Volume |
|---|---|---|---|---|
| **GOBLIN** | 77–80% | "Lock Picks / Money Makers" | 3x | 10 picks/day |
| **STANDARD** | 60–65% | "Solid Plays" | 5x | 10 picks/day |
| **DEMON** | 50–55% | "Moon Shots" | 10x | 10 picks/day |

Tiers are determined by calibrated probability (`p_cal`) after the active CatBoost v5cD runtime. The tier labels match PrizePicks multiplier tiers (GOBLIN = highest payout tier, DEMON = speculative).

### Slip Products

| Slip Family | Description | Sorted By |
|---|---|---|
| **System** | Main daily output — beam-search optimized across all legs | `score_adj` (edge × probability) |
| **Windfall** | Hybrid probability + edge blend | `score_adj` variant |
| **DemonHunter** | All-DEMON tier only — highest-multiplier speculative plays | DEMON tier filter |
| **Marketed** | Subscriber-facing product — stat × tier calibration applied | `p_cal_marketed` |

Slips are produced in 3-leg, 4-leg, and 5-leg variants. Win-probability variants (`_winprob.csv`) are also available, sorted by raw hit probability rather than edge.

### Marketed Slip Performance Baseline

Historical v18 marketed baseline (43-slate corpus):

| Slip | Win Rate | EV |
|---|---|---|
| 3-leg | **60.5%** (26/43) | +2.63x |
| 4-leg | **37.2%** (16/43) | +2.72x |
| 5-leg | **20.9%** (9/43) | +3.19x |

Current v5cD 10-date marketed eval:

| Slip | Win Rate | Claimed Hit Prob | Realized EV Mult |
|---|---:|---:|---:|
| 3-leg | 70.0% | 51.2% | 1.3517 |
| 4-leg | 40.0% | 30.0% | 0.7588 |
| 5-leg | 20.0% | 14.9% | 0.4290 |

### Delivery Infrastructure

- **Model outputs:** `data/output/latest/` — CSV slips per family
- **Dashboard API:** Cloudflare Pages — `/data/recommended_latest.json`, `/data/status_latest.json`, `/data/invalidations_latest.json`
- **Graphics team feed:** `daily_top_picks_YYYYMMDD.csv` — 30 picks (10 per tier), delivered after each run
- **Social distribution:** Twitter/X automated posting (active when account credits available)
- **Replay archive:** `data/bundles/` — 47+ dated zip bundles for replay evaluation and corpus expansion

### Data Sources

| Input | Source | Refresh |
|---|---|---|
| PrizePicks board | Live API fetch | Each run |
| NBA game logs | NBA API | Daily (6 AM automation) |
| Injury report | IAEL / Rotowire | Each run |
| Spreads & totals | Rotowire | Each run |
| External priors | BettingPros / OddsAPI | Each run |
| Role metrics | CraftedNBA / DARKO | Pre-fetch cache (9 AM) |

---

## Subscriber Experience (Current)

1. **Morning:** Run fires at 11 AM. Dashboard updates within 5 minutes.
2. **Subscriber opens dashboard** at `atlas-dashboard` (Cloudflare URL) — sees top slips, tier picks, injury flags.
3. **Graphics team** receives `daily_top_picks_YYYYMMDD.csv` and produces social assets.
4. **Social posts** go out after each run (X/Twitter) with pick graphics.
5. **Afternoon/evening runs** refresh the board for late-slate and playoff-window changes.

---

## Model — NBA Current Runtime

| Metric | Value |
|---|---|
| Active calibrator | CatBoost playoff v5cD residual regressor |
| CatBoost features | 19 |
| Training legs | 29,029 across 10 playoff dates |
| Date range | 2026-04-30 → 2026-05-09 |
| Reference replay Brier | 0.179322 vs raw `p_adj` 0.183652 |
| Historical v18 LODO Brier | 0.201529 |
| Historical v18 GBM | Available but disabled |
| Telemetry isotonic | Available but disabled |

See `ai/ATLAS_MODEL_CONTEXT.md` for full model specification.

---

## What Makes Atlas Different

1. **Full probability chain.** Every pick has a traceable path from raw Monte Carlo simulation through kernel transforms and CatBoost calibration. Probability estimates are backed by truth labels.
2. **Daily telemetry feedback loop.** Every run is archived. Eval legs are auto-generated the next morning. The corpus grows every day and the model is periodically retrained on fresh data.
3. **Injury-aware.** The share matrix redistributes production from out players to their teammates — not a static lookup, but a learned weight from historical gamelog patterns.
4. **No stale lines.** The board is ingested at run time, not pre-loaded. IAEL injury state is frozen at the moment of each run, minimizing stale injury information.
5. **Multi-tier slip construction.** Slips are not just "pick the highest probability legs." The beam-search builder penalizes over-concentration on one team or player family, creating diverse, balanced slips.

---

## Brand Visual Language (Graphics Team Reference)

| Tier | Color Theme | Icon | Tagline |
|---|---|---|---|
| GOBLIN | Green | 🔒 | "Lock Pick" / "Money Maker" |
| STANDARD | Blue | 💰 | "Solid Play" |
| DEMON | Red / Orange | 🚀 | "Moon Shot" |

Format per pick:

```text
🔒 GOBLIN LOCK (80.0%)
[Player Name] [Stat] [OVER/UNDER] [Line]
[TEAM] vs [OPP] | [Time] ET
```
