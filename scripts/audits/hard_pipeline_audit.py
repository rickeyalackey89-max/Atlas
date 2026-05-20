"""Hard post-run audit for Atlas probability and builder integrity.

This audit is intentionally stricter than the surface audit. It checks:
- source-stage ordering for probability-changing transforms
- probability lineage from p_adj -> p_for_cal -> p_catboost -> p_cal
- external-prior math bounds and flags
- CatBoost feature-contract rebuilds
- published slip artifacts, mirrors, and selected-leg lookup
- duplicate transform call-sites that can drift over time
"""
from __future__ import annotations

import argparse
import filecmp
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LEG_RE = re.compile(
    r"(?P<player>.+?)\s+(?P<direction>OVER|UNDER)\s+"
    r"(?P<stat>[A-Z0-9]+)\s+(?P<line>-?\d+(?:\.\d+)?)\s+"
    r"\((?P<tier>[A-Z]+)\)(?:\s+\[id:(?P<source_projection_id>[^\]]+)\])?"
)

PROB_COLS = [
    "p",
    "p_role",
    "p_adj",
    "p_for_cal",
    "p_catboost",
    "p_cal",
    "p_cal_marketed",
    "p_close",
    "p_close_raw",
    "p_close_role",
]


def _latest_run_dir() -> Path:
    runs = ROOT / "data" / "output" / "runs"
    candidates = [p for p in runs.iterdir() if p.is_dir()] if runs.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.astype("float64")


