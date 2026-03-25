# Replay and Backtest Evaluation Plan

This document defines the evaluation ladder for the current Atlas model work.

The short version:
- **Replay** verifies historical fidelity for one slate at a time.
- **Backtest** runs many replays and writes the artifacts that the reader consumes.
- **Reader** judges the corpus and tells us whether the candidate is actually better.

## Why this matters

The allocator is now fresh and the share matrix is aligned. That means the next improvement cycle should focus less on structural repair and more on evaluation discipline.

If we do not separate replay from backtest, we will mix two different jobs:
- replay answers: “Did we reconstruct this one run correctly?”
- backtest answers: “Does this candidate improve across a corpus?”

## 1) Replay

Replay is a strict historical reconstruction.

Replay should:
- use pinned raw PrizePicks JSON
- use pinned injury artifacts for that run
- use pinned Rotowire lines for that run
- rebuild `today.csv` from the raw payload
- fail closed if a required artifact is missing

Replay should not:
- fetch fresh live Rotowire lines
- fall back to the live injury dashboard
- use a current-time filter that changes the historical slate

### Replay success criteria

Replay is successful if the run:
- reproduces the intended slate inputs
- writes the expected outputs without drift
- preserves the injury and matchup context that existed at that time

## 2) Backtest

Backtest is a multi-replay harness.

Backtest should:
- run a fixed set of replay slates
- emit the run folders and evaluation artifacts the reader needs
- keep the corpus stable while we compare candidates

Backtest is not the place to chase live freshness. It is the place to compare model candidates under the same historical conditions.

### Backtest output contract

Each replay in the corpus should produce, at minimum:
- `scored_legs.csv`
- `scored_legs_deduped.csv`
- `recommended_3leg.csv`
- `recommended_4leg.csv`
- `recommended_5leg.csv`
- the matching `_winprob.csv` files when available
- `eval_legs.csv` when the corpus needs reader-grade outcome scoring
- `meta.json` or equivalent run metadata when available

The corpus directory should then be passed to the reader.

## 3) Reader

The reader is the decision layer.

It should compare control vs challenger corpora and answer:
- did calibration improve?
- did slip quality improve?
- did the model regress on protected slices?
- is the change broad enough to promote?

Current reader behavior already expects historical run artifacts and skips incomplete runs rather than hard-failing.

## 4) Proposed evaluation corpus

Use a small but deliberate corpus first.

Recommended slices:
1. **Injury-heavy slates**
- slates with visible OUT / DOUBTFUL redistribution pressure

2. **Questionable-heavy slates**
- slates where soft-risk visibility matters and the allocator must not overreact

3. **Deep-team slates**
- teams with enough depth that redistribution should stay modest

4. **Role-sensitive slates**
- slates where the role context genuinely changes beneficiary behavior

5. **Under-heavy slates**
- slates that historically exposed under-relief or directional bias problems

6. **Mixed stat-family slates**
- slates covering `PTS`, `PR`, `PRA`, `RA`, `REB`, `PA`, `AST`, `FG3M`

### Corpus size guidance

Start with a tight corpus:
- 1 representative replay for a smoke test
- 3 to 5 slates for a first candidate check
- 10 to 20 slates for a meaningful A/B comparison

Do not jump straight to a huge corpus before the candidate survives the small one.

## 5) Metrics to track

Track metrics at two levels: corpus-wide and slice-level.

### Corpus-wide metrics

- Brier score
- log loss
- hit rate by leg count
- average expected value distribution
- payout alignment versus realized outcomes

### Slice-level metrics

- under-heavy slice performance
- injury-heavy slice performance
- role-sensitive slice performance
- questionable-player handling
- deep-team redistribution stability

### Guardrail metrics

- false positive rate on soft-risk signals
- overreaction to minor injuries
- slip concentration on fragile legs
- regression on protected benchmark slices

## 6) Comparison order

Use this sequence:

1. **Single replay smoke test**
- confirm the strict replay contract works on one slate

2. **Small backtest A/B**
- compare control and candidate on 3 to 5 slates

3. **Reader pass**
- verify whether the candidate actually improves the corpus view

4. **Wider corpus**
- only after the small corpus is clean

5. **Promote or reject**
- promote only if the reader shows broad enough improvement without meaningful regressions

## 7) What we should change next

The next work should be evaluation-first, not more allocator surgery.

Priority order:
1. Build the replay corpus from pinned artifacts.
2. Run the backtest on that corpus.
3. Feed the resulting run folders to the reader.
4. Compare baseline versus candidate using the same corpus.
5. Only then decide whether the model change is worth promoting.

## 8) Practical next step

The immediate next step is to pick a small, named corpus and run one control-versus-candidate comparison on it.

That gives us a real answer on whether the fresh allocator and aligned share matrix are improving the model, or just changing where the risk lands.

## 9) Existing corpus sources in this workspace

There are already replay/backtest corpora available in the workspace that can serve as the starting point for comparison:

- `outputtelem/telemetry_ab_control/runs/20260312_070945/`
- `outputtelem/backtest_promote_20260320_1/runs/20260320_172445/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_173824/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_173943/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_174212/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_174415/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_174658/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_174918/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_175112/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_175332/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_175544/`
- `outputtelem/backtest_promote_20260320_last10/runs/20260320_175810/`

Recommended first corpus choice:
- use `outputtelem/backtest_promote_20260320_last10/` as the small multi-replay comparison set
- use `outputtelem/telemetry_ab_control/` as the baseline control anchor when needed

This keeps the first comparison bounded and uses data the reader already knows how to consume.