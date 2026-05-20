"""PrizePicks payout formula estimates and live quote audit artifacts."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORMULA_MODEL_SCHEMA_VERSION = "atlas_prizepicks_payout_formula_model_v1"
FORMULA_AUDIT_SCHEMA_VERSION = "atlas_prizepicks_payout_formula_audit_v1"
FORMULA_TOOL_VERSION = "prizepicks_payout_formula_v1"

DEFAULT_POWER_MULTIPLIERS = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
DEFAULT_TIER_FACTORS = {"GOBLIN": 0.72, "STANDARD": 1.0, "DEMON": 1.18}
DEFAULT_FAMILY_FACTORS = {
    "marketed": 1.0,
    "system": 1.0,
    "system_winprob": 1.0,
    "windfall": 0.92,
    "windfall_winprob": 0.92,
    "demonhunter": 1.08,
}
TIER_ORDER = ("GOBLIN", "STANDARD", "DEMON")


def estimate_payout_formula(
    legs: list[dict[str, Any]],
    *,
    family: str = "",
    label: str = "",
    sport: str = "",
    model_path: str | Path | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate PrizePicks all-correct payout from leg count and tier mix."""

    n_legs = len(legs)
    tier_counts = tier_counts_from_legs(legs)
    loaded_model = model if isinstance(model, dict) else load_formula_model(model_path, sport=sport)
    if loaded_model:
        estimate = _predict_from_model(
            loaded_model,
            n_legs=n_legs,
            tier_counts=tier_counts,
            family=family,
            label=label,
        )
    else:
        estimate = _predict_default(n_legs=n_legs, tier_counts=tier_counts, family=family)

    estimate.update(
        {
            "schema_version": FORMULA_AUDIT_SCHEMA_VERSION,
            "tool_version": FORMULA_TOOL_VERSION,
            "sport": str(sport or "").lower(),
            "family": family,
            "label": label,
            "n_legs": n_legs,
            "tier_counts": tier_counts,
        }
    )
    return estimate


