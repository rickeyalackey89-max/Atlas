# MLB Baseball Context Codex Brief

Last updated: 2026-05-22

This is the implementation contract for the passive MLB baseball-context layer.
The source brief lives in `MLB_info_DO_NOT_DELETE/MLB_BASEBALL_CONTEXT_CODEX_IMPLEMENTATION_BRIEF.md`.

## Operating Rule

The layer is baseball-first and passive:

- Do not change `p_cal`, `model_probability`, or promoted CAT artifacts.
- Do not retrain from these tags alone.
- Do not fake missing lineup, pitcher, weather, park, or matchup data.
- Do write tags, gates, context packets, and audit artifacts for live and replay.

## Evaluation Order

MLB legs should be reviewed in this order:

1. Opportunity: confirmed lineup, batting order, plate appearances, confirmed starter, workload.
2. Matchup: hitter/pitcher profile, handedness, contact, strikeout, walk, power, bullpen.
3. Environment: ballpark, weather, wind, roof, umpire, run environment.
4. Prop volatility: hits, total bases, home runs, RBI, runs, walks, pitcher strikeouts, pitcher outs.
5. Slip fit: same game script conflicts, clustered risk, high-variance anchor risk.

## Passive Artifacts

Every MLB run that builds slips should write:

- `mlb_scored_legs_context.csv`
- `mlb_publication_gate_report.json`
- `mlb_pick_context_packets.json`

The latest passive copies are mirrored under:

- `data/mlb/output/context/latest_mlb_scored_legs_context.csv`
- `data/mlb/output/context/latest_mlb_publication_gate_report.json`
- `data/mlb/output/context/latest_mlb_pick_context_packets.json`

## Gate Meanings

- `ok`: context supports the leg.
- `caution`: context exists but contains baseball risk that should be considered before public use.
- `suppress`: required baseball context is missing or the leg has a hard publication blocker.

Current suppress reasons:

- incomplete player/stat/line/side identity
- unknown hitter lineup for hitter props
- unknown starter status for pitcher props
- weather delay risk on pitcher workload props

Current caution reasons:

- projected lineup
- bottom-order volume risk
- high-variance over
- line-only market context
- missing matchup or weather context
- hostile power environment
- feature context missing

## Strict Fidelity

Replay and live must generate these artifacts from the same scored-leg and
feature-table contracts. A corpus is not valid for future CAT or builder work if
these passive artifacts reveal missing baseball context that live would have had.

