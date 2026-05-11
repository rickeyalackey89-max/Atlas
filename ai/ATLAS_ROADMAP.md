# Atlas Sports AI — Product Roadmap & Expansion Plan

> **Last updated:** 2026-05-10
> **Status:** NBA in production. MLB in active development. NFL and mobile app planned.

---

## Strategic Overview

Atlas Sports AI is being built in phases, using each sport's launch to fund the next. NBA is the cash cow that pays for baseball infrastructure. Baseball proves the multi-sport engine architecture. NFL adds the highest-volume sport in the US market. The mobile app is the subscriber interface that ties all three together into a single subscription product.

**Guiding principle:** Don't build the next phase until the current phase is stable and generating revenue. No premature abstractions.

---

## Phase Timeline at a Glance

| Phase | Sport | Status | Target Launch |
|---|---|---|---|
| **Phase 1** | NBA | ✅ Production | Live (Feb 2026) |
| **Phase 2** | MLB | 🔧 In development | End of NBA Playoffs (~June 2026) |
| **Phase 3** | NFL | 📋 Planned | August 2026 (preseason) |
| **Phase 4** | Mobile App | 📋 Planned | Q4 2026 |
| **Phase 5** | AI Marketing Shorts | 📋 Planned | Post-MLB launch |

---

## Phase 1 — NBA (Production)

**Status:** Live and generating revenue.

**What runs:**

- Four full daily automated runs (8:00 AM, 11:00 AM, 2:30 PM, 5:30 PM ET) plus a 4:30 PM graphics/free-pick job
- Active CatBoost playoff v5cD calibrator (19 features, 10-date playoff corpus)
- Historical GBM v18 ensemble retained as baseline (33 features, 50-date corpus, LODO Brier 0.201529)
- Three pick tiers: GOBLIN (77–80%), STANDARD (60–65%), DEMON (50–55%)
- Marketed slips: 60.5% 3-leg win rate over 43-slate sample
- Cloudflare dashboard (live), graphics team CSV feed, social posting

**Remaining NBA work before MLB pivot:**

- Revalidate/retrain CatBoost v5cD after additional playoff eval dates are available
- Run DemonHunter and marketed slip trainer sweeps once regular-season 8+ game slates return (post-Finals)
- Consider v19 GBM retrain or a successor CatBoost model once 25–30 playoff dates are in corpus
- Finalize NBA Finals corpus (through ~June 15) as the definitive regular-season + playoffs training set

---

## Phase 2 — MLB (In Development)

**Status:** Architecture underway in `Atlas-Dev` workspace. Target launch: end of NBA Playoffs (approximately June 2026).

### Why MLB

- MLB runs April through October, overlapping minimally with NBA (which ends ~June 15).
- Player props on PrizePicks for MLB are primarily: **hits, strikeouts, total bases, home runs, RBI, walks**.
- These are stat families with strong per-PA (plate appearance) and per-inning (pitcher) base rate structures — a natural fit for the Monte Carlo per-unit-rate approach used in NBA.
- MLB runs **every day** (162-game regular season), meaning higher data volume and more daily slip opportunities than NBA.

### Key Architecture Differences vs NBA

| Aspect | NBA | MLB |
|---|---|---|
| Simulation unit | Per-minute rate | Per plate appearance (hitter) / per batter faced (pitcher) |
| Lineup source | PrizePicks board + Rotowire | Starting lineup confirmation (typically 4–6 hours before first pitch) |
| Injury state | IAEL + Rotowire | MLB injury report + lineup scratch tracking |
| Role context | Share matrix (teammate production shift) | Not applicable — lineup order, not teammate dependency |
| Blowout analog | Score margin → minute risk | Blowout game → fewer PA for backups; not applicable to starters |
| Slate size | 2–14 games | Up to 15 games (full MLB slate) |
| Stat families | Points, reb, ast, 3PM, PRA, etc. | Hits, K, TB, HR, RBI, BB, ERA proxies |

