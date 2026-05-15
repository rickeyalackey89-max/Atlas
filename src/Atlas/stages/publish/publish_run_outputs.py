from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from Atlas.core.fingerprint import (
    read_ensemble_meta,
    build_manifest,
    _sanitize_keys,
)


def write_run_manifest(
    run_dir: Path,
    cfg: dict,
    ensemble_dir: str | Path | None = None,
) -> Path:
    """
    Write run_manifest.json — the single source of truth for what config
    and model were used in this run. Every replay and live run gets one.
    """
    # Build the core manifest from the shared module
    manifest = build_manifest(
        source="run_publish",
        cfg=cfg,
        ensemble_dir=ensemble_dir,
    )

    # Enrich with run-specific details the shared manifest doesn't include
    ensemble_meta = read_ensemble_meta(ensemble_dir)
    telemetry = cfg.get("telemetry", {}) or {}
    posthoc = cfg.get("posthoc_calibrator", {}) or {}

    manifest["ensemble"] = {
        "version": ensemble_meta.get("version", "unknown"),
        "architecture": ensemble_meta.get("architecture", "unknown"),
        "features": ensemble_meta.get("features", []),
        "n_features": len(ensemble_meta.get("features", [])),
        "lodo_brier": ensemble_meta.get("lodo_brier_ensemble"),
        "training_cache": ensemble_meta.get("training_cache"),
        "training_dates": ensemble_meta.get("training_dates"),
        "training_legs": ensemble_meta.get("training_legs"),
        "temperature": ensemble_meta.get("temperature"),
        "seeds": ensemble_meta.get("ensemble_seeds", []),
    }
    manifest["calibration"] = {
        "posthoc_enabled": posthoc.get("enabled"),
        "ensemble_dir": posthoc.get("ensemble_dir"),
        "active_calibration": telemetry.get("active_calibration"),
        "apply_active_calibration": telemetry.get("apply_active_calibration"),
    }
    manifest["full_config"] = _sanitize_keys(cfg)

    out_path = run_dir / "run_manifest.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False, default=str),
        encoding="utf-8",
    )
    return out_path


def write_post_run_audit_manifests(run_dir: Path) -> list[Path]:
    """Write non-blocking post-run audit manifests into the run folder."""

    written: list[Path] = []

    audits: list[tuple[str, str, Callable[[Path], dict]]] = []
    try:
        from scripts.audits.pipeline_contract_audit import audit_run as contract_audit

        audits.append(("pipeline_contract_audit", "pipeline_contract_audit.json", contract_audit))
    except Exception as exc:
        print(f"[POST_RUN_AUDIT][WARN] pipeline contract audit unavailable: {exc}")

    try:
        from scripts.audits.live_pipeline_surface_audit import audit_run as surface_audit

        audits.append(("live_pipeline_surface_audit", "live_pipeline_surface_audit.json", surface_audit))
    except Exception as exc:
        print(f"[POST_RUN_AUDIT][WARN] live surface audit unavailable: {exc}")

    try:
        from scripts.audits.hard_pipeline_audit import audit_run as hard_audit

        audits.append(("hard_pipeline_audit", "hard_pipeline_audit.json", hard_audit))
    except Exception as exc:
        print(f"[POST_RUN_AUDIT][WARN] hard pipeline audit unavailable: {exc}")

    for label, filename, audit_fn in audits:
        try:
            result = audit_fn(run_dir)
            out_path = run_dir / filename
            out_path.write_text(json.dumps(result, indent=2, sort_keys=False, default=str), encoding="utf-8")
            written.append(out_path)
            verdict = str(result.get("verdict", "UNKNOWN"))
            failures = len(result.get("failures", []) or [])
            warnings = len(result.get("warnings", []) or [])
            print(f"[POST_RUN_AUDIT] {label}: {verdict} failures={failures} warnings={warnings} -> {out_path}")
        except Exception as exc:
            print(f"[POST_RUN_AUDIT][WARN] {label} failed: {exc}")

    return written


