"""Print gain-based feature importances from the production GBM ensemble."""
import sys, pathlib
import lightgbm as lgb
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
ens = ROOT / "data" / "model" / "ensemble"

FEATS = [
    "z_line","min_cv","is_combo","bp_score_gated","bp_has","is_assists","is_threes",
    "games_norm","thin_flag","line_norm","is_home_feat","min_sensitivity","game_total_norm",
    "is_b2b","l20_edge","l10_has","margin","stat_cat","tier_cat","l40_hr","logit_p_x_demon",
    "player_te","player_stat_te","player_dir_te","player_n_norm","line_dist","tail_risk",
    "line_tightness","margin_x_under","q_blowout","rate_cv","abs_logit_p","q_x_under",
]

over_imp  = np.zeros(len(FEATS))
under_imp = np.zeros(len(FEATS))
over_n = under_n = 0

for f in sorted(ens.glob("*.txt")):
    bst = lgb.Booster(model_file=str(f))
    imp_map = dict(zip(bst.feature_name(), bst.feature_importance(importance_type="gain")))
    arr = np.array([imp_map.get(feat, 0.0) for feat in FEATS])
    if "over" in f.name:
        over_imp += arr; over_n += 1
    else:
        under_imp += arr; under_n += 1

over_imp  /= max(over_n, 1)
under_imp /= max(under_n, 1)
combined   = over_imp + under_imp

print(f"Feature importances (gain) — avg over {over_n} OVER + {under_n} UNDER models")
print(f"{'Feature':<22}  {'OVER':>10}  {'UNDER':>10}  {'COMBINED':>10}  {'OVER%':>6}  {'UNDER%':>6}")
print("-" * 72)
pairs = sorted(zip(FEATS, over_imp, under_imp, combined), key=lambda x: -x[3])
total_o = over_imp.sum(); total_u = under_imp.sum()
for feat, oi, ui, ci in pairs:
    pct_o = 100 * oi / total_o if total_o else 0
    pct_u = 100 * ui / total_u if total_u else 0
    print(f"{feat:<22}  {oi:>10.1f}  {ui:>10.1f}  {ci:>10.1f}  {pct_o:>5.1f}%  {pct_u:>5.1f}%")

print()
print("Bottom 5 combined (weakest features):")
for feat, oi, ui, ci in pairs[-5:]:
    print(f"  {feat:<22}  combined={ci:.1f}")
