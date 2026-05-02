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
Legacy support only. The live standard now points at ``data/model/telemetry_calibration.v2.json``.

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

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TelemetryCalibration:
    version: int = 1
    generated_at: str = ""
    mode: str = "telemetry"
    k_shrink: float = 1.0
    standard_under_penalty: float = 0.90
    demon_tier_penalty: float = 1.0
    mult: Dict[str, float] = None  # key: "STAT|DIRECTION"
    # Optional per-role-context multiplier maps. Keys same as `mult` ("STAT|DIRECTION").
    # `mult_rolectx_on` is applied when `role_ctx_outs_used` > 0, `mult_rolectx_off` when == 0.
    mult_rolectx_on: Dict[str, float] = None
    mult_rolectx_off: Dict[str, float] = None
    source_scales: List[Tuple[Tuple[str, ...], float]] = None
    bucket_rules: List[Tuple[float, float, float]] = None  # (min, max, mult)
    apply_only_p_cal_src_prefixes: Tuple[str, ...] = ()
    exclude_p_cal_src_prefixes: Tuple[str, ...] = ()
    cap_min: float = 0.01
    cap_max: float = 0.99
    isotonic_x: Tuple[float, ...] = ()
    isotonic_y: Tuple[float, ...] = ()
    isotonic_mix: float = 1.0
    isotonic_source_col: str = ""
    pre_calibration: Optional["TelemetryCalibration"] = None
    protected_calibration: Optional["TelemetryCalibration"] = None
    protected_stat_directions: Tuple[str, ...] = ()
    protected_role_ctx: str = ""
    protected_tier: str = ""
    scoped_families: Tuple[Dict[str, Any], ...] = ()

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

        def _norm_float_tuple(raw: Any) -> Tuple[float, ...]:
            if not isinstance(raw, list):
                return ()
            vals: List[float] = []
            for item in raw:
                try:
                    vals.append(float(item))
                except Exception:
                    continue
            return tuple(vals)

        def _maybe_float(raw: Any) -> Optional[float]:
            try:
                if raw is None:
                    return None
                return float(raw)
            except Exception:
                return None

        mode = str(d.get("mode", "")).strip().lower()
        if mode:
            meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
            pre_calibration_raw = d.get("pre_calibration")
            if pre_calibration_raw is None and isinstance(meta.get("pre_calibration"), dict):
                pre_calibration_raw = meta.get("pre_calibration")
            pre_calibration = TelemetryCalibration.from_json(pre_calibration_raw) if isinstance(pre_calibration_raw, dict) else None
            include_prefixes = _norm_prefixes(
                d.get("apply_only_p_cal_src_prefixes")
                if d.get("apply_only_p_cal_src_prefixes") is not None
                else meta.get("apply_only_p_cal_src_prefixes")
            )
            exclude_prefixes = _norm_prefixes(
                d.get("exclude_p_cal_src_prefixes")
                if d.get("exclude_p_cal_src_prefixes") is not None
                else meta.get("exclude_p_cal_src_prefixes")
            )
            cap = d.get("cap") if isinstance(d.get("cap"), dict) else {}
            cap_min = float(cap.get("min", d.get("cap_min", 0.01)))
            cap_max = float(cap.get("max", d.get("cap_max", 0.99)))

            if mode == "keep_identity":
                return TelemetryCalibration(
                    version=version,
                    generated_at=str(d.get("generated_at", "")),
                    mode=mode,
                    apply_only_p_cal_src_prefixes=include_prefixes,
                    exclude_p_cal_src_prefixes=exclude_prefixes,
                    cap_min=cap_min,
                    cap_max=cap_max,
                    pre_calibration=pre_calibration,
                )

            if mode == "telemetry_key":
                raw_mult = meta.get("mult_map") if isinstance(meta.get("mult_map"), dict) else d.get("mult")
                mult_map = raw_mult if isinstance(raw_mult, dict) else {}
                return TelemetryCalibration(
                    version=version,
                    generated_at=str(d.get("generated_at", "")),
                    mode=mode,
                    mult={str(k): float(v) for k, v in mult_map.items()},
                    apply_only_p_cal_src_prefixes=include_prefixes,
                    exclude_p_cal_src_prefixes=exclude_prefixes,
                    cap_min=cap_min,
                    cap_max=cap_max,
                    pre_calibration=pre_calibration,
                )

            if mode in {"isotonic_global", "isotonic_blend", "isotonic_hybrid"}:
                isotonic_x = _norm_float_tuple(
                    meta.get("x_thresholds")
                    if meta.get("x_thresholds") is not None
                    else d.get("x_thresholds")
                )
                isotonic_y = _norm_float_tuple(
                    meta.get("y_thresholds")
                    if meta.get("y_thresholds") is not None
                    else d.get("y_thresholds")
                )
                mix_raw = meta.get("mix", d.get("mix", 1.0 if mode == "isotonic_global" else 0.5))
                try:
                    isotonic_mix = float(mix_raw)
                except Exception:
                    isotonic_mix = 1.0 if mode == "isotonic_global" else 0.5
                isotonic_source_col = str(meta.get("source_col") or d.get("source_col") or "").strip()
                protected_calibration_raw = d.get("protected_calibration")
                if protected_calibration_raw is None and isinstance(meta.get("protected_calibration"), dict):
                    protected_calibration_raw = meta.get("protected_calibration")
                protected_calibration = TelemetryCalibration.from_json(protected_calibration_raw) if isinstance(protected_calibration_raw, dict) else None
                protected_stat_directions = _norm_prefixes(
                    d.get("protected_stat_directions")
                    if d.get("protected_stat_directions") is not None
                    else meta.get("protected_stat_directions")
                )
                protected_role_ctx = str(
                    d.get("protected_role_ctx")
                    if d.get("protected_role_ctx") is not None
                    else meta.get("protected_role_ctx")
                    or ""
                ).strip().lower()
                protected_tier = str(
                    d.get("protected_tier")
                    if d.get("protected_tier") is not None
                    else meta.get("protected_tier")
                    or ""
                ).strip().upper()
                return TelemetryCalibration(
                    version=version,
                    generated_at=str(d.get("generated_at", "")),
                    mode=mode,
                    apply_only_p_cal_src_prefixes=include_prefixes,
                    exclude_p_cal_src_prefixes=exclude_prefixes,
                    cap_min=cap_min,
                    cap_max=cap_max,
                    isotonic_x=isotonic_x,
                    isotonic_y=isotonic_y,
                    isotonic_mix=isotonic_mix,
                    isotonic_source_col=isotonic_source_col,
                    pre_calibration=pre_calibration,
                    protected_calibration=protected_calibration,
                    protected_stat_directions=protected_stat_directions,
                    protected_role_ctx=protected_role_ctx,
                    protected_tier=protected_tier,
                )

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
            scoped_families: List[Dict[str, Any]] = []
            source_scales: List[Tuple[Tuple[str, ...], float]] = []
            families = d.get("families") or []
            if isinstance(families, list):
                for family in families:
                    if not isinstance(family, dict):
                        continue
                    scope = family.get("scope") if isinstance(family.get("scope"), dict) else {}
                    role_ctx = str(family.get("role_ctx") or scope.get("role_ctx") or family.get("context") or "").strip().lower()
                    source_prefixes_raw = family.get("p_cal_src_prefixes") or family.get("source_prefixes") or family.get("source_prefix") or family.get("p_cal_src")
                    if isinstance(source_prefixes_raw, list):
                        source_prefixes = _norm_prefixes(source_prefixes_raw)
                    elif isinstance(source_prefixes_raw, str):
                        source_prefixes = _norm_prefixes([source_prefixes_raw])
                    else:
                        source_prefixes = _norm_prefixes(source_prefixes_raw)
                    scale_raw = family.get("scale")
                    scale_val = None
                    try:
                        if scale_raw is not None:
                            scale_val = float(scale_raw)
                    except Exception:
                        scale_val = None
                    if source_prefixes and scale_val is not None:
                        source_scales.append((source_prefixes, scale_val))
                        continue

                    family_mult = family.get("mult") or family.get("map") or {}
                    if not isinstance(family_mult, dict):
                        continue
                    stat_directions = _norm_prefixes(scope.get("stat_directions") if scope.get("stat_directions") is not None else family.get("stat_directions"))
                    q_blowout_min = _maybe_float(scope.get("q_blowout_min") if scope.get("q_blowout_min") is not None else family.get("q_blowout_min", family.get("min_q")))
                    q_blowout_max = _maybe_float(scope.get("q_blowout_max") if scope.get("q_blowout_max") is not None else family.get("q_blowout_max", family.get("max_q")))
                    if stat_directions or q_blowout_min is not None or q_blowout_max is not None:
                        scoped_families.append(
                            {
                                "role_ctx": role_ctx,
                                "stat_directions": stat_directions,
                                "q_blowout_min": q_blowout_min,
                                "q_blowout_max": q_blowout_max,
                                "mult": {str(k): float(v) for k, v in family_mult.items()},
                            }
                        )
                        continue
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
                mode="telemetry",
                k_shrink=float(base.get("k_shrink", d.get("k_shrink", 1.0))),
                standard_under_penalty=float(base.get("standard_under_penalty", d.get("standard_under_penalty", 0.90))),
                demon_tier_penalty=float(base.get("demon_tier_penalty", d.get("demon_tier_penalty", 1.0))),
                mult=mult,
                mult_rolectx_on=mult_rolectx_on,
                mult_rolectx_off=mult_rolectx_off,
                source_scales=source_scales,
                bucket_rules=bucket_rules,
                apply_only_p_cal_src_prefixes=_norm_prefixes(policy.get("apply_only_p_cal_src_prefixes") if policy else d.get("apply_only_p_cal_src_prefixes")),
                exclude_p_cal_src_prefixes=_norm_prefixes(policy.get("exclude_p_cal_src_prefixes") if policy else d.get("exclude_p_cal_src_prefixes")),
                cap_min=cap_min,
                cap_max=cap_max,
                scoped_families=tuple(scoped_families),
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
            mode="telemetry",
            k_shrink=float(d.get("k_shrink", 1.0)),
            standard_under_penalty=float(d.get("standard_under_penalty", 0.90)),
            demon_tier_penalty=float(d.get("demon_tier_penalty", 1.0)),
            mult={str(k): float(v) for k, v in mult.items()},
            mult_rolectx_on={str(k): float(v) for k, v in mult_rolectx_on.items()},
            mult_rolectx_off={str(k): float(v) for k, v in mult_rolectx_off.items()},
            source_scales=[],
            bucket_rules=bucket_rules,
            apply_only_p_cal_src_prefixes=_norm_prefixes(d.get("apply_only_p_cal_src_prefixes")),
            exclude_p_cal_src_prefixes=_norm_prefixes(d.get("exclude_p_cal_src_prefixes")),
            cap_min=cap_min,
            cap_max=cap_max,
        )