def _num_fill(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    return _num(df, col, default=default).fillna(default)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    values = df[col]
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    text = values.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    detail: Any | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if detail is not None:
        out["detail"] = detail
    return out


def _line_number(text: str, index: int) -> int | None:
    if index < 0:
        return None
    return text.count("\n", 0, index) + 1


def _find_index(text: str, needle: str) -> int:
    return text.find(needle)


def _manifest_cfg(manifest: dict[str, Any]) -> dict[str, Any]:
    cfg = manifest.get("full_config") if isinstance(manifest, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _source_order_audit() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    main_path = ROOT / "src" / "Atlas" / "engine" / "main.py"
    text = main_path.read_text(encoding="utf-8")
    needles = {
        "score_new_engine": "_run_score_board_new",
        "iael_soft_risk": "apply_iael_soft_risk(scored, iael_df)",
        "external_priors_pre_cat": "EXTERNAL PRIORS (pre-CAT)",
        "p_for_cal_assignment": 'scored["p_for_cal"] = p_adj',
        "raw_slate_guard": "apply_raw_slate_fragility_guard",
        "gbm_ensemble": "apply_gbm_ensemble",
        "catboost": "apply_catboost_calibrator",
        "zero_dnp_postcal": "ZERO-DNP POST-CAL OVERRIDE",
        "prep_optimizer": "run_prep_for_optimizer",
        "builder": "run_build_slips",
        "marketed_builder": "build_marketed_slips",
        "publish": "run_publish_stage",
    }
    positions = {
        name: {
            "index": _find_index(text, needle),
            "line": _line_number(text, _find_index(text, needle)),
        }
        for name, needle in needles.items()
    }

    expected_order = [
        "score_new_engine",
        "iael_soft_risk",
        "external_priors_pre_cat",
        "p_for_cal_assignment",
        "raw_slate_guard",
        "gbm_ensemble",
        "catboost",
        "zero_dnp_postcal",
        "prep_optimizer",
        "builder",
        "marketed_builder",
        "publish",
    ]
    findings: list[dict[str, Any]] = []
    missing = [name for name in expected_order if positions[name]["index"] < 0]
    if missing:
        findings.append(
            _finding("fail", "source_order_missing_stage", "main.py is missing expected stage markers", detail=missing)
        )
    else:
        for left, right in zip(expected_order, expected_order[1:]):
            if positions[left]["index"] >= positions[right]["index"]:
                findings.append(
                    _finding(
                        "fail",
                        "source_order_violation",
                        f"{left} should run before {right}",
                        detail={"left": positions[left], "right": positions[right]},
                    )
                )

    return {
        "file": str(main_path.relative_to(ROOT)),
        "positions": positions,
        "expected_order": expected_order,
    }, findings


def _duplicate_transform_audit() -> dict[str, Any]:
    patterns = {
        "apply_external_priors": "apply_external_priors(",
        "apply_iael_soft_risk": "apply_iael_soft_risk(",
        "apply_minute_risk_guard": "apply_minute_risk_guard(",
        "apply_single_game_script_annotations": "apply_single_game_script_annotations(",
        "apply_raw_slate_fragility_guard": "apply_raw_slate_fragility_guard(",
    }
    files = [
        ROOT / "src" / "Atlas" / "engine" / "main.py",
        ROOT / "src" / "Atlas" / "stages" / "prep_for_optimizer" / "prep_for_optimizer.py",
        ROOT / "src" / "Atlas" / "core" / "slip_builders.py",
        ROOT / "src" / "Atlas" / "core" / "marketed_slip_builder.py",
    ]
    calls: dict[str, list[dict[str, Any]]] = {key: [] for key in patterns}
    for path in files:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for name, pattern in patterns.items():
                if pattern in stripped:
                    calls[name].append(
                        {
                            "file": str(path.relative_to(ROOT)),
                            "line": i,
                            "text": stripped[:220],
                        }
                    )
    return calls


def _artifact_audit(run_dir: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cfg = _manifest_cfg(manifest)
    marketed_enabled = bool((cfg.get("marketed_slips") or {}).get("enabled", False))
    required = [
        "run_manifest.json",
        "scored_legs.csv",
        "scored_legs_deduped.csv",
        "catboost_scale_policy_manifest.json",
        "raw_slate_fragility_guard_manifest.json",
        "single_game_mode_manifest.json",
        "System/recommended_3leg.csv",
        "System/recommended_4leg.csv",
        "System/recommended_5leg.csv",
        "Windfall/recommended_3leg.csv",
        "Windfall/recommended_4leg.csv",
        "Windfall/recommended_5leg.csv",
        "recommended_3leg.csv",
        "recommended_4leg.csv",
        "recommended_5leg.csv",
    ]
    if marketed_enabled:
        required.extend(["marketed_slips.json", "marketed_slips.csv"])

    files = {rel: (run_dir / rel).exists() for rel in required}
    findings: list[dict[str, Any]] = []
    missing = [rel for rel, exists in files.items() if not exists]
    if missing:
        findings.append(_finding("fail", "missing_required_artifacts", "run is missing required artifacts", detail=missing))

    mirrors: list[dict[str, Any]] = []
    for name in ["recommended_3leg.csv", "recommended_4leg.csv", "recommended_5leg.csv"]:
        top = run_dir / name
        system = run_dir / "System" / name
        if top.exists() and system.exists():
            equal = filecmp.cmp(top, system, shallow=False)
            mirrors.append({"top_level": name, "system": f"System/{name}", "byte_equal": bool(equal)})
            if not equal:
                findings.append(
                    _finding(
                        "fail",
                        "system_mirror_mismatch",
                        f"top-level {name} no longer mirrors System/{name}",
                    )
                )

    return {"required_files": files, "system_legacy_mirrors": mirrors}, findings


def _probability_range_audit(df: pd.DataFrame, frame_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for col in [c for c in PROB_COLS if c in df.columns]:
        vals = _num(df, col)
        non_null = vals.dropna()
        out_of_range = vals[(vals < -1e-9) | (vals > 1 + 1e-9)]
        row = {
            "frame": frame_name,
            "column": col,
            "rows": int(len(vals)),
            "null_rows": int(vals.isna().sum()),
            "out_of_range_rows": int(len(out_of_range)),
            "min": float(non_null.min()) if not non_null.empty else None,
            "max": float(non_null.max()) if not non_null.empty else None,
            "mean": float(non_null.mean()) if not non_null.empty else None,
        }
        summary.append(row)
        if row["out_of_range_rows"]:
            findings.append(
                _finding("fail", "probability_out_of_range", f"{frame_name}.{col} contains values outside [0,1]", detail=row)
            )
        if col in {"p_adj", "p_for_cal", "p_cal", "p_catboost"} and row["null_rows"]:
            findings.append(
                _finding("fail", "required_probability_nulls", f"{frame_name}.{col} has null rows", detail=row)
            )
    return summary, findings


def _probability_lineage_audit(
    scored: pd.DataFrame,
    optimizer: pd.DataFrame,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    required = ["p_adj", "p_for_cal", "p_cal", "p_catboost", "p_cal_src", "p_for_cal_src"]
    missing = [col for col in required if col not in scored.columns]
    if missing:
        findings.append(
            _finding("fail", "missing_probability_lineage_columns", "scored_legs.csv missing lineage columns", detail=missing)
        )

    scored_ranges, range_findings = _probability_range_audit(scored, "scored")
    optimizer_ranges, optimizer_range_findings = _probability_range_audit(optimizer, "optimizer")
    findings.extend(range_findings)
    findings.extend(optimizer_range_findings)

    raw_guard_shifted = int(_num_fill(scored, "raw_slate_fragility_guard_shifted", 0.0).sum()) if not scored.empty else 0
    p_adj = _num_fill(scored, "p_adj", 0.5)
    p_for_cal = _num_fill(scored, "p_for_cal", 0.5)
    p_for_cal_diff = (p_for_cal - p_adj).abs()
    max_p_for_cal_diff = float(p_for_cal_diff.max()) if len(p_for_cal_diff) else None
    if raw_guard_shifted <= 0 and max_p_for_cal_diff is not None and max_p_for_cal_diff > 1e-9:
        findings.append(
            _finding(
                "fail",
                "p_for_cal_p_adj_drift_without_guard",
                "p_for_cal differs from p_adj even though raw slate guard did not shift rows",
                detail={"max_abs_diff": max_p_for_cal_diff},
            )
        )

    p_catboost = _num_fill(scored, "p_catboost", 0.5)
    p_cal = _num_fill(scored, "p_cal", 0.5)
    cat_diff = (p_cal - p_catboost).abs()
    diff_mask = cat_diff > 1e-9
    cfg = _manifest_cfg(manifest)
    role_ctx_cfg = cfg.get("role_ctx", {}) if isinstance(cfg.get("role_ctx"), dict) else {}
    zdnp_thresh = float(role_ctx_cfg.get("zero_dnp_postcal_blend_thresh", 1.40) or 1.40)
    zdnp_mask = _num_fill(scored, "zero_dnp_mult", 1.0) >= zdnp_thresh
    zdnp_flip = _bool(scored, "_zero_dnp_flip")
    telemetry_cfg = cfg.get("telemetry", {}) if isinstance(cfg.get("telemetry"), dict) else {}
    active_overlay = bool(telemetry_cfg.get("apply_active_calibration", False))
    allowed_mask = zdnp_mask | zdnp_flip
    if active_overlay:
        allowed_mask = pd.Series(True, index=scored.index)
    unexplained = diff_mask & ~allowed_mask
    if int(unexplained.sum()):
        sample_cols = [c for c in ["player", "stat", "line", "direction", "tier", "p_catboost", "p_cal", "zero_dnp_mult", "_zero_dnp_flip"] if c in scored.columns]
        findings.append(
            _finding(
                "fail",
                "unexplained_post_cat_probability_change",
                "p_cal differs from p_catboost outside known post-CAT override paths",
                detail=scored.loc[unexplained, sample_cols].head(25).to_dict(orient="records"),
            )
        )

    src_counts = {}
    for col in ["p_cal_src", "p_for_cal_src", "catboost_feature_source", "catboost_defaulted_features"]:
        if col in scored.columns:
            src_counts[col] = scored[col].fillna("").astype(str).value_counts().head(20).to_dict()

    return {
        "probability_ranges": scored_ranges + optimizer_ranges,
        "raw_slate_guard_shifted_rows": raw_guard_shifted,
        "p_for_cal_minus_p_adj_max_abs": max_p_for_cal_diff,
        "p_cal_minus_p_catboost_rows": int(diff_mask.sum()),
        "p_cal_minus_p_catboost_allowed_rows": int((diff_mask & allowed_mask).sum()),
        "p_cal_minus_p_catboost_unexplained_rows": int(unexplained.sum()),
        "zero_dnp_postcal_blend_threshold": zdnp_thresh,
        "source_column_counts": src_counts,
    }, findings


def _external_prior_audit(scored: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if scored.empty:
        return {}, findings

    prior_n = _num_fill(scored, "external_prior_n", 0.0)
    delta = _num_fill(scored, "external_prior_delta_p", 0.0)
    cap = _num_fill(scored, "external_prior_cap_applied", 0.0)
    applied = _bool(scored, "external_prior_probability_applied")
    direction = scored["direction"].astype(str).str.upper().str.strip() if "direction" in scored.columns else pd.Series("", index=scored.index)
    sources = (
        scored["external_prior_sources"].astype(str).str.lower()
        if "external_prior_sources" in scored.columns
        else pd.Series("", index=scored.index)
    )
    exact_market = sources.str.contains("bettingpros_market", regex=False, na=False)
    negative_applied = applied & (delta < -1e-12)
    negative_non_exact = negative_applied & ~exact_market

    flag_should_apply = delta.abs() > 1e-12
    flag_false_nonzero = (~applied) & flag_should_apply
    flag_true_zero = applied & ~flag_should_apply
    if int(flag_false_nonzero.sum()):
        findings.append(
            _finding(
                "fail",
                "external_prior_flag_delta_mismatch",
                "external_prior_probability_applied is false while delta_p is materially nonzero",
                detail={"rows": int(flag_false_nonzero.sum())},
            )
        )
    if int(flag_true_zero.sum()):
        findings.append(
            _finding(
                "warn",
                "external_prior_applied_flag_on_zero_delta",
                "external_prior_probability_applied is true on near-zero delta_p rows; current code clamps this going forward",
                detail={"rows": int(flag_true_zero.sum())},
            )
        )

    cap_violation = delta.abs() > (cap.abs() + 1e-9)
    if int(cap_violation.sum()):
        sample = scored.loc[cap_violation, [c for c in ["player", "stat", "direction", "line", "external_prior_delta_p", "external_prior_cap_applied"] if c in scored.columns]]
        findings.append(
            _finding(
                "fail",
                "external_prior_delta_exceeds_cap",
                "external_prior_delta_p exceeds external_prior_cap_applied",
                detail=sample.head(25).to_dict(orient="records"),
            )
        )

    if int(((prior_n > 0) & (cap == 0) & applied).sum()):
        findings.append(
            _finding(
                "fail",
                "external_prior_applied_with_zero_cap",
                "external prior probability applied despite zero row cap",
            )
        )

    if int(negative_non_exact.sum()):
        findings.append(
            _finding(
                "warn",
                "external_prior_negative_delta",
                "projection external priors applied negative probability deltas; verify projection blend",
                detail={"rows": int(negative_non_exact.sum())},
            )
        )

    by_direction: list[dict[str, Any]] = []
    work = pd.DataFrame(
        {
            "direction": direction,
            "prior_n": prior_n,
            "delta": delta,
            "cap": cap,
            "applied": applied.astype(int),
        }
    )
    for d, grp in work.groupby("direction", dropna=False):
        by_direction.append(
            {
                "direction": str(d),
                "prior_rows": int((grp["prior_n"] > 0).sum()),
                "applied_rows": int(grp["applied"].sum()),
                "delta_min": float(grp["delta"].min()) if len(grp) else None,
                "delta_max": float(grp["delta"].max()) if len(grp) else None,
                "cap_max": float(grp["cap"].max()) if len(grp) else None,
            }
        )

    return {
        "prior_rows": int((prior_n > 0).sum()),
        "applied_rows": int(applied.sum()),
        "flag_false_nonzero_rows": int(flag_false_nonzero.sum()),
        "flag_true_zero_rows": int(flag_true_zero.sum()),
        "cap_violation_rows": int(cap_violation.sum()),
        "negative_delta_applied_rows": int(negative_applied.sum()),
        "negative_exact_market_delta_rows": int((negative_applied & exact_market).sum()),
        "negative_non_exact_market_delta_rows": int(negative_non_exact.sum()),
        "by_direction": sorted(by_direction, key=lambda r: r["direction"]),
    }, findings


def _cat_feature_contract_audit(scored: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if scored.empty:
        return {}, findings
    try:
        from Atlas.engine.catboost_calibrator import _build_feature_df_regressor
    except Exception as exc:
        return {"error": f"import failed: {exc}"}, [
            _finding("fail", "catboost_feature_builder_import_failed", "could not import CatBoost feature builder", detail=str(exc))
        ]

    meta_path = ROOT / "data" / "model" / "catboost_playoff" / "catboost_v5cD_full_corpus.meta.json"
    logs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
    if not meta_path.exists() or not logs_path.exists():
        missing = [str(p.relative_to(ROOT)) for p in [meta_path, logs_path] if not p.exists()]
        findings.append(_finding("fail", "catboost_contract_inputs_missing", "CatBoost audit inputs are missing", detail=missing))
        return {"missing_inputs": missing}, findings

    meta = _read_json(meta_path)
    logs = pd.read_csv(logs_path, low_memory=False)
    X, diag = _build_feature_df_regressor(
        scored,
        logs,
        list(meta.get("features") or []),
        list(meta.get("cat_features") or []),
        ROOT / "data" / "model" / "ensemble",
    )
    defaulted = list(diag.get("defaulted_features") or [])
    if defaulted:
        findings.append(
            _finding("fail", "catboost_defaulted_trained_features", "CatBoost feature builder defaulted trained features", detail=defaulted)
        )
    artifact_defaulted = []
    if "catboost_defaulted_features" in scored.columns:
        artifact_defaulted = sorted(
            set(x for x in scored["catboost_defaulted_features"].fillna("").astype(str).tolist() if x)
        )
    if artifact_defaulted:
        findings.append(
            _finding("fail", "catboost_artifact_reports_defaulted_features", "scored artifact reports defaulted CatBoost features", detail=artifact_defaulted)
        )

    reported_counts = sorted(set(_num_fill(scored, "catboost_feature_count", -1).astype(int).tolist())) if "catboost_feature_count" in scored.columns else []
    if reported_counts and reported_counts != [int(len(X.columns))]:
        findings.append(
            _finding(
                "fail",
                "catboost_feature_count_mismatch",
                "reported catboost_feature_count does not match rebuilt feature frame",
                detail={"reported": reported_counts, "rebuilt": int(len(X.columns))},
            )
        )

    return {
        "meta_path": str(meta_path.relative_to(ROOT)),
        "feature_count": int(len(X.columns)),
        "feature_source": diag.get("feature_source"),
        "defaulted_features": defaulted,
        "reported_feature_counts": reported_counts,
        "artifact_defaulted_features": artifact_defaulted,
    }, findings


def _parse_leg(text: Any) -> dict[str, Any] | None:
    match = LEG_RE.search(str(text))
    if not match:
        return None
    out = match.groupdict()
    out["line"] = _safe_float(out.get("line"))
    out["direction"] = str(out.get("direction", "")).upper()
    out["stat"] = str(out.get("stat", "")).upper()
    out["tier"] = str(out.get("tier", "")).upper()
    return out


def _family_for_path(path: Path, run_dir: Path) -> str:
    rel = path.relative_to(run_dir)
    if len(rel.parts) >= 2 and rel.parts[0] in {"System", "Windfall"}:
        return rel.parts[0]
    if path.name.startswith("recommended_"):
        return "SystemLegacyMirror"
    if path.name == "marketed_slips.csv":
        return "Marketed"
    if path.name == "demonhunter.csv":
        return "DemonHunter"
    return "Other"


def _slip_file_paths(run_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for path in run_dir.glob("*.csv"):
        if path.name not in {"scored_legs.csv", "scored_legs_deduped.csv"}:
            paths.append(path)
    for sub in ["System", "Windfall"]:
        paths.extend((run_dir / sub).glob("*.csv"))
    return sorted(paths)


def _selected_legs_from_file(path: Path, run_dir: Path) -> list[dict[str, Any]]:
    df = _read_csv(path)
    out: list[dict[str, Any]] = []
    if df.empty:
        return out
    family = _family_for_path(path, run_dir)
    rel = str(path.relative_to(run_dir))

    if {"player", "direction", "stat", "tier", "line"}.issubset(df.columns):
        for idx, row in df.iterrows():
            out.append(
                {
                    "file": rel,
                    "family": family,
                    "row": int(idx),
                    "slip": str(row.get("slip", "")),
                    "player": str(row.get("player", "")),
                    "direction": str(row.get("direction", "")).upper(),
                    "stat": str(row.get("stat", "")).upper(),
                    "tier": str(row.get("tier", "")).upper(),
                    "line": _safe_float(row.get("line")),
                    "source_projection_id": str(row.get("source_projection_id", "")),
                    "displayed_p": _safe_float(row.get("p_cal")),
                }
            )
        return out

    leg_cols = [c for c in df.columns if re.fullmatch(r"leg_\d+", str(c))]
    for idx, row in df.iterrows():
        slip_label = str(row.get("n_legs", ""))
        for col in leg_cols:
            parsed = _parse_leg(row.get(col, ""))
            if parsed:
                parsed.update({"file": rel, "family": family, "row": int(idx), "slip": slip_label, "displayed_p": None})
                out.append(parsed)
    return out


def _prop_lookup(df: pd.DataFrame) -> dict[tuple[str, str, str, float, str], pd.Series]:
    lookup: dict[tuple[str, str, str, float, str], pd.Series] = {}
    if df.empty:
        return lookup
    needed = {"player", "stat", "direction", "line", "tier"}
    if not needed.issubset(df.columns):
        return lookup
    for _, row in df.iterrows():
        line = _safe_float(row.get("line"))
        if line is None:
            continue
        key = (
            str(row.get("player", "")).strip().lower(),
            str(row.get("stat", "")).strip().upper(),
            str(row.get("direction", "")).strip().upper(),
            round(float(line), 4),
            str(row.get("tier", "")).strip().upper(),
        )
        lookup[key] = row
    return lookup


def _slip_output_audit(run_dir: Path, optimizer: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    paths = _slip_file_paths(run_dir)
    selected: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    for path in paths:
        legs = _selected_legs_from_file(path, run_dir)
        selected.extend(legs)
        file_rows.append(
            {
                "file": str(path.relative_to(run_dir)),
                "family": _family_for_path(path, run_dir),
                "csv_rows": int(len(_read_csv(path))),
                "parsed_legs": int(len(legs)),
            }
        )

    selected_df = pd.DataFrame(selected)
    if selected_df.empty:
        findings.append(_finding("warn", "no_selected_legs_parsed", "no selected legs were parsed from slip outputs"))
        return {"files": file_rows, "selected_legs": 0}, findings

    production = selected_df[selected_df["family"] != "SystemLegacyMirror"].copy()
    invalid = production[
        (production["direction"] == "UNDER") & (production["tier"].isin(["GOBLIN", "DEMON"]))
    ]
    if not invalid.empty:
        findings.append(
            _finding("fail", "invalid_under_tier_selected", "UNDER legs selected on GOBLIN/DEMON tiers", detail=invalid.head(25).to_dict(orient="records"))
        )

    exact_key = ["family", "player", "direction", "stat", "line"]
    dup_family = (
        production.groupby(exact_key, dropna=False)
        .agg(files=("file", lambda s: sorted(set(s))), rows=("row", "size"))
        .reset_index()
    )
    dup_family = dup_family[dup_family["rows"] > 1]
    if not dup_family.empty:
        findings.append(
            _finding(
                "fail",
                "duplicate_exact_prop_within_family",
                "same player/stat/direction/line appears more than once within a slip family",
                detail=dup_family.head(25).to_dict(orient="records"),
            )
        )

    lookup = _prop_lookup(optimizer)
    unmatched: list[dict[str, Any]] = []
    marketed_p_mismatches: list[dict[str, Any]] = []
    for leg in production.to_dict(orient="records"):
        line = _safe_float(leg.get("line"))
        if line is None:
            unmatched.append(leg)
            continue
        key = (
            str(leg.get("player", "")).strip().lower(),
            str(leg.get("stat", "")).strip().upper(),
            str(leg.get("direction", "")).strip().upper(),
            round(float(line), 4),
            str(leg.get("tier", "")).strip().upper(),
        )
        match = lookup.get(key)
        if match is None:
            unmatched.append(leg)
            continue
        if leg.get("family") == "Marketed" and leg.get("displayed_p") is not None:
            source_p = _safe_float(match.get("p_cal_marketed", match.get("p_cal")))
            displayed = _safe_float(leg.get("displayed_p"))
            if source_p is not None and displayed is not None and abs(round(source_p, 4) - displayed) > 1e-4:
                marketed_p_mismatches.append({**leg, "optimizer_p_cal_marketed": source_p})

    if unmatched:
        findings.append(
            _finding("fail", "selected_leg_missing_from_optimizer_pool", "selected slip leg was not found in scored_legs_deduped", detail=unmatched[:25])
        )
    if marketed_p_mismatches:
        findings.append(
            _finding("fail", "marketed_probability_mismatch", "marketed CSV p_cal does not match optimizer p_cal_marketed", detail=marketed_p_mismatches[:25])
        )

    by_family = []
    for family, grp in production.groupby("family", dropna=False):
        by_family.append(
            {
                "family": str(family),
                "selected_legs": int(len(grp)),
                "under_legs": int((grp["direction"] == "UNDER").sum()),
                "over_legs": int((grp["direction"] == "OVER").sum()),
                "unique_exact_props": int(
                    grp[["player", "direction", "stat", "line"]].drop_duplicates().shape[0]
                ),
            }
        )

    marketed_order: list[str] = []
    if (run_dir / "marketed_slips.csv").exists():
        marketed = _read_csv(run_dir / "marketed_slips.csv")
        if "slip" in marketed.columns:
            marketed_order = marketed["slip"].astype(str).drop_duplicates().tolist()
            expected = sorted(marketed_order, key=lambda label: int(str(label).split("-")[0]) if str(label).split("-")[0].isdigit() else 999)
            if marketed_order != expected:
                findings.append(
                    _finding(
                        "warn",
                        "marketed_slip_order_not_ascending",
                        "marketed slips are not emitted in 3-leg, 4-leg, 5-leg order",
                        detail={"actual": marketed_order, "expected": expected},
                    )
                )

    return {
        "files": file_rows,
        "selected_legs": int(len(production)),
        "unmatched_selected_legs": int(len(unmatched)),
        "marketed_p_mismatches": int(len(marketed_p_mismatches)),
        "duplicate_exact_props_within_family": int(len(dup_family)),
        "by_family": sorted(by_family, key=lambda r: r["family"]),
        "marketed_slip_order": marketed_order,
    }, findings


def audit_run(run_dir: Path) -> dict[str, Any]:
    manifest = _read_json(run_dir / "run_manifest.json")
    scored = _read_csv(run_dir / "scored_legs.csv")
    optimizer = _read_csv(run_dir / "scored_legs_deduped.csv")

    findings: list[dict[str, Any]] = []

    source_order, f = _source_order_audit()
    findings.extend(f)
    duplicate_calls = _duplicate_transform_audit()
    artifact, f = _artifact_audit(run_dir, manifest)
    findings.extend(f)
    lineage, f = _probability_lineage_audit(scored, optimizer, manifest)
    findings.extend(f)
    external_priors, f = _external_prior_audit(scored)
    findings.extend(f)
    cat_features, f = _cat_feature_contract_audit(scored)
    findings.extend(f)
    slips, f = _slip_output_audit(run_dir, optimizer)
    findings.extend(f)

    external_calls = duplicate_calls.get("apply_external_priors", [])
    prep_path = ROOT / "src" / "Atlas" / "stages" / "prep_for_optimizer" / "prep_for_optimizer.py"
    prep_text = prep_path.read_text(encoding="utf-8") if prep_path.exists() else ""
    external_guarded = "_external_prior_probability_already_applied" in prep_text
    if len(external_calls) > 2 and not external_guarded:
        findings.append(
            _finding(
                "warn",
                "multiple_external_prior_call_sites",
                "external prior transform has multiple call-sites without an idempotency guard",
                detail=external_calls,
            )
        )
    elif len(external_calls) > 1:
        findings.append(
            _finding(
                "info",
                "external_prior_dual_use_call_sites",
                "external priors have guarded pre-CAT and optimizer-prep call-sites",
                detail=external_calls,
            )
        )
    iael_calls = duplicate_calls.get("apply_iael_soft_risk", [])
    if len(iael_calls) > 2:
        findings.append(
            _finding(
                "warn",
                "multiple_iael_soft_risk_call_sites",
                "IAEL soft risk has multiple call-sites; verify it remains idempotent and non-probability-changing",
                detail=iael_calls,
            )
        )
    elif len(iael_calls) > 1:
        findings.append(
            _finding(
                "info",
                "iael_soft_risk_dual_use_call_sites",
                "IAEL soft risk is applied pre-CAT and again to the optimizer frame after dedupe",
                detail=iael_calls,
            )
        )
    for name in ["apply_minute_risk_guard", "apply_single_game_script_annotations"]:
        calls = duplicate_calls.get(name, [])
        if len(calls) > 1:
            findings.append(
                _finding(
                    "info",
                    f"{name}_dual_use_call_sites",
                    f"{name} is used for artifact telemetry and builder scoring; keep these call-sites deterministic",
                    detail=calls,
                )
            )

    severity_rank = {"fail": 3, "warn": 2, "info": 1}
    worst = max((severity_rank.get(finding["severity"], 0) for finding in findings), default=0)
    verdict = "FAIL" if worst >= 3 else ("WARN" if worst == 2 else "PASS")
    counts = {
        "fail": sum(1 for item in findings if item["severity"] == "fail"),
        "warn": sum(1 for item in findings if item["severity"] == "warn"),
        "info": sum(1 for item in findings if item["severity"] == "info"),
    }

    return {
        "verdict": verdict,
        "finding_counts": counts,
        "failures": [item["message"] for item in findings if item["severity"] == "fail"],
        "warnings": [item["message"] for item in findings if item["severity"] == "warn"],
        "infos": [item["message"] for item in findings if item["severity"] == "info"],
        "findings": findings,
        "run_dir": str(run_dir),
        "rows": {
            "scored_legs": int(len(scored)),
            "scored_legs_deduped": int(len(optimizer)),
        },
        "source_order": source_order,
        "duplicate_transform_call_sites": duplicate_calls,
        "artifacts": artifact,
        "probability_lineage": lineage,
        "external_priors": external_priors,
        "catboost_feature_contract": cat_features,
        "slip_outputs": slips,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard audit an Atlas run from probability surface to slip outputs.")
    parser.add_argument("--run-dir", default=None, help="Run directory. Defaults to latest data/output/runs/*.")
    parser.add_argument("--json-out", default=None, help="Optional path to write JSON audit.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir

    result = audit_run(run_dir)
    text = json.dumps(result, indent=2, sort_keys=False, default=str)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if result["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
