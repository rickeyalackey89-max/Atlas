# Atlas MLB Replay Fidelity Rule

Status: binding rule  
Last updated: 2026-05-21

This document is backed by the machine-readable replay contract at
`C:\Users\13142\Atlas\MLB\config\replay_fidelity_contract.yaml` and the
workspace operating memory at `C:\Users\13142\Atlas\ATLAS_OPERATING_MEMORY.md`.

## Rule

Atlas MLB replays are strict-fidelity replays.

Replay inputs must match the artifacts and source-selection rules the live
model would have consumed for that run. A replay may not feed probability
scoring with post-date context, invented fallbacks, manually completed future
knowledge, settlement data, or replay-only model inputs.

This rule applies before calibration, kernels, caches, corpus construction,
trainer inputs, and dashboard comparisons.

If replay fidelity fails, stop before scoring/training decisions. Do not run
corpus, LODO, CAT, or builder training on a failed replay source contract.

## Run Surfaces

There are three canonical run surfaces:

- `live`: same-day probability scoring and operator review.
- `replay_single`: one historical live-fidelity replay.
- `replay_corpus`: many `replay_single` members aggregated for calibration,
  cache, corpus, holdout, or trainer work.

Compatibility aliases may exist at the CLI boundary, but manifests must use the
canonical names above.

Run outputs are physically separated:

- `data/mlb/live_runs/<run_id>/` is reserved for actual live model runs.
- `data/mlb/replay_runs/<run_id>/` is used for single replay, corpus replay,
  and replay sweep run artifacts.
- `data/mlb/test_runs/<run_id>/` is a legacy/read-only compatibility root and
  must not be used for new replay output.

## Source Timing

Replay model inputs must be date-safe:

- use the exact source snapshot from the historical run when available
- otherwise use a source snapshot whose declared snapshot date is on or before
  the replay date
- record missing context when no date-safe source exists
- do not substitute a later full-slate source into probability scoring
- live runs refresh same-day source context before scoring; replay consumes those
  captured manifests later and does not become a separate source path
- market context source selection uses actual row `game_date`, not folder
  timestamp text
- market context must be passed an explicit selected-source directory list.
  Live and replay both use the same contract: one primary BettingPros source
  plus any enabled supplemental market sources that were selected for the run.
  Replay must not silently scan every staged market folder for the date.
- DraftKings Pick6/Sportsbook MLB props are timing-sensitive supplemental
  sources. Hitter strikeouts, walks, and pitches-thrown markets may not populate
  until lineups/rotation context is firm. The run manifest records
  `draftkings_timing_policy` with one target window per game. A missing DK
  supplemental source is `contract_status: timing_pending` only when every
  unstarted game is still before its own one-hour-before-first-pitch target.
  Once any game is inside its target window, missing DK context is a source
  contract failure for that ready portion of the slate.

Settlement data, boxscores, and final outcomes belong only to eval artifacts
after scoring is complete.

## Manifest Requirements

Every replayable run must carry:

- `run_mode`
- `replay_type`
- `fidelity_policy`
- source paths for normalized board, feature context, parameters, score, and
  simulation artifacts
- source-selection metadata for each context layer that chooses staged source
  snapshots
- explicit coverage and missing-context counts
- `source_selection_manifest.json`, also embedded under `run_manifest.json`
  as `source_selection`

Every context feature must write its own manifest and the run manifest must
reference those child manifests or their JSON paths.

`source_selection_manifest.json` is the live/replay parity contract. It records
the configured primary market source, enabled supplemental sources, selected
source dirs, timing classification, lineup/weather/roster/history/advanced/
injury sources, source completeness, and any fidelity warnings. If a live-enabled
source such as DraftKings Pick6 or DraftKings Sportsbook is missing from replay,
the manifest uses `contract_status: fail` instead of allowing a silent omission.

Every replayable tool must also write or consume a manifest. If a live tool
depends on an external service, replay must either read the captured manifest or
emit an explicitly flagged fallback record. PrizePicks payout quoting follows
this rule through `slips/payout_quote_manifest.json`.

## Kernel Rule

Kernel, parameter, calibration, and simulation versions are part of replay
identity. Corpus replays must not mix kernel changes without a new corpus
manifest or versioned experiment label.
