# Share Matrix Reference

This note explains what the share matrix is, how it is built, how the engine reads it, and why it matters for role-context support.

## What It Is

The share matrix is the precomputed lookup table that ties an out player to the teammates who can benefit from that absence.

At runtime it is used to decide whether an IAEL out should actually produce support for a given player, team, and stat.

## Where It Comes From

The matrix is built by [tools/build_share_matrix.py](../tools/build_share_matrix.py).

Build flow:

1. Read historical logs from `data/gamelogs/nba_gamelogs.csv` unless a different path is supplied.
2. Pass those logs into `Atlas.model.team_share_reallocator.build_removed_share_matrix(...)`.
3. Write the result to `data/model/share_matrix.csv`.

The builder also applies cleanup filters:

- `--min-pattern-games` removes weak patterns with too few games.
- `--keep-zero-weights` keeps rows that would otherwise be dropped for zero weight.
- `--recent-days`, `--min-rotation-games`, and `--min-rotation-avg-min` control how the source logs are reduced before matrix construction.

## How The Engine Reads It

The runtime loader lives in [src/Atlas/engine/new_probability.py](../src/Atlas/engine/new_probability.py).

On first use it:

- loads `data/model/share_matrix.csv`
- caches it in memory
- normalizes key columns for matching

The loader prepares these helper columns:

- `team_u` from `team`
- `stat_u` from `stat`
- `out_canon` from `out_player`
- `ben_canon` from `beneficiary_player`
- numeric `games`
- numeric `weight`

If the file is missing or unreadable, the runtime falls back to a no-op role-context path.

## How It Is Matched

The core runtime match in `compute_role_multiplier(...)` looks for rows where all of the following line up:

- team matches `team_u`
- stat matches `stat_u`
- beneficiary matches the current player
- out player is one of the IAEL outs for that team
- `games` is at least `min_games`

If no row survives that filter, role context stays effectively off for that leg and `role_ctx_outs_used` remains zero.

## What It Does

When the matrix has a match, it produces a role-context multiplier that nudges the player’s mean rate upward.

That feeds into the engine output fields such as:

- `role_ctx_mult`
- `role_ctx_mult_raw`
- `role_ctx_reason`
- `role_ctx_outs_used`
- `p_role`
- `p_adj`

The model still applies the rest of the normal probability pipeline after that, including blowout adjustment and the usual runtime guardrails.

## Teamshare Support Logic

The allocator side in [src/Atlas/model/team_share_reallocator.py](../src/Atlas/model/team_share_reallocator.py) uses the same matrix to decide how much redistribution support is actually credible for a given out pattern.

Two key controls are:

- `min_games_for_pattern`
- `teamshare_rel_effective_threshold`

Those control whether an out pattern is treated as strongly supported, weakly supported, or effectively unsupported.

## Common Reasons Support Drops To Zero

When `role_ctx_outs_used` stays at zero, the usual causes are:

- the IAEL outs list is empty for that team
- the share matrix has no row for that `(team, stat, out_player, beneficiary)` combination
- the pattern exists but does not meet `min_games`
- the matrix was built from a different source snapshot or different timestamped injury report than the run being compared

## Practical Rule

For a fair comparison, the replay snapshot, the timestamped injury report, and the share matrix source state need to line up with the same run window.

If any of those differ, the support output can legitimately change.
