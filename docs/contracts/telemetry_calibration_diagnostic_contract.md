# Telemetry Calibration Diagnostic v1

Purpose:
- Read a replay corpus and isolate where calibration error is coming from before proposing another challenger.

Inputs:
- corpus root with either `root/runs/<run_id>` or `root/<run_id>` layout
- each run must contain `eval_legs.csv` and `scored_legs_deduped.csv`

Outputs:
- `diagnostic_summary.json`
- `diagnostic_summary.md`
- `per_run_diagnostics.csv`
- `bucket_diagnostics_p_adj.csv`
- `bucket_diagnostics_p_cal.csv`
- `slice_diagnostics_stat_direction.csv`
- `slice_diagnostics_games_used.csv`
- `slice_diagnostics_role_ctx.csv`
- `slice_diagnostics_questionable.csv`
- optional `slice_diagnostics_p_cal_src.csv`
- optional `slice_diagnostics_role_ctx_reason.csv`
- `top_overconfident_slices.csv`
- `top_underconfident_slices.csv`

Rules:
- no config promotion
- no calibration promotion
- no logic patch proposal
- diagnostics only

Primary questions answered:
1. Which probability buckets are most overconfident or underconfident?
2. Which stat/direction slices are most miscalibrated?
3. Does sample depth matter?
4. Does role context matter?
5. Does questionable status matter?
6. Does calibration source matter?