def write_catboost_scale_policy_manifest(
    run_dir: Path,
    OUT_DIR: Path,
    scored: pd.DataFrame,
) -> Optional[Path]:
    """Write a small operational manifest for the CAT residual-scale policy."""

    if scored is None or scored.empty or "catboost_residual_scale" not in scored.columns:
        return None

    first = scored.iloc[0]

    def _first_bool(col: str) -> bool:
        if col not in scored.columns:
            return False
        return bool(first.get(col, False))

    def _first_float(col: str) -> float | None:
        if col not in scored.columns:
            return None
        try:
            value = float(first.get(col))
            return value if value == value else None
        except Exception:
            return None

    reasons_raw = str(first.get("catboost_scale_policy_reasons", "") or "")
    reasons = [x for x in reasons_raw.split(",") if x]
    triggered = _first_bool("catboost_scale_policy_triggered")
    status = "defensive" if triggered else "normal"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "harmful_slate_indicator": triggered,
        "message": (
            "CAT defensive residual scale active; slate has pregame risk profile that previously amplified CAT tail loss."
            if triggered
            else "CAT aggressive residual scale active; slate did not match defensive-risk trigger."
        ),
        "catboost": {
            "model_version": str(first.get("catboost_model_version", "")),
            "residual_scale": _first_float("catboost_residual_scale"),
            "policy_enabled": _first_bool("catboost_scale_policy_enabled"),
            "policy_triggered": triggered,
            "policy_reasons": reasons,
        },
        "slate_metrics": {
            "games": _first_float("catboost_scale_games"),
            "q_out_frac_mean": _first_float("catboost_scale_q_out_frac_mean"),
            "q_blowout_p90": _first_float("catboost_scale_q_blowout_p90"),
            "role_ctx_outs_used_share_gt0": _first_float("catboost_scale_role_ctx_outs_used_share_gt0"),
            "bp_has_mean": _first_float("catboost_scale_bp_has_mean"),
        },
    }

    out_path = run_dir / "catboost_scale_policy_manifest.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")

    latest_dir = OUT_DIR / "dashboard"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "catboost_scale_policy_latest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return out_path


def write_raw_slate_fragility_guard_manifest(
    run_dir: Path,
    OUT_DIR: Path,
    scored: pd.DataFrame,
) -> Optional[Path]:
    """Write an operational manifest for the pre-CAT raw slate guard."""

    if scored is None or scored.empty or "raw_slate_fragility_guard_enabled" not in scored.columns:
        return None

    first = scored.iloc[0]

    def _first_bool(col: str) -> bool:
        if col not in scored.columns:
            return False
        return bool(first.get(col, False))

    def _first_float(col: str) -> float | None:
        if col not in scored.columns:
            return None
        try:
            value = float(first.get(col))
            return value if value == value else None
        except Exception:
            return None

    reasons_raw = str(first.get("raw_slate_fragility_guard_reasons", "") or "")
    reasons = [x for x in reasons_raw.split(",") if x]
    triggered = _first_bool("raw_slate_fragility_guard_triggered")
    shifted_count = _first_float("raw_slate_fragility_guard_shifted_count")

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active" if triggered else "inactive",
        "harmful_raw_slate_indicator": triggered,
        "message": (
            "Pre-CAT raw slate fragility guard active; p_for_cal was direction-aware logit-shifted for q-out/high-confidence legs."
            if triggered
            else "Pre-CAT raw slate fragility guard inactive; slate did not match thin q-out/blowout trigger."
        ),
        "guard": {
            "enabled": _first_bool("raw_slate_fragility_guard_enabled"),
            "triggered": triggered,
            "reasons": reasons,
            "logit_shift": _first_float("raw_slate_fragility_guard_logit_shift"),
            "over_logit_shift": _first_float("raw_slate_fragility_guard_over_logit_shift"),
            "under_logit_shift": _first_float("raw_slate_fragility_guard_under_logit_shift"),
            "shifted_legs": shifted_count,
            "over_shifted_legs": _first_float("raw_slate_fragility_guard_over_shifted_count"),
            "under_shifted_legs": _first_float("raw_slate_fragility_guard_under_shifted_count"),
        },
        "slate_metrics": {
            "games": _first_float("raw_slate_fragility_guard_games"),
            "q_out_frac_mean": _first_float("raw_slate_fragility_guard_q_out_frac_mean"),
            "q_blowout_p90": _first_float("raw_slate_fragility_guard_q_blowout_p90"),
        },
    }

    out_path = run_dir / "raw_slate_fragility_guard_manifest.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")

    latest_dir = OUT_DIR / "dashboard"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "raw_slate_fragility_guard_latest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return out_path


