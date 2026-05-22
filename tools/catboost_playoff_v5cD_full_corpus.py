"""Train final v5cD full-corpus CatBoost residual regressor.

Trains a SINGLE model on every row in a strict-fidelity cache (no holdout) and
saves the CatBoost model file used by runtime inference. The promoted feature
contract, training params, and residual scale are CLI-controlled so production
can match a selected LODO candidate exactly.

Outputs:
    data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm
    data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json
"""
from __future__ import annotations

import json
import pathlib
import pickle
import time
import warnings
import argparse
from datetime import datetime

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
V5B_PATH      = ROOT / "data" / "model" / "catboost_playoff_v5b_lodo.json"
OUT_DIR       = ROOT / "data" / "model" / "catboost_playoff"
MODEL_OUT     = OUT_DIR / "catboost_v5cD_full_corpus.cbm"
META_OUT      = OUT_DIR / "catboost_v5cD_full_corpus.meta.json"

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

# v5cD architecture constants (must match runtime applier exactly)
RESIDUAL_CLIP  = 0.20
RESIDUAL_SCALE = 0.50
P_LO, P_HI     = 0.03, 0.97

PARAMS = dict(
    iterations=600,
    depth=5,
    learning_rate=0.075,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=100,  # show progress every 100 iters
)


def parse_feature_list(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    values: list[str] = []
    for item in raw:
        for part in str(item).replace(",", " ").split():
            part = part.strip()
            if part:
                values.append(part)
    return values


def load_feature_contract(path: pathlib.Path | None = None) -> tuple[list[str], str]:
    if path is not None:
        with open(path, "r") as f:
            payload = json.load(f)
        features = payload.get("features") or payload.get("v5b_features") or []
        if not features:
            raise ValueError(f"No feature contract found in {path}")
        return list(features), str(path)

    current_meta = OUT_DIR / "catboost_v5cD_full_corpus.meta.json"
    if current_meta.is_file():
        with open(current_meta, "r") as f:
            payload = json.load(f)
        features = payload.get("features") or []
        if features:
            return list(features), str(current_meta)

    with open(V5B_PATH, "r") as f:
        payload = json.load(f)
    return list(payload["v5b_features"]), str(V5B_PATH)


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def prep_X(df, features):
    cat_in = [c for c in CAT_FEATURES_ALL if c in features]
    X = df[features].copy()
    for col in features:
        if col in cat_in:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int).astype(str)
        else:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)
    return X, cat_in


def apply_residual(p, r, *, residual_scale: float = RESIDUAL_SCALE):
    return np.clip(p + residual_scale * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP),
                   P_LO, P_HI)