### MLB Development Plan

1. **Data infrastructure** — MLB API gamelog ingestion (batter and pitcher), per-PA/per-batter-faced rate computation, rolling windows
2. **Lineup lock detection** — ingest lineup confirmation (starting batters, starting pitcher). Props not valid if player not in lineup
3. **MC kernel port** — adapt `new_probability.py` for per-PA/per-BF rates. Poisson/binomial sim for discrete counting stats (HR, K)
4. **Matchup features** — pitcher vs batter handedness, park factor (normalized 1.0), weather (wind direction, temperature)
5. **GBM calibrator** — retrain from scratch on MLB data. Do not transfer NBA GBM weights — the feature distributions are fundamentally different
6. **Slip builder** — reuse `slip_builders.py` with MLB-appropriate config. GOBLIN/STANDARD/DEMON tiers apply directly
7. **Cloudflare dashboard** — extend existing dashboard to show sport tab (NBA / MLB)

### MLB Timeline

| Milestone | Target Date |
|---|---|
| MLB gamelog ingestion working | May 2026 |
| MC kernel producing valid MLB probabilities | Late May 2026 |
| First test corpus (30+ dates) | June 2026 |
| GBM trained and calibrated on MLB | June 2026 |
| Live MLB run (internal test) | End of NBA Playoffs (~June 15) |
| Subscriber-facing MLB picks | July 2026 (mid-regular season) |

### MLB Risk Items

- **Lineup lock timing:** MLB lineups are not official until ~3–4 hours before game time. A run that fires before lineup confirmation will have unknown scratch status. Need a late-afternoon run or a lineup-lock check gate.
- **Starting pitcher confirmation:** Some days a team has a scheduled opener or a bullpen day. The prop engine must detect these and suppress pitcher prop legs.
- **Park factor calibration:** Atlas currently has no park factor model. This is a meaningful omission for home run and extra-base hit props.
- **Small corpus bootstrap:** The first MLB GBM will train on a much smaller corpus than NBA v1. Early calibration will be noisy — expect wide confidence intervals until 50+ dates accumulate.

---

## Phase 3 — NFL (Planned)

**Status:** Planned. Target: preseason August 2026, regular season September 2026.

### Why NFL

- NFL is the largest sports betting market in the United States by volume.
- PrizePicks NFL props include: **receiving yards, rushing yards, passing yards, touchdowns, receptions, fantasy score**.
- The per-touch/per-route-run rate structure maps naturally to the Atlas Monte Carlo approach.
- NFL season is September–January, with playoffs through February — minimal overlap with MLB (October–November both active).

### Key Architecture Differences vs NBA / MLB

| Aspect | NBA / MLB | NFL |
|---|---|---|
| Games per slate | 2–15 | 14–16 (regular season Sunday) |
| Simulation unit | Per-minute / per-PA rate | Per snap / per route run / per target |
| Snap count dependency | Not modeled | Critical — a receiver with 80% snap rate vs 40% is fundamentally different |
| Injury timing | Same-day news | Thursday injury report, Friday final injury report, game-day inactives |
| Weather | Not modeled (indoor arenas) | Outdoor game weather (wind > 15 mph, temperature < 32°F) affects pass volume |
| Blowout analog | Score margin → minute risk | Script dependency: team losing → more passing volume, winning → more rushing |
| Game total slate | 8–12 games | Full NFL slate |
| Season length | 82-game (NBA), 162-game (MLB) | 18-game regular season + playoffs |

### NFL Development Plan