def _default_calibration_path(project_root: Path) -> Path:
    return project_root / "data" / "model" / "telemetry_calibration.v2.json"


def seed_telemetry_columns(scored: pd.DataFrame, *, include_bucket_mult: bool = False) -> pd.DataFrame:
    """Initialize telemetry diagnostic columns with no-op defaults."""
    out = scored.copy()
    if "stat" in out.columns:
        stat = out["stat"].astype(str).str.upper().str.strip()
    else:
        stat = pd.Series("", index=out.index, dtype=str)
    if "direction" in out.columns:
        direction = out["direction"].astype(str).str.upper().str.strip()
    else:
        direction = pd.Series("", index=out.index, dtype=str)

    out["telemetry_cal_key"] = (stat + "|" + direction).astype(str)
    out["telemetry_k_shrink"] = 1.0
    out["telemetry_under_penalty"] = 1.0
    out["telemetry_demon_penalty"] = 1.0
    out["telemetry_mult"] = 1.0
    if include_bucket_mult:
        out["telemetry_bucket_mult"] = 1.0
    out["telemetry_cal_applied"] = False
    return out


def load_calibration(project_root: Path, calibration_path: Optional[Path] = None) -> Optional[TelemetryCalibration]:
    """Load calibration from disk. Returns None if missing/unreadable."""
    path = calibration_path or _default_calibration_path(project_root)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return None
        return TelemetryCalibration.from_json(d)
    except Exception:
        return None


