# MLB Strict Replay Workflow

Status: binding workflow  
Last updated: 2026-05-21

This is the working order for MLB model work. The order matters.

## Order Of Operations

1. Run strict preflight for the target replay dates.
2. Repair or exclude failed dates.
3. Run the replay corpus only after preflight passes.
4. Aggregate the corpus and check source contracts.
5. Run CAT/LODO on the passed corpus.
6. Tune residual scales only against the selected CAT artifact.
7. Run builder training with the selected CAT/LODO probability overlay.
8. Promote only after brier, hit-rate, and source-contract evidence agree.

## Single Replay

A single replay is valid only when it uses one historical board date and pinned
context. It is useful for debugging live parity, but it is not a training corpus.

Single replay checks:

- One game date only.
- No started game leakage.
- No next-day slate leakage.
- Source manifest is present.
- Source manifest is not `contract_status: fail`.
- Scored output and eval output exist.
- Context coverage matches the active live contract.

## Corpus Replay

A corpus replay is a collection of valid single replays. It is the only replay
surface that may feed CAT/LODO or builder training.

Corpus checks:

- Every member date passed `scripts/mlb/preflight_strict_replay_dates.py`.
- Every member has source-stamped external market rows for its board date.
- Every member wrote a run JSON and eval JSON.
- Every member source contract passed aggregation.
- Aggregate context coverage is reviewed before CAT.
- No CAT trainer starts until the aggregate is clean.

## Fast Failure Rule

If a preflight failure appears, stop. Do not start the expensive replay and hope
the aggregate fixes it later.

If an aggregate failure appears, stop. Do not start CAT and treat the number as
usable.

If CAT improves brier on a broken corpus, the improvement is invalid.

## Current Expected MLB Corpus Window

The active working window is:

```text
2026-04-26 through 2026-05-20
```

Dates may be excluded only when strict preflight proves the required artifacts
do not exist or the date has no usable settlement truth.

## Tail/Background Convention

Long jobs should write a log file and can be run in a separate PowerShell
window. The visible tail should show:

- corpus directory
- output directory
- date currently running
- run/eval completion
- failures immediately when they happen
- final aggregate brier/logloss and context coverage

## Required Artifacts From A Clean Corpus

The corpus directory must contain:

- `replay_single_*.run.json`
- `replay_single_*.eval.json`
- `aggregate_summary.json`
- `aggregate_members.csv`
- `slip_builder_family_summary.csv` or equivalent slip aggregate
- `progress.jsonl`

Each run referenced by the corpus must also exist under:

```text
data/mlb/replay_runs/<run_id>/
data/mlb/eval/<run_id>/
```

## CAT And Builder Handoff

CAT training produces:

- `best_config.json`
- `lodo_predictions.csv`
- `training_corpus.csv`
- `sweep_results.csv`
- trainer metadata with fair LODO metrics

Builder training consumes the selected CAT/LODO output through
`--probability-overlay-csv` when comparing slip policies. This prevents the
builder from learning against stale runtime probabilities after CAT changes.
