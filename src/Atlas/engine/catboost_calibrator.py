"""CatBoost playoff calibrator -- runtime inference module.

Supports two model kinds, switched by meta.json["model_kind"] (or cfg "kind"):

  1. "CatBoostClassifier" (legacy v1)
       - 34 features (33 GBM base + p_for_cal)
       - predict_proba()[:,1] -> p_cal directly
       - applier modes: replace / blend

  2. "CatBoostRegressor"  (v5cD, residual)
       - N features from meta["features"] (currently 19)
       - cat_features from meta["cat_features"]
       - predict() -> residual
       - p_new = clip(p_for_cal + scale * clip(residual, +/-clip), p_lo, p_hi)
       - scale, clip, p_lo, p_hi all read from meta

Feature columns are pulled directly from the scored DataFrame (the same
columns the resim cache captures from scored_legs_deduped).  No
gbm_ensemble.compute_features() pass is required for the regressor path.

Wire-in point: called from main.py after the GBM ensemble block.
Config key: catboost_playoff_calibrator.enabled
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants -- legacy classifier path
# ---------------------------------------------------------------------------
P_LO_CLF, P_HI_CLF = 0.03, 0.97

BASE_FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
FEATURES_CLF = BASE_FEATS + ["p_for_cal"]
CAT_FEATURES_CLF = ["stat_cat", "tier_cat"]
N_BASE = len(BASE_FEATS)  # 33

# Module-level singleton -- loaded once per process
_model_cache: dict[str, Any] = {}
_meta_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _load_model(model_path: Path, kind: str) -> Any:
    """Load and cache the CatBoost model. Kind is 'classifier' or 'regressor'."""
    key = f"{kind}::{model_path.resolve()}"
    if key in _model_cache:
        return _model_cache[key]

    try:
        from catboost import CatBoostClassifier, CatBoostRegressor  # type: ignore[import]
    except ImportError as e:
        raise ImportError(
            "CatBoost is not installed. Run: python -m pip install catboost"
        ) from e

    if not model_path.exists():
        raise FileNotFoundError(f"CatBoost model not found: {model_path}")

    if kind == "regressor":
        model = CatBoostRegressor()
    else:
        model = CatBoostClassifier()
    model.load_model(str(model_path))
    _model_cache[key] = model
    log.info("[CATBOOST_CAL] Loaded %s: %s (trees=%d)",
             kind, model_path.name, model.tree_count_)
    return model


def _load_meta(meta_path: Path) -> dict[str, Any]:
    key = str(meta_path.resolve())
    if key in _meta_cache:
        return _meta_cache[key]
    if not meta_path.exists():
        _meta_cache[key] = {}
        return {}
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        log.warning("[CATBOOST_CAL] Failed to read meta %s: %r", meta_path, e)
        meta = {}
    _meta_cache[key] = meta
    return meta


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------

def _build_feature_df_classifier(
    scored: pd.DataFrame, logs: pd.DataFrame, ensemble_dir: Path
) -> pd.DataFrame:
    """Compute the 34 features for the classifier path (legacy v1)."""
    from Atlas.engine.gbm_ensemble import (  # type: ignore[import]
        _enrich_te_columns,
        compute_features,
        _ALL_FEATURE_NAMES,
    )

    scored = _enrich_te_columns(scored, ensemble_dir)
    X_full, _ = compute_features(scored, logs)

    actual_base = _ALL_FEATURE_NAMES[:N_BASE]
    if actual_base != BASE_FEATS:
        mismatch = [(i, a, b) for i, (a, b) in enumerate(zip(actual_base, BASE_FEATS)) if a != b]
        raise RuntimeError(
            f"[CATBOOST_CAL] Feature contract mismatch with gbm_ensemble -- "
            f"first discrepancy: {mismatch[:3]}"
        )

    X_base = X_full[:, :N_BASE]
    X_df = pd.DataFrame(X_base, columns=BASE_FEATS, index=scored.index)
    for cat_col in CAT_FEATURES_CLF:
        X_df[cat_col] = X_df[cat_col].astype(int).astype(str)

    p_for_cal = pd.to_numeric(
        scored.get("p_for_cal", pd.Series(0.5, index=scored.index)),
        errors="coerce",
    ).fillna(0.5).clip(P_LO_CLF, P_HI_CLF)
    X_df["p_for_cal"] = p_for_cal.values
    return X_df


def _build_feature_df_regressor(
    scored: pd.DataFrame, features: list[str], cat_features: list[str]
) -> pd.DataFrame:
    """Build feature DataFrame for the regressor path (v5cD).

    Pulls columns directly from `scored`. The resim cache that v5cD trained
    on captured these columns from scored_legs_deduped, so the same columns
    must exist at runtime. Numeric features get NaN -> 0.0; cat features
    get NaN -> 0 then cast to string.

    Special handling: `use_role` is derived from `role_ctx_outs_used > 0` if
    the column is missing (matches trainer behavior).
    `p_for_cal` is taken from scored (set by GBM stage); falls back to p_adj.
    """
    out = pd.DataFrame(index=scored.index)
    cat_set = set(cat_features)

    for col in features:
        if col == "use_role" and col not in scored.columns:
            outs = pd.to_numeric(
                scored.get("role_ctx_outs_used", pd.Series(0, index=scored.index)),
                errors="coerce",
            ).fillna(0).astype(int)
            out[col] = (outs > 0).astype(int)
        elif col == "p_for_cal" and col not in scored.columns:
            out[col] = pd.to_numeric(
                scored.get("p_adj", pd.Series(0.5, index=scored.index)),
                errors="coerce",
            ).fillna(0.5).clip(0.0, 1.0)
        else:
            s = scored.get(col, pd.Series(0.0, index=scored.index))
            out[col] = pd.to_numeric(s, errors="coerce")

        if col in cat_set:
            out[col] = out[col].fillna(0).astype(int).astype(str)
        else:
            out[col] = out[col].fillna(0.0).astype(float)

    return out[features]


# ---------------------------------------------------------------------------
# Main apply function
# ---------------------------------------------------------------------------

def apply_catboost_calibrator(
    scored: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any],
    repo_root: Path,
) -> pd.DataFrame:
    """Apply CatBoost playoff calibrator to scored DataFrame.

    Config keys (catboost_playoff_calibrator):
        enabled:      true/false
        model_path:   path to .cbm
        meta_path:    path to meta.json (kind, features, params)
        kind:         "regressor" or "classifier" (overrides meta)
        ensemble_dir: GBM ensemble dir (classifier path only)
        mode:         "replace" (default) or "blend"
        blend_alpha:  weight on CatBoost when mode=blend
    """
    cat_cfg = cfg.get("catboost_playoff_calibrator", {}) or {}
    if not cat_cfg.get("enabled", False):
        return scored

    # Resolve paths
    model_path_str = cat_cfg.get(
        "model_path", "data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm"
    )
    model_path = Path(model_path_str)
    if not model_path.is_absolute():
        model_path = repo_root / model_path

    meta_path_str = cat_cfg.get(
        "meta_path", "data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json"
    )
    meta_path = Path(meta_path_str)
    if not meta_path.is_absolute():
        meta_path = repo_root / meta_path

    meta = _load_meta(meta_path)

    # Determine kind: cfg overrides meta; default classifier for backwards compat
    kind_cfg = str(cat_cfg.get("kind", "")).strip().lower()
    model_kind_meta = str(meta.get("model_kind", "")).strip().lower()
    if kind_cfg in ("regressor", "classifier"):
        kind = kind_cfg
    elif "regressor" in model_kind_meta:
        kind = "regressor"
    elif "classifier" in model_kind_meta:
        kind = "classifier"
    else:
        kind = "classifier"

    try:
        model = _load_model(model_path, kind)

        if kind == "regressor":
            features = list(meta.get("features") or [])
            cat_features = list(meta.get("cat_features") or [])
            if not features:
                raise RuntimeError(
                    f"[CATBOOST_CAL] Regressor meta missing 'features': {meta_path}"
                )

            scale = float(meta.get("residual_scale", 0.50))
            rclip = float(meta.get("residual_clip", 0.20))
            p_lo = float(meta.get("p_lo", 1e-4))
            p_hi = float(meta.get("p_hi", 1.0 - 1e-4))

            X_df = _build_feature_df_regressor(scored, features, cat_features)

            from catboost import Pool  # type: ignore[import]
            pool = Pool(X_df, cat_features=cat_features) if cat_features else Pool(X_df)
            residual = np.asarray(model.predict(pool), dtype=float)
            residual_clipped = np.clip(residual, -rclip, rclip)

            p_for_cal = pd.to_numeric(
                scored.get("p_for_cal", scored.get("p_adj", 0.5)),
                errors="coerce",
            ).fillna(0.5).clip(0.0, 1.0).values

            p_new = np.clip(p_for_cal + scale * residual_clipped, p_lo, p_hi)

            scored = scored.copy()
            scored["p_catboost_residual"] = residual
            scored["p_catboost"] = p_new

            mode = str(cat_cfg.get("mode", "replace")).strip().lower()
            if mode == "blend":
                alpha = float(cat_cfg.get("blend_alpha", 0.5))
                p_prev = pd.to_numeric(
                    scored.get("p_cal", scored.get("p_for_cal", 0.5)),
                    errors="coerce",
                ).fillna(0.5).values
                scored["p_cal"] = np.clip(
                    alpha * p_new + (1.0 - alpha) * p_prev, p_lo, p_hi
                )
            else:
                scored["p_cal"] = p_new

            print(
                f"[CATBOOST_CAL] regressor/{mode} -- "
                f"residual mean={residual.mean():+.4f} std={residual.std():.4f}, "
                f"p_for_cal mean={p_for_cal.mean():.4f}, "
                f"p_cal mean={float(scored['p_cal'].mean()):.4f}, "
                f"n={len(scored)}, version={meta.get('version', '?')}"
            )

        else:
            # Legacy classifier path
            ens_dir_str = (
                cat_cfg.get("ensemble_dir")
                or (cfg.get("posthoc_calibrator", {}) or {}).get(
                    "ensemble_dir", "data/model/ensemble"
                )
            )
            ensemble_dir = Path(ens_dir_str)
            if not ensemble_dir.is_absolute():
                ensemble_dir = repo_root / ensemble_dir

            X_df = _build_feature_df_classifier(scored, logs, ensemble_dir)

            from catboost import Pool  # type: ignore[import]
            pool = Pool(X_df, cat_features=CAT_FEATURES_CLF)
            p_cat = model.predict_proba(pool)[:, 1]
            p_cat = np.clip(p_cat, P_LO_CLF, P_HI_CLF)

            scored = scored.copy()
            scored["p_catboost"] = p_cat

            mode = str(cat_cfg.get("mode", "replace")).strip().lower()
            if mode == "blend":
                alpha = float(cat_cfg.get("blend_alpha", 0.5))
                p_cal_arr = pd.to_numeric(
                    scored.get("p_cal", scored.get("p_for_cal", 0.5)),
                    errors="coerce",
                ).fillna(0.5).values
                scored["p_cal"] = np.clip(
                    alpha * p_cat + (1.0 - alpha) * p_cal_arr, P_LO_CLF, P_HI_CLF
                )
            else:
                scored["p_cal"] = p_cat

            print(
                f"[CATBOOST_CAL] classifier/{mode} -- "
                f"mean p_catboost={p_cat.mean():.4f}, "
                f"mean p_cal={float(scored['p_cal'].mean()):.4f}, "
                f"n={len(scored)}"
            )

    except Exception as e:
        print(f"[CATBOOST_CAL] ERROR: {e!r} -- falling back to existing p_cal")
        log.exception("[CATBOOST_CAL] Calibration failed")

    return scored
