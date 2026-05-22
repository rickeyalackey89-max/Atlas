from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _numeric_summary(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce")
    filled = values.fillna(0.0)
    nonzero_rate = float((filled.abs() > 1e-12).mean()) if len(filled) else 0.0
    unique_count = int(values.nunique(dropna=True))
    if len(values) == 0:
        status = "missing"
    elif nonzero_rate == 0.0:
        status = "constant_zero"
    elif unique_count <= 1:
        status = "constant_nonzero"
    else:
        status = "active"

    finite = values.replace([np.inf, -np.inf], np.nan)
    return {
        "status": status,
        "nonzero_rate": nonzero_rate,
        "unique_count": unique_count,
        "mean": _safe_float(finite.mean()),
        "min": _safe_float(finite.min()),
        "max": _safe_float(finite.max()),
        "nan_rate": float(values.isna().mean()) if len(values) else 1.0,
    }


def _categorical_summary(series: pd.Series) -> dict[str, Any]:
    values = series.astype(str).fillna("")
    unique_count = int(values.nunique(dropna=True))
    top = values.value_counts(dropna=False).head(8).to_dict()
    return {
        "status": "active" if unique_count > 1 else "constant",
        "unique_count": unique_count,
        "top_values": {str(k): int(v) for k, v in top.items()},
    }


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def _model_meta(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _feature_section(frame: pd.DataFrame, features: list[str], cat_features: set[str] | None = None) -> dict[str, Any]:
    cat_features = cat_features or set()
    items: dict[str, Any] = {}
    for feature in features:
        if feature not in frame.columns:
            items[feature] = {"status": "missing"}
            continue
        if feature in cat_features:
            items[feature] = _categorical_summary(frame[feature])
        else:
            items[feature] = _numeric_summary(frame[feature])

    counts: dict[str, int] = {}
    for stats in items.values():
        status = str(stats.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1

    return {
        "feature_count": len(features),
        "status_counts": counts,
        "features": items,
    }


def build_feature_audit_payload(
    *,
    scored: pd.DataFrame,
    logs: pd.DataFrame,
    cfg: dict[str, Any] | None,
    repo_root: Path,
) -> dict[str, Any]:
    """Build a compact runtime feature audit for live/post-run inspection.

    The active NBA runtime has two surfaces:
    - the 33-feature GBM basis from ensemble_meta.json
    - the promoted 19-feature CatBoost residual contract

    This audit recomputes both feature frames from the same scored legs and
    gamelog store the live model uses, then summarizes missing/constant/active
    features. It is intentionally read-only and does not affect probabilities.
    """

    repo_root = Path(repo_root)
    ensemble_dir_raw = ((cfg or {}).get("posthoc_calibrator", {}) or {}).get("ensemble_dir", "data/model/ensemble")
    ensemble_dir = Path(str(ensemble_dir_raw))
    if not ensemble_dir.is_absolute():
        ensemble_dir = repo_root / ensemble_dir

    ensemble_meta_path = ensemble_dir / "ensemble_meta.json"
    cat_meta_path = repo_root / "data" / "model" / "catboost_playoff" / "catboost_v5cD_full_corpus.meta.json"
    ensemble_meta = _model_meta(ensemble_meta_path)
    cat_meta = _model_meta(cat_meta_path)

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema": "nba_runtime_feature_audit_v1",
        "row_count": int(len(scored)),
        "models": {
            "gbm": {
                "meta_path": str(ensemble_meta_path),
                "version": ensemble_meta.get("version"),
                "feature_count": len(ensemble_meta.get("features") or []),
            },
            "catboost": {
                "meta_path": str(cat_meta_path),
                "version": cat_meta.get("version"),
                "feature_count": len(cat_meta.get("features") or []),
            },
        },
        "gbm": {"error": None},
        "catboost": {"error": None},
        "runtime_columns": {},
        "notes": [
            "Single-game NBA playoff slates can legitimately make game_total_norm and q_blowout constant.",
            "is_b2b is only expected to move on true back-to-back slates.",
        ],
    }

    for col in [
        "role_metrics_mult",
        "zero_dnp_mult",
        "thin_window_mult",
        "single_game_robustness_score",
        "q_blowout",
        "game_total_norm",
        "spread_ok",
        "bp_has",
        "external_prior_n",
    ]:
        if col in scored.columns:
            payload["runtime_columns"][col] = _numeric_summary(scored[col])

    try:
        from Atlas.engine.gbm_ensemble import _ALL_FEATURE_NAMES, _enrich_te_columns, compute_features

        enriched = _enrich_te_columns(scored.copy(), ensemble_dir)
        X_full, _ = compute_features(enriched, logs)
        gbm_frame = pd.DataFrame(X_full, columns=_ALL_FEATURE_NAMES, index=scored.index)
        gbm_features = list(ensemble_meta.get("features") or [])
        payload["gbm"] = _feature_section(gbm_frame, gbm_features)
    except Exception as exc:
        payload["gbm"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        from Atlas.engine.catboost_calibrator import _build_feature_df_regressor

        cat_features = list(cat_meta.get("features") or [])
        cat_cat_features = set(cat_meta.get("cat_features") or [])
        if cat_features:
            cat_frame, diagnostics = _build_feature_df_regressor(
                scored.copy(),
                logs,
                features=cat_features,
                cat_features=list(cat_cat_features),
                ensemble_dir=ensemble_dir,
            )
            payload["catboost"] = _feature_section(cat_frame, cat_features, cat_features=cat_cat_features)
            payload["catboost"]["diagnostics"] = diagnostics
        else:
            payload["catboost"] = {"error": "catboost meta missing features"}
    except Exception as exc:
        payload["catboost"] = {"error": f"{type(exc).__name__}: {exc}"}

    return payload
