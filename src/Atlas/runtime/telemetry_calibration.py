"""Telemetry-driven calibration layer for Atlas.

This module is intentionally **optional** and **no-op by default**.

Why it exists
-------------
Atlas already produces *telemetry* / evaluation artifacts (e.g. via
``tools/backtest_snapshots_accuracy.py``). This module lets the live
scoring path consume a small, explicit calibration artifact generated
from that telemetry—without hard-coding constants in the engine.

The calibration is applied late (in ``ensure_p_adj``) so it can be
iterated quickly and reverted safely.

Calibration JSON schema (v1)
----------------------------
File: ``data/model/telemetry_calibration.json``

::

  {
    "version": 1,
    "generated_at": "2026-02-11T20:15:00Z",
    "k_shrink": 0.85,                 # shrink-to-0.5 factor (0..1.5)
    "standard_under_penalty": 0.90,   # multiplier applied to STANDARD UNDER
    "mult": {                         # optional extra multipliers
      "PTS|OVER": 1.00,
      "PTS|UNDER": 0.98,
      "FG3M|OVER": 1.02
    },
    "bucket_rules": [                # optional upper/lower bucket cooling
      {"min": 0.70, "max": 0.80, "mult": 0.995},
      {"min": 0.80, "max": 0.90, "mult": 0.990},
      {"min": 0.90, "max": 1.00, "mult": 0.980}
    ],
    "apply_only_p_cal_src_prefixes": ["p_adj"],
    "exclude_p_cal_src_prefixes": ["p_role"],
    "cap": {"min": 0.01, "max": 0.99}
  }

Only these fields are consumed. Unknown fields are ignored.

Calibration JSON schema (v2)
----------------------------
File: ``data/model/telemetry_calibration.v2.json``

::

    {
        "version": 2,
        "generated_at": "2026-03-18T20:00:00Z",
        "policy": {
            "apply_only_p_cal_src_prefixes": ["p_adj"],
            "exclude_p_cal_src_prefixes": [],
            "cap": {"min": 0.01, "max": 0.99}
        },
        "base": {
            "k_shrink": 0.96,
            "standard_under_penalty": 0.98
        },
        "families": [
            {"name": "role_off", "role_ctx": "off", "mult": {"PA|OVER": 1.03}},
            {"name": "role_on", "role_ctx": "on", "mult": {"PA|OVER": 1.01}}
        ]
    }

Schema v2 keeps the same runtime semantics but groups the payload into base
settings plus named families so experiments can be composed and reasoned
about more cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class TelemetryCalibration:
    version: int = 1
    generated_at: str = ""
    k_shrink: float = 1.0
    standard_under_penalty: float = 0.90
    mult: Dict[str, float] = None  # key: "STAT|DIRECTION"
    # Optional per-role-context multiplier maps. Keys same as `mult` ("STAT|DIRECTION").
    # `mult_rolectx_on` is applied when `role_ctx_outs_used` > 0, `mult_rolectx_off` when == 0.
    mult_rolectx_on: Dict[str, float] = None
    mult_rolectx_off: Dict[str, float] = None
    bucket_rules: List[Tuple[float, float, float]] = None  # (min, max, mult)
    apply_only_p_cal_src_prefixes: Tuple[str, ...] = ()
    exclude_p_cal_src_prefixes: Tuple[str, ...] = ()
    cap_min: float = 0.01
    cap_max: float = 0.99

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "TelemetryCalibration":
        version = int(d.get("version", 1))
        is_v2 = version >= 2 or isinstance(d.get("families"), list) or isinstance(d.get("policy"), dict) or isinstance(d.get("base"), dict)

        def _norm_prefixes(raw: Any) -> Tuple[str, ...]:
            if not isinstance(raw, list):
                return ()
            vals = []
            for item in raw:
                s = str(item).strip()
                if s:
                    vals.append(s)
            return tuple(vals)

        if is_v2:
            base = d.get("base") or {}
            policy = d.get("policy") or {}
            bucket_rules_raw = d.get("bucket_rules") or base.get("bucket_rules") or policy.get("bucket_rules") or []
            bucket_rules: List[Tuple[float, float, float]] = []
            if isinstance(bucket_rules_raw, list):
                for rule in bucket_rules_raw:
                    if not isinstance(rule, dict):
                        continue
                    try:
                        lo = float(rule.get("min"))
                        hi = float(rule.get("max"))
                        mult_v = float(rule.get("mult", 1.0))
                    except Exception:
                        continue
                    if 0.0 <= lo < hi <= 1.0:
                        bucket_rules.append((lo, hi, mult_v))

            mult: Dict[str, float] = {}
            mult_rolectx_on: Dict[str, float] = {}
            mult_rolectx_off: Dict[str, float] = {}
            families = d.get("families") or []
            if isinstance(families, list):
                for family in families:
                    if not isinstance(family, dict):
                        continue
                    family_mult = family.get("mult") or family.get("map") or {}
                    if not isinstance(family_mult, dict):
                        continue
                    role_ctx = str(family.get("role_ctx") or family.get("scope", {}).get("role_ctx") or family.get("context") or "").strip().lower()
                    if role_ctx in {"on", "true", "1", "rolectx_on"}:
                        mult_rolectx_on.update({str(k): float(v) for k, v in family_mult.items()})
                    elif role_ctx in {"off", "false", "0", "rolectx_off"}:
                        mult_rolectx_off.update({str(k): float(v) for k, v in family_mult.items()})
                    else:
                        mult.update({str(k): float(v) for k, v in family_mult.items()})

            cap = policy.get("cap") or d.get("cap") or {}
            cap_min = float(cap.get("min", d.get("cap_min", 0.01)))
            cap_max = float(cap.get("max", d.get("cap_max", 0.99)))
            return TelemetryCalibration(
                version=version,
                generated_at=str(d.get("generated_at", "")),
                k_shrink=float(base.get("k_shrink", d.get("k_shrink", 1.0))),
                standard_under_penalty=float(base.get("standard_under_penalty", d.get("standard_under_penalty", 0.90))),
                mult=mult,
                mult_rolectx_on=mult_rolectx_on,
                mult_rolectx_off=mult_rolectx_off,
                bucket_rules=bucket_rules,
                apply_only_p_cal_src_prefixes=_norm_prefixes(policy.get("apply_only_p_cal_src_prefixes") if policy else d.get("apply_only_p_cal_src_prefixes")),
                exclude_p_cal_src_prefixes=_norm_prefixes(policy.get("exclude_p_cal_src_prefixes") if policy else d.get("exclude_p_cal_src_prefixes")),
                cap_min=cap_min,
                cap_max=cap_max,
            )

        mult = d.get("mult") or {}
        if not isinstance(mult, dict):
            mult = {}

        mult_rolectx_on = d.get("mult_rolectx_on") or {}
        if not isinstance(mult_rolectx_on, dict):
            mult_rolectx_on = {}

        mult_rolectx_off = d.get("mult_rolectx_off") or {}
        if not isinstance(mult_rolectx_off, dict):
            mult_rolectx_off = {}

        bucket_rules_raw = d.get("bucket_rules") or []
        bucket_rules: List[Tuple[float, float, float]] = []
        if isinstance(bucket_rules_raw, list):
            for rule in bucket_rules_raw:
                if not isinstance(rule, dict):
                    continue
                try:
                    lo = float(rule.get("min"))
                    hi = float(rule.get("max"))
                    mult_v = float(rule.get("mult", 1.0))
                except Exception:
                    continue
                if 0.0 <= lo < hi <= 1.0:
                    bucket_rules.append((lo, hi, mult_v))

        cap = d.get("cap") or {}
        cap_min = float(cap.get("min", 0.01))
        cap_max = float(cap.get("max", 0.99))

        return TelemetryCalibration(
            version=int(d.get("version", 1)),
            generated_at=str(d.get("generated_at", "")),
            k_shrink=float(d.get("k_shrink", 1.0)),
            standard_under_penalty=float(d.get("standard_under_penalty", 0.90)),
            mult={str(k): float(v) for k, v in mult.items()},
            mult_rolectx_on={str(k): float(v) for k, v in mult_rolectx_on.items()},
            mult_rolectx_off={str(k): float(v) for k, v in mult_rolectx_off.items()},
            bucket_rules=bucket_rules,
            apply_only_p_cal_src_prefixes=_norm_prefixes(d.get("apply_only_p_cal_src_prefixes")),
            exclude_p_cal_src_prefixes=_norm_prefixes(d.get("exclude_p_cal_src_prefixes")),
            cap_min=cap_min,
            cap_max=cap_max,
        )


def _default_calibration_path(project_root: Path) -> Path:
    return project_root / "data" / "model" / "telemetry_calibration.json"


def load_calibration(project_root: Path) -> Optional[TelemetryCalibration]:
    """Load calibration from disk. Returns None if missing/unreadable."""
    path = _default_calibration_path(project_root)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return None
        return TelemetryCalibration.from_json(d)
    except Exception:
        return None


def apply_calibration(
    scored: pd.DataFrame,
    calib: TelemetryCalibration,
    *,
    apply_under_penalty: bool = True,
) -> pd.DataFrame:
    """Apply calibration to ``p_adj``.

    Adds small diagnostic columns:
      - telemetry_k_shrink
      - telemetry_mult
      - telemetry_bucket_mult
      - telemetry_under_penalty
    """
    out = scored.copy()

    if "p_adj" not in out.columns:
        return out

    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    out["tier"] = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    out["stat"] = out.get("stat", "").astype(str).str.upper().str.strip()
    out["direction"] = out.get("direction", "").astype(str).str.upper().str.strip()

    k = float(calib.k_shrink)
    if k != 1.0:
        out["p_adj"] = (0.5 + k * (out["p_adj"] - 0.5)).clip(0.0, 1.0)

    under_pen = float(calib.standard_under_penalty)
    if apply_under_penalty:
        m_under_std = (out["tier"] == "STANDARD") & (out["direction"] == "UNDER")
        if m_under_std.any() and under_pen != 1.0:
            out.loc[m_under_std, "p_adj"] = (out.loc[m_under_std, "p_adj"] * under_pen).clip(0.0, 1.0)

    # Build composite multiplier per-row: base * role-specific (on/off) if present
    keys = (out["stat"] + "|" + out["direction"]).astype(str)
    base_map = calib.mult or {}
    base_mult = keys.map(base_map).fillna(1.0).astype(float)

    # role-context specific maps (optional)
    rolectx_on_map = getattr(calib, "mult_rolectx_on", {}) or {}
    rolectx_off_map = getattr(calib, "mult_rolectx_off", {}) or {}
    if rolectx_on_map or rolectx_off_map:
        on_mult = keys.map(rolectx_on_map).fillna(1.0).astype(float)
        off_mult = keys.map(rolectx_off_map).fillna(1.0).astype(float)
        if "role_ctx_outs_used" in out.columns:
            role_mask = pd.to_numeric(out["role_ctx_outs_used"], errors="coerce").fillna(0).astype(float) > 0
        else:
            role_mask = pd.Series(False, index=out.index, dtype=bool)
        role_mult = on_mult.where(role_mask, off_mult)
    else:
        role_mult = pd.Series(1.0, index=out.index, dtype=float)

    # Final telemetry multiplier applied to p_adj (before bucket and caps)
    mult = (base_mult * role_mult).astype(float)
    out["p_adj"] = (out["p_adj"] * mult).clip(0.0, 1.0)

    bucket_mult = pd.Series(1.0, index=out.index, dtype=float)
    for lo_b, hi_b, mult_b in (calib.bucket_rules or []):
        mask = out["p_adj"].gt(lo_b) & out["p_adj"].le(hi_b)
        if mask.any() and mult_b != 1.0:
            bucket_mult.loc[mask] = float(mult_b)
    if bucket_mult.ne(1.0).any():
        out["p_adj"] = (out["p_adj"] * bucket_mult).clip(0.0, 1.0)

    lo = float(calib.cap_min)
    hi = float(calib.cap_max)
    if 0.0 <= lo < hi <= 1.0:
        out["p_adj"] = out["p_adj"].clip(lo, hi)

    out["telemetry_k_shrink"] = float(k)
    out["telemetry_under_penalty"] = float(under_pen)
    out["telemetry_mult"] = pd.to_numeric(mult, errors="coerce").fillna(1.0)
    out["telemetry_bucket_mult"] = pd.to_numeric(bucket_mult, errors="coerce").fillna(1.0)
    return out


def _telemetry_source_allowed_mask(
    scored: pd.DataFrame,
    calib: TelemetryCalibration,
    *,
    source_label_col: str,
) -> pd.Series:
    """Return a row mask for whether telemetry is allowed to apply.

    When no source-prefix filters are configured, all rows are allowed.
    When filters are configured but the source label column is missing, the
    safest behavior is to allow no rows so a source-gated challenger cannot
    silently degrade into an unrestricted challenger.
    """
    include_prefixes = tuple(calib.apply_only_p_cal_src_prefixes or ())
    exclude_prefixes = tuple(calib.exclude_p_cal_src_prefixes or ())
    if not include_prefixes and not exclude_prefixes:
        return pd.Series(True, index=scored.index, dtype=bool)
    if source_label_col not in scored.columns:
        return pd.Series(False, index=scored.index, dtype=bool)

    src = scored[source_label_col].astype(str).fillna("").str.strip()
    allowed = pd.Series(True, index=scored.index, dtype=bool)
    if include_prefixes:
        allowed &= src.map(lambda x: any(x.startswith(prefix) for prefix in include_prefixes))
    if exclude_prefixes:
        allowed &= ~src.map(lambda x: any(x.startswith(prefix) for prefix in exclude_prefixes))
    return allowed.fillna(False)


def apply_calibration_to_column(
    scored: pd.DataFrame,
    calib: TelemetryCalibration,
    *,
    source_col: str = "p_cal",
    out_col: str = "p_cal",
    apply_under_penalty: bool = True,
) -> pd.DataFrame:
    """Apply telemetry calibration to an arbitrary probability column.

    Keeps the existing ``apply_calibration`` semantics, but lets callers overlay
    telemetry tuning on top of a precomputed ``p_cal`` surface instead of only
    mutating ``p_adj``.
    """
    out = scored.copy()
    if source_col not in out.columns:
        key = (
            out.get("stat", "").astype(str).str.upper().str.strip()
            + "|"
            + out.get("direction", "").astype(str).str.upper().str.strip()
        ) if len(out.index) else pd.Series(dtype=str)
        out["telemetry_k_shrink"] = 1.0
        out["telemetry_under_penalty"] = 1.0
        out["telemetry_mult"] = 1.0
        out["telemetry_bucket_mult"] = 1.0
        out["telemetry_cal_key"] = key if len(key) else ""
        out["telemetry_cal_applied"] = False
        return out

    source_label_col = f"{source_col}_src"
    allowed_mask = _telemetry_source_allowed_mask(out, calib, source_label_col=source_label_col)

    work = out.copy()
    work["p_adj"] = pd.to_numeric(out[source_col], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    work = apply_calibration(work, calib, apply_under_penalty=apply_under_penalty)

    base_probs = pd.to_numeric(out[source_col], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    cal_probs = pd.to_numeric(work["p_adj"], errors="coerce").fillna(base_probs).clip(0.0, 1.0)
    out[out_col] = base_probs.where(~allowed_mask, cal_probs)

    out["telemetry_k_shrink"] = pd.to_numeric(work.get("telemetry_k_shrink", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_under_penalty"] = pd.to_numeric(work.get("telemetry_under_penalty", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_mult"] = pd.to_numeric(work.get("telemetry_mult", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_bucket_mult"] = pd.to_numeric(work.get("telemetry_bucket_mult", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)

    stat = out.get("stat", "").astype(str).str.upper().str.strip()
    direction = out.get("direction", "").astype(str).str.upper().str.strip()
    tier = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    out["telemetry_cal_key"] = (stat + "|" + direction).astype(str)

    k = float(calib.k_shrink)
    under_pen = float(calib.standard_under_penalty)
    shrink_applied = (k != 1.0)
    if apply_under_penalty and (under_pen != 1.0):
        under_mask = (tier == "STANDARD") & (direction == "UNDER")
    else:
        under_mask = pd.Series(False, index=out.index)
    mult_applied = pd.to_numeric(out["telemetry_mult"], errors="coerce").fillna(1.0).ne(1.0)
    bucket_applied = pd.to_numeric(out["telemetry_bucket_mult"], errors="coerce").fillna(1.0).ne(1.0)
    if shrink_applied:
        out["telemetry_cal_applied"] = allowed_mask
    else:
        out["telemetry_cal_applied"] = allowed_mask & (under_mask | mult_applied | bucket_applied)
    return out