def _apply_isotonic_curve(series: pd.Series, calib: TelemetryCalibration) -> pd.Series:
    base = pd.to_numeric(series, errors="coerce")
    x = np.asarray(tuple(calib.isotonic_x or ()), dtype=float)
    y = np.asarray(tuple(calib.isotonic_y or ()), dtype=float)
    if x.size < 2 or y.size != x.size:
        return base.clip(0.0, 1.0)

    order = np.argsort(x)
    x = x[order]
    y = y[order]

    out = pd.Series(np.nan, index=base.index, dtype=float)
    valid = base.notna()
    if not valid.any():
        return out

    clipped = base.loc[valid].clip(float(x[0]), float(x[-1]))
    interp = np.interp(clipped.to_numpy(dtype=float), x, y, left=float(y[0]), right=float(y[-1]))
    out.loc[valid] = pd.Series(interp, index=clipped.index, dtype=float)
    return out.clip(0.0, 1.0)


def _isotonic_probs(series: pd.Series, calib: TelemetryCalibration) -> pd.Series:
    base = pd.to_numeric(series, errors="coerce").fillna(0.50).clip(0.0, 1.0)
    if calib.mode == "keep_identity":
        return base
    isotonic = _apply_isotonic_curve(base, calib)
    blend = 1.0 if calib.mode == "isotonic_global" else float(calib.isotonic_mix)
    blend = min(max(blend, 0.0), 1.0)
    return ((1.0 - blend) * base + blend * isotonic).clip(0.0, 1.0)


