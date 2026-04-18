"""
Config fingerprinting for Atlas runs and trainers.

Every run and every trainer result must record which config and model
produced it.  This module provides the shared building blocks.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sanitize_keys(obj: Any) -> Any:
    """Recursively convert non-string dict keys to strings for JSON serialization."""
    if isinstance(obj, dict):
        return {str(k): _sanitize_keys(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_keys(v) for v in obj]
    return obj


def config_fingerprint(cfg: dict) -> str:
    """Deterministic SHA-256 (first 16 hex chars) of the full config dict."""
    canonical = json.dumps(_sanitize_keys(cfg), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def read_ensemble_meta(ensemble_dir: str | Path | None) -> dict:
    """Read ensemble_meta.json if it exists, else empty dict."""
    if ensemble_dir is None:
        return {}
    meta_path = Path(ensemble_dir) / "ensemble_meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_manifest(
    *,
    source: str,
    cfg: dict,
    ensemble_dir: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a manifest dict suitable for embedding in any results file.

    Parameters
    ----------
    source : str
        Identifier for what produced this manifest (e.g. "kernel_trainer_v1",
        "leg_trainer_v5_ev", "run_publish").
    cfg : dict
        The full config.yaml dict loaded at runtime.
    ensemble_dir : str | Path | None
        Path to the ensemble directory (for reading ensemble_meta.json).
    extra : dict | None
        Additional key-value pairs to include in the manifest.
    """
    ensemble_meta = read_ensemble_meta(ensemble_dir)
    blowout = cfg.get("blowout", {}) or {}
    role_ctx = cfg.get("role_ctx", {}) or {}

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "source": source,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config_fingerprint": config_fingerprint(cfg),
        "ensemble_version": ensemble_meta.get("version", "unknown"),
        "ensemble_lodo_brier": ensemble_meta.get("lodo_brier_ensemble"),
        "ensemble_features": len(ensemble_meta.get("features", [])),
        "kernel_params": {
            "spread_sd": blowout.get("spread_sd"),
            "threshold_margin": blowout.get("threshold_margin"),
            "star_minute_drop": blowout.get("star_minute_drop"),
            "role_minute_drop": blowout.get("role_minute_drop"),
            "post_sim_exponent": blowout.get("post_sim_exponent"),
            "rate_min_correlation": blowout.get("rate_min_correlation"),
            "thin_window_games": blowout.get("thin_window_games"),
            "thin_window_max_mult": blowout.get("thin_window_max_mult"),
            "opp_defense_strength": blowout.get("opp_defense_strength"),
            "rate_std_multiplier_by_stat": blowout.get("rate_std_multiplier_by_stat", {}),
        },
        "role_ctx": {
            "projection_clamp_lo": role_ctx.get("projection_clamp_lo"),
            "projection_clamp_hi": role_ctx.get("projection_clamp_hi"),
            "variance_k": role_ctx.get("variance_k"),
            "under_relief_factor": role_ctx.get("factor"),
            "under_relief_q_min": role_ctx.get("q_min"),
            "under_relief_haircut_min": role_ctx.get("haircut_min"),
        },
    }
    if extra:
        manifest.update(extra)
    return manifest


def load_config_and_fingerprint(
    config_path: str | Path | None = None,
    ensemble_dir: str | Path | None = None,
) -> tuple[dict, str, dict]:
    """
    Convenience: load config.yaml, compute fingerprint, build manifest dict.

    Returns (cfg, fingerprint_str, manifest_dict).
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parents[3] / "config.yaml"
    config_path = Path(config_path)
    with open(config_path) as f:
        cfg = __import__("yaml").safe_load(f) or {}
    fp = config_fingerprint(cfg)
    if ensemble_dir is None:
        ensemble_dir = cfg.get("posthoc_calibrator", {}).get("ensemble_dir")
    manifest = build_manifest(source="standalone", cfg=cfg, ensemble_dir=ensemble_dir)
    return cfg, fp, manifest
