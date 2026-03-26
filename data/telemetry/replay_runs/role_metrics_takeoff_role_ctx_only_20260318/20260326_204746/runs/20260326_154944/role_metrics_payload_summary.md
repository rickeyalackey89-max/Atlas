# Role Metrics Payload Summary

- Rows: `5038`
- Snapshot rows: `0` (0.0)
- Role-context active rows: `0` (0.0)
- Active tuning families: `scoring, rebound`
- Warnings: `assist_family_metrics_missing_or_null, rebound_family_metrics_missing_or_null, scoring_family_metrics_missing_or_null`
- Assist payload ready: `False`
- Assist payload missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg`

## Family Coverage
- `scoring` populated_rows_any=`0` share=`0.0`
- `rebound` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_trb_pct`
- `assist` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg`
- `threes` populated_rows_any=`0` share=`0.0`
- `impact_priors` populated_rows_any=`0` share=`0.0`

## Family Contribution Report
- `scoring` rows=`2867` brier=`0.233433` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `rebound` rows=`1275` brier=`0.199674` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `assist` rows=`516` brier=`0.199544` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `threes` rows=`338` brier=`0.189268` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`