def _hybrid_protected_mask(scored: pd.DataFrame, calib: TelemetryCalibration) -> pd.Series:
    mask = pd.Series(True, index=scored.index, dtype=bool)

    keys = tuple((calib.protected_stat_directions or ()))
    if keys:
        if "stat" in scored.columns and "direction" in scored.columns:
            stat = scored["stat"].astype(str).str.upper().str.strip()
            direction = scored["direction"].astype(str).str.upper().str.strip()
            stat_dir = (stat + "|" + direction).astype(str)
            mask &= stat_dir.isin(keys)
        else:
            mask &= False

    role_ctx = str(calib.protected_role_ctx or "").strip().lower()
    if role_ctx in {"off", "on"}:
        if "role_ctx_outs_used" in scored.columns:
            role_on = pd.to_numeric(scored["role_ctx_outs_used"], errors="coerce").fillna(0).astype(float) > 0
            mask &= ~role_on if role_ctx == "off" else role_on
        else:
            mask &= False

    tier_filter = str(calib.protected_tier or "").strip().upper()
    if tier_filter:
        if "tier" in scored.columns:
            tier = scored["tier"].astype(str).str.upper().str.strip()
            mask &= tier == tier_filter
        else:
            mask &= False

    return mask.fillna(False)


def _resolve_isotonic_base_probs(
    scored: pd.DataFrame,
    calib: TelemetryCalibration,
    *,
    source_col: str,
    apply_under_penalty: bool,
) -> pd.Series:
    isotonic_source_col = calib.isotonic_source_col or source_col
    source_name = isotonic_source_col if isotonic_source_col in scored.columns else source_col
    if calib.pre_calibration is not None:
        nested = apply_calibration_to_column(
            scored.copy(),
            calib.pre_calibration,
            source_col=source_name,
            out_col="__telemetry_precal__",
            apply_under_penalty=apply_under_penalty,
        )
        return pd.to_numeric(nested.get("__telemetry_precal__"), errors="coerce").fillna(0.50).clip(0.0, 1.0)
    return pd.to_numeric(scored[source_name], errors="coerce").fillna(0.50).clip(0.0, 1.0)


