# Future Chat Reference

Date: 2026-03-24
Repo: Atlas

## Purpose

This file is the working reference for future chats in this repo.

It exists to prevent broad, unapproved behavior changes during debugging or tuning work.

## Non-Negotiable Working Rules

1. Do not make broad optimizer or model behavior changes without explicit user approval.
2. Prefer the smallest possible fix first.
3. If a change affects live selection behavior, replay recommendations, slip counts, beam search, exposure rules, ranking, or probability routing, stop and explain the proposed change before editing code.
4. Config-only tuning can be proposed, but it still requires explicit approval when it changes selection behavior or runtime materially.
5. Do not silently rely on fallback defaults for important runtime behavior when the intended value is known.
6. Verify changes with a focused check before claiming the issue is fixed.
7. If replay and live behavior diverge, say so clearly.
8. If a run completes but recommendations drift, do not describe that as fully fixed.

## What To Do

1. Isolate root cause before changing multiple knobs.
2. Prefer targeted fixes over structural rewrites.
3. Use replay to validate optimizer changes before claiming live safety.
4. Keep slip count explicit in config when the intended target is known.
5. State tradeoffs before changing beam width, beam window, target pool, ranking, role-aware ordering, or fallback behavior.
6. When proposing a tuning change, include:
   - exact parameter change
   - expected runtime effect
   - expected selection effect
   - rollback path
7. Distinguish between:
   - operational success: the run finishes
   - behavioral equivalence: recommendations remain materially aligned
8. Preserve existing semantics unless the user explicitly approves a behavior change.

## What Not To Do

1. Do not widen search, alter ranking, or add fallback selection logic without approval.
2. Do not treat an emergency runtime fix as permission to change optimizer behavior globally.
3. Do not assume a missing config value means the fallback is desired.
4. Do not report replay as fully fixed if the recommendation set materially changed.
5. Do not change multiple optimizer knobs at once unless the user explicitly asks for a larger tuning pass.
6. Do not hide impactful edits inside a bug-fix response.
7. Do not describe a behavior-changing edit as a harmless performance fix.

## Approved Current State

These are the changes currently accepted as of this document.

1. `optimizer.top_n_slips` is explicitly set to `10` in `config.yaml`.
2. Engine fallback default for `top_n_slips` is `10` in:
   - `src/Atlas/engine/main.py`
   - `src/Atlas/engine/new_engine.py`
3. `slip_build.beam_width` is set to `250` in `config.yaml`.

## Current Behavior-Changing Optimizer Edits Still Present

These remain in place and can affect replay/live recommendations.

1. Beam window defaults in `src/Atlas/core/slip_builders.py` were decoupled from `target_pool_mult`.
   - Intent: reduce runtime blow-up.
   - Effect: different candidate coverage from the prior tied-window behavior.

2. Greedy top-off fallback in `src/Atlas/core/slip_builders.py` was added after beam stall.
   - Intent: avoid incomplete-portfolio failure under exposure caps.
   - Effect: portfolio composition can change in edge cases instead of throwing.

## Verified State As Of 2026-03-24

1. Live slip target is back to `10`.
2. Replay run completes successfully.
3. Replay `scored_legs_deduped.csv` row count matched the prior comparison run: `4469`.
4. Recommendation files changed materially versus the prior replay comparison run.
5. Recommendation row counts changed from `25` to `10` because the intended slip target was restored.
6. Recommendation content also changed beyond simple truncation, so replay is operationally fixed but not behavior-identical.

## Safe Change Protocol For Future Chats

When the user reports runtime, replay, or recommendation issues:

1. Confirm the exact symptom.
2. Identify whether the issue is:
   - crash
   - slowdown
   - config drift
   - recommendation drift
   - replay/live mismatch
3. Inspect current config and active defaults before changing code.
4. If the likely fix changes behavior, present the proposed edit first.
5. After approval, make only the approved edit.
6. Validate with the smallest relevant test or replay.
7. Report separately:
   - what now works
   - what still differs

## Commands And Checks That Were Useful

1. Focused tests:
   - `run-focused-python-tests`
2. Replay check:
   - `replay-bundle-under-relief`
3. Inspect active diff:
   - `git diff -- config.yaml src/Atlas/core/slip_builders.py src/Atlas/engine/main.py src/Atlas/engine/new_engine.py`

## Immediate Next-Step Reminder

Before making any further optimizer edits, explicitly confirm with the user whether they want:

1. behavior preservation first
2. runtime tuning first
3. replay recommendation alignment first

Do not assume these are the same goal.