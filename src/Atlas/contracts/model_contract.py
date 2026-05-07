"""
src/Atlas/contracts/model_contract.py

CANONICAL MODEL CONTRACT — v18
==============================
⚠️  READ BEFORE MODIFYING ANY MODEL PARAMETERS  ⚠️

This module is the single source of truth for the v18 production model.
It is loaded and validated at the start of every live run via the
orchestrator. If any parameter drifts from the canonical contract,
the run will emit a loud warning (and optionally hard-stop).

To promote a new model version:
  1. Train and validate against the current baseline.
  2. Confirm improvement on the reader corpus.
  3. Update THIS file with the new canonical values.
  4. Update data/model/ensemble/ensemble_meta.json to match.
  5. Get explicit approval before merging.

DO NOT change individual values in config.yaml, ensemble_meta.json, or
the engine code without updating this contract first.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────
# Canonical v18 contract values
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelContract:
    version: str = "v18"
    architecture: str = "dn-d11nl50-top7-33feat"

    # Ensemble
    seeds: Tuple[int, ...] = (65536, 9999, 137, 999, 98765, 54321, 12345)
    temperature: float = 1.04
    n_rounds: int = 200
    feature_count: int = 33
    cat_features: Tuple[str, ...] = ("stat_cat", "tier_cat")

    # OVER GBM (slim: fewer leaves for enriched q_blowout)
    over_max_depth: int = 8
    over_num_leaves: int = 30
    over_min_child_samples: int = 200
    over_lambda_l2: float = 1.0

    # UNDER GBM
    under_max_depth: int = 11
    under_num_leaves: int = 50
    under_min_child_samples: int = 150
    under_lambda_l2: float = 6.0

    # Calibration bounds
    p_clamp_min: float = 0.03
    p_clamp_max: float = 0.97

    # Baseline metrics (for regression detection)
    baseline_lodo_brier: float = 0.201529
    baseline_raw_brier: float = 0.216372
    baseline_training_legs: int = 173495
    baseline_training_dates: int = 50


CONTRACT = ModelContract()
V18 = CONTRACT  # current production alias


# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────

@dataclass
class ContractViolation:
    field: str
    expected: object
    actual: object

    def __str__(self) -> str:
        return f"  {self.field}: expected {self.expected!r}, got {self.actual!r}"


def validate_ensemble_meta(meta_path: Path, contract: ModelContract = CONTRACT) -> List[ContractViolation]:
    """Validate ensemble_meta.json against the canonical contract."""
    violations: List[ContractViolation] = []

    if not meta_path.exists():
        violations.append(ContractViolation("ensemble_meta.json", "exists", "MISSING"))
        return violations

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    checks = [
        ("version", contract.version, meta.get("version")),
        ("temperature", contract.temperature, meta.get("temperature")),
        ("n_rounds", contract.n_rounds, meta.get("n_rounds")),
        ("feature_count", contract.feature_count,
         len(meta.get("features", [])) if "features" in meta else None),
        ("seeds", list(contract.seeds), meta.get("ensemble_seeds")),
    ]

    params_over = meta.get("params_over", {})
    checks += [
        ("over.max_depth", contract.over_max_depth, params_over.get("max_depth")),
        ("over.num_leaves", contract.over_num_leaves, params_over.get("num_leaves")),
        ("over.min_child_samples", contract.over_min_child_samples, params_over.get("min_child_samples")),
        ("over.lambda_l2", contract.over_lambda_l2, params_over.get("lambda_l2")),
    ]

    params_under = meta.get("params_under", {})
    checks += [
        ("under.max_depth", contract.under_max_depth, params_under.get("max_depth")),
        ("under.num_leaves", contract.under_num_leaves, params_under.get("num_leaves")),
        ("under.min_child_samples", contract.under_min_child_samples, params_under.get("min_child_samples")),
        ("under.lambda_l2", contract.under_lambda_l2, params_under.get("lambda_l2")),
    ]

    for field_name, expected, actual in checks:
        if actual != expected:
            violations.append(ContractViolation(field_name, expected, actual))

    return violations


def validate_config(config: dict, contract: ModelContract = CONTRACT) -> List[ContractViolation]:
    """Validate relevant config.yaml values against the contract."""
    violations: List[ContractViolation] = []

    pc = config.get("posthoc_calibrator", {})
    ensemble_dir = pc.get("ensemble_dir", "")
    if ensemble_dir and "ensemble" not in str(ensemble_dir):
        violations.append(ContractViolation(
            "posthoc_calibrator.ensemble_dir",
            "contains 'ensemble'",
            ensemble_dir,
        ))

    return violations


def enforce_contract(
    repo_root: Path,
    config: Optional[dict] = None,
    hard_stop: bool = False,
) -> bool:
    """
    Run all contract validations. Returns True if clean.

    Called by orchestrator.run_today() at pipeline startup.
    If hard_stop=True, raises RuntimeError on any violation.
    """
    meta_path = repo_root / "data" / "model" / "ensemble" / "ensemble_meta.json"
    violations = validate_ensemble_meta(meta_path)

    if config:
        violations.extend(validate_config(config))

    if not violations:
        print(f"[CONTRACT] {CONTRACT.version} model contract validated — {CONTRACT.feature_count} features, "
              f"T={CONTRACT.temperature}, {len(CONTRACT.seeds)} seeds. All clear.")
        return True

    # Violations found
    print("\n" + "=" * 72, file=sys.stderr)
    print("⚠️  MODEL CONTRACT VIOLATION DETECTED", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(f"Contract version: {CONTRACT.version}", file=sys.stderr)
    print(f"Reference: src/Atlas/contracts/model_contract.py", file=sys.stderr)
    print(f"Baseline doc: src/Atlas/contracts/model_contract.py", file=sys.stderr)
    print("", file=sys.stderr)
    print("Violations:", file=sys.stderr)
    for v in violations:
        print(str(v), file=sys.stderr)
    print("", file=sys.stderr)
    print("Update the contract to match the promoted model BEFORE", file=sys.stderr)
    print("changing model parameters.", file=sys.stderr)
    print("=" * 72, file=sys.stderr)

    if hard_stop:
        raise RuntimeError(
            f"MODEL CONTRACT VIOLATION: {len(violations)} issue(s). "
            "Fix the contract or the model files before running."
        )

    return False
