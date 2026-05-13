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
gbm_ensemble.compute_features() pass is required for the legacy classifier
path. The promoted regressor path rebuilds the GBM feature surface and slices
the 19-feature CatBoost residual contract from it.

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


DEFAULT_RESIDUAL_SCALE_POLICY = {
    "enabled": False,
    "aggressive_residual_scale": 0.55,
    "defensive_residual_scale": 0.10,
    "thin_slate_games_max": 2,
    "thin_slate_q_out_frac_mean_min": 0.05,
    "thin_slate_q_blowout_p90_min": 0.45,
    "blowout_q_p90_min": 0.55,
    "blowout_role_ctx_share_max": 0.30,
    "no_role_ctx_share_max": 0.01,
    "low_external_prior_bp_has_mean_max": 0.10,
}


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

    p_for_cal = _coerce_numeric_series(
        scored["p_for_cal"] if "p_for_cal" in scored.columns else 0.5,
        scored.index,
        default=0.5,
    ).clip(P_LO_CLF, P_HI_CLF)
    X_df["p_for_cal"] = p_for_cal.to_numpy(dtype="float64")
    return X_df


def _build_feature_df_regressor(
    scored: pd.DataFrame,
    logs: pd.DataFrame,
    features: list[str],
    cat_features: list[str],
    ensemble_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build feature DataFrame for the regressor path (v5cD).

    Builds the same GBM feature surface used by the resim cache/trainer, then
    slices it to the CatBoost residual model's feature contract.

    Special handling: `use_role` is derived from `role_ctx_outs_used > 0` if
    needed (matches trainer behavior).
    `p_for_cal` is taken from scored (set by GBM stage); falls back to p_adj.
    """
    from Atlas.engine.gbm_ensemble import (  # type: ignore[import]
        _ALL_FEATURE_NAMES,
        _enrich_te_columns,
        compute_features,
    )

    enriched = _enrich_te_columns(scored, ensemble_dir)
    X_full, _ = compute_features(enriched, logs)
    if X_full.shape[1] != len(_ALL_FEATURE_NAMES):
        raise RuntimeError(
            "[CATBOOST_CAL] GBM feature surface shape mismatch: "
            f"got {X_full.shape[1]} columns, expected {len(_ALL_FEATURE_NAMES)}"
        )

    gbm_features = pd.DataFrame(X_full, columns=_ALL_FEATURE_NAMES, index=scored.index)
    out = pd.DataFrame(index=scored.index)
    cat_set = set(cat_features)
    defaulted_features: list[str] = []

    for col in features:
        if col == "use_role":
            outs = _coerce_numeric_series(
                scored["role_ctx_outs_used"] if "role_ctx_outs_used" in scored.columns else 0,
                scored.index,
                default=0.0,
            ).astype(int)
            out[col] = (outs > 0).astype(int)
        elif col == "p_for_cal":
            p_adj_source = scored["p_adj"] if "p_adj" in scored.columns else 0.5
            out[col] = _coerce_numeric_series(
                p_adj_source,
                scored.index,
                default=0.5,
            ).clip(0.0, 1.0)
            if "p_for_cal" in scored.columns:
                raw_p_for_cal = pd.to_numeric(scored[col], errors="coerce")
                if not isinstance(raw_p_for_cal, pd.Series):
                    raw_p_for_cal = pd.Series(raw_p_for_cal, index=scored.index)
                out[col] = raw_p_for_cal.reindex(scored.index).fillna(out[col]).clip(0.0, 1.0)
        elif col in gbm_features.columns:
            out[col] = _coerce_numeric_series(gbm_features[col], scored.index, default=0.0)
        elif col in scored.columns:
            out[col] = _coerce_numeric_series(scored[col], scored.index, default=0.0)
        else:
            defaulted_features.append(col)
            out[col] = pd.Series(0.0, index=scored.index)

        if col in cat_set:
            out[col] = out[col].fillna(0).astype(int).astype(str)
        else:
            out[col] = out[col].fillna(0.0).astype(float)

    if defaulted_features:
        raise RuntimeError(
            "[CATBOOST_CAL] Regressor feature contract missing runtime features: "
            + ", ".join(defaulted_features)
        )

    diagnostics = {
        "feature_source": "gbm_compute_features",
        "feature_count": len(features),
        "defaulted_features": defaulted_features,
    }
    return out[features], diagnostics


def _numeric_series(scored: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in scored.columns:
        return pd.Series(np.full(len(scored), default, dtype="float64"), index=scored.index)
    values = pd.to_numeric(scored[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=scored.index)
    return values.fillna(default)


def _coerce_numeric_series(values: Any, index: pd.Index, default: float) -> pd.Series:
    """Convert scalar/array/Series input into a float Series on the target index."""
    if values is None:
        raw = pd.Series(np.full(len(index), default, dtype="float64"), index=index)
    elif isinstance(values, pd.Series):
        raw = values.reindex(index)
    elif np.isscalar(values):
        raw = pd.Series(np.full(len(index), float(values), dtype="float64"), index=index)
    else:
        raw = pd.Series(values, index=index)

    numeric = pd.to_numeric(raw, errors="coerce")
    if not isinstance(numeric, pd.Series):
        numeric = pd.Series(numeric, index=index)
    return numeric.fillna(default).astype(float)


def _probability_array(values: Any, index: pd.Index, default: float = 0.5) -> np.ndarray:
    """Return a clipped float64 probability array for CatBoost arithmetic."""
    return (
        _coerce_numeric_series(values, index, default)
        .clip(0.0, 1.0)
        .to_numpy(dtype="float64")
    )


def _merge_residual_scale_policy(cat_cfg: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    policy = dict(DEFAULT_RESIDUAL_SCALE_POLICY)

    meta_policy = meta.get("residual_scale_policy")
    if isinstance(meta_policy, dict):
        policy.update(meta_policy)

    cfg_policy = cat_cfg.get("residual_scale_policy")
    if isinstance(cfg_policy, dict):
        policy.update(cfg_policy)

    for key in [
        "aggressive_residual_scale",
        "defensive_residual_scale",
        "thin_slate_q_out_frac_mean_min",
        "thin_slate_q_blowout_p90_min",
        "blowout_q_p90_min",
        "blowout_role_ctx_share_max",
        "no_role_ctx_share_max",
        "low_external_prior_bp_has_mean_max",
    ]:
        if key in policy:
            policy[key] = float(policy[key])
    if "thin_slate_games_max" in policy:
        policy["thin_slate_games_max"] = int(policy["thin_slate_games_max"])
    policy["enabled"] = bool(policy.get("enabled", False))
    return policy


def resolve_residual_scale(
    scored: pd.DataFrame,
    cat_cfg: dict[str, Any],
    meta: dict[str, Any],
    *,
    fallback_scale: float,
) -> tuple[float, dict[str, Any]]:
    """Resolve runtime residual scale from pregame slate metrics only."""

    policy = _merge_residual_scale_policy(cat_cfg, meta)
    metrics: dict[str, Any] = {
        "policy_enabled": bool(policy.get("enabled", False)),
        "policy_triggered": False,
        "policy_reasons": [],
    }
    if scored.empty or not policy.get("enabled", False):
        return fallback_scale, metrics

    games = int(scored["game_id"].nunique()) if "game_id" in scored.columns else 0
    q_out_frac = _numeric_series(scored, "q_out_frac", default=0.0)
    q_blowout = _numeric_series(scored, "q_blowout", default=0.0)
    role_outs = _numeric_series(scored, "role_ctx_outs_used", default=0.0)
    if "bp_has" in scored.columns:
        bp_has = _numeric_series(scored, "bp_has", default=0.0)
    elif "external_prior_n" in scored.columns:
        bp_has = (_numeric_series(scored, "external_prior_n", default=0.0) > 0.0).astype(float)
    else:
        bp_has = pd.Series(np.zeros(len(scored), dtype="float64"), index=scored.index)

    q_out_frac_mean = float(q_out_frac.mean())
    q_blowout_p90 = float(q_blowout.quantile(0.90))
    role_ctx_share = float((role_outs > 0.0).mean())
    bp_has_mean = float(bp_has.mean())

    metrics.update(
        {
            "games": games,
            "q_out_frac_mean": q_out_frac_mean,
            "q_blowout_p90": q_blowout_p90,
            "role_ctx_outs_used_share_gt0": role_ctx_share,
            "bp_has_mean": bp_has_mean,
        }
    )

    reasons: list[str] = []
    if (
        games <= int(policy["thin_slate_games_max"])
        and q_out_frac_mean >= float(policy["thin_slate_q_out_frac_mean_min"])
        and q_blowout_p90 >= float(policy["thin_slate_q_blowout_p90_min"])
    ):
        reasons.append("thin_injury_uncertainty")
    if q_blowout_p90 >= float(policy["blowout_q_p90_min"]) and role_ctx_share <= float(policy["blowout_role_ctx_share_max"]):
        reasons.append("high_blowout_limited_role_context")
    if role_ctx_share <= float(policy["no_role_ctx_share_max"]) and bp_has_mean <= float(policy["low_external_prior_bp_has_mean_max"]):
        reasons.append("no_role_low_external_prior")

    triggered = bool(reasons)
    metrics["policy_triggered"] = triggered
    metrics["policy_reasons"] = reasons
    if triggered:
        return float(policy["defensive_residual_scale"]), metrics
    return float(policy["aggressive_residual_scale"]), metrics


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

            scale_default = float(cat_cfg.get("residual_scale", meta.get("residual_scale", 0.50)))
            rclip = float(meta.get("residual_clip", 0.20))
            p_lo = float(meta.get("p_lo", 1e-4))
            p_hi = float(meta.get("p_hi", 1.0 - 1e-4))
            scale, scale_metrics = resolve_residual_scale(
                scored,
                cat_cfg,
                meta,
                fallback_scale=scale_default,
            )

            ens_dir_str = (
                cat_cfg.get("ensemble_dir")
                or (cfg.get("posthoc_calibrator", {}) or {}).get(
                    "ensemble_dir", "data/model/ensemble"
                )
            )
            ensemble_dir = Path(ens_dir_str)
            if not ensemble_dir.is_absolute():
                ensemble_dir = repo_root / ensemble_dir

            X_df, feature_diagnostics = _build_feature_df_regressor(
                scored,
                logs,
                features,
                cat_features,
                ensemble_dir,
            )

            from catboost import Pool  # type: ignore[import]
            pool = Pool(X_df, cat_features=cat_features) if cat_features else Pool(X_df)
            residual = np.asarray(model.predict(pool), dtype=float)
            residual_clipped = np.clip(residual, -rclip, rclip)

            p_source: Any
            if "p_for_cal" in scored.columns:
                p_source = scored["p_for_cal"]
            elif "p_adj" in scored.columns:
                p_source = scored["p_adj"]
            else:
                p_source = 0.5
            p_for_cal = _probability_array(p_source, scored.index, default=0.5)

            p_new = np.clip(p_for_cal + (scale * residual_clipped), p_lo, p_hi)

            scored = scored.copy()
            scored["p_catboost_residual"] = residual
            scored["p_catboost"] = p_new
            scored["catboost_model_version"] = str(meta.get("version", ""))
            scored["catboost_residual_scale"] = scale
            scored["catboost_scale_policy_enabled"] = bool(scale_metrics.get("policy_enabled", False))
            scored["catboost_scale_policy_triggered"] = bool(scale_metrics.get("policy_triggered", False))
            scored["catboost_scale_policy_reasons"] = ",".join(scale_metrics.get("policy_reasons", []) or [])
            scored["catboost_feature_source"] = str(feature_diagnostics.get("feature_source", ""))
            scored["catboost_feature_count"] = int(feature_diagnostics.get("feature_count", len(features)))
            scored["catboost_defaulted_features"] = ",".join(feature_diagnostics.get("defaulted_features", []) or [])
            for key in [
                "games",
                "q_out_frac_mean",
                "q_blowout_p90",
                "role_ctx_outs_used_share_gt0",
                "bp_has_mean",
            ]:
                if key in scale_metrics:
                    scored[f"catboost_scale_{key}"] = scale_metrics[key]

            mode = str(cat_cfg.get("mode", "replace")).strip().lower()
            if mode == "blend":
                alpha = float(cat_cfg.get("blend_alpha", 0.5))
                if "p_cal" in scored.columns:
                    prev_source = scored["p_cal"]
                elif "p_for_cal" in scored.columns:
                    prev_source = scored["p_for_cal"]
                else:
                    prev_source = 0.5
                p_prev = _probability_array(prev_source, scored.index, default=0.5)
                scored["p_cal"] = np.clip(
                    alpha * p_new + (1.0 - alpha) * p_prev, p_lo, p_hi
                )
            else:
                scored["p_cal"] = p_new

            print(
                f"[CATBOOST_CAL] regressor/{mode} -- "
                f"residual mean={residual.mean():+.4f} std={residual.std():.4f}, "
                f"scale={scale:.2f}, "
                f"scale_policy={scale_metrics.get('policy_triggered', False)}"
                f"({','.join(scale_metrics.get('policy_reasons', []) or [])}), "
                f"features={feature_diagnostics.get('feature_source', '?')}:{feature_diagnostics.get('feature_count', len(features))}, "
                f"p_for_cal mean={p_for_cal.mean():.4f}, "
                f"p_cal mean={float(scored['p_cal'].mean()):.4f}, "
                f"n={len(scored)}, version={meta.get('version', '?')}"
            )
            if scale_metrics.get("policy_triggered", False):
                print(
                    "[CATBOOST_DEFENSE] ACTIVE -- "
                    f"residual_scale={scale:.2f}, "
                    f"reasons={','.join(scale_metrics.get('policy_reasons', []) or [])}, "
                    f"games={scale_metrics.get('games')}, "
                    f"q_out_frac_mean={scale_metrics.get('q_out_frac_mean'):.4f}, "
                    f"q_blowout_p90={scale_metrics.get('q_blowout_p90'):.4f}, "
                    f"role_ctx_share={scale_metrics.get('role_ctx_outs_used_share_gt0'):.4f}, "
                    f"bp_has_mean={scale_metrics.get('bp_has_mean'):.4f}"
                )
            elif scale_metrics.get("policy_enabled", False):
                print(
                    "[CATBOOST_DEFENSE] inactive -- "
                    f"residual_scale={scale:.2f}, "
                    f"games={scale_metrics.get('games')}, "
                    f"q_out_frac_mean={scale_metrics.get('q_out_frac_mean'):.4f}, "
                    f"q_blowout_p90={scale_metrics.get('q_blowout_p90'):.4f}, "
                    f"role_ctx_share={scale_metrics.get('role_ctx_outs_used_share_gt0'):.4f}, "
                    f"bp_has_mean={scale_metrics.get('bp_has_mean'):.4f}"
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
                if "p_cal" in scored.columns:
                    prev_source = scored["p_cal"]
                elif "p_for_cal" in scored.columns:
                    prev_source = scored["p_for_cal"]
                else:
                    prev_source = 0.5
                p_cal_arr = _probability_array(prev_source, scored.index, default=0.5)
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