def payout_formula_audit_row(
    *,
    legs: list[dict[str, Any]],
    family: str = "",
    label: str = "",
    quote: dict[str, Any] | None = None,
    sport: str = "",
    model_path: str | Path | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one formula-vs-actual audit row for a quoted slip."""

    formula = estimate_payout_formula(
        legs,
        family=family,
        label=label,
        sport=sport,
        model_path=model_path,
        model=model,
    )
    chosen = (quote or {}).get("chosen") if isinstance((quote or {}).get("chosen"), dict) else {}
    actual = _optional_float(chosen.get("all_correct"))
    actual_is_exact = bool(chosen.get("payout_is_exact"))
    formula_mult = _optional_float(formula.get("formula_payout_mult"))
    abs_error = None
    pct_error = None
    if actual is not None and actual > 0 and formula_mult is not None and actual_is_exact:
        abs_error = abs(formula_mult - actual)
        pct_error = abs_error / actual
    return {
        "sport": str(sport or "").lower(),
        "family": family,
        "label": label,
        "slip_id": f"{family}:{label}" if family or label else "",
        "n_legs": formula.get("n_legs", 0),
        "tier_counts": formula.get("tier_counts", {}),
        "formula_payout_mult": formula_mult,
        "formula_source": formula.get("formula_source"),
        "formula_model_version": formula.get("formula_model_version"),
        "actual_payout_mult": actual,
        "actual_is_exact": actual_is_exact,
        "actual_source": "prizepicks_game_types" if actual_is_exact else str((quote or {}).get("source") or ""),
        "quote_status": str((quote or {}).get("quote_status") or ""),
        "quote_key": str((quote or {}).get("quote_key") or ""),
        "abs_error": round(abs_error, 6) if abs_error is not None else None,
        "pct_error": round(pct_error, 6) if pct_error is not None else None,
        "formula": formula,
    }


def write_payout_formula_audit(
    path: str | Path,
    *,
    rows: list[dict[str, Any]],
    run_id: str = "",
    run_mode: str = "",
    sport: str = "",
    model_path: str | Path | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a run-level formula-vs-quote artifact."""

    loaded_model = model if isinstance(model, dict) else load_formula_model(model_path, sport=sport)
    exact_rows = [
        row for row in rows
        if bool(row.get("actual_is_exact"))
        and _optional_float(row.get("actual_payout_mult")) is not None
        and _optional_float(row.get("formula_payout_mult")) is not None
    ]
    abs_errors = [_optional_float(row.get("abs_error")) for row in exact_rows]
    abs_errors = [value for value in abs_errors if value is not None]
    pct_errors = [_optional_float(row.get("pct_error")) for row in exact_rows]
    pct_errors = [value for value in pct_errors if value is not None]
    payload = {
        "schema_version": FORMULA_AUDIT_SCHEMA_VERSION,
        "tool_version": FORMULA_TOOL_VERSION,
        "generated_at_utc": _utc_now(),
        "sport": str(sport or "").lower(),
        "run_id": run_id,
        "run_mode": run_mode,
        "formula_model": _model_summary(loaded_model),
        "row_count": len(rows),
        "exact_compare_count": len(exact_rows),
        "summary": {
            "mae": round(sum(abs_errors) / len(abs_errors), 6) if abs_errors else None,
            "mape": round(sum(pct_errors) / len(pct_errors), 6) if pct_errors else None,
            "max_abs_error": round(max(abs_errors), 6) if abs_errors else None,
        },
        "rows": rows,
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_sanitize(payload), indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return payload


def tier_counts_from_legs(legs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {tier: 0 for tier in TIER_ORDER}
    for leg in legs:
        tier = normalize_tier(leg.get("tier") or leg.get("odds_type") or leg.get("projection_type"))
        if tier not in counts:
            tier = "STANDARD"
        counts[tier] += 1
    return counts


def normalize_tier(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if text in {"GOBLIN", "DISCOUNT", "ALT", "ALTS", "BELOW_ALT", "BELOW_ALTS"}:
        return "GOBLIN"
    if text in {"DEMON", "MORE", "ABOVE_ALT", "ABOVE_ALTS"}:
        return "DEMON"
    if text == "STANDARD":
        return "STANDARD"
    return text or "STANDARD"


def load_formula_model(value: dict[str, Any] | str | Path | None = None, *, sport: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        return value if value.get("schema_version") == FORMULA_MODEL_SCHEMA_VERSION else {}
    path = Path(value).expanduser() if value is not None else _default_formula_model_path(sport=sport)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != FORMULA_MODEL_SCHEMA_VERSION:
        return {}
    return payload


def _predict_from_model(
    model: dict[str, Any],
    *,
    n_legs: int,
    tier_counts: dict[str, int],
    family: str,
    label: str,
) -> dict[str, Any]:
    features = _feature_map(n_legs=n_legs, tier_counts=tier_counts, family=family, label=label)
    coefficients = model.get("coefficients") if isinstance(model.get("coefficients"), dict) else {}
    score = 0.0
    for name, coef in coefficients.items():
        score += _float(coef) * _float(features.get(name))
    clamp = model.get("clamp") if isinstance(model.get("clamp"), list) else [1.0, 100.0]
    lower = _float(clamp[0]) if clamp else 1.0
    upper = _float(clamp[1]) if len(clamp) > 1 else 100.0
    try:
        estimate = math.exp(score)
    except OverflowError:
        estimate = upper
    estimate = max(lower, min(upper, estimate))
    return {
        "formula_payout_mult": round(estimate, 6),
        "formula_source": "trained_log_linear_tier_mix",
        "formula_model_version": str(model.get("model_version") or model.get("tool_version") or ""),
        "features": features,
    }


def _predict_default(*, n_legs: int, tier_counts: dict[str, int], family: str) -> dict[str, Any]:
    base = float(DEFAULT_POWER_MULTIPLIERS.get(int(n_legs), 0.0) or 0.0)
    if base <= 0:
        estimate = 0.0
    else:
        estimate = base
        for tier, count in tier_counts.items():
            estimate *= float(DEFAULT_TIER_FACTORS.get(tier, 1.0)) ** int(count)
        estimate *= float(DEFAULT_FAMILY_FACTORS.get(_key(family), 1.0))
    return {
        "formula_payout_mult": round(max(0.0, estimate), 6),
        "formula_source": "default_tier_mix_formula",
        "formula_model_version": "default_v1",
        "base_power_multiplier": base,
        "tier_factors": dict(DEFAULT_TIER_FACTORS),
        "family_factor": float(DEFAULT_FAMILY_FACTORS.get(_key(family), 1.0)),
    }


def _feature_map(*, n_legs: int, tier_counts: dict[str, int], family: str, label: str) -> dict[str, float]:
    family_key = _key(family)
    label_key = _key(label)
    features = {
        "intercept": 1.0,
        "n_legs": float(n_legs),
        "goblin_count": float(tier_counts.get("GOBLIN", 0)),
        "standard_count": float(tier_counts.get("STANDARD", 0)),
        "demon_count": float(tier_counts.get("DEMON", 0)),
    }
    for size in range(2, 7):
        features[f"leg_count_{size}"] = 1.0 if int(n_legs) == size else 0.0
    if family_key:
        features[f"family_{family_key}"] = 1.0
    if label_key:
        features[f"label_{label_key}"] = 1.0
    return features


def _default_formula_model_path(*, sport: str = "") -> Path | None:
    env_path = os.environ.get("ATLAS_PP_PAYOUT_FORMULA_PATH")
    if env_path:
        return Path(env_path).expanduser()
    sport_key = str(sport or "").strip().lower()
    relative_paths = []
    if sport_key == "mlb":
        relative_paths.append(Path("data") / "mlb" / "model" / "prizepicks_payout_formula.json")
    else:
        relative_paths.append(Path("data") / "model" / "prizepicks_payout_formula.json")
    relative_paths.append(Path("data") / "mlb" / "model" / "prizepicks_payout_formula.json")
    search_roots = [Path.cwd(), *Path(__file__).resolve().parents]
    for root in search_roots:
        for relative in relative_paths:
            candidate = root / relative
            if candidate.exists():
                return candidate
    return None


def _model_summary(model: dict[str, Any]) -> dict[str, Any]:
    if not model:
        return {
            "schema_version": FORMULA_MODEL_SCHEMA_VERSION,
            "model_version": "default_v1",
            "formula_source": "default_tier_mix_formula",
            "tier_factors": dict(DEFAULT_TIER_FACTORS),
            "family_factors": dict(DEFAULT_FAMILY_FACTORS),
        }
    return {
        "schema_version": model.get("schema_version"),
        "tool_version": model.get("tool_version"),
        "model_version": model.get("model_version"),
        "model_type": model.get("model_type"),
        "source": model.get("source"),
        "train_metrics": model.get("train_metrics"),
    }


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(value) for value in obj]
    return obj


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _float(value: Any) -> float:
    parsed = _optional_float(value)
    return float(parsed) if parsed is not None else 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