1. **Snap count and target data** — not available from standard NBA/MLB sources. Requires Pro Football Reference or NFL Next Gen Stats integration
2. **Weekly schedule cadence** — NFL runs Thursday (TNF), Sunday (full slate), Monday (MNF). Automation must handle a 3-times-per-week cadence with different slate sizes
3. **Injury report integration** — NFL has a formal Wed/Thu/Fri injury report with practice status (Limited, DNP, Full). Must replace IAEL pipeline with NFL-specific injury tracking
4. **Snap dependency kernel** — `role_ctx_mult` analog for NFL: when a starting RB is out, backup receives ~70% of the missing snap share (team-specific, historically calibrated)
5. **Weather gate** — suppress or heavily haircut outdoor passing props when wind > 15 mph
6. **GBM retrain from scratch** — NFL corpus will need a full season (at minimum preseason 2026 + early regular season 2026) before GBM is meaningful. Expect ~10-week ramp-up

### NFL Timeline

| Milestone | Target Date |
|---|---|
| NFL data infrastructure | July 2026 |
| MC kernel adapted for NFL | August 2026 |
| Preseason test runs (internal) | August 2026 |
| Subscriber-facing NFL picks | Week 1 — September 2026 |
| GBM v1 trained on 2026 regular season | November 2026 |
| Full pipeline (GBM + isotonic + slips) | December 2026 |

### NFL Risk Items

- **Snap count data is proprietary.** Pro Football Reference has lagged data (posted after games). Real-time snap counts require NFL Next Gen Stats API (requires licensing) or a scraping solution.
- **Small preseason corpus.** The first NFL runs will use the Monte Carlo kernel without a trained GBM — relying only on base rates and isotonic calibration. This is acceptable for preseason but must be disclosed to subscribers.
- **Thursday / Monday cadence disruption.** The automation jobs are built for daily morning + afternoon runs. NFL TNF and MNF require late-night runs — the scheduler needs modification.

---

## Phase 4 — Mobile App

**Status:** Planned. Target: Q4 2026 (in parallel with NFL regular season).

### What the App Is

A subscriber-facing mobile interface that:

- Shows today's picks across all active sports (NBA / MLB / NFL based on calendar)
- Displays tier (GOBLIN / STANDARD / DEMON), stat, player, line, and probability
- Sends push notifications when a new run completes (current NBA full runs: 8 AM, 11 AM, 2:30 PM, 5:30 PM; NFL nights later)
- Allows subscribers to mark picks as "played" and tracks personal hit rate
- Surfaces the daily marketed slips (3-leg, 4-leg, 5-leg) ready to enter into PrizePicks

### Core Features

| Feature | Priority | Notes |
|---|---|---|
| Today's picks by sport and tier | P0 | Mirror of Cloudflare dashboard |
| Push notifications on run complete | P0 | Replaces needing to check manually |
| Slip view (3/4/5-leg) | P0 | Marketed slip formatted for easy entry |
| Personal hit tracking | P1 | User marks picks as played, app tracks record |
| Historical pick archive | P1 | Scroll back to previous dates |
| Injury flag display | P1 | Show which players are questionable |
| Multi-sport tab switching | P1 | NBA / MLB / NFL tabs, grayed-out when off-season |
| Subscription gate | P0 | Free tier (limited picks) vs paid tier (full access) |

### Tech Stack Options

| Option | Pros | Cons |
|---|---|---|
| React Native | Single codebase iOS + Android | Larger bundle, slower native feel |
| Flutter | Fast, good native feel, growing ecosystem | Dart language, smaller library ecosystem |
| Native (Swift + Kotlin) | Best performance | Two separate codebases |
| PWA (Progressive Web App) | Reuse existing Cloudflare dashboard | Limited push notification support on iOS |

**Recommendation:** React Native first for speed-to-market. The backend API is already Cloudflare-hosted JSON — the app is primarily a consumer of existing endpoints.

### Backend Requirements

- Push notification service (Firebase Cloud Messaging or OneSignal)
- User accounts + subscription state (Stripe billing integration)
- API endpoint: `/api/picks/today?sport=nba` → returns current day's picks in app-ready JSON
- API endpoint: `/api/slips/today?sport=nba&legs=3` → returns marketed 3-leg slip
- API endpoint: `/api/user/history` → returns user's personal pick log

---

## Phase 5 — AI Marketing Shorts

**Status:** Planned. Begins after MLB launch.