def write_single_game_mode_manifest(
    run_dir: Path,
    OUT_DIR: Path,
    scored: pd.DataFrame,
) -> Optional[Path]:
    """Write an operational manifest for single-game robustness mode."""

    if scored is None or scored.empty or "single_game_slate" not in scored.columns:
        return None

    first = scored.iloc[0]

    def _first_bool(col: str) -> bool:
        if col not in scored.columns:
            return False
        return bool(first.get(col, False))

    def _first_str(col: str) -> str:
        if col not in scored.columns:
            return ""
        return str(first.get(col, "") or "")

    def _first_float(col: str) -> float | None:
        if col not in scored.columns:
            return None
        try:
            value = float(first.get(col))
            return value if value == value else None
        except Exception:
            return None

    def _sum_flag(col: str) -> int:
        if col not in scored.columns:
            return 0
        vals = pd.to_numeric(scored[col], errors="coerce")
        if not isinstance(vals, pd.Series):
            vals = pd.Series(vals, index=scored.index)
        return int((vals.fillna(0.0) > 0.0).sum())

    fit_mean = None
    if "single_game_script_fit" in scored.columns:
        vals = pd.to_numeric(scored["single_game_script_fit"], errors="coerce")
        if isinstance(vals, pd.Series):
            fit_mean = float(vals.dropna().mean()) if not vals.dropna().empty else None
    robustness_mean = None
    if "single_game_robustness_score" in scored.columns:
        vals = pd.to_numeric(scored["single_game_robustness_score"], errors="coerce")
        if isinstance(vals, pd.Series):
            robustness_mean = float(vals.dropna().mean()) if not vals.dropna().empty else None
    dependency_mean = None
    if "single_game_script_dependency_score" in scored.columns:
        vals = pd.to_numeric(scored["single_game_script_dependency_score"], errors="coerce")
        if isinstance(vals, pd.Series):
            dependency_mean = float(vals.dropna().mean()) if not vals.dropna().empty else None
    severity_mean = None
    if "single_game_slate_severity_score" in scored.columns:
        vals = pd.to_numeric(scored["single_game_slate_severity_score"], errors="coerce")
        if isinstance(vals, pd.Series):
            severity_mean = float(vals.dropna().mean()) if not vals.dropna().empty else None
    severity_label = _first_str("single_game_slate_severity_label")

    active = _first_bool("single_game_slate")
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active" if active else "inactive",
        "single_game_slate": active,
        "message": (
            "Single-game robustness mode active; Atlas should favor multi-script legs and avoid narrow game-script exposure."
            if active
            else "Single-game robustness mode inactive."
        ),
        "mode": {
            "enabled": _first_bool("single_game_mode_enabled"),
            "profile_active": _first_bool("single_game_profile_active"),
            "games": _first_float("single_game_games"),
            "script_label": _first_str("single_game_script_label"),
            "branch_label": _first_str("single_game_branch_label"),
            "fox_state": _first_str("single_game_fox_state"),
            "harper_state": _first_str("single_game_harper_state"),
            "mean_script_fit": fit_mean,
            "mean_robustness_score": robustness_mean,
            "mean_script_dependency_score": dependency_mean,
            "slate_severity_score": severity_mean,
            "slate_severity_label": severity_label,
        },
        "leg_counts": {
            "total_legs": int(len(scored)),
            "stable_anchor_legs": _sum_flag("single_game_anchor_flag"),
            "role_shooter_over_legs": _sum_flag("single_game_role_shooter_over_flag"),
            "fg3m_over_legs": _sum_flag("single_game_fg3m_over_flag"),
            "non_shooting_volume_legs": _sum_flag("single_game_non_shooting_volume_flag"),
            "low_minute_bench_over_legs": _sum_flag("single_game_low_minute_bench_over_flag"),
            "low_line_noise_legs": _sum_flag("single_game_low_line_noise_flag"),
            "multi_script_survival_legs": _sum_flag("single_game_multi_script_survival_flag"),
            "injury_uncertainty_legs": _sum_flag("single_game_injury_uncertainty_flag"),
        },
    }

    out_path = run_dir / "single_game_mode_manifest.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")

    latest_dir = OUT_DIR / "dashboard"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "single_game_mode_latest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return out_path


