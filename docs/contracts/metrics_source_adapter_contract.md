# Metrics Source Adapter Contract

This contract defines how Atlas should ingest a daily HTML metrics page that provides role-aware player context, including fields like plus/minus, role awareness, and VORP-style value measures.

The source is not treated as a replacement for Atlas. It is an upstream adapter that supplies richer role-state inputs for the existing model.

## Purpose

Use this adapter to turn a daily scraped metrics page into a deterministic, date-pinned player-state snapshot that Atlas can join against injury and game-log data.

The adapter should support:

- role-context enrichment
- minutes/rotation context
- player quality context
- deterministic replay through snapshots
- canonical joins against Atlas injury and gamelog data

## Source Characteristics

The source is expected to be:

- refreshed daily
- HTML-first, not API-first
- table-structured
- row-oriented by player
- stable enough to parse by selectors or column order
- snapshotable for replay

The source does not need to expose injury status directly.

Atlas should merge the metrics snapshot with the already-pulled injury snapshot for the same slate date.

## Required Input Fields

The adapter must extract these fields when they are present on the page:

- `player_name`
- `player_slug` or other stable source identifier
- `team`
- `position`
- `snapshot_date` or as-of date
- `source_url`
- `source_timestamp` or fetch time

## Strongly Recommended Fields

These fields should be captured when available because they help Atlas explain role context:

- `plus_minus`
- `vorp`
- `role_awareness`
- `minutes_projection`
- `usage_projection`
- `starter_flag`
- `rotation_tier`
- `depth_role`
- `game_count`
- `source_rank`

## Optional Fields

These can be ingested if the page provides them, but Atlas should not depend on them being present:

- `height`
- `wingspan`
- `weight`
- `length`
- `pos_size`
- `confidence`
- `notes`
- `raw_row_html`

## Internal Atlas Schema

The adapter should normalize the HTML rows into the following internal shape:

- `player`
- `player_key`
- `team`
- `position`
- `game_date`
- `source_url`
- `source_timestamp`
- `snapshot_id`
- `html_sha256`
- `plus_minus`
- `vorp`
- `role_awareness`
- `minutes_projection`
- `usage_projection`
- `starter_flag`
- `rotation_tier`
- `depth_role`
- `source_rank`
- `height`
- `wingspan`
- `weight`
- `length`
- `pos_size`

All numeric fields should be stored as nullable numeric values.

## Join Rules

Atlas should merge this source with existing injury state using:

1. canonical player key
2. slate game date
3. team where available as a secondary guardrail

The join should be a left join from metrics rows to injury rows so the metrics snapshot remains the base table.

Missing injury status should be treated as unknown, not healthy.

## Injury Handling

This source does not author availability.

Atlas should continue to source injury state from the existing injury pipeline and join it onto the metrics snapshot.

Recommended injury fields after the merge:

- `injury_status`
- `is_out`
- `is_doubtful`
- `is_questionable`
- `injury_source`
- `injury_snapshot_id`

## Snapshot Rules

Every run should preserve the exact HTML or parsed payload used for the snapshot.

Live fetch configuration should come from one of these environment variables:

- `ATLAS_ROLE_METRICS_URL`
- `ATLAS_ROLE_METRICS_HTML_PATH`

If both are set, the local HTML path should take precedence so replayable fixture inputs can be used without changing the code.

Required snapshot artifacts:

- raw HTML capture
- parsed CSV or JSON output
- sha256 hash of the raw HTML
- source URL
- fetch timestamp
- parser version
- row count

Recommended runtime filenames in Atlas:

- `data/output/dashboard/role_metrics_latest.json`
- `data/output/dashboard/role_metrics_latest.html`
- `data/output/dashboard/role_metrics_snapshot_manifest.json`
- `data/output/role_metrics/snapshots/<game_date>/<snapshot_id>.json`
- `data/output/role_metrics/snapshots/<game_date>/<snapshot_id>.html`

Snapshot paths should be date-pinned and run-pinned so replay can use the same source state later.

## Validation Rules

The adapter should fail closed if any of these conditions are true:

- the HTML cannot be parsed into rows
- player names cannot be canonicalized
- the source date does not match the slate date
- the snapshot hash is missing
- the row count is zero
- the page layout changed enough to break selector-based extraction

The adapter should warn, but not necessarily fail, if:

- optional metric columns are missing
- some numeric cells are blank
- the page contains repeated headers

## Atlas Integration Philosophy

Atlas should treat this source as a richer role-context feed, not as the final model.

In practice:

- game logs remain the realized truth layer
- injury snapshots remain the availability source
- this adapter supplies daily player-state enrichment
- the probability engine and calibration layers still belong to Atlas

## Suggested Output Contract

The adapter should write a normalized daily file with these columns at minimum:

- `snapshot_id`
- `game_date`
- `player`
- `player_key`
- `team`
- `position`
- `source_url`
- `source_timestamp`
- `html_sha256`
- `plus_minus`
- `vorp`
- `role_awareness`
- `minutes_projection`
- `usage_projection`
- `starter_flag`
- `rotation_tier`
- `depth_role`

That output can then be merged with Atlas injury and gamelog snapshots downstream.

## Practical Recommendation

If this source is updated daily and the HTML is stable, it is worth adding.

It is a better fit than trying to infer the same information from game logs alone because it gives Atlas direct role-state context instead of a reconstructed approximation.
