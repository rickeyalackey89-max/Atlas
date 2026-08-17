# WNBA Eval Completion — Existing Scored Live Runs — 2026-08-13 and 2026-08-16

Status: **USER AUTHORIZED**

Execution class: **OPERATIONAL_EVAL_RECOVERY**

User authorization date: `2026-08-17`

## Purpose

Complete the two genuinely unresolved WNBA prior-day eval dates, `2026-08-13` and `2026-08-16`, by evaluating the existing matching scored Live runs even when those runs do not carry `runtime_publication.published=true`.

This task exists because the prior four-date scheduled-wrapper catch-up established two different states:

- `2026-08-14`: prior-day eval `complete`, 2 runs. Do **not** rerun.
- `2026-08-15`: prior-day eval `complete`, 1 run. Do **not** rerun.
- `2026-08-13`: truth merged, scheduled games present, prior-day eval `skipped_missing_scored_run`, 0 runs under the wrapper's `--published-only` filter even though scored Live-run directories exist.
- `2026-08-16`: truth merged, scheduled games present, prior-day eval `skipped_missing_scored_run`, 0 runs under the wrapper's `--published-only` filter even though scored Live-run directories exist.

The canonical evaluator's run resolver filters scored runs through `runtime_publication.published` only when `published_only=true`. Therefore `skipped_missing_scored_run` under the scheduled wrapper does not prove that no scored run exists.

## Authority and starting state

Parent Prime expected start:

`cbbe0c5f00d7a478f4d54908c913afc0f188a196`

Target repository:

`rickeyalackey89-max/Atlas-WNBA`

Branch:

`builder-method-contract-v1`

Expected WNBA HEAD:

`fd0df85a70559d830cd2ae5e76a711453a9f4dca`

Builder review stop that must remain unchanged:

`BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`

Accepted sealed 4L R2 surface:

- commit `fd0df85a70559d830cd2ae5e76a711453a9f4dca`;
- 23 eligible dates;
- 2,208 candidates;
- pretruth seal `UNIFORM_OUTCOME_BLIND_23_DATE_4L_SURFACE_SEALED`;
- all sealed R2 files must remain byte/hash unchanged.

## Canonical execution path

Use the existing repository evaluator through `wnba.testing_cli`.

Run exactly once for `2026-08-13`:

```powershell
uv run python -m wnba.testing_cli eval prior-day --date 2026-08-13 --all-matching-runs --data-root data\wnba
```

Run exactly once for `2026-08-16`:

```powershell
uv run python -m wnba.testing_cli eval prior-day --date 2026-08-16 --all-matching-runs --data-root data\wnba
```

**Do not pass `--published-only`.**

Do not run the full scheduled wrapper again in this task. Strict ESPN truth for both dates already merged successfully in the immediately preceding catch-up attempt.

If the existing canonical truth store required by the evaluator is absent or invalid despite that prior successful truth merge, stop fail-closed and report the blocker rather than inventing a new truth source.

## Required pre-execution checks

1. Sync Prime cleanly.
2. Confirm canonical WNBA repository root and sentinel using target-repo authority.
3. Confirm WNBA HEAD remains `fd0df85a70559d830cd2ae5e76a711453a9f4dca` unless an unrelated authorized change occurred before task start; otherwise stop and report authority drift.
4. Confirm the active Builder lane remains at `BLOCKED_USER_REVIEW_WNBA_4L_UNIFORM_STATEFUL_SURFACE_R2`.
5. Hash/verify the sealed R2 artifact set before execution.
6. Inventory matching `data/wnba/live_runs/live_20260813*` and `live_20260816*` scored-run directories outcome-blind with respect to Builder research. For each candidate run, record:
   - run id;
   - scored legs path present;
   - row count for target date;
   - `runtime_publication.published` value from `run_manifest.json`;
   - whether canonical evaluator should include it when `published_only=false`.

This inventory is operational provenance only. Do not grade slips or inspect 4L outcomes.

## Required success criteria

For both `2026-08-13` and `2026-08-16`:

- `data/wnba/eval/live_prior_day/<date>/prior_day_eval_manifest.json` status is `complete`;
- `run_count >= 1`;
- every run included by the canonical resolver is recorded by exact run id;
- each evaluated run's actual `runtime_publication.published` status is reported unchanged;
- eval artifacts are produced by the canonical evaluator;
- no publication flag is added, removed, or altered;
- no Live source/model/Builder artifact is changed;
- no scheduled waterfall, public-performance refresh, rolling-corpus append, or maintenance pipeline is required in this task.

If an unpublished run is evaluated, label it in the final report as:

`NONPUBLIC_LIVE_RUN_EVAL_OPERATIONAL_TRUTH_ONLY`

That label means the eval is valid operational settlement of an existing scored Live run but does **not** create public-publication authority, promotion authority, protected-validation authority, or lockbox authority.

## Explicit prohibitions

Do **not**:

- rerun `2026-08-14`;
- rerun `2026-08-15`;
- use `scripts/run_prior_day_eval.ps1` in this task;
- pass `--published-only`;
- modify any `runtime_publication.published` field;
- rename or copy a run to make it appear published;
- mutate Live/model/minutes/allocator/calibration/QMC/dependence;
- mutate Builder method, control, scoring, candidate generation, or R2 artifacts;
- grade the sealed R2 4L candidate surface;
- inspect selected 4L wins/losses for research;
- fit or tune any Builder learner;
- run FromDeep;
- open protected validation or lockbox;
- decide whether 8/13–8/16 qualify as future protected evidence;
- repair the Builder Prime-hash mismatch created by changing `CODEX_PRIME.md`;
- start consumer-performance/maintenance repair;
- auto-start the next Builder forensic.

## Evidence-use boundary

Operational settlement is authorized.

Builder research consumption of the newly produced Aug. 13/Aug. 16 outcomes is **not** authorized by this task.

The new eval files may exist normally in the operational eval store while the Builder remains frozen at its review stop.

## Git contract

Operational eval data are expected to remain repo-local data artifacts and may require no source commit.

If no authorized tracked source/control change is necessary, do not invent a WNBA commit.

If an unexpected tracked-file mutation appears, classify it and stop rather than broad-stage it.

Never use broad staging or destructive Git commands. Preserve the protected stash unchanged.

## Required final report

Report:

### Aug. 13
- evaluator command exit code;
- prior-day eval status;
- run count;
- exact evaluated run ids;
- publication status of each run;
- eval manifest path;
- whether all included scored rows for the target date were evaluated.

### Aug. 16
Same fields.

Then report:

- Aug. 14 remains previously complete with 2 runs and was not rerun;
- Aug. 15 remains previously complete with 1 run and was not rerun;
- all four dates now have complete core prior-day evals: true/false;
- WNBA HEAD/tracking/direct remote equality;
- WNBA/Prime worktree cleanliness;
- protected stash unchanged;
- sealed R2 artifact hashes unchanged;
- Builder stop unchanged;
- Builder validation reads = 0;
- Builder lockbox reads = 0;
- newly settled outcomes used for Builder research = false.

## Required final stop

`BLOCKED_USER_REVIEW_WNBA_EVAL_COMPLETION_20260813_20260816`

## Next after success — NOT AUTHORIZED

After Chat/User review, the remaining Aug. 14/Aug. 15 consumer-performance hard alerts may be handled as a separate operational maintenance task if desired.

Separately, a future Builder work order may grade the accepted sealed 4L R2 surface only after explicit user authorization. Neither action is authorized here.
