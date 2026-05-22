#!/usr/bin/env python
"""Fast add/drop screen for expanded CAT features.

This is a cheap first pass before any full LODO sweep:
1. Use a small number of representative held-out dates.
2. Use reduced iterations by default.
3. Test one added candidate feature at a time against the current contract.
4. Optionally test small top-N combinations.

Only finalists from this screen should receive a full 18-date / 800-iteration
LODO.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data/model/candidates/strict_fidelity_corpus_20260501_20260520_v2_cat_cache_20260521_161940.pkl"
META_PATH = ROOT / "data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json"
CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]
RESIDUAL_CLIP = 0.20


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def apply_residual(p: np.ndarray, r: np.ndarray, scale: float) -> np.ndarray:
    return np.clip(p + scale * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP), 1e-4, 1.0 - 1e-4)


def prep_x(df: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, list[str]]:
    cat_in = [c for c in CAT_FEATURES_ALL if c in features]
    x = df[features].copy()
    for col in features:
        if col in cat_in:
            x[col] = pd.to_numeric(x[col], errors="coerce").fillna(0).astype(int).astype(str)
        else:
            x[col] = pd.to_numeric(x[col], errors="coerce").fillna(0.0).astype(float)
    return x, cat_in


def make_pool(x: pd.DataFrame, y: np.ndarray | None, cat_in: list[str]) -> Pool:
    if y is None:
        return Pool(x, cat_features=cat_in)
    return Pool(x, label=y, cat_features=cat_in)


def load_current_features() -> list[str]:
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    features = list(meta.get("features") or [])
    if not features:
        raise RuntimeError(f"No features found in {META_PATH}")
    return features


def candidate_features() -> list[str]:
    return [
        # game context
        "game_spread",
        "game_total",
        "q_blowout_spread_only",
        "q_blowout_team_adj",
        "q_blowout_matchup_adj",
        "spread_ok",
        # exact market / priors
        "external_prior_market_prob",
        "external_prior_exact_market",
        "external_prior_market_divergence",
        "external_prior_delta_p",
        "external_prior_probability_applied",
        "external_prior_score",
        "external_prior_n",
        # role / usage / minutes
        "role_metrics_mult",
        "role_metrics_score",
        "role_metrics_impact_score",
        "role_metrics_usage_projection_weighted",
        "role_metrics_minutes_projection_weighted",
        "role_metrics_load_weighted",
        "role_metrics_touches_weighted",
        "usage_dep_eff",
        "usage_burden_ratio",
        "modeled_minutes",
        "minutes_cv",
        # single-game construction signals
        "single_game_slate",
        "single_game_games",
        "single_game_robustness_score",
        "single_game_script_dependency_score",
        "single_game_slate_severity_score",
        "single_game_anchor_flag",
        "single_game_role_shooter_over_flag",
        "single_game_fg3m_over_flag",
        "single_game_non_shooting_volume_flag",
        "single_game_multi_script_survival_flag",
        "single_game_low_line_noise_flag",
        # minute/blowout simulation
        "minutes_s_blowout",
        "minutes_s_close",
        "blowout_minute_drop",
        "blowout_minute_delta",
        "sim_minutes_close",
        "sim_minutes_blowout",
        "projected_minutes_model",
        "projected_minutes_delta_from_gamelog",
        # model-side stat projection
        "atlas_projection_mean",
        "atlas_projection_delta",
        "atlas_projection_side_delta",
        "atlas_projection_abs_delta",
        "atlas_projection_line_ratio",
    ]


def feature_bundles() -> dict[str, list[str]]:
    return {
        "game_context_plus": [
            "game_spread",
            "game_total",
            "q_blowout_spread_only",
            "q_blowout_team_adj",
            "q_blowout_matchup_adj",
            "spread_ok",
        ],
        "market_exact_plus": [
            "external_prior_market_prob",
            "external_prior_exact_market",
            "external_prior_market_divergence",
            "external_prior_delta_p",
            "external_prior_probability_applied",
            "external_prior_score",
            "external_prior_n",
        ],
        "role_usage_plus": [
            "role_metrics_mult",
            "role_metrics_score",
            "role_metrics_impact_score",
            "role_metrics_usage_projection_weighted",
            "role_metrics_minutes_projection_weighted",
            "role_metrics_load_weighted",
            "role_metrics_touches_weighted",
            "usage_dep_eff",
            "usage_burden_ratio",
            "modeled_minutes",
            "minutes_cv",
        ],
        "single_game_plus": [
            "single_game_slate",
            "single_game_games",
            "single_game_robustness_score",
            "single_game_script_dependency_score",
            "single_game_slate_severity_score",
            "single_game_anchor_flag",
            "single_game_role_shooter_over_flag",
            "single_game_fg3m_over_flag",
            "single_game_non_shooting_volume_flag",
            "single_game_multi_script_survival_flag",
            "single_game_low_line_noise_flag",
        ],
        "minutes_blowout_plus": [
            "minutes_s_blowout",
            "minutes_s_close",
            "blowout_minute_drop",
            "blowout_minute_delta",
            "sim_minutes_close",
            "sim_minutes_blowout",
            "projected_minutes_model",
            "projected_minutes_delta_from_gamelog",
        ],
        "projection_plus": [
            "atlas_projection_mean",
            "atlas_projection_delta",
            "atlas_projection_side_delta",
            "atlas_projection_abs_delta",
            "atlas_projection_line_ratio",
        ],
    }


def feature_audit(df: pd.DataFrame, features: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    ok: list[str] = []
    rows: list[dict[str, Any]] = []
    for feature in dict.fromkeys(features):
        if feature not in df.columns:
            rows.append({"feature": feature, "status": "missing"})
            continue
        s = pd.to_numeric(df[feature], errors="coerce")
        non_null = int(s.notna().sum())
        nunique = int(s.nunique(dropna=True))
        nonzero_rate = float((s.fillna(0.0) != 0.0).mean()) if len(s) else 0.0
        status = "ok" if non_null > 0 and nunique > 1 else "dead"
        rows.append(
            {
                "feature": feature,
                "status": status,
                "non_null": non_null,
                "nunique": nunique,
                "nonzero_rate": nonzero_rate,
                "mean": float(s.mean()) if non_null else None,
            }
        )
        if status == "ok":
            ok.append(feature)
    return ok, rows


def select_screen_dates(all_dates: list[str], explicit: list[str] | None) -> list[str]:
    if explicit:
        wanted = [d.strip() for d in explicit if d.strip()]
        missing = sorted(set(wanted) - set(all_dates))
        if missing:
            raise ValueError(f"Requested screen dates missing from cache: {missing}")
        return wanted
    preferred = ["2026-05-01", "2026-05-05", "2026-05-10", "2026-05-15", "2026-05-18", "2026-05-20"]
    selected = [d for d in preferred if d in all_dates]
    if len(selected) >= 3:
        return selected
    idxs = sorted(set([0, len(all_dates) // 3, (2 * len(all_dates)) // 3, len(all_dates) - 1]))
    return [all_dates[i] for i in idxs]


def run_lodo_subset(
    cv: pd.DataFrame,
    features: list[str],
    held_dates: list[str],
    *,
    iterations: int,
    depth: int,
    learning_rate: float,
    residual_scale: float,
) -> dict[str, Any]:
    cv = cv.copy()
    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv.get("role_ctx_outs_used", 0), errors="coerce").fillna(0).astype(int) > 0).astype(int)
    hit_arr = cv["hit"].astype(float).to_numpy()
    p_arr = cv["p_for_cal"].to_numpy()
    date_arr = cv["game_date"].astype(str).str[:10].to_numpy()
    residual_tgt = hit_arr - p_arr
    x_full, cat_in = prep_x(cv, features)

    params = dict(
        iterations=int(iterations),
        depth=int(depth),
        learning_rate=float(learning_rate),
        l2_leaf_reg=6.0,
        min_data_in_leaf=50,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50,
        use_best_model=True,
    )
    rows = []
    oof_idx: list[np.ndarray] = []
    oof_pred: list[np.ndarray] = []
    t0 = time.time()
    for held in held_dates:
        test_mask = date_arr == held
        train_mask = ~test_mask
        y_all = residual_tgt[train_mask]
        x_all = x_full[train_mask].reset_index(drop=True)
        x_te = x_full[test_mask].reset_index(drop=True)
        rng = np.random.default_rng(42)
        n_tr = len(x_all)
        eval_idx = rng.choice(n_tr, size=max(1, n_tr // 10), replace=False)
        train_idx = np.setdiff1d(np.arange(n_tr), eval_idx)
        model = CatBoostRegressor(**params)
        model.fit(
            make_pool(x_all.iloc[train_idx], y_all[train_idx], cat_in),
            eval_set=make_pool(x_all.iloc[eval_idx], y_all[eval_idx], cat_in),
        )
        pred = model.predict(make_pool(x_te, None, cat_in))
        p_after = apply_residual(p_arr[test_mask], pred, residual_scale)
        b_pre = brier(hit_arr[test_mask], p_arr[test_mask])
        b_post = brier(hit_arr[test_mask], p_after)
        rows.append(
            {
                "date": held,
                "n": int(test_mask.sum()),
                "brier_pforcal": b_pre,
                "brier_after_cal": b_post,
                "delta_mB": (b_post - b_pre) * 1000.0,
                "best_iter": int(model.get_best_iteration()),
            }
        )
        oof_idx.append(np.where(test_mask)[0])
        oof_pred.append(pred)

    idx = np.concatenate(oof_idx)
    pred = np.concatenate(oof_pred)
    p_after_all = apply_residual(p_arr[idx], pred, residual_scale)
    out = {
        "features": features,
        "feature_count": len(features),
        "held_dates": held_dates,
        "screen_brier_pforcal": brier(hit_arr[idx], p_arr[idx]),
        "screen_brier_after_cal": brier(hit_arr[idx], p_after_all),
        "screen_delta_mB": (brier(hit_arr[idx], p_after_all) - brier(hit_arr[idx], p_arr[idx])) * 1000.0,
        "folds": rows,
        "elapsed_sec": time.time() - t0,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast add/drop screen for expanded CAT features.")
    parser.add_argument("--cache-path", default=str(DEFAULT_CACHE))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--screen-dates", nargs="*")
    parser.add_argument("--iterations", type=int, default=250)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--residual-scale", type=float, default=0.50)
    parser.add_argument("--top-n-combos", type=int, default=8)
    parser.add_argument("--mode", choices=["single", "bundles"], default="single")
    parser.add_argument(
        "--bundles",
        nargs="*",
        default=["game_context_plus", "market_exact_plus", "role_usage_plus", "single_game_plus", "minutes_blowout_plus", "expanded_compact_all"],
        help="Bundle names to test when --mode bundles.",
    )
    args = parser.parse_args()

    cache_path = Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    with cache_path.open("rb") as fh:
        cache = pickle.load(fh)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    all_dates = sorted(cv["game_date"].astype(str).str[:10].unique().tolist())
    held_dates = select_screen_dates(all_dates, args.screen_dates)

    current = load_current_features()
    bundle_map = feature_bundles()
    all_bundle_features: list[str] = []
    for values in bundle_map.values():
        all_bundle_features.extend(values)
    bundle_map["expanded_compact_all"] = list(dict.fromkeys(all_bundle_features))

    if args.mode == "bundles":
        requested_bundles = []
        for raw in args.bundles or []:
            for part in str(raw).replace(",", " ").split():
                if part:
                    requested_bundles.append(part)
        unknown = sorted(set(requested_bundles) - set(bundle_map))
        if unknown:
            raise ValueError(f"Unknown bundles: {unknown}; valid={sorted(bundle_map)}")
        requested_features = []
        for name in requested_bundles:
            requested_features.extend(bundle_map[name])
        candidates, audit_rows = feature_audit(cv, [f for f in requested_features if f not in current])
    else:
        candidates, audit_rows = feature_audit(cv, [f for f in candidate_features() if f not in current])
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data/model/candidates" / f"nba_cat_adddrop_screen_{datetime.now():%Y%m%d_%H%M%S}"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[ADDDROP] mode={args.mode} dates={held_dates} current_features={len(current)} candidates={len(candidates)}", flush=True)
    baseline = run_lodo_subset(
        cv,
        current,
        held_dates,
        iterations=args.iterations,
        depth=args.depth,
        learning_rate=args.learning_rate,
        residual_scale=args.residual_scale,
    )
    print(f"[ADDDROP] baseline screen_brier={baseline['screen_brier_after_cal']:.6f}", flush=True)

    add_rows: list[dict[str, Any]] = []
    combo_result = None
    winners: list[str] = []
    if args.mode == "bundles":
        requested_bundles = []
        for raw in args.bundles or []:
            for part in str(raw).replace(",", " ").split():
                if part:
                    requested_bundles.append(part)
        for i, name in enumerate(requested_bundles, start=1):
            valid_features, _ = feature_audit(cv, [f for f in bundle_map[name] if f not in current])
            result = run_lodo_subset(
                cv,
                list(dict.fromkeys(current + valid_features)),
                held_dates,
                iterations=args.iterations,
                depth=args.depth,
                learning_rate=args.learning_rate,
                residual_scale=args.residual_scale,
            )
            row = {
                "feature": name,
                "kind": "bundle",
                "added_features": ",".join(valid_features),
                "added_feature_count": len(valid_features),
                "screen_brier_after_cal": result["screen_brier_after_cal"],
                "screen_delta_vs_baseline": result["screen_brier_after_cal"] - baseline["screen_brier_after_cal"],
                "screen_delta_mB_vs_baseline": (result["screen_brier_after_cal"] - baseline["screen_brier_after_cal"]) * 1000.0,
                "screen_delta_mB": result["screen_delta_mB"],
                "feature_count": result["feature_count"],
                "elapsed_sec": result["elapsed_sec"],
            }
            add_rows.append(row)
            print(
                f"[ADDDROP] bundle {i:02d}/{len(requested_bundles)} {name}: "
                f"features={len(valid_features)} brier={row['screen_brier_after_cal']:.6f} "
                f"vs_base={row['screen_delta_mB_vs_baseline']:+.2f}mB",
                flush=True,
            )
    else:
        for i, feature in enumerate(candidates, start=1):
            result = run_lodo_subset(
                cv,
                list(dict.fromkeys(current + [feature])),
                held_dates,
                iterations=args.iterations,
                depth=args.depth,
                learning_rate=args.learning_rate,
                residual_scale=args.residual_scale,
            )
            row = {
                "feature": feature,
                "kind": "single_feature",
                "screen_brier_after_cal": result["screen_brier_after_cal"],
                "screen_delta_vs_baseline": result["screen_brier_after_cal"] - baseline["screen_brier_after_cal"],
                "screen_delta_mB_vs_baseline": (result["screen_brier_after_cal"] - baseline["screen_brier_after_cal"]) * 1000.0,
                "screen_delta_mB": result["screen_delta_mB"],
                "feature_count": result["feature_count"],
                "elapsed_sec": result["elapsed_sec"],
            }
            add_rows.append(row)
            print(
                f"[ADDDROP] {i:02d}/{len(candidates)} +{feature}: "
                f"brier={row['screen_brier_after_cal']:.6f} "
                f"vs_base={row['screen_delta_mB_vs_baseline']:+.2f}mB",
                flush=True,
            )

        add_df_tmp = pd.DataFrame(add_rows).sort_values("screen_brier_after_cal")
        winners = add_df_tmp[add_df_tmp["screen_delta_vs_baseline"] < 0]["feature"].head(int(args.top_n_combos)).tolist()
        if winners:
            combo_result = run_lodo_subset(
                cv,
                list(dict.fromkeys(current + winners)),
                held_dates,
                iterations=args.iterations,
                depth=args.depth,
                learning_rate=args.learning_rate,
                residual_scale=args.residual_scale,
            )
            print(
                f"[ADDDROP] combo winners={len(winners)} brier={combo_result['screen_brier_after_cal']:.6f} "
                f"vs_base={(combo_result['screen_brier_after_cal'] - baseline['screen_brier_after_cal']) * 1000.0:+.2f}mB",
                flush=True,
            )

    pd.DataFrame(audit_rows).to_csv(out_dir / "candidate_feature_audit.csv", index=False)
    add_df = pd.DataFrame(add_rows).sort_values("screen_brier_after_cal")
    add_df.to_csv(out_dir / ("bundle_feature_screen.csv" if args.mode == "bundles" else "single_feature_add_screen.csv"), index=False)
    payload = {
        "source": "catboost_playoff_v5cD_feature_adddrop_screen",
        "mode": args.mode,
        "cache_path": str(cache_path),
        "held_dates": held_dates,
        "params": {
            "iterations": args.iterations,
            "depth": args.depth,
            "learning_rate": args.learning_rate,
            "residual_scale": args.residual_scale,
        },
        "baseline": baseline,
        "single_feature_results": add_rows,
        "winning_features": winners,
        "combo_result": combo_result,
        "outputs": {
            "candidate_feature_audit": str((out_dir / "candidate_feature_audit.csv").resolve()),
            "screen_results": str((out_dir / ("bundle_feature_screen.csv" if args.mode == "bundles" else "single_feature_add_screen.csv")).resolve()),
        },
    }
    (out_dir / "adddrop_screen_summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[ADDDROP] summary={out_dir / 'adddrop_screen_summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
