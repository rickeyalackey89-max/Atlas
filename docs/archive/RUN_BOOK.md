# Atlas RUNBOOK (Commands + Expected Results + Row-Count Baselines)

This runbook is the single operational reference for:
- Live runs (production)
- Cloudflare export + publish
- Deterministic replays
- Telemetry measurement
- Role-context tuning
- Payout multiplier analysis

---

## 0) Conventions

### Repo roots
- Engine: `C:\Users\rick\projects\Atlas`
- Dashboard: `C:\Users\rick\projects\AtlasDashboard`

### Python invocation (Windows)
- Prefer `py`
- If `py` is not available, use pinned:
  - `C:\Users\rick\AppData\Local\Programs\Python\Python311\python.exe`

### Trust hierarchy
1) Latest placeable outputs: `data/output/latest/<tag>/...`
2) Cloudflare payload: `data/output/dashboard/cloudflare_payload.json`
3) Run snapshot: `data/output/runs/<run_id>/...`
4) Audit + bundles: `.atlas_audit/...` and `data/bundles/...`

---

## 1) Daily Operator Flow (Do this every run)

### Step 1 — Live run (authoritative)
From **Atlas** repo root:

```powershell
.\run.ps1
Expected artifacts (minimum)

Canonical board

data/board/fetch_board.csv

data/board/today.csv

data/board/snapshots/today_YYYYMMDD_HHMMSS.csv (append-only snapshot)

Run folder (immutable snapshot)

data/output/runs/<run_id>/scored_legs.csv

data/output/runs/<run_id>/scored_legs_deduped.csv

data/output/runs/<run_id>/System/recommended_{3,4,5}leg.csv

data/output/runs/<run_id>/Windfall/recommended_{3,4,5}leg.csv

Latest (placeable surface)

data/output/latest/all/System/recommended_{3,4,5}leg.csv

data/output/latest/all/Windfall/recommended_{3,4,5}leg.csv

optionally data/output/latest/{early,main,late}/... depending on slate timing/place-window rules

Audit + bundle

.atlas_audit/events_<run_id>.jsonl

data/bundles/atlas_bundle_<run_id>.zip

Row-count baselines (expected ranges)

These vary by slate, but the shape should be consistent. Numbers in parentheses are an example from a recent standard run.

data/board/fetch_board.csv

Expected: ~4,000–8,000 rows (example: 5574)

data/board/today.csv (after canonical normalization)

Expected: ~3,000–6,000 rows (example: 4703)

Post-validation “usable rows” (after invalid/unknown stat/line filtering)

Expected: ~2,500–4,500 rows (example: 3494 after invalid drops)

scored_legs.csv

Expected: close to usable rows

scored_legs_deduped.csv

Expected: ≤ scored_legs (dedupe reduces rows)

recommended_*leg.csv

Expected: non-zero for at least one product/leg-size on a normal slate.

Typical: tens of rows (not thousands). Empty is allowed only when constraints + placeability wipe the pool.

Quick sanity checks

data/board/today.csv exists and row count is in the expected range.

Run folder exists: data/output/runs/<run_id>/

data/output/latest/all/System/recommended_4leg.csv OR Windfall equivalent has rows > 0 (unless slate truly dead).

Bundle zip exists for the <run_id>.

Step 2 — Export Cloudflare payload (Atlas side)

From Atlas repo root:

py scripts/dev/export/export_cloudflare_payload.py
Expected artifact

data/output/dashboard/cloudflare_payload.json

Baselines / sanity checks

File modified time is “now”

JSON contains top-level keys:

generated_at, system, windfall (gamescript may be empty/placeholder)

Each slip:

has n_legs as 3/4/5

has legs_detail array length == n_legs

Step 3 — Publish to Cloudflare (AtlasDashboard repo)

From AtlasDashboard repo root:

pwsh -NoProfile -ExecutionPolicy Bypass -File .\publish-atlas.ps1 -AtlasRoot "C:\Users\rick\projects\Atlas"
Expected artifacts

public/data/cloudflare_payload.json updated

Git commit created and pushed (Cloudflare Pages deploy triggers)

Cloudflare sanity checks

Site shows updated timestamp

Direct JSON: /data/cloudflare_payload.json shows the same generated_at as your local payload

2) Tool Flight Checklist (Separation Tools)

These tools are the long-term moat: replayability, measurement integrity, role-context quality, and payout correctness.

A) Role Context (build + inspect)
A1) Build share matrix

From Atlas repo root:

py tools/build_share_matrix.py

Expected artifact

data/model/share_matrix.csv

Expected row counts

Depends heavily on gamelog freshness and rotation thresholds.

Expected: non-zero on active season slates; can be 0 if cleanup is aggressive or gamelog feed is missing.

Sanity checks

File exists

Not all weights are zero unless intended

If rows=0 unexpectedly: check gamelogs freshness + thresholds

A2) Inspect role context multipliers

From Atlas repo root:

py tools/inspect_role_ctx.py

Expected result

Console summary:

distribution of role_ctx_mult and role_ctx_mult_raw

reason counts

extreme examples

What “good” looks like

p99 not insane (tails exist but aren’t dominating)

reasons are interpretable (not “unknown reason” spam)

extreme rows are rare and explainable

B) Deterministic Replay (Scenario + Bundle)
B1) Replay a raw snapshot (scenario replay)

From Atlas repo root:

.\Run-Sandbox.ps1 -RawPath "PATH\TO\prizepicks_snapshot.json"

Expected artifacts

.atlas_audit/sandbox_runlog_<runId>.txt

.atlas_audit/sandbox_cmds_<runId>.log

data/output/sandbox_runs/<scenario_id>/<ts>/... (engine outputs)

Sanity checks

sandbox run folder has scored_legs*.csv and recommended slips

sandbox audit log exists and contains engine stdout/stderr

B2) Replay from a FULL_RUN bundle zip (bundle replay)

From Atlas repo root:

py replay_bundle.py --bundle "PATH\TO\atlas_bundle_<run_id>.zip"

Expected artifacts

extracted workspace under:

archives/bundles/<scenario_id>/analysis/<ts>/workspace/...

sandbox outputs under:

data/output/sandbox_runs/<scenario_id>/<ts>/...

analysis logs captured

Sanity checks

workspace contains data/board/today.csv

sandbox outputs exist and are non-empty

engine logs recorded in analysis folder

C) IAEL Seeding (historical truth for replay)
C1) Build IAEL seed from normalized IAEL JSON

From Atlas repo root:

py tools/build_iael_seed_from_normalized.py --in "PATH\TO\normalized_iael.json"

Expected artifacts
Under data/archives/iael_seed/<year>/<stamp>/...:

status_latest.json

injury_invalidations_latest.json

seed_meta.json

Sanity checks

status file contains only filtered statuses (OUT/DOUBTFUL/QUESTIONABLE)

invalidations file exists and is non-empty when appropriate

D) Telemetry (archives-only measurement loop)
D1) Run telemetry reader

From Atlas repo root:

py tools/telemetry_reader.py

Expected artifacts

reports under data/archives/.../analysis/... (NOT data/output/)

Sanity checks

output folder path printed

report files exist (rows_main.csv, summaries, etc.)

no new telemetry files written under data/output/

E) Payout / Multiplier Analysis (finance layer)
E1) Rank slips by payout/EV multiplier

From Atlas repo root (example input):

py tools/financial_multiplier.py --in "data/output/latest/all/Windfall/recommended_5leg.csv"

Expected result

console ranking and/or report output (depends on flags)

sorted by available multiplier columns (ev_mult / payout_mult / hit_prob, etc.)

Sanity checks

expected columns detected (no NaN spam)

top rows look plausible (no impossible multipliers)

3) Fast triage (when something looks wrong)

today.csv empty or tiny:

upstream fetch/rebuild issue (board empty, Cloudflare blocks, raw selection wrong)

run folder exists but recommended CSVs empty:

engine constraints too strict or most legs invalidated (IAEL/unknown stat/line)

run folder has slips but latest/<tag> empty:

placeability filter is rejecting everything (time buckets / min-minutes / strictness)

Cloudflare shows old data:

export didn’t run OR publish didn’t copy/commit/push OR browser cache

replay differs wildly:

missing seed artifacts (IAEL), mismatched gamelogs, or config drift