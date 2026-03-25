from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml


def get_calibration_path_from_env() -> Optional[str]:
    """Legacy shim for the retired grid-map path; always disabled."""
    return None


def apply_calibration_column(
    df: pd.DataFrame,
    *,
    map_path: Optional[str],
    in_col: str = "p_adj",
    out_col: str = "p_cal",
    warn: bool = True,
) -> pd.DataFrame:
    """
    Add calibrated probability column (no overwrite).

    Legacy grid-map interpolation has been retired. The live path now writes
    ``p_cal`` from the telemetry calibration surface only.
    """
    if in_col in df.columns:
        base = pd.to_numeric(df[in_col], errors="coerce").fillna(0.50).clip(0.0, 1.0)
        df[out_col] = base
    elif out_col not in df.columns:
        df[out_col] = 0.50

    # Telemetry overlay stage (best-effort): always try to compute a telemetry-
    # adjusted column while preserving any existing `out_col`. The telemetry
    # overlay will be written to `<out_col>_telemetry` and diagnostics copied
    # back onto the frame; nothing is overwritten.
    try:
        from Atlas.runtime.telemetry_calibration import load_calibration, apply_calibration_to_column

        proj_root = Path(".").resolve()
        calib_path = None
        cfg_path = Path(os.environ.get("ATLAS_CONFIG_PATH", str(proj_root / "config.yaml"))).resolve()
        if cfg_path.exists():
            try:
                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                telemetry_cfg = cfg.get("telemetry", {}) if isinstance(cfg, dict) else {}
                raw_path = telemetry_cfg.get("active_calibration_path")
                if raw_path:
                    candidate = Path(str(raw_path))
                    calib_path = candidate if candidate.is_absolute() else (proj_root / candidate)
            except Exception:
                calib_path = None

        calib = load_calibration(proj_root, calibration_path=calib_path)
        if calib is not None:
            telemetry_out = f"{out_col}_telemetry"
            tmp = df.copy()

            # Choose a source column for telemetry overlay: prefer existing map
            # output if present, otherwise fall back to the provided input column.
            if out_col in tmp.columns:
                tmp_source = out_col
            elif in_col in tmp.columns:
                tmp_source = in_col
            else:
                tmp_source = None

            if tmp_source is not None:
                tmp[tmp_source] = pd.to_numeric(tmp[tmp_source], errors="coerce").clip(0.0, 1.0)
                res = apply_calibration_to_column(tmp, calib, source_col=tmp_source, out_col=telemetry_out, apply_under_penalty=True)
                if telemetry_out in res.columns:
                    df[telemetry_out] = res[telemetry_out]
                for col in ("telemetry_k_shrink", "telemetry_under_penalty", "telemetry_mult", "telemetry_bucket_mult", "telemetry_cal_applied", "telemetry_cal_key"):
                    if col in res.columns:
                        df[col] = res[col]
    except Exception:
        # Best-effort: do not fail caller flow on telemetry overlay errors
        pass

    return df