def _apply_isotonic_like_mode(
    scored: pd.DataFrame,
    calib: TelemetryCalibration,
    *,
    source_col: str,
    out_col: str,
    allowed_mask: pd.Series,
    apply_under_penalty: bool,
) -> pd.DataFrame:
    out = seed_telemetry_columns(scored, include_bucket_mult=True)
    base_probs = _resolve_isotonic_base_probs(out, calib, source_col=source_col, apply_under_penalty=apply_under_penalty)

    if calib.mode == "isotonic_hybrid":
        main_probs = _isotonic_probs(base_probs, TelemetryCalibration(
            mode="isotonic_blend",
            isotonic_x=calib.isotonic_x,
            isotonic_y=calib.isotonic_y,
            isotonic_mix=calib.isotonic_mix,
        ))
        protected_calib = calib.protected_calibration
        if protected_calib is None:
            protected_probs = base_probs
        else:
            protected_probs = _isotonic_probs(base_probs, protected_calib)
        protected_mask = _hybrid_protected_mask(out, calib)
        cal_probs = main_probs.where(~protected_mask, protected_probs)
        changed = ((cal_probs - base_probs).abs() > 1e-12) & allowed_mask
        out[out_col] = base_probs.where(~allowed_mask, cal_probs)
        out["telemetry_cal_applied"] = changed.fillna(False)
        return out

    cal_probs = _isotonic_probs(base_probs, calib)
    out[out_col] = base_probs.where(~allowed_mask, cal_probs)
    if calib.mode == "keep_identity":
        out["telemetry_cal_applied"] = False
    else:
        changed = (cal_probs - base_probs).abs() > 1e-12
        out["telemetry_cal_applied"] = (allowed_mask & changed).fillna(False)
    return out


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
      - telemetry_demon_penalty
    """
    out = scored.copy()

    if "p_adj" not in out.columns:
        return out

    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    out["tier"] = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    out["stat"] = out.get("stat", "").astype(str).str.upper().str.strip()
    out["direction"] = out.get("direction", "").astype(str).str.upper().str.strip()

    if calib.mode in {"keep_identity", "isotonic_global", "isotonic_blend", "isotonic_hybrid"}:
        if calib.mode == "isotonic_hybrid":
            protected_calib = calib.protected_calibration
            main_probs = _isotonic_probs(out["p_adj"], TelemetryCalibration(
                mode="isotonic_blend",
                isotonic_x=calib.isotonic_x,
                isotonic_y=calib.isotonic_y,
                isotonic_mix=calib.isotonic_mix,
            ))
            protected_probs = _isotonic_probs(out["p_adj"], protected_calib) if protected_calib is not None else out["p_adj"].copy()
            protected_mask = _hybrid_protected_mask(out, calib)
            calibrated = main_probs.where(~protected_mask, protected_probs)
        else:
            calibrated = _isotonic_probs(out["p_adj"], calib)

        out["p_adj"] = calibrated
        out["telemetry_k_shrink"] = 1.0
        out["telemetry_under_penalty"] = 1.0
        out["telemetry_demon_penalty"] = 1.0
        out["telemetry_mult"] = 1.0
        out["telemetry_bucket_mult"] = 1.0
        return out

    k = float(calib.k_shrink)
    if k != 1.0:
        out["p_adj"] = (0.5 + k * (out["p_adj"] - 0.5)).clip(0.0, 1.0)

    under_pen = float(calib.standard_under_penalty)
    if apply_under_penalty:
        m_under_std = (out["tier"] == "STANDARD") & (out["direction"] == "UNDER")
        if m_under_std.any() and under_pen != 1.0:
            out.loc[m_under_std, "p_adj"] = (out.loc[m_under_std, "p_adj"] * under_pen).clip(0.0, 1.0)

    # Apply DEMON tier penalty (both OVER and UNDER)
    demon_pen = float(calib.demon_tier_penalty)
    if apply_under_penalty:  # using same gate as standard_under_penalty for consistency
        m_demon = (out["tier"] == "DEMON")
        if m_demon.any() and demon_pen != 1.0:
            out.loc[m_demon, "p_adj"] = (out.loc[m_demon, "p_adj"] * demon_pen).clip(0.0, 1.0)

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

    source_scale = pd.Series(1.0, index=out.index, dtype=float)
    source_label = out.get("_telemetry_source_label")
    if source_label is None and "p_cal_src" in out.columns:
        source_label = out["p_cal_src"]
    if source_label is None and "p_adj_src" in out.columns:
        source_label = out["p_adj_src"]
    if source_label is not None:
        source_label = source_label.fillna("").astype(str).str.strip()
        for prefixes, scale_val in (getattr(calib, "source_scales", None) or []):
            if not prefixes:
                continue
            mask = source_label.str.startswith(prefixes, na=False)
            if mask.any() and float(scale_val) != 1.0:
                source_scale.loc[mask] = source_scale.loc[mask] * float(scale_val)

    scoped_mult = pd.Series(1.0, index=out.index, dtype=float)
    for family in tuple(getattr(calib, "scoped_families", ()) or ()):
        if not isinstance(family, dict):
            continue
        family_map = family.get("mult") if isinstance(family.get("mult"), dict) else {}
        if not family_map:
            continue
        family_mask = _scoped_family_mask(out, family)
        if not family_mask.any():
            continue
        family_mult = keys.map({str(k).upper().strip(): float(v) for k, v in family_map.items()}).fillna(1.0).astype(float)
        scoped_mult.loc[family_mask] = scoped_mult.loc[family_mask] * family_mult.loc[family_mask]

    # Final telemetry multiplier applied to p_adj (before bucket and caps)
    mult = (base_mult * role_mult * source_scale * scoped_mult).astype(float)
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
    out["telemetry_demon_penalty"] = float(demon_pen)
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


def _scoped_family_mask(scored: pd.DataFrame, family: Dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=scored.index, dtype=bool)

    role_ctx = str(family.get("role_ctx") or "").strip().lower()
    if role_ctx in {"off", "on"}:
        if "role_ctx_outs_used" not in scored.columns:
            return pd.Series(False, index=scored.index, dtype=bool)
        role_on = pd.to_numeric(scored["role_ctx_outs_used"], errors="coerce").fillna(0).astype(float) > 0
        mask &= role_on if role_ctx == "on" else ~role_on

    stat_directions = tuple(family.get("stat_directions") or ())
    if stat_directions:
        if "telemetry_cal_key" in scored.columns:
            stat_dir = scored["telemetry_cal_key"].astype(str).str.upper().str.strip()
        elif {"stat", "direction"}.issubset(scored.columns):
            stat_dir = (scored["stat"].astype(str).str.upper().str.strip() + "|" + scored["direction"].astype(str).str.upper().str.strip()).astype(str)
        else:
            return pd.Series(False, index=scored.index, dtype=bool)
        mask &= stat_dir.isin({str(item).upper().strip() for item in stat_directions})

    q_blowout_min = family.get("q_blowout_min")
    q_blowout_max = family.get("q_blowout_max")
    if q_blowout_min is not None or q_blowout_max is not None:
        if "q_blowout" not in scored.columns:
            return pd.Series(False, index=scored.index, dtype=bool)
        q_vals = pd.to_numeric(scored["q_blowout"], errors="coerce")
        if q_blowout_min is not None:
            mask &= q_vals.ge(float(q_blowout_min))
        if q_blowout_max is not None:
            mask &= q_vals.le(float(q_blowout_max))

    return mask.fillna(False)


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
        return seed_telemetry_columns(out, include_bucket_mult=True)

    source_label_col = f"{source_col}_src"
    allowed_mask = _telemetry_source_allowed_mask(out, calib, source_label_col=source_label_col)

    if calib.mode in {"keep_identity", "isotonic_global", "isotonic_blend", "isotonic_hybrid"}:
        return _apply_isotonic_like_mode(
            out,
            calib,
            source_col=source_col,
            out_col=out_col,
            allowed_mask=allowed_mask,
            apply_under_penalty=apply_under_penalty,
        )

    work = out.copy()
    work["_telemetry_source_label"] = out[source_label_col].astype(str)
    work["p_adj"] = pd.to_numeric(out[source_col], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    work = apply_calibration(work, calib, apply_under_penalty=apply_under_penalty)

    base_probs = pd.to_numeric(out[source_col], errors="coerce").fillna(0.50).clip(0.0, 1.0)
    cal_probs = pd.to_numeric(work["p_adj"], errors="coerce").fillna(base_probs).clip(0.0, 1.0)
    out[out_col] = base_probs.where(~allowed_mask, cal_probs)

    out["telemetry_k_shrink"] = pd.to_numeric(work.get("telemetry_k_shrink", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_under_penalty"] = pd.to_numeric(work.get("telemetry_under_penalty", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_demon_penalty"] = pd.to_numeric(work.get("telemetry_demon_penalty", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_mult"] = pd.to_numeric(work.get("telemetry_mult", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)
    out["telemetry_bucket_mult"] = pd.to_numeric(work.get("telemetry_bucket_mult", 1.0), errors="coerce").fillna(1.0).where(allowed_mask, 1.0)

    stat = out.get("stat", "").astype(str).str.upper().str.strip()
    direction = out.get("direction", "").astype(str).str.upper().str.strip()
    tier = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    out["telemetry_cal_key"] = (stat + "|" + direction).astype(str)

    k = float(calib.k_shrink)
    under_pen = float(calib.standard_under_penalty)
    demon_pen = float(calib.demon_tier_penalty)
    shrink_applied = (k != 1.0)
    if apply_under_penalty and (under_pen != 1.0):
        under_mask = (tier == "STANDARD") & (direction == "UNDER")
    else:
        under_mask = pd.Series(False, index=out.index)
    if apply_under_penalty and (demon_pen != 1.0):
        demon_mask = (tier == "DEMON")
    else:
        demon_mask = pd.Series(False, index=out.index)
    mult_applied = pd.to_numeric(out["telemetry_mult"], errors="coerce").fillna(1.0).ne(1.0)
    bucket_applied = pd.to_numeric(out["telemetry_bucket_mult"], errors="coerce").fillna(1.0).ne(1.0)
    if shrink_applied:
        out["telemetry_cal_applied"] = allowed_mask
    else:
        out["telemetry_cal_applied"] = allowed_mask & (under_mask | demon_mask | mult_applied | bucket_applied)
    return out
