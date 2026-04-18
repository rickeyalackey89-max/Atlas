from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Callable

import pandas as pd
import yaml

from Atlas.core.fingerprint import (
    config_fingerprint,
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
    demonhunter: Optional[pd.DataFrame] = None,
    sys3_winprob: Optional[pd.DataFrame] = None,
    sys4_winprob: Optional[pd.DataFrame] = None,
    sys5_winprob: Optional[pd.DataFrame] = None,
    wind3_winprob: Optional[pd.DataFrame] = None,
    wind4_winprob: Optional[pd.DataFrame] = None,
    wind5_winprob: Optional[pd.DataFrame] = None,
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

    # SYSTEM (default / kernel EV)
    w(sys3, system_dir / "recommended_3leg.csv")
    w(sys4, system_dir / "recommended_4leg.csv")
    w(sys5, system_dir / "recommended_5leg.csv")

    # SYSTEM (secondary / no-kernel win-prob)
    if sys3_winprob is not None:
        w(sys3_winprob, system_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, system_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, system_dir / "recommended_5leg_winprob.csv")

    # WINDFALL (default / kernel EV)
    w(wind3, windfall_dir / "recommended_3leg.csv")
    w(wind4, windfall_dir / "recommended_4leg.csv")
    w(wind5, windfall_dir / "recommended_5leg.csv")

    # WINDFALL (secondary / no-kernel win-prob)
    if wind3_winprob is not None:
        w(wind3_winprob, windfall_dir / "recommended_3leg_winprob.csv")
    if wind4_winprob is not None:
        w(wind4_winprob, windfall_dir / "recommended_4leg_winprob.csv")
    if wind5_winprob is not None:
        w(wind5_winprob, windfall_dir / "recommended_5leg_winprob.csv")

    # DEMONHUNTER – single CSV with best 3/4/5-leg all-DEMON slips
    if demonhunter is not None and len(demonhunter) > 0:
        w(demonhunter, run_dir / "demonhunter.csv")

    dashboard_dir = run_dir / "dashboard"
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
    w(sys3, run_dir / "recommended_3leg.csv")
    w(sys4, run_dir / "recommended_4leg.csv")
    w(sys5, run_dir / "recommended_5leg.csv")

    # Legacy mirrors SYSTEM (secondary / no-kernel win-prob)
    if sys3_winprob is not None:
        w(sys3_winprob, run_dir / "recommended_3leg_winprob.csv")
    if sys4_winprob is not None:
        w(sys4_winprob, run_dir / "recommended_4leg_winprob.csv")
    if sys5_winprob is not None:
        w(sys5_winprob, run_dir / "recommended_5leg_winprob.csv")

    print("Model run complete.")
    print(f"Outputs folder: {OUT_DIR}")
    print(f"Run folder: {run_dir}")
    print("Wrote:")
    print(f" - {run_dir / 'scored_legs.csv'}")
    print(f" - {run_dir / 'scored_legs_deduped.csv'}")
    print(f" - {system_dir / 'recommended_3leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_4leg.csv'} (SYSTEM)")
    print(f" - {system_dir / 'recommended_5leg.csv'} (SYSTEM)")
    print(f" - {windfall_dir / 'recommended_3leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_4leg.csv'} (WINDFALL)")
    print(f" - {windfall_dir / 'recommended_5leg.csv'} (WINDFALL)")

    if sys3_winprob is not None:
        print(f" - {system_dir / 'recommended_3leg_winprob.csv'} (SYSTEM winprob)")
    if sys4_winprob is not None:
        print(f" - {system_dir / 'recommended_4leg_winprob.csv'} (SYSTEM winprob)")
    if sys5_winprob is not None:
        print(f" - {system_dir / 'recommended_5leg_winprob.csv'} (SYSTEM winprob)")

    if wind3_winprob is not None:
        print(f" - {windfall_dir / 'recommended_3leg_winprob.csv'} (WINDFALL winprob)")
    if wind4_winprob is not None:
        print(f" - {windfall_dir / 'recommended_4leg_winprob.csv'} (WINDFALL winprob)")
    if wind5_winprob is not None:
        print(f" - {windfall_dir / 'recommended_5leg_winprob.csv'} (WINDFALL winprob)")

    if snapshot_artifacts:
        print(f" - {dashboard_dir / 'injury_invalidations_latest.json'} (IAEL snapshot)")
        print(f" - {dashboard_dir / 'status_latest.json'} (IAEL snapshot)")
        print(f" - {dashboard_dir / 'injury_snapshot_manifest.json'} (IAEL snapshot manifest)")

    return run_dir