# Archived Tools Reference — 2026-04-16

All archived files live on **D:\AtlasTestMarch26\archived_tools\**.

## superseded_trainers/ (6 files)
Old leg trainer and demonhunter trainer versions replaced by v5/v4.
- leg_trainer.py (v3)
- leg_trainer_v2_backup.py
- leg_trainer_v4.py
- leg_trainer_v4_5leg.py
- demonhunter_trainer.py (v1)
- demonhunter_trainer_v3.py

## superseded_builders/ (6 files)
Cache and resim builders for older model versions (v10–v15).
- build_v12_corpus.py
- build_v13_cache.py
- build_v15_cache.py
- expand_resim_cache_v10.py
- full_resim_v10.py
- full_resim_v11.py

## superseded_gbm/ (4 files)
GBM trainers for v10/v11 and investigation scripts. Current: gbm_v12_train.py.
- gbm_v10_train.py
- gbm_v10b_train_old.py
- gbm_v11_train.py
- gbm_v12_investigate.py

## results_and_logs/ (17 files)
Trainer output YAML results and log files. Not used at runtime — trainers regenerate these on each run.
- calibration_trainer_results.yaml
- demonhunter_trainer_results.yaml
- demonhunter_trainer_results_v4.yaml
- demonhunter_trainer_v3_output.log
- external_priors_trainer_results.yaml
- feature_discovery_results.yaml
- kernel_trainer_results_v1.yaml
- leg_trainer_results_v3.yaml
- leg_trainer_results_v4.yaml
- leg_trainer_results_v5_ev.yaml
- leg_trainer_results_v5_hit.yaml
- leg_trainer_results_v5_hit_partial.yaml
- leg_trainer_v5_ev_output.log
- leg_trainer_v5_hit_output.log
- leg_trainer_v5_output.log
- role_ctx_trainer_results_v1.yaml
- share_matrix_trainer_results_v1.yaml

## old_analysis/ (11 files)
One-off analysis, comparison, and diagnostic tools not used by the active pipeline.
- diagnose_blowout_accuracy.py
- financial_multiplier.py
- leg_agg_analysis.py
- leg_level_comparison.py
- multi_replay_slip_sim.py
- oracle_tuner.py
- replay_ab_comparison.py
- replay_scenario.py
- slip_constraint_ab_test.py
- telemetry_calibration_diagnostic.py
- telemetry_reader.py

## Also deleted (not archived — throwaway)
53 temp/tmp scripts (`_temp_*`, `_tmp_*`, `_smoke_*`, `_show_*`, `_build_*`, `_v10_*`) deleted outright across two cleanup passes.
