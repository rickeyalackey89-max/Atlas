# WNBA Codex Prime

Status: **ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before execution, the Prime mirror must be a valid clean Git worktree on branch `main` and fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, read and obey WNBA `AGENTS.md` and all current target-repo governing controls.

Prime coordinates scope; it does not replace target-repo authority.

The WNBA Builder lane remains paused at:

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`

Do not advance, repair, reinterpret, grade, or consume Builder outcomes during this operational task.

## Validation doctrine

Operational Live-run eval creation is not automatically Builder development, protected validation, or lockbox evidence.

Public/live slips are never scientific validation authority.

Builder validation reads must remain `0` and lockbox reads must remain `0`.

## Git / workspace contract

Use only canonical WNBA root `C:\Users\13142\Atlas\WNBA` and its workspace guard.

If no tracked source/control change is required, do not invent a WNBA commit.

Never broad-stage, use destructive Git commands, or alter the protected stash.

## Accepted 4L R2 state

WNBA commit:

`fd0df85a70559d830cd2ae5e76a711453a9f4dca`

Accepted result:

- disposition `UNIFORM_23_DATE_STATEFUL_4L_SURFACE_R2_PASS`;
- 23 structurally eligible 3+ game dates;
- 2,208 candidates = 96/date;
- all four R1 canary identity/order/scorer hashes reproduced;
- pretruth seal `UNIFORM_OUTCOME_BLIND_23_DATE_4L_SURFACE_SEALED`;
- target outcome reads 0;
- validation reads 0;
- lockbox reads 0;
- no grading/fitting/tuning/freeze/promotion authority.

All sealed R2 files must remain byte/hash unchanged.

## Last completed operational delegation

Task:

`docs/coordination/wnba/codex/archive/2026-08-17_wnba_eval_catchup_20260813_20260816.md`

Prime start:

`cbbe0c5f00d7a478f4d54908c913afc0f188a196`

Result:

The canonical scheduled wrapper was attempted once for each date `2026-08-13` through `2026-08-16` in chronological order and failed closed overall.

Exact result anatomy:

- `2026-08-13`: strict truth merged; scheduled games present; prior-day eval `skipped_missing_scored_run`, 0 runs; maintenance not reached.
- `2026-08-14`: prior-day eval `complete`, 2 runs; waterfall completed but consumer performance unavailable; 4 hard alerts.
- `2026-08-15`: prior-day eval `complete`, 1 run; waterfall completed but consumer performance unavailable; 2 hard alerts.
- `2026-08-16`: strict truth merged; scheduled games present; prior-day eval `skipped_missing_scored_run`, 0 runs; maintenance not reached.

Accepted Chat interpretation:

- Aug. 14 and Aug. 15 core evals are complete and must not be rerun in the active task.
- Aug. 13 and Aug. 16 scored Live-run directories exist; the scheduled wrapper called canonical prior-day eval with `--published-only`, so `skipped_missing_scored_run` means no scored run survived the publication filter, not necessarily no scored run exists.
- Consumer-performance hard alerts on Aug. 14/Aug. 15 are a separate maintenance issue and do not invalidate their completed core evals.
- Builder R2 remained unchanged and no newly settled outcome was consumed for Builder research.

## Active user-authorized task

Execution class: **OPERATIONAL_EVAL_RECOVERY**

Read and execute exactly:

`docs/coordination/wnba/codex/archive/2026-08-17_wnba_eval_completion_unpublished_live_runs_20260813_20260816.md`

Work-order publication commit:

`5542d44726f03168acbb7ee1b6844d9e6e28d83c`

Expected WNBA HEAD:

`fd0df85a70559d830cd2ae5e76a711453a9f4dca`

Purpose:

**Complete only the unresolved Aug. 13 and Aug. 16 core prior-day evals by evaluating existing matching scored Live runs without the scheduled wrapper's `--published-only` filter.**

Run exactly once:

```powershell
uv run python -m wnba.testing_cli eval prior-day --date 2026-08-13 --all-matching-runs --data-root data\wnba
uv run python -m wnba.testing_cli eval prior-day --date 2026-08-16 --all-matching-runs --data-root data\wnba
```

Critical constraints:

- do **not** pass `--published-only`;
- do not rerun Aug. 14 or Aug. 15;
- do not rerun `scripts/run_prior_day_eval.ps1`;
- use existing successfully merged canonical truth;
- report exact evaluated run ids and each run's actual `runtime_publication.published` value;
- never alter publication flags;
- label evaluated unpublished runs `NONPUBLIC_LIVE_RUN_EVAL_OPERATIONAL_TRUTH_ONLY` in the final report;
- do not run waterfall/public-performance/rolling-corpus/maintenance recovery in this task;
- preserve all sealed 4L R2 bytes/hashes;
- preserve Builder stop;
- no Builder grading, learner fitting, FromDeep, Live/model mutation, validation, lockbox, or follow-on auto-start.

Success requires both Aug. 13 and Aug. 16 `prior_day_eval_manifest.json` files to be `complete` with `run_count >= 1`.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_EVAL_COMPLETION_20260813_20260816`

## Next after success — NOT AUTHORIZED

Two separate future choices remain:

1. operationally repair Aug. 14/Aug. 15 consumer-performance hard alerts if desired;
2. separately authorize Builder grading of the accepted sealed 4L R2 surface.

Neither is authorized by this task.
