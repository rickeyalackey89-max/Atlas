# Atlas Website And Discord To-Do

Last updated: 2026-05-11

This file is the working contract for what the Atlas website and Discord automation must do around daily IAEL runs, eval reporting, and public/premium posting.

## Website Publishing Rules

- Every successful live IAEL run should update the Cloudflare website payload and publish to `atlas-dashboard`.
- Live IAEL runs should not rewrite yesterday's eval/results block. That block belongs to the 6AM eval job only.
- The 6AM eval job should refresh gamelogs, create `eval_legs.csv` for prior-day runs, select one canonical prior-day report run, rebuild `cloudflare_payload.json`, and publish it to the website.
- The 6AM eval job owns the Performance tab's leg windows: `overall.last_7d`, `overall.last_30d`, `by_tier.*`, and `performance.meta`.
- Live runs should preserve the latest 6AM performance windows while updating today's board, slips, market odds, injuries, and other live data.
- The website's yesterday-results record must use the same canonical prior-day report run used by the 6AM eval report.

## Canonical 6AM Eval Report Run

The 6AM eval job should evaluate all eligible prior-day run directories, but it should report and publish results from one selected run:

- Saturday/Sunday game date: use the 2:30 PM report run, closest to 14:30 local time.
- Monday-Friday game date: use the 5:30 PM report run, closest to 17:30 local time.
- If the exact target run is missing, choose the closest timestamped run to the target time, preferring the earlier run on an exact tie.
- The selected run should already have `eval_legs.csv` before Discord results are posted.

## Performance Window Rules

- Leg hit-rate windows are computed from unique scored board legs in `data/telemetry/live_runs/**/eval_legs.csv`.
- Duplicate legs are deduped by `game_date`, `player`, `stat`, `line`, and `direction`.
- The 7-day and 30-day windows are anchored to the latest scored game date in the eval archive, not the wall-clock date.
- `last_7d` means latest scored game date minus 6 days through latest scored game date.
- `last_30d` means latest scored game date minus 29 days through latest scored game date.
- These are board-leg hit rates, not marketed slip hit rates.

Current example:

- Game date: `2026-05-10` Sunday.
- Required report run: `data/output/runs/20260510_142919`.
- Reason: weekend rule, closest run to the 2:30 PM pre-game report.

## Discord Posting Rules

- 6AM eval job: post prior-day premium slip results to the results channel.
- Weekday 8AM live IAEL run: post premium slips of the day to the locked `picks_today` channel.
- Weekday 5:30PM live IAEL run: post premium slips of the day to the locked `picks_today` channel.
- Weekday 4:30PM free-slip job: post one free slip to the free Discord channel.
- Weekend free-slip posting is still open. Current intended target is likely around 2PM, before weekend games begin.

## Known Gaps / Decisions

- Confirm whether "three IAEL runs should post to Discord" means:
  - 6AM eval results plus 8AM premium picks plus 5:30PM premium picks, or
  - three live premium-pick IAEL posts in addition to 6AM results.
- Premium Discord posting is gated by `ATLAS_DISCORD_PICKS_POST=1`. The 8AM and 5:30PM scripts enable it on weekdays; 11AM and 2:30PM keep it off.
- Weekend free-slip automation needs a dedicated run time, channel config, and post format.

## Implementation Checklist

- [x] Fix the 6AM batch run enumeration so prior-day wildcard folders are actually processed.
- [x] Add a canonical prior-day report-run selector.
- [x] Allow Discord results mode to score a specific selected run.
- [x] Allow website yesterday-results payload to honor the selected report run.
- [x] Make 6AM eval the updater for Performance tab 7-day/30-day leg windows.
- [x] Gate premium Discord posting so only the intended live runs post to `picks_today`.
- [ ] Add weekend free-slip automation once the 2PM plan is confirmed.
- [ ] Add a lightweight post-run audit that verifies the Cloudflare payload's `performance.yesterday_slips.run_id` equals the selected report run.