def main() -> int:
    ap = argparse.ArgumentParser(description="Train v5cD full-corpus CatBoost residual regressor.")
    ap.add_argument("--cache-path", default=str(CACHE_PATH), help="Input cache pickle path.")
    ap.add_argument("--model-out", default=str(MODEL_OUT), help="Output CatBoost model path.")
    ap.add_argument("--meta-out", default=str(META_OUT), help="Output metadata JSON path.")
    ap.add_argument("--version", default="catboost_playoff_v5cD", help="Version string written to metadata.")
    ap.add_argument("--residual-scale", type=float, default=RESIDUAL_SCALE, help="Default runtime residual scale.")
    ap.add_argument("--policy-defensive-scale", type=float, default=None, help="Optional slate-policy defensive residual scale.")
    ap.add_argument("--iterations", type=int, default=PARAMS["iterations"], help="CatBoost iterations.")
    ap.add_argument("--depth", type=int, default=PARAMS["depth"], help="CatBoost tree depth.")
    ap.add_argument("--learning-rate", type=float, default=PARAMS["learning_rate"], help="CatBoost learning rate.")
    ap.add_argument("--l2-leaf-reg", type=float, default=PARAMS["l2_leaf_reg"], help="CatBoost L2 leaf regularization.")
    ap.add_argument("--min-data-in-leaf", type=int, default=PARAMS["min_data_in_leaf"], help="CatBoost min_data_in_leaf.")
    ap.add_argument("--features", nargs="*", help="Explicit feature list. Space or comma separated.")
    ap.add_argument("--feature-contract", default=None, help="Optional JSON file with a 'features' list.")
    ap.add_argument("--lodo-path", default=None, help="LODO report JSON that justified this promotion.")
    ap.add_argument("--notes", default="", help="Free-form promotion notes stored in metadata.")
    args = ap.parse_args()
    params = dict(PARAMS)
    params.update(
        iterations=args.iterations,
        depth=args.depth,
        learning_rate=args.learning_rate,
        l2_leaf_reg=args.l2_leaf_reg,
        min_data_in_leaf=args.min_data_in_leaf,
    )

    cache_path = pathlib.Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    model_out = pathlib.Path(args.model_out)
    if not model_out.is_absolute():
        model_out = ROOT / model_out
    meta_out = pathlib.Path(args.meta_out)
    if not meta_out.is_absolute():
        meta_out = ROOT / meta_out

    print("=" * 80, flush=True)
    print("v5cD FULL-CORPUS Trainer (residual regressor)", flush=True)
    print("=" * 80, flush=True)

    explicit_features = parse_feature_list(args.features)
    if explicit_features:
        features = explicit_features
        feature_source = "cli:--features"
    else:
        feature_contract = pathlib.Path(args.feature_contract) if args.feature_contract else None
        if feature_contract is not None and not feature_contract.is_absolute():
            feature_contract = ROOT / feature_contract
        features, feature_source = load_feature_contract(feature_contract)
    print(f"features ({len(features)}) from {feature_source}: {features}", flush=True)
    print(flush=True)

    # Load cache
    print(f"Loading cache: {cache_path}", flush=True)
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                        .fillna(0).astype(int) > 0).astype(int)

    hit      = cv["hit"].astype(float).to_numpy()
    p_in     = cv["p_for_cal"].to_numpy()
    dates    = sorted(cv["game_date"].astype(str).str[:10].unique().tolist())
    print(f"  {len(cv):,} legs | {len(dates)} dates", flush=True)
    print(f"  Date range: {dates[0]} -> {dates[-1]}", flush=True)
    print(flush=True)

    # Prepare features
    residual_tgt = hit - p_in
    X, cat_in = prep_X(cv, features)
    print(f"  Features: {len(features)} | Categoricals: {cat_in}", flush=True)
    print(f"  Residual target: mean={residual_tgt.mean():+.4f}  "
          f"std={residual_tgt.std():.4f}  "
          f"range=[{residual_tgt.min():.4f}, {residual_tgt.max():.4f}]", flush=True)
    print(flush=True)

    # Baseline (no calibration)
    b_baseline = brier(hit, p_in)
    print(f"Baseline Brier (p_for_cal alone): {b_baseline:.6f}", flush=True)
    print(flush=True)

    # Train on full corpus
    print("Training full-corpus model (no holdout)...", flush=True)
    print(f"  iter={params['iterations']}  depth={params['depth']}  "
          f"lr={params['learning_rate']}  l2={params['l2_leaf_reg']}", flush=True)
    print("-" * 80, flush=True)

    t0 = time.time()
    pool = Pool(X, label=residual_tgt, cat_features=cat_in)
    model = CatBoostRegressor(**params)
    model.fit(pool)
    elapsed = time.time() - t0

    print("-" * 80, flush=True)
    print(f"Training complete in {elapsed:.1f}s  ({model.tree_count_} trees)", flush=True)
    print(flush=True)

    # In-sample sanity check (NOT a generalization metric)
    pred_resid = model.predict(pool)
    p_after = apply_residual(p_in, pred_resid, residual_scale=args.residual_scale)
    b_after = brier(hit, p_after)
    print(f"In-sample Brier after calibration: {b_after:.6f}  "
          f"({(b_after - b_baseline) * 1000:+.2f} mB vs baseline)", flush=True)
    print("  (LODO is the real generalization metric -- this is just a fit check)", flush=True)

    # Feature importance
    importances = dict(zip(features, model.get_feature_importance().tolist()))
    print("\nFeature importances:", flush=True)
    for f, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True):
        print(f"  {f:<25s}  {imp:>8.2f}", flush=True)

    # Save model
    model_out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_out))
    print(f"\nSaved model: {model_out}", flush=True)

    # Save meta — runtime applier reads this
    meta = {
        "version": args.version,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_kind": "CatBoostRegressor",
        "target": "hit - p_for_cal",
        "applier": "p + RESIDUAL_SCALE * clip(residual, -RESIDUAL_CLIP, RESIDUAL_CLIP)",
        "residual_scale": args.residual_scale,
        "residual_clip":  RESIDUAL_CLIP,
        "p_lo": P_LO,
        "p_hi": P_HI,
        "features":     features,
        "cat_features": cat_in,
        "n_features":   len(features),
        "params":       {k: (str(v) if not isinstance(v, (int, float, str, bool)) else v)
                         for k, v in params.items()},
        "feature_source": feature_source,
        "cache_path":   str(cache_path),
        "lodo_path":    str(args.lodo_path or ""),
        "promotion_notes": args.notes,
        "n_legs":       int(len(cv)),
        "n_dates":      len(dates),
        "dates":        dates,
        "baseline_brier": round(b_baseline, 6),
        "in_sample_brier_after": round(b_after, 6),
        "feature_importances": importances,
        "tree_count": int(model.tree_count_),
        "elapsed_sec": round(elapsed, 1),
    }
    if args.policy_defensive_scale is not None:
        meta["residual_scale_policy"] = {
            "enabled": True,
            "aggressive_residual_scale": args.residual_scale,
            "defensive_residual_scale": args.policy_defensive_scale,
            "thin_slate_games_max": 2,
            "thin_slate_q_out_frac_mean_min": 0.05,
            "blowout_q_p90_min": 0.55,
            "blowout_role_ctx_share_max": 0.30,
            "no_role_ctx_share_max": 0.01,
            "low_external_prior_bp_has_mean_max": 0.10,
            "source_audit": "logs/cat_residual_policy_trigger_audit_20260512/summary.json",
        }
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_out, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved meta:  {meta_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
