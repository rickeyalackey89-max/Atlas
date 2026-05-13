"""Audit live Atlas run surfaces from scored legs through slip outputs.

This is a post-run integrity audit. It does not judge whether the picks will
win; it checks whether the probability surface and builder outputs are coherent
for a live run.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LEG_RE = re.compile(
    r"(?P<player>.+?)\s+(?P<direction>OVER|UNDER)\s+"
    r"(?P<stat>[A-Z0-9]+)\s+(?P<line>-?\d+(?:\.\d+)?)\s+"
    r"\((?P<tier>[A-Z]+)\)"
)


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


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.fillna(default).astype(float)


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


def _describe_numeric(series: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"mean": None, "p50": None, "p90": None, "max": None, "min": None}
    return {
        "mean": float(values.mean()),
        "p50": float(values.quantile(0.50)),
        "p90": float(values.quantile(0.90)),
        "max": float(values.max()),
        "min": float(values.min()),
    }


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _direction_tier_surface(scored: pd.DataFrame) -> list[dict[str, Any]]:
    if scored.empty or not {"tier", "direction", "p_cal"}.issubset(scored.columns):
        return []

    work = scored.copy()
    work["p_cal"] = _num(work, "p_cal")
    rows: list[dict[str, Any]] = []
    for (tier, direction), grp in work.groupby(["tier", "direction"], dropna=False):
        p = grp["p_cal"]
        rows.append(
            {
                "tier": str(tier),
                "direction": str(direction),
                "rows": int(len(grp)),
                "players": int(grp["player"].nunique()) if "player" in grp.columns else None,
                "p_cal": _describe_numeric(p),
                "count_p_cal_ge_50": int((p >= 0.50).sum()),
                "count_p_cal_ge_55": int((p >= 0.55).sum()),
                "count_p_cal_ge_60": int((p >= 0.60).sum()),
                "count_p_cal_ge_65": int((p >= 0.65).sum()),
            }
        )
    return sorted(rows, key=lambda r: (r["tier"], r["direction"]))


def _under_eligible_summary(scored: pd.DataFrame, manifest: dict[str, Any]) -> dict[str, Any]:
    if scored.empty or "direction" not in scored.columns:
        return {}

    full_config = manifest.get("full_config") if isinstance(manifest, dict) else {}
    marketed_cfg = full_config.get("marketed_slips", {}) if isinstance(full_config, dict) else {}
    slip_cfg = full_config.get("slip_build", {}) if isinstance(full_config, dict) else {}

    work = scored.copy()
    work["p_cal"] = _num(work, "p_cal")
    work["q_out_frac"] = _num(work, "q_out_frac", default=0.0)
    direction = work["direction"].astype(str).str.upper().str.strip()
    tier = work["tier"].astype(str).str.upper().str.strip() if "tier" in work.columns else ""
    stat = work["stat"].astype(str).str.upper().str.strip() if "stat" in work.columns else ""

    under = work[direction == "UNDER"].copy()
    standard_under = work[(direction == "UNDER") & (tier == "STANDARD")].copy()

    marketed_min_raw = (
        marketed_cfg.get("min_raw_thresholds", {}) if isinstance(marketed_cfg, dict) else {}
    )
    standard_floor = float(marketed_min_raw.get("STANDARD", 0.0) or 0.0)
    marketed_excluded = {
        str(item).upper()
        for item in (
            marketed_cfg.get("excluded_stats")
            or marketed_cfg.get("exclude_stats")
            or []
        )
    } | {
        str(item).split("_")[0].upper()
        for item in marketed_cfg.get("exclude_stat_directions", [])
        if str(item).lower().endswith("_under")
    }
    exclude_q = float(marketed_cfg.get("exclude_q_out_frac_gt", 0.0) or 0.0)
    exclude_questionable = bool(marketed_cfg.get("exclude_questionable", False))

    eligible_mask = (direction == "UNDER") & (tier == "STANDARD")
    if standard_floor > 0.0:
        eligible_mask &= work["p_cal"] >= standard_floor
    if marketed_excluded:
        eligible_mask &= ~stat.isin(marketed_excluded)
    if exclude_questionable or exclude_q >= 0.0:
        eligible_mask &= work["q_out_frac"] <= exclude_q

    system_floor = float(slip_cfg.get("min_leg_prob", 0.0) or 0.0) if isinstance(slip_cfg, dict) else 0.0
    system_mask = (direction == "UNDER") & (tier == "STANDARD")
    if system_floor > 0.0:
        system_mask &= work["p_cal"] >= system_floor

    top_cols = [
        c
        for c in [
            "player",
            "team",
            "stat",
            "tier",
            "direction",
            "line",
            "p_adj",
            "p_for_cal",
            "p_cal",
            "external_prior_cap_applied",
            "external_prior_delta_p",
            "external_prior_n",
            "q_out_frac",
        ]
        if c in work.columns
    ]
    top_under = (
        under.sort_values("p_cal", ascending=False)[top_cols]
        .head(15)
        .to_dict(orient="records")
    )

    return {
        "under_rows": int(len(under)),
        "standard_under_rows": int(len(standard_under)),
        "standard_under_p_cal": _describe_numeric(standard_under["p_cal"]) if not standard_under.empty else {},
        "marketed_standard_under_floor": standard_floor,
        "marketed_standard_under_eligible_rows": int(eligible_mask.sum()),
        "system_min_leg_prob": system_floor,
        "system_standard_under_rows_above_floor": int(system_mask.sum()),
        "top_under_by_p_cal": top_under,
    }


def _external_prior_audit(scored: pd.DataFrame) -> dict[str, Any]:
    if scored.empty:
        return {}
    prior_n = _num(scored, "external_prior_n", default=0.0)
    delta = _num(scored, "external_prior_delta_p", default=0.0)
    cap_applied = _num(scored, "external_prior_cap_applied", default=0.0)
    applied = _bool(scored, "external_prior_probability_applied")
    direction = scored["direction"].astype(str).str.upper().str.strip() if "direction" in scored.columns else ""

    applied_df = scored[applied].copy()
    applied_df["_delta"] = delta[applied]
    grouped: list[dict[str, Any]] = []
    if not applied_df.empty and "direction" in applied_df.columns:
        for (d, stat), grp in applied_df.groupby(["direction", "stat"], dropna=False):
            grouped.append(
                {
                    "direction": str(d),
                    "stat": str(stat),
                    "rows": int(len(grp)),
                    "delta": _describe_numeric(grp["_delta"]),
                }
            )

    p_adj = _num(scored, "p_adj", default=0.5)
    p_for_cal = _num(scored, "p_for_cal", default=0.5)
    p_diff = (p_for_cal - p_adj).abs()

    under_mask = direction == "UNDER" if isinstance(direction, pd.Series) else pd.Series(False, index=scored.index)
    over_mask = direction == "OVER" if isinstance(direction, pd.Series) else pd.Series(False, index=scored.index)
    prior_df = scored[prior_n > 0].copy()
    prior_df["_cap_applied"] = cap_applied[prior_n > 0]
    cap_by_direction: list[dict[str, Any]] = []
    if not prior_df.empty and "direction" in prior_df.columns:
        for d, grp in prior_df.groupby("direction", dropna=False):
            cap_by_direction.append(
                {
                    "direction": str(d),
                    "rows": int(len(grp)),
                    "cap_applied": _describe_numeric(grp["_cap_applied"]),
                }
            )
    return {
        "prior_rows": int((prior_n > 0).sum()),
        "probability_applied_rows": int(applied.sum()),
        "applied_negative_delta_rows": int(((delta < -1e-12) & applied).sum()),
        "applied_under_rows": int((applied & under_mask).sum()),
        "applied_over_rows": int((applied & over_mask).sum()),
        "cap_applied_by_direction": sorted(cap_by_direction, key=lambda r: r["direction"]),
        "delta_by_direction_stat": sorted(grouped, key=lambda r: (r["direction"], -r["rows"])),
        "p_for_cal_equals_p_adj_max_abs_diff": float(p_diff.max()) if len(p_diff) else None,
    }


def _parse_leg(text: str) -> dict[str, Any] | None:
    match = LEG_RE.search(str(text))
    if not match:
        return None
    out = match.groupdict()
    out["line"] = _safe_float(out.get("line"))
    return out


def _slip_output_audit(run_dir: Path) -> dict[str, Any]:
    slip_files = []
    for p in run_dir.glob("*.csv"):
        if p.name not in {"scored_legs.csv", "scored_legs_deduped.csv"}:
            slip_files.append(p)
    slip_files.extend((run_dir / "System").glob("*.csv"))
    slip_files.extend((run_dir / "Windfall").glob("*.csv"))

    rows: list[dict[str, Any]] = []
    selected_legs: list[dict[str, Any]] = []
    for path in sorted(slip_files):
        df = _read_csv(path)
        if df.empty:
            rows.append({"file": str(path.relative_to(run_dir)), "rows": 0})
            continue

        parsed: list[dict[str, Any]] = []
        if {"player", "direction", "stat", "tier", "line"}.issubset(df.columns):
            for _, row in df.iterrows():
                parsed.append(
                    {
                        "player": str(row.get("player", "")),
                        "direction": str(row.get("direction", "")).upper(),
                        "stat": str(row.get("stat", "")).upper(),
                        "tier": str(row.get("tier", "")).upper(),
                        "line": _safe_float(row.get("line")),
                    }
                )
        else:
            leg_cols = [c for c in df.columns if re.fullmatch(r"leg_\d+", str(c))]
            if leg_cols:
                for _, row in df.iterrows():
                    for col in leg_cols:
                        leg = _parse_leg(str(row.get(col, "")))
                        if leg:
                            parsed.append(leg)
            elif "legs" in df.columns:
                for text in df["legs"].astype(str):
                    for part in text.split(" | "):
                        leg = _parse_leg(part)
                        if leg:
                            parsed.append(leg)

        for leg in parsed:
            leg["file"] = str(path.relative_to(run_dir))
            leg["family"] = _family_for_slip_path(path, run_dir)
        selected_legs.extend(parsed)

        legs_df = pd.DataFrame(parsed)
        if legs_df.empty:
            rows.append({"file": str(path.relative_to(run_dir)), "rows": int(len(df)), "parsed_legs": 0})
            continue
        rows.append(
            {
                "file": str(path.relative_to(run_dir)),
                "rows": int(len(df)),
                "parsed_legs": int(len(legs_df)),
                "over_legs": int((legs_df["direction"] == "OVER").sum()),
                "under_legs": int((legs_df["direction"] == "UNDER").sum()),
                "standard_legs": int((legs_df["tier"] == "STANDARD").sum()),
                "goblin_legs": int((legs_df["tier"] == "GOBLIN").sum()),
                "demon_legs": int((legs_df["tier"] == "DEMON").sum()),
            }
        )

    legs = pd.DataFrame(selected_legs)
    duplicate_props_anywhere: list[dict[str, Any]] = []
    duplicate_props_within_family: list[dict[str, Any]] = []
    duplicate_props_cross_family: list[dict[str, Any]] = []
    invalid_under_tiers: list[dict[str, Any]] = []
    production_legs = legs
    if not legs.empty:
        # Top-level recommended_Nleg.csv files are legacy mirrors of System/.
        # Keep them visible in file rows, but exclude them from exposure totals
        # and duplicate warnings so the audit does not double-count System slips.
        production_legs = legs[legs["family"] != "SystemLegacyMirror"].copy()
        key_cols = ["player", "direction", "stat", "line"]
        dup = production_legs.groupby(key_cols, dropna=False).agg(
            files=("file", lambda s: sorted(set(s))),
            families=("family", lambda s: sorted(set(s))),
            count=("file", "size"),
        )
        dup = dup[dup["count"] > 1].reset_index()
        duplicate_props_anywhere = dup.head(25).to_dict(orient="records")

        family_key_cols = ["family", *key_cols]
        dup_family = production_legs.groupby(family_key_cols, dropna=False).agg(
            files=("file", lambda s: sorted(set(s))),
            count=("file", "size"),
        )
        dup_family = dup_family[dup_family["count"] > 1].reset_index()
        duplicate_props_within_family = dup_family.head(25).to_dict(orient="records")

        cross_family = dup[dup["families"].map(lambda vals: len(vals) > 1)]
        duplicate_props_cross_family = cross_family.head(25).to_dict(orient="records")

        invalid = production_legs[
            (production_legs["direction"] == "UNDER")
            & (production_legs["tier"].isin(["GOBLIN", "DEMON"]))
        ]
        invalid_under_tiers = invalid.to_dict(orient="records")

    return {
        "files": rows,
        "total_selected_legs": int(len(production_legs)) if not production_legs.empty else 0,
        "total_under_legs": int((production_legs["direction"] == "UNDER").sum()) if not production_legs.empty else 0,
        "duplicate_exact_props_anywhere_top25": duplicate_props_anywhere,
        "duplicate_exact_props_within_family_top25": duplicate_props_within_family,
        "duplicate_exact_props_cross_family_top25": duplicate_props_cross_family,
        "invalid_under_tiers": invalid_under_tiers,
    }


def _family_for_slip_path(path: Path, run_dir: Path) -> str:
    rel = path.relative_to(run_dir)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] in {"System", "Windfall"}:
        return str(parts[0])
    if path.name.startswith("recommended_"):
        return "SystemLegacyMirror"
    if path.name == "demonhunter.csv":
        return "DemonHunter"
    if path.name == "marketed_slips.csv":
        return "Marketed"
    return "Other"


def _cat_policy_audit(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "catboost_scale_policy_manifest.json"
    if not path.exists():
        return {"manifest_found": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"manifest_found": True, "error": str(exc)}
    return {
        "manifest_found": True,
        "status": data.get("status"),
        "harmful_slate_indicator": data.get("harmful_slate_indicator"),
        "policy_reasons": (data.get("catboost") or {}).get("policy_reasons"),
        "residual_scale": (data.get("catboost") or {}).get("residual_scale"),
        "slate_metrics": data.get("slate_metrics"),
    }


def audit_run(run_dir: Path) -> dict[str, Any]:
    scored = _read_csv(run_dir / "scored_legs_deduped.csv")
    scored_raw = _read_csv(run_dir / "scored_legs.csv")
    manifest = _load_manifest(run_dir)

    warnings: list[str] = []
    failures: list[str] = []

    if scored.empty:
        failures.append("missing or empty scored_legs_deduped.csv")

    direction_surface = _direction_tier_surface(scored)
    under_summary = _under_eligible_summary(scored, manifest)
    external_priors = _external_prior_audit(scored)
    slips = _slip_output_audit(run_dir)
    cat_policy = _cat_policy_audit(run_dir)

    if external_priors.get("prior_rows", 0) > 0 and external_priors.get("probability_applied_rows", 0) == 0:
        failures.append("external priors exist but no rows were probability-applied")
    if external_priors.get("applied_negative_delta_rows", 0) > 0:
        warnings.append("external priors applied negative deltas; inspect market/projection blend")
    max_diff = external_priors.get("p_for_cal_equals_p_adj_max_abs_diff")
    if max_diff is not None and max_diff > 1e-9:
        warnings.append("p_for_cal differs from p_adj; confirm this is intentional before CAT")

    if slips.get("invalid_under_tiers"):
        failures.append("UNDER legs appeared on GOBLIN/DEMON tiers in slip outputs")
    if slips.get("duplicate_exact_props_within_family_top25"):
        warnings.append("duplicate exact props repeated within at least one slip family")

    eligible_under = int(under_summary.get("marketed_standard_under_eligible_rows", 0) or 0)
    selected_under = int(slips.get("total_under_legs", 0) or 0)
    selected_total = int(slips.get("total_selected_legs", 0) or 0)
    if eligible_under >= 3 and selected_under == 0:
        warnings.append("eligible STANDARD UNDER pool exists but no UNDER legs reached slip outputs")
    elif eligible_under >= 5 and selected_total > 0 and (selected_under / selected_total) < 0.05:
        warnings.append("eligible STANDARD UNDER pool exists but selected UNDER exposure is below 5%")

    cat_metrics = cat_policy.get("slate_metrics") or {}
    cat_bp_has_mean = cat_metrics.get("bp_has_mean") if isinstance(cat_metrics, dict) else None
    if external_priors.get("prior_rows", 0) > 0 and cat_bp_has_mean == 0.0:
        warnings.append("CAT policy manifest reports bp_has_mean=0.0 despite external-prior rows")

    return {
        "verdict": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "rows": {
            "scored_legs": int(len(scored_raw)),
            "scored_legs_deduped": int(len(scored)),
        },
        "direction_tier_surface": direction_surface,
        "under_eligibility": under_summary,
        "external_priors": external_priors,
        "slip_outputs": slips,
        "catboost_scale_policy_manifest": cat_policy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a live Atlas run probability/build surface.")
    parser.add_argument("--run-dir", default=None, help="Run directory. Defaults to latest data/output/runs/*.")
    parser.add_argument("--json-out", default=None, help="Optional path to write JSON audit.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir

    result = audit_run(run_dir)
    text = json.dumps(result, indent=2)
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
