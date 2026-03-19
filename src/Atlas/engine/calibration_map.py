from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


@lru_cache(maxsize=8)
def _load_grid(path: str) -> tuple[np.ndarray, np.ndarray]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    x = np.asarray(obj["grid_p_in"], dtype=float)
    y = np.asarray(obj["grid_p_out"], dtype=float)

    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 2:
        raise ValueError("Invalid calibration map grid arrays")
    if not np.all(np.diff(x) >= 0):
        raise ValueError("grid_p_in must be non-decreasing")
    return x, y


def get_calibration_path_from_env() -> Optional[str]:
    return (os.environ.get("ATLAS_CAL_MAP", "") or "").strip() or None


def _env_true(name: str) -> bool:
    return (os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _use_role_off_only_gate() -> bool:
    profile = (os.environ.get("ATLAS_CAL_PROFILE", "") or "").strip().lower()
    if profile == "telemetry_key_role_off_light":
        return True
    return _env_true("ATLAS_CAL_ROLE_CTX_OFF_ONLY")


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

    Optional gating:
    - If ATLAS_CAL_PROFILE=telemetry_key_role_off_light, or
      ATLAS_CAL_ROLE_CTX_OFF_ONLY=1, apply the calibration map only on
      rows where role_ctx_outs_used <= 0 (or is missing/non-numeric).
    - Rows outside that gate keep the input probability unchanged in p_cal.
    """
    # Mapping stage: try to load a grid map if provided; failures do not block
    mapping_ok = False
    if map_path and in_col in df.columns:
        try:
            x, y = _load_grid(map_path)
            p = pd.to_numeric(df[in_col], errors="coerce").to_numpy(dtype=float)
            out = np.full_like(p, np.nan, dtype=float)
            ok = np.isfinite(p)
            if ok.any():
                if _use_role_off_only_gate() and "role_ctx_outs_used" in df.columns:
                    role_used = pd.to_numeric(df["role_ctx_outs_used"], errors="coerce").to_numpy(dtype=float)
                    gate = ~np.isfinite(role_used) | (role_used <= 0)
                else:
                    gate = np.ones_like(p, dtype=bool)

                apply_mask = ok & gate
                passthrough_mask = ok & ~gate

                if apply_mask.any():
                    out[apply_mask] = np.interp(np.clip(p[apply_mask], 0.0, 1.0), x, y)
                if passthrough_mask.any():
                    out[passthrough_mask] = p[passthrough_mask]

            df[out_col] = out
            mapping_ok = True
        except Exception as e:
            if warn:
                print(f"[WARN] calibration map skipped: {e}")

    # Telemetry overlay stage (best-effort): always try to compute a telemetry-
    # adjusted column while preserving any existing `out_col`. The telemetry
    # overlay will be written to `<out_col>_telemetry` and diagnostics copied
    # back onto the frame; nothing is overwritten.
    try:
        from Atlas.runtime.telemetry_calibration import load_calibration, apply_calibration_to_column

        proj_root = Path(".").resolve()
        calib = load_calibration(proj_root)
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
