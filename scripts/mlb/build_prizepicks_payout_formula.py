"""Fit a PrizePicks payout formula from exact live quote artifacts."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - exercised only when numpy is unavailable
    np = None


SCHEMA_VERSION = "atlas_prizepicks_payout_formula_model_v1"
TOOL_VERSION = "build_prizepicks_payout_formula_v1"
TIER_ORDER = ("GOBLIN", "STANDARD", "DEMON")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/mlb/model/prizepicks_payout_formula.json"),
    )
    parser.add_argument("--ridge-alpha", type=float, default=0.35)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    rows = _exact_slip_rows(root)
    payload = _fit_formula(rows, root=root, ridge_alpha=args.ridge_alpha)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Exact slip quote rows: {len(rows)}")
    metrics = payload.get("train_metrics") or {}
    print(f"MAE={metrics.get('mae')} MAPE={metrics.get('mape')} max_abs_error={metrics.get('max_abs_error')}")
    return 0


def _exact_slip_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "mlb" / "live_runs").glob("**/slips/*.json")):
        if path.name in {"payout_quote_manifest.json", "payout_formula_audit.json", "slips_manifest.json"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for slip in _iter_slips(payload):
            quote = slip.get("payout_quote") if isinstance(slip.get("payout_quote"), dict) else {}
            chosen = quote.get("chosen") if isinstance(quote.get("chosen"), dict) else {}
            if not bool(chosen.get("payout_is_exact")):
                continue
            actual = _float(chosen.get("all_correct"))
            legs = slip.get("legs") if isinstance(slip.get("legs"), list) else []
            if actual <= 0 or len(legs) < 2:
                continue
            rows.append(
                {
                    "source_path": str(path),
                    "family": str(slip.get("family") or _family_from_path(path)),
                    "label": str(slip.get("label") or f"{len(legs)}leg"),
                    "n_legs": len(legs),
                    "tier_counts": _tier_counts(legs),
                    "actual": actual,
                }
            )
    return rows


def _iter_slips(value: Any):
    if isinstance(value, dict):
        if isinstance(value.get("payout_quote"), dict) and isinstance(value.get("legs"), list):
            yield value
        for nested in value.values():
            yield from _iter_slips(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_slips(item)


def _fit_formula(rows: list[dict[str, Any]], *, root: Path, ridge_alpha: float) -> dict[str, Any]:
    feature_names = _feature_names(rows)
    coefficients: dict[str, float] = {}
    if rows and np is not None:
        x = np.array([[_features(row).get(name, 0.0) for name in feature_names] for row in rows], dtype=float)
        y = np.array([math.log(float(row["actual"])) for row in rows], dtype=float)
        ridge = np.eye(len(feature_names), dtype=float) * float(ridge_alpha)
        if feature_names and feature_names[0] == "intercept":
            ridge[0, 0] = 0.0
        beta = np.linalg.pinv(x.T @ x + ridge) @ x.T @ y
        coefficients = {name: round(float(coef), 10) for name, coef in zip(feature_names, beta)}
    else:
        coefficients = _default_coefficients(feature_names)

    predictions = [_predict(row, coefficients) for row in rows]
    errors = [abs(pred - float(row["actual"])) for pred, row in zip(predictions, rows)]
    pct_errors = [err / float(row["actual"]) for err, row in zip(errors, rows) if float(row["actual"]) > 0]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "model_version": "pp_payout_formula_log_linear_v1",
        "model_type": "log_linear_ridge",
        "target": "log(prizepicks_all_correct_multiplier)",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "root": str(root),
            "source_glob": "data/mlb/live_runs/**/slips/*.json",
            "exact_quote_count": len(rows),
            "note": "Uses exact live PrizePicks quote rows from slip JSON artifacts; no replay fallback quotes are used.",
        },
        "ridge_alpha": ridge_alpha,
        "feature_names": feature_names,
        "coefficients": coefficients,
        "clamp": [1.0, 100.0],
        "train_metrics": {
            "mae": round(sum(errors) / len(errors), 6) if errors else None,
            "mape": round(sum(pct_errors) / len(pct_errors), 6) if pct_errors else None,
            "max_abs_error": round(max(errors), 6) if errors else None,
        },
    }


def _feature_names(rows: list[dict[str, Any]]) -> list[str]:
    names = ["intercept", "n_legs", "goblin_count", "standard_count", "demon_count"]
    names.extend(f"leg_count_{size}" for size in range(2, 7))
    family_keys = sorted({_key(row.get("family")) for row in rows if _key(row.get("family"))})
    label_keys = sorted({_key(row.get("label")) for row in rows if _key(row.get("label"))})
    names.extend(f"family_{key}" for key in family_keys)
    names.extend(f"label_{key}" for key in label_keys)
    return names


def _features(row: dict[str, Any]) -> dict[str, float]:
    n_legs = int(row.get("n_legs") or 0)
    tiers = row.get("tier_counts") if isinstance(row.get("tier_counts"), dict) else {}
    values = {
        "intercept": 1.0,
        "n_legs": float(n_legs),
        "goblin_count": float(tiers.get("GOBLIN", 0)),
        "standard_count": float(tiers.get("STANDARD", 0)),
        "demon_count": float(tiers.get("DEMON", 0)),
    }
    for size in range(2, 7):
        values[f"leg_count_{size}"] = 1.0 if n_legs == size else 0.0
    family = _key(row.get("family"))
    label = _key(row.get("label"))
    if family:
        values[f"family_{family}"] = 1.0
    if label:
        values[f"label_{label}"] = 1.0
    return values


def _predict(row: dict[str, Any], coefficients: dict[str, float]) -> float:
    features = _features(row)
    score = sum(float(coefficients.get(name, 0.0)) * float(features.get(name, 0.0)) for name in coefficients)
    try:
        return max(1.0, min(100.0, math.exp(score)))
    except OverflowError:
        return 100.0


def _default_coefficients(feature_names: list[str]) -> dict[str, float]:
    defaults = {
        "intercept": math.log(2.2),
        "n_legs": 0.35,
        "goblin_count": math.log(0.72),
        "standard_count": 0.0,
        "demon_count": math.log(1.18),
    }
    return {name: round(float(defaults.get(name, 0.0)), 10) for name in feature_names}


def _tier_counts(legs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {tier: 0 for tier in TIER_ORDER}
    for leg in legs:
        tier = str(leg.get("tier") or leg.get("odds_type") or "").strip().upper()
        if tier not in counts:
            tier = "STANDARD"
        counts[tier] += 1
    return counts


def _family_from_path(path: Path) -> str:
    stem = path.stem.lower()
    if "demon" in stem:
        return "DemonHunter"
    if "windfall" in stem:
        return "Windfall"
    if "marketed" in stem:
        return "Marketed"
    if "system" in stem:
        return "System"
    return ""


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
