# Role Metrics Payload Summary

- Rows: `1539`
- Snapshot rows: `0` (0.0)
- Role-context active rows: `360` (0.233918)
- Active tuning families: `scoring, rebound`
- Warnings: `assist_family_metrics_missing_or_null, rebound_family_metrics_missing_or_null, scoring_family_metrics_missing_or_null`
- Assist payload ready: `False`
- Assist payload missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg, role_metrics_bc, role_metrics_load, role_metrics_pr`

## Family Coverage
- `scoring` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_usg_pct, role_metrics_ts_pct, role_metrics_sq, role_metrics_ftr`
- `rebound` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_trb_pct, role_metrics_orb_pct, role_metrics_drb_pct`
- `assist` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_ast_pct, role_metrics_touches, role_metrics_ast_usg, role_metrics_bc, role_metrics_load, role_metrics_pr`
- `threes` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_three_par, role_metrics_sq, role_metrics_ts_pct`
- `impact_priors` populated_rows_any=`0` share=`0.0`
  - missing: `role_metrics_darko, role_metrics_vorp, role_metrics_cpm, role_metrics_drip_total`

## Family Contribution Report
- `scoring` rows=`820` brier=`0.201716` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `rebound` rows=`371` brier=`0.19351` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `threes` rows=`98` brier=`0.186157` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`
- `assist` rows=`143` brier=`0.180275` metric_mult=`1.0` scoring=`1.0` assist=`1.0` rebound=`1.0` threes=`1.0`