def run_publish_stage(
    *,
    LOCAL_TZ,
    OUT_DIR: Path,
    scored: pd.DataFrame,
    scored_for_optimizer: pd.DataFrame,
    sys3: pd.DataFrame,
    sys4: pd.DataFrame,
    sys5: pd.DataFrame,
    wind3: pd.DataFrame,
    wind4: pd.DataFrame,
    wind5: pd.DataFrame,
    sys2: Optional[pd.DataFrame] = None,
    wind2: Optional[pd.DataFrame] = None,
    demonhunter: Optional[pd.DataFrame] = None,
    sys2_winprob: Optional[pd.DataFrame] = None,
    sys3_winprob: Optional[pd.DataFrame] = None,
    sys4_winprob: Optional[pd.DataFrame] = None,
    sys5_winprob: Optional[pd.DataFrame] = None,
    wind2_winprob: Optional[pd.DataFrame] = None,
    wind3_winprob: Optional[pd.DataFrame] = None,
    wind4_winprob: Optional[pd.DataFrame] = None,
    wind5_winprob: Optional[pd.DataFrame] = None,
    marketed_slips: Optional[list] = None,
    public_slip_quality_manifest: Optional[dict] = None,
    iael_invalidations_path: Optional[Path] = None,
    iael_status_path: Optional[Path] = None,
    write_csv_clean: Optional[Callable[[pd.DataFrame, Path], Path]] = None,
    cfg: Optional[dict] = None,
    ensemble_dir: Optional[str | Path] = None,
) -> Path:
    """
    Publish Stage (IO only).
    Creates run dirs, writes outputs, prints summary.
    No business logic / transforms.
    """

    if write_csv_clean is None:
        raise ValueError("write_csv_clean must be provided")
    w = write_csv_clean  # local non-optional alias

    ts = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    windfall_dir = run_dir / "Windfall"
    system_dir = run_dir / "System"
    windfall_dir.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)

    # ── Run manifest: capture EXACTLY what config + model produced this run ──
    if cfg is not None:
        manifest_path = write_run_manifest(run_dir, cfg, ensemble_dir=ensemble_dir)
        print(f" - {manifest_path} (config fingerprint)")

    w(scored, run_dir / "scored_legs.csv")
    w(scored_for_optimizer, run_dir / "scored_legs_deduped.csv")
    cat_policy_manifest_path = write_catboost_scale_policy_manifest(run_dir, OUT_DIR, scored)
    raw_guard_manifest_path = write_raw_slate_fragility_guard_manifest(run_dir, OUT_DIR, scored)
    single_game_manifest_path = write_single_game_mode_manifest(run_dir, OUT_DIR, scored)
    public_quality_manifest_path: Optional[Path] = None
    if public_slip_quality_manifest is not None:
        public_quality_manifest_path = run_dir / "public_slip_quality_manifest.json"
        public_quality_manifest_path.write_text(
            json.dumps(public_slip_quality_manifest, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    # SYSTEM (default / kernel EV)
    if sys2 is not None:
        w(sys2, system_dir / "recommended_2leg.csv")
    w(sys3, system_dir / "recommended_3leg.csv")
    w(sys4, system_dir / "recommended_4leg.csv")
    w(sys5, system_dir / "recommended_5leg.csv")

    # SYSTEM (secondary / no-kernel win-prob)
    if sys2_winprob is not None:
        w(sys2_winprob, system_dir / "recommended_2leg_winprob.csv")
    if sys3_winprob is not None:
        w(sys3_winprob, system_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, system_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, system_dir / "recommended_5leg_winprob.csv")

    # WINDFALL (default / kernel EV)
    if wind2 is not None:
        w(wind2, windfall_dir / "recommended_2leg.csv")
    w(wind3, windfall_dir / "recommended_3leg.csv")
    w(wind4, windfall_dir / "recommended_4leg.csv")
    w(wind5, windfall_dir / "recommended_5leg.csv")

    # WINDFALL (secondary / no-kernel win-prob)
    if wind2_winprob is not None:
        w(wind2_winprob, windfall_dir / "recommended_2leg_winprob.csv")
    if wind3_winprob is not None:
        w(wind3_winprob, windfall_dir / "recommended_3leg_winprob.csv")
    if wind4_winprob is not None:
        w(wind4_winprob, windfall_dir / "recommended_4leg_winprob.csv")
    if wind5_winprob is not None:
        w(wind5_winprob, windfall_dir / "recommended_5leg_winprob.csv")

    # DEMONHUNTER – single CSV with best 3/4/5-leg all-DEMON slips
    if demonhunter is not None and len(demonhunter) > 0:
        w(demonhunter, run_dir / "demonhunter.csv")

    # MARKETED SLIPS – JSON + CSV output for subscriber product.
    # Always write the artifacts when the builder ran, even when quality gates
    # reject every slip. Missing files should indicate publisher failure.
    if marketed_slips is not None:
        marketed_path = run_dir / "marketed_slips.json"
        with open(marketed_path, 'w') as f:
            json.dump({
                "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "slips": marketed_slips,
                "meta": {
                    "builder": "marketed_slip_builder",
                    "correlation_adjusted": True,
                    "stat_calibrated": True,
                    "templates": [slip.get("label", "") for slip in marketed_slips]
                }
            }, f, indent=2)

        # CSV companion — one row per leg for easy viewing
        import pandas as _pd
        csv_rows = []
        for slip in marketed_slips:
            for leg in slip.get("legs", []):
                csv_rows.append({
                    "slip": slip.get("label"),
                    "high_confidence": slip.get("high_confidence", False),
                    "hit_prob": round(slip.get("hit_prob", 0.0), 4),
                    "payout_mult": round(slip.get("payout_mult", 0.0), 3),
                    "ev": round(slip.get("ev", 0.0), 4),
                    "player": leg.get("player"),
                    "team": leg.get("team"),
                    "opp": leg.get("opp"),
                    "stat": leg.get("stat"),
                    "direction": leg.get("direction"),
                    "tier": leg.get("tier"),
                    "line": leg.get("line"),
                    "p_cal": round(float(leg.get("p_cal", 0.0)), 4) if leg.get("p_cal") is not None else None,
                    "is_questionable": int(float(leg.get("is_questionable", 0) or 0)),
                    "q_out_frac": round(float(leg.get("q_out_frac", 0.0) or 0.0), 4),
                    "public_survival_score": round(float(slip.get("public_survival_score", 0.0)), 4),
                    "public_quality_pass": slip.get("public_quality_pass", True),
                    "public_quality_reasons": slip.get("public_quality_reasons", ""),
                    "slip_consensus_legs": slip.get("slip_consensus_legs", 0),
                    "slip_consensus_share": round(float(slip.get("slip_consensus_share", 0.0)), 4),
                    "public_portfolio_status": slip.get("public_portfolio_status", ""),
                    "public_portfolio_reason": slip.get("public_portfolio_reason", ""),
                })
        marketed_csv_path = run_dir / "marketed_slips.csv"
        marketed_columns = [
            "slip",
            "high_confidence",
            "hit_prob",
            "payout_mult",
            "ev",
            "player",
            "team",
            "opp",
            "stat",
            "direction",
            "tier",
            "line",
            "p_cal",
            "is_questionable",
            "q_out_frac",
            "public_survival_score",
            "public_quality_pass",
            "public_quality_reasons",
            "slip_consensus_legs",
            "slip_consensus_share",
            "public_portfolio_status",
            "public_portfolio_reason",
        ]
        _pd.DataFrame(csv_rows, columns=marketed_columns).to_csv(marketed_csv_path, index=False)

        # Copy to latest if configured
        if cfg and cfg.get("marketed_slips", {}).get("publish_to_latest", False):
            latest_path = OUT_DIR / cfg.get("marketed_slips", {}).get("output_name", "marketed_slips_latest.json")
            shutil.copy2(marketed_path, latest_path)

    dashboard_dir = OUT_DIR / "runs_manifest" / ts
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    snapshot_artifacts: dict[str, dict[str, str]] = {}
    snapshot_manifest: dict[str, object] = {
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_dir": str(run_dir),
        "artifacts": snapshot_artifacts,
    }

    def _copy_snapshot(src: Optional[Path], dst_name: str) -> None:
        if src is None:
            return
        src_path = Path(src)
        if not src_path.exists() or not src_path.is_file():
            return
        dst_path = dashboard_dir / dst_name
        shutil.copy2(src_path, dst_path)
        snapshot_artifacts[dst_name] = {
            "source": str(src_path.resolve()),
            "destination": str(dst_path.resolve()),
        }

    _copy_snapshot(iael_invalidations_path, "injury_invalidations_latest.json")
    _copy_snapshot(iael_status_path, "status_latest.json")

    if snapshot_artifacts:
        (dashboard_dir / "injury_snapshot_manifest.json").write_text(
            json.dumps(snapshot_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Legacy mirrors SYSTEM (default)
    if sys2 is not None:
        w(sys2, run_dir / "recommended_2leg.csv")
    w(sys3, run_dir / "recommended_3leg.csv")
    w(sys4, run_dir / "recommended_4leg.csv")
    w(sys5, run_dir / "recommended_5leg.csv")

    # Legacy mirrors SYSTEM (secondary / no-kernel win-prob)
    if sys2_winprob is not None:
        w(sys2_winprob, run_dir / "recommended_2leg_winprob.csv")
    if sys3_winprob is not None:
        w(sys3_winprob, run_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, run_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, run_dir / "recommended_5leg_winprob.csv")

    post_run_audit_paths = write_post_run_audit_manifests(run_dir)

    print("Model run complete.")
    print(f"Outputs folder: {OUT_DIR}")
    print(f"Run folder: {run_dir}")
    print("Wrote:")
    print(f" - {run_dir / 'scored_legs.csv'}")
    print(f" - {run_dir / 'scored_legs_deduped.csv'}")
    if cat_policy_manifest_path is not None:
        print(f" - {cat_policy_manifest_path} (CAT scale policy manifest)")
        print(f" - {OUT_DIR / 'dashboard' / 'catboost_scale_policy_latest.json'} (CAT scale policy latest)")
    if raw_guard_manifest_path is not None:
        print(f" - {raw_guard_manifest_path} (raw slate fragility guard manifest)")
        print(f" - {OUT_DIR / 'dashboard' / 'raw_slate_fragility_guard_latest.json'} (raw slate guard latest)")
    if single_game_manifest_path is not None:
        print(f" - {single_game_manifest_path} (single-game mode manifest)")
        print(f" - {OUT_DIR / 'dashboard' / 'single_game_mode_latest.json'} (single-game mode latest)")
    if public_quality_manifest_path is not None:
        print(f" - {public_quality_manifest_path} (public slip quality manifest)")
    if sys2 is not None:
        print(f" - {system_dir / 'recommended_2leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_3leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_4leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_5leg.csv'} (SYSTEM)")
    if wind2 is not None:
        print(f" - {windfall_dir / 'recommended_2leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_3leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_4leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_5leg.csv'} (WINDFALL)")

    if sys2_winprob is not None:
        print(f" - {system_dir / 'recommended_2leg_winprob.csv'} (SYSTEM winprob)")
    if sys3_winprob is not None:
        print(f" - {system_dir / 'recommended_3leg_winprob.csv'} (SYSTEM winprob)")
    if sys4_winprob is not None:
        print(f" - {system_dir / 'recommended_4leg_winprob.csv'} (SYSTEM winprob)")
    if sys5_winprob is not None:
        print(f" - {system_dir / 'recommended_5leg_winprob.csv'} (SYSTEM winprob)")

    if wind2_winprob is not None:
        print(f" - {windfall_dir / 'recommended_2leg_winprob.csv'} (WINDFALL winprob)")
    if wind3_winprob is not None:
        print(f" - {windfall_dir / 'recommended_3leg_winprob.csv'} (WINDFALL winprob)")
    if wind4_winprob is not None:
        print(f" - {windfall_dir / 'recommended_4leg_winprob.csv'} (WINDFALL winprob)")
    if wind5_winprob is not None:
        print(f" - {windfall_dir / 'recommended_5leg_winprob.csv'} (WINDFALL winprob)")

    if marketed_slips is not None:
        print(f" - {run_dir / 'marketed_slips.json'} (MARKETED SLIPS - {len(marketed_slips)} slips)")
        print(f" - {run_dir / 'marketed_slips.csv'} (MARKETED SLIPS CSV)")
        if cfg and cfg.get("marketed_slips", {}).get("publish_to_latest", False):
            latest_name = cfg.get("marketed_slips", {}).get("output_name", "marketed_slips_latest.json")
            print(f" - {OUT_DIR / latest_name} (MARKETED SLIPS latest)")

    if snapshot_artifacts:
        print(f" - {dashboard_dir / 'injury_invalidations_latest.json'} (IAEL snapshot)")
        print(f" - {dashboard_dir / 'status_latest.json'} (IAEL snapshot)")
        print(f" - {dashboard_dir / 'injury_snapshot_manifest.json'} (IAEL snapshot manifest)")
    for audit_path in post_run_audit_paths:
        print(f" - {audit_path} (POST-RUN AUDIT)")

    return run_dir
