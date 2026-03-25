# Role-Active Slice Audit 2026-03-25

Matched role-active corpus: `temp_experiments/role_active_only_corpus_20260325`
Matched role-off control: `temp_experiments/role_off_matched_corpus_20260325`

## Role-active corpus slices

- `all`: rows=`20640` hit_rate=`0.425921` mean_p_adj=`0.300071` mean_p_cal=`0.420464` brier_p_adj=`0.241489` brier_p_cal=`0.222909`
- `role_ctx_on`: rows=`1792` hit_rate=`0.493304` mean_p_adj=`0.398026` mean_p_cal=`0.462480` brier_p_adj=`0.228798` brier_p_cal=`0.235951`
- `recent_third`: rows=`8374` hit_rate=`0.427991` mean_p_adj=`0.296405` mean_p_cal=`0.416736` brier_p_adj=`0.241987` brier_p_cal=`0.222283`
- `role_ctx_on_recent_third`: rows=`725` hit_rate=`0.495172` mean_p_adj=`0.395521` mean_p_cal=`0.464986` brier_p_adj=`0.226982` brier_p_cal=`0.233395`
- `role_ctx_off`: rows=`18848` hit_rate=`0.419514` mean_p_adj=`0.290758` mean_p_cal=`0.416469` brier_p_adj=`0.242695` brier_p_cal=`0.221669`

Recent-third run ids in the role-active corpus:
- `20260325_085110`
- `20260325_085210`

## Role-off control reference

- `all`: rows=`20640` hit_rate=`0.425921` mean_p_adj=`0.299937` mean_p_cal=`0.422019` brier_p_adj=`0.241533` brier_p_cal=`0.222900`
- `recent_third`: rows=`8374` hit_rate=`0.427991` mean_p_adj=`0.296268` mean_p_cal=`0.417805` brier_p_adj=`0.242033` brier_p_cal=`0.222390`

## Readout

- `recent_third` is not the main failure surface by itself. It is essentially neutral relative to the whole matched corpus.
- `role_ctx_on` is the unstable slice. It carries better raw hit rate than the full corpus, but its calibrated probabilities run too hot: `brier_p_cal=0.235951` versus `0.222909` overall.
- The `role_ctx_on_recent_third` intersection stays weaker than the corpus baseline on `p_cal`, but it is slightly better than the full `role_ctx_on` slice. That points to role-on calibration pressure more than a pure recency problem.
- The next model-side seam should therefore be conservative and targeted at role-on usage pressure rather than a broad recent-window adjustment.
