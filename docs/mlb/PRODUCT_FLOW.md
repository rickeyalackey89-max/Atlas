# Atlas MLB Product Flow

Status: product architecture draft  
Last updated: 2026-05-11

## Goal

Build Atlas MLB so it feels operationally consistent with NBA Atlas while using baseball-specific data, features, settlement rules, and model artifacts.

## Target Flow

```text
PrizePicks MLB board
  -> normalize players, teams, markets, lines
  -> ESPN MLB injuries
  -> MLB game logs and minor-league call-up context
  -> external market/stat priors
  -> MLB share matrix
  -> game environment kernel
  -> player prop kernel
  -> CAT/GBM model stack
  -> slip family builder
  -> replay/eval
  -> dashboard and Discord adapters
```

## Keep From NBA Atlas

- PrizePicks fetch discipline:
  - raw snapshot first
  - normalized board second
  - strict player and market naming
  - replayable run manifests
- ESPN game log fetch pattern.
- External adapter pattern.
- CAT/GBM model-family concept.
- Slip family shape so the website can align:
  - standard slips
  - risky slips
  - windfall slips
  - marketed/free/premium presentation surfaces
- Dashboard payload discipline:
  - latest picks
  - status
  - model version
  - run metadata
  - performance sections once eval exists
- Replay-before-live rule.

## Replace For MLB

- NBA model artifacts.
- NBA CatBoost playoff features.
- NBA minutes, role, and injury logic.
- NBA share matrix math.
- NBA settlement rules.
- NBA calibration thresholds.
- NBA-only trainer assumptions.
- NBA hard-coded market aliases.

## PrizePicks MLB Board

Fetch all available MLB projections first. Filtering comes later.

Initial supported board categories:

- pitcher strikeouts
- total bases
- hits + runs + RBIs
- hitter fantasy score
- pitcher fantasy score
- pitching outs
- hits allowed
- hits
- runs
- RBIs
- home runs
- plate appearances
- walks
- stolen bases
- pitches thrown
- earned runs allowed
- walks allowed
- hitter strikeouts
- singles
- doubles
- triples
- pitcher strikeouts combo

## Injuries

Preferred source: ESPN MLB injuries.

Reason:

- team-grouped list
- player status
- estimated return
- current update note
- broader day-to-day and IL coverage than a short transaction-only feed

The injury feed should influence:

- projected lineup certainty
- batting-order confidence
- defensive replacement risk
- pitcher availability
- bullpen fatigue
- call-up likelihood
- DNP/reboot risk

## Game Logs

Major-league and minor-league game logs should use MLB StatsAPI as the canonical
baseball stat source.

Required coverage:

- batter daily game logs
- pitcher daily game logs
- team schedules
- game status
- probable starters when available
- box-score settlement values

StatsAPI endpoints:

- teams by `sportId`
- roster by `teamId`
- schedule by `sportId`
- boxscore by `gamePk`
- player game logs by `personId`, group, and season

## Minor League / Call-Up Layer

MLB needs a second player-history lane for call-ups.

Requirements:

- minor-league roster identity
- affiliated MLB organization
- current level/team
- handedness
- position
- recent batting/pitching stats
- promotion date if available
- MLB roster mapping once called up

This layer should feed a fallback prior when a player has little or no MLB history.

## MLB Share Matrix

The share matrix concept stays, but the NBA implementation does not.

MLB matrix jobs:

- resolve starting lineup probability
- estimate batting-order slot stability
- adjust plate-appearance expectation
- account for platoon risk
- account for injury-driven replacements
- account for pitcher rotation and opener/bulk roles
- account for bullpen availability
- account for defensive substitutions where relevant

## Model Stack

CAT/GBM stays as the family concept, but every artifact and feature must be MLB-native.

Initial split:

- Game environment kernel:
  - park
  - weather
  - starting pitcher
  - bullpen fatigue
  - market total
- Player prop kernel:
  - market-specific player form
  - lineup role
  - handedness matchup
  - pitcher/batter split
  - line movement
  - injury/call-up context

## Filtering Philosophy

Start broad. Score all PrizePicks markets first.

Then filter out:

- unsupported markets
- weakly identified players
- probable DNPs
- unstable combo markets
- props with missing settlement path
- coinflip lines with no modeled edge

## Publishing Gate

MLB publishing stays disabled until:

- raw fetch is stable
- board normalization is stable
- eval can settle at least one full slate
- model artifacts are generated from MLB data only
- dashboard schema is reviewed
- Discord routing is explicitly enabled
