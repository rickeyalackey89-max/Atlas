# MLB Strict Replay Fidelity Contract

Status: binding  
Last updated: 2026-05-23

This contract exists so MLB replay, corpus, CAT, and builder work cannot train
on a replay surface that live would never have seen.

## Definitions

`live` is the production scoring path. It may fetch current PrizePicks, market,
lineup, injury, weather, matchup, and player-history context before scoring.

`replay_single` is one historical live-fidelity replay. It must use a pinned
historical board and date-safe context for that board.

`replay_corpus` is a set of `replay_single` members. It is eligible for CAT,
LODO, or builder training only when every member passed strict preflight and
post-run source-contract checks.

## Non-Negotiable Rule

If a replay date does not have the context live would have consumed, the replay
does not run for model decisions. It is repaired, excluded, or explicitly
converted into a non-training diagnostic.

Do not run corpus, CAT, residual scaling, stacker tests, or builder training on
a failed replay source contract.

## Required Inputs

Each MLB replay date must have:

- One pinned MLB PrizePicks board snapshot or approved GitHub PrizePicks import.
- One date-safe external market context source.
  - BettingPros is preferred when available.
  - OddsAPI, ParlayAPI, DraftKings Pick6, or DraftKings Sportsbook rows are valid
    historical replacements only when normalized for the replay date and clearly
    source-stamped.
  - PrizePicks-only / no-market rows are not a valid substitute for market
    context.
- Any live-enabled supplemental market sources selected for that run, including
  DraftKings Pick6/Sportsbook when the slate timing says those rows should be
  available.
- Date-safe StatsAPI schedule rows.
- Pregame lineup, probable pitcher, bullpen, and environment context from ESPN,
  Rotowire, Baseball Reference reconstructed pregame context, or another
  manifest-backed source.
- Date-safe injury context snapshot.
- Roster identity from either a date-safe roster snapshot or prior-date season
  gamelog identity.
- Player-history context from prior games only.
- Advanced player profile or Baseball Savant context.
- Ballpark profile or static wind-factor context.
- Projection-feature context when a projection-feature CAT is active:
  `projection_mean_from_base`, `projection_delta_from_line`,
  `projection_abs_delta_from_line`, and `projection_line_ratio`.
- Evaluation truth only after scoring. Boxscores and settlement data never feed
  pregame probability scoring.

## Hard Blocks

The strict preflight must fail the date when any of these are true:

- Missing replay board snapshot.
- Missing normalized external market context.
- Missing market source stamp.
- Missing StatsAPI schedule rows.
- Missing pregame lineup/probable pitcher/environment context.
- Missing date-safe injury context snapshot.
- Thin roster identity and thin prior-history identity.
- Missing advanced profile/Savant context.
- Missing both ballpark and wind context.
- Missing projection-feature columns while the active CAT artifact expects them.
- Post-start or postgame context is present in probability inputs.

Historical umpire context is currently a warning, not a hard block, until a true
date-safe umpire source exists.

## Required Manifests

Every replayable run must write:

- `run_manifest.json`
- `source_selection_manifest.json`
- feature/table manifests for board, market, injury, StatsAPI, roster,
  player-history, matchup, advanced context, parameter table, score, slips, and
  replay eval.

`source_selection_manifest.json` is binding. `contract_status: fail` means the
run cannot be used for corpus aggregation, CAT training, residual scaling, or
builder training.

## Required Commands

Before any replay corpus:

```powershell
cd C:\Users\13142\Atlas\MLB
uv run python scripts\mlb\preflight_strict_replay_dates.py --dates 2026-04-26 2026-04-27
```

Only after all requested dates pass:

```powershell
.\scripts\mlb\run_fidelity_replay_sweep.ps1 -OutputDir data\mlb\corpus_replays\<corpus_name>
```

Before CAT:

```powershell
uv run python scripts\mlb\aggregate_fidelity_replay_sweep.py --input-dir data\mlb\corpus_replays\<corpus_name>
```

The CAT trainer also calls `enforce_corpus_source_contracts()` and must stop if
any member has a failed source contract.

## Promotion Criteria

A CAT artifact may be promoted only when:

- The corpus preflight verdict is `PASS`.
- The aggregate source contract verdict is `PASS`.
- Fair LODO brier improves or there is a documented reason to accept a tiny
  regression for material slip-quality improvement.
- Live-fidelity replay does not regress.
- CAT feature coverage is not improved by missing, defaulted, or stale context.

A builder policy may be promoted only after CAT is fixed for the corpus and the
builder trainer uses the selected CAT/LODO probability overlay.
