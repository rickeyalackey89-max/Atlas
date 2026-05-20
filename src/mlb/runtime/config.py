"""Active MLB operational config helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from mlb.runtime.paths import repo_root

DEFAULT_CONFIG_RELATIVE_PATH = Path("config") / "sports" / "mlb.yaml"
CONFIG_SCHEMA_VERSION = "atlas_mlb_operational_config_v1"


def active_mlb_config_path(root: Path | None = None) -> Path:
    """Return the default active MLB config path for a repo root."""

    base = root or repo_root()
    return base / DEFAULT_CONFIG_RELATIVE_PATH


def load_active_mlb_config(root: Path | None = None, path: Path | None = None) -> dict[str, Any]:
    """Load the active MLB operational config.

    Test fixtures may run from temporary roots without a config file. In that
    case we return a minimal disabled config instead of failing the pipeline.
    Real repo runs should always resolve the config and emit its hash.
    """

    config_path = path or active_mlb_config_path(root)
    if not config_path.exists():
        return {
            "sport": "mlb",
            "status": "missing",
            "schema_version": CONFIG_SCHEMA_VERSION,
            "config_version": "missing",
            "contract_name": "missing",
        }
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"MLB config must be a mapping: {config_path}")
    return payload


def active_mlb_config_manifest(root: Path | None = None, path: Path | None = None) -> dict[str, Any]:
    """Return the config identity payload that is written into run manifests."""

    config_path = path or active_mlb_config_path(root)
    exists = config_path.exists()
    payload = load_active_mlb_config(root=root, path=config_path)
    raw_bytes = config_path.read_bytes() if exists else b""
    slips = payload.get("slips") if isinstance(payload.get("slips"), dict) else {}
    kernels = payload.get("kernels") if isinstance(payload.get("kernels"), dict) else {}
    cat = kernels.get("cat_residual") if isinstance(kernels.get("cat_residual"), dict) else {}
    probability = kernels.get("probability") if isinstance(kernels.get("probability"), dict) else {}
    market_sources = payload.get("market_sources") if isinstance(payload.get("market_sources"), dict) else {}
    features = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    readiness_gates = features.get("readiness_gates") if isinstance(features.get("readiness_gates"), dict) else {}
    return {
        "schema_version": str(payload.get("schema_version") or CONFIG_SCHEMA_VERSION),
        "config_version": str(payload.get("config_version") or ""),
        "contract_name": str(payload.get("contract_name") or ""),
        "path": str(config_path),
        "exists": exists,
        "sha256": hashlib.sha256(raw_bytes).hexdigest() if exists else "",
        "active_probability_kernel": str(probability.get("active_version") or ""),
        "active_simulation_kernel": str(probability.get("simulation_version") or ""),
        "active_calibration_version": str(cat.get("active_version") or ""),
        "active_calibration_artifact": str(cat.get("active_artifact") or ""),
        "active_market_source": str(market_sources.get("primary") or ""),
        "active_slip_builder_version": str(slips.get("active_builder_version") or ""),
        "readiness_gates": dict(readiness_gates),
    }


def stable_config_hash(payload: dict[str, Any]) -> str:
    """Hash a decoded config payload after deterministic JSON normalization."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