### What They Are

Short-form video content (30–60 seconds) for TikTok, Instagram Reels, and YouTube Shorts, generated using AI tools, featuring Atlas picks. The goal is to drive subscriber growth organically through daily pick content.

### Content Format

Each short follows the same template:

1. **Hook (0–3s):** "Atlas AI found a GOBLIN pick for tonight."
2. **Pick reveal (3–15s):** Player, stat, line, probability, tier graphic
3. **Model credibility (15–25s):** Brief stat — use the current v5cD eval or the historical v18 43-slate stat depending on the campaign claim.
4. **CTA (25–30s):** "Link in bio — get today's picks"

### Production Tools (Planned)

- **Script generation:** GPT-4o / Claude — auto-generate commentary from pick data
- **Voice:** ElevenLabs or similar TTS with a branded voice
- **Video assembly:** Remotion (React-based video rendering) or CapCut API
- **Graphics layer:** Existing tier graphics (GOBLIN/STANDARD/DEMON) embedded in video
- **Scheduling:** Auto-post after selected live runs via social APIs

### Distribution Targets

| Platform | Format | Frequency |
|---|---|---|
| TikTok | 30–60s vertical | 2x daily (post-run) |
| Instagram Reels | 30–60s vertical | 2x daily |
| YouTube Shorts | 60s max | 1x daily (morning run only) |
| X (Twitter) | Video card + text | 2x daily (already partially live) |

### Dependency

AI marketing shorts require:

- MLB model live (demonstrates multi-sport, creates more content per day)
- A stable pick graphic template (already exists from GRAPHICS_TEAM_README)
- At minimum one social API integration active (X is partially built)

---

## Multi-Sport Calendar

The following shows active Atlas products by month:

| Month | NBA | MLB | NFL | App |
|---|---|---|---|---|
| May 2026 | ✅ Playoffs | – | – | – |
| June 2026 | ✅ Finals | 🔧 Launch | – | – |
| July 2026 | – | ✅ Active | – | – |
| August 2026 | – | ✅ Active | 🔧 Preseason | – |
| September 2026 | – | ✅ Active | ✅ Active | 🔧 Build |
| October 2026 | – | ✅ Playoffs | ✅ Active | 🔧 Build |
| November 2026 | – | – | ✅ Active | ✅ Launch |
| December 2026 | – | – | ✅ Active | ✅ Active |
| January 2027 | 🔧 Retrain | – | ✅ Playoffs | ✅ Active |
| February 2027 | ✅ Active | – | ✅ Super Bowl | ✅ Active |

---

## Key Dependencies & Risks

| Risk | Severity | Mitigation |
|---|---|---|
| MLB lineup lock timing | High | Late-afternoon run cadence; lineup-lock gate before slip publish |
| NFL snap data licensing | High | Evaluate Pro Football Reference, ESPN, Next Gen Stats; build scraper fallback |
| Mobile app store approval | Medium | Start Apple App Store review process 6–8 weeks before target date |
| GBM cold start (MLB/NFL) | Medium | Use isotonic-only calibration while corpus grows; disclose to subscribers |
| Social API rate limits / credits | Low | Twitter 402 is known; backup to manual posting if credits deplete |
| Cross-sport subscriber confusion | Low | Clear sport-tab UI in app; email segmentation by active sport |

---

## Guiding Constraints

1. **Do not build NFL until MLB is live and stable.** Two in-development models simultaneously creates debt.
2. **Do not migrate NBA to new architecture to accommodate MLB/NFL.** Keep NBA on its own module. Multi-sport is additive, not a refactor.
3. **Production NBA system is untouched during development.** `Atlas-Dev` workspace is the sandbox. Promotions to production require explicit sign-off.
4. **Each sport needs its own GBM trained on sport-specific data.** There is no universal sports model. Feature engineering is sport-specific.
5. **Subscribers must always know which sport a pick is for.** No ambiguous "today's picks" without sport context.
