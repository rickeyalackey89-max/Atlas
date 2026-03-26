# Role Metrics Payload Summary

- Rows: `4469`
- Snapshot rows: `4030` (0.901768)
- Role-context active rows: `346` (0.077422)
- Active tuning families: `scoring, rebound`
- Warnings: `assist_family_metrics_missing_or_null`
- Assist payload ready: `False`
- Assist payload missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg`

## Family Coverage
- `scoring` populated_rows_any=`4030` share=`0.901768`
- `rebound` populated_rows_any=`4030` share=`0.901768`
  - missing: `role_metrics_trb_pct`
- `assist` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg`
- `threes` populated_rows_any=`4030` share=`0.901768`
- `impact_priors` populated_rows_any=`4030` share=`0.901768`

## Family Contribution Report
- `scoring` rows=`2340` brier=`0.246047` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `rebound` rows=`993` brier=`0.232554` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `assist` rows=`355` brier=`0.207883` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `threes` rows=`269` brier=`0.179621` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`