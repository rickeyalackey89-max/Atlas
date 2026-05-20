# Atlas MLB Source Snapshots

Status: implemented skeleton  
Last updated: 2026-05-11

## Purpose

Source snapshots are the foundation for live runs and replays.

This layer does not need:

- probability files
- model artifacts
- CAT/GBM trainers
- slip scoring
- dashboard publishing

It only needs to fetch, preserve, and normalize source data.

## Commands

List configured sources:

```powershell
uv run atlas-mlb sources
```

Fetch full PrizePicks raw board, MLB raw board, and normalized MLB board:

```powershell
uv run atlas-mlb fetch prizepicks
```

This writes:

- full all-sports raw snapshot under `data/mlb/raw/prizepicks_all_sports`
- MLB-scoped raw snapshot under `data/mlb/raw/prizepicks`
- normalized MLB board under `data/mlb/staged/board`
- engine-ready board CSV/JSON under `data/mlb/staged/engine_board`

Fetch raw snapshots only:

```powershell
uv run atlas-mlb fetch prizepicks --no-normalize
```

Fetch only the MLB-scoped raw snapshot:

```powershell
uv run atlas-mlb fetch prizepicks --skip-all-sports
```

Normalize latest saved PrizePicks snapshot:

```powershell
uv run atlas-mlb normalize board
```

Publish engine-ready CSV/JSON from the latest normalized PrizePicks board:

```powershell
uv run atlas-mlb prepare engine-board
```

Import existing Atlas PrizePicks raw JSON fixtures:

```powershell
uv run atlas-mlb import legacy-prizepicks --source-dir C:\Users\13142\Atlas\Atlas\data\raw --start-date 2026-04-30 --end-date 2026-05-11
```

Fetch and normalize ESPN MLB injuries:

```powershell
uv run atlas-mlb fetch injuries
```

Normalize latest saved injury snapshot:

```powershell
uv run atlas-mlb normalize injuries
```

Fetch and normalize live OddsAPI MLB props:

```powershell
uv run atlas-mlb fetch oddsapi-live
```

Fetch one historical OddsAPI MLB prop date:

```powershell
uv run atlas-mlb fetch oddsapi-historical --date 2026-04-01
```

Estimate a season-to-date OddsAPI historical backfill:

```powershell
uv run atlas-mlb backfill oddsapi --start-date 2026-04-01 --end-date 2026-05-11 --dry-run
```

Run the backfill:

```powershell
uv run atlas-mlb backfill oddsapi --start-date 2026-04-01 --end-date 2026-05-11
```

Fetch and normalize MLB/MiLB StatsAPI teams:

```powershell
uv run atlas-mlb fetch statsapi-teams --season 2026
```

Fetch and normalize one StatsAPI roster:

```powershell
uv run atlas-mlb fetch statsapi-roster --team-id 133 --season 2026
```

Fetch and normalize StatsAPI schedule/game IDs:

```powershell
uv run atlas-mlb fetch statsapi-schedule --sport-id 1 --start-date 2026-04-01 --end-date 2026-09-30
uv run atlas-mlb fetch statsapi-schedule --sport-id 11 --start-date 2026-04-01 --end-date 2026-09-30
```

Fetch and normalize one StatsAPI boxscore:

```powershell
uv run atlas-mlb fetch statsapi-boxscore --game-pk <gamePk>
```

Fetch and normalize one player game log:

```powershell
uv run atlas-mlb fetch statsapi-gamelog --person-id <personId> --group hitting --season 2026
uv run atlas-mlb fetch statsapi-gamelog --person-id <personId> --group pitching --season 2026
uv run atlas-mlb fetch statsapi-gamelog --person-id <personId> --group fielding --season 2026
```

## Raw Snapshot Layout

PrizePicks:

```text
data/mlb/raw/prizepicks_all_sports/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json

data/mlb/raw/prizepicks/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json
```

ESPN injuries:

```text
data/mlb/raw/espn_injuries/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json
```

OddsAPI MLB:

```text
data/mlb/raw/oddsapi_mlb_live/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json

data/mlb/raw/oddsapi_mlb_historical/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json
```

MLB StatsAPI:

```text
data/mlb/raw/statsapi_teams/<YYYY-MM-DD>/<timestamp>/
data/mlb/raw/statsapi_rosters/<YYYY-MM-DD>/<timestamp>/
data/mlb/raw/statsapi_schedule/<YYYY-MM-DD>/<timestamp>/
data/mlb/raw/statsapi_boxscore/<YYYY-MM-DD>/<timestamp>/
data/mlb/raw/statsapi_player_gamelog/<YYYY-MM-DD>/<timestamp>/
```

Legacy Atlas PrizePicks imports:

```text
data/mlb/raw/legacy_prizepicks_nba/<YYYY-MM-DD>/<timestamp>/
  payload.json
  manifest.json
```

These are copied from production Atlas raw PrizePicks files for JSON format inspection and importer tests.
They are intentionally separate from `data/mlb/raw/prizepicks` so MLB board normalization does not consume NBA
boards by accident.

Each manifest includes:

- `snapshot_id`
- `source`
- `sport`
- `pulled_at_utc`
- `payload_path`
- `checksum_sha256`
- `request`
- `record_count`

## Staged Output Layout

PrizePicks normalized board:

```text
data/mlb/staged/board/<run_id>/
  normalized_board.jsonl
  rejected_board.jsonl
  normalize_manifest.json
```

Engine-ready board inputs:

```text
data/mlb/staged/engine_board/<run_id>/
  engine_board.csv
  engine_board.json
  engine_board_manifest.json

data/mlb/staged/engine_board/latest.csv
data/mlb/staged/engine_board/latest.json
data/mlb/staged/engine_board/latest_manifest.json
```

ESPN normalized injuries:

```text
data/mlb/staged/injuries/<run_id>/
  injuries.jsonl
  normalize_manifest.json
```

OddsAPI normalized props:

```text
data/mlb/staged/oddsapi/<run_id>/
  oddsapi_props.jsonl
  oddsapi_rejected.jsonl
  normalize_manifest.json
```

MLB StatsAPI normalized outputs:

```text
data/mlb/staged/statsapi_teams/<run_id>/statsapi_teams.jsonl
data/mlb/staged/statsapi_rosters/<run_id>/statsapi_rosters.jsonl
data/mlb/staged/statsapi_schedule/<run_id>/statsapi_schedule.jsonl
data/mlb/staged/statsapi_boxscore/<run_id>/statsapi_boxscore.jsonl
data/mlb/staged/statsapi_player_gamelog/<run_id>/statsapi_player_gamelog.jsonl
```

## StatsAPI Sport IDs

Atlas MLB uses StatsAPI as the canonical baseball identity spine.

- `sportId=1`: MLB
- `sportId=11`: Triple-A
- `sportId=12`: Double-A
- `sportId=13`: High-A
- `sportId=14`: Single-A
- `sportId=16`: Rookie

PrizePicks remains the prop/line source.

ESPN remains the injury-note source.

StatsAPI owns:

- major/minor team identity
- rosters
- parent-org mapping
- schedule/game IDs
- box scores
- player game logs

## OddsAPI MLB Markets

Atlas MLB preserves raw OddsAPI event JSON, then normalizes consensus over/under rows.

Default core markets:

- `batter_hits`
- `batter_total_bases`
- `batter_rbis`
- `batter_runs_scored`
- `batter_hits_runs_rbis`
- `batter_singles`
- `batter_doubles`
- `batter_walks`
- `batter_strikeouts`
- `batter_stolen_bases`
- `batter_home_runs`
- `pitcher_strikeouts`
- `pitcher_hits_allowed`
- `pitcher_walks`
- `pitcher_earned_runs`

Optional `--markets all` adds:

- `batter_triples`
- `batter_fantasy_score`

## Current Live Smoke Result

On 2026-05-11:

- PrizePicks MLB board fetched successfully.
- PrizePicks normalized rows: `4,417`.
- PrizePicks rejected rows after adding `Triples`: `0`.
- ESPN MLB injury rows: `333`.
- StatsAPI teams fetched for MLB + configured MiLB levels: `231`.
- StatsAPI MLB schedule one-day smoke rows: `15`.
- StatsAPI roster smoke rows: `26`.
- StatsAPI boxscore smoke rows: `52`.
- StatsAPI pitching game-log smoke rows: `8`.
- OddsAPI MLB raw/normalization path implemented; live and historical pulls require `ODDSAPI_KEY`.

These are intake counts only. They are not model scores.

## Design Rules

- Save raw payloads before normalization.
- Every normal PrizePicks fetch should save both full all-sports raw and MLB-scoped raw snapshots.
- Every normalized PrizePicks board should produce engine-readable CSV and JSON inputs.
- Save full OddsAPI event responses before consensus normalization.
- Keep legacy NBA PrizePicks fixtures isolated from true MLB PrizePicks snapshots.
- Normalize broadly; filter later.
- Unsupported markets go to `rejected_board.jsonl`.
- Do not require model artifacts to build source snapshots.
- Do not publish source snapshots directly.
- Replays should point at saved raw snapshots, not refetch historical inputs.
