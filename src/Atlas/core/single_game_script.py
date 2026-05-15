from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_ROBUSTNESS: dict[str, Any] = {
    "name": "single_game_robust_mode",
    "core_minutes": 28.0,
    "low_minutes": 18.0,
    "low_line_pts_threshold": 6.5,
    "low_line_fg3m_threshold": 0.5,
    "low_line_ast_threshold": 2.5,
    "low_line_reb_threshold": 3.5,
    "q_out_frac_threshold": 0.10,
    "high_volatility_threshold": 0.70,
    "high_fragility_threshold": 0.35,
    "core_minutes_stability_bonus": 0.02,
    "multi_script_survival_bonus": 0.03,
    "non_shooting_volume_bonus": 0.02,
    "fragile_shooter_over_penalty": 0.05,
    "low_minutes_role_penalty": 0.08,
    "low_line_noise_penalty": 0.03,
    "injury_uncertainty_penalty": 0.06,
    "high_volatility_penalty": 0.03,
    "high_fragility_penalty": 0.03,
    "max_abs_selection_delta": 0.12,
    "role_shooter_stats": ["FG3M", "3PM", "3PTM", "PTS"],
    "fg3m_stats": ["FG3M", "3PM", "3PTM", "3PT MADE", "THREES"],
    "non_shooting_volume_stats": ["REB", "AST", "RA", "PA", "PR", "PRA"],
}


def _section(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    sg = cfg.get("single_game_mode", {}) or {}
    return sg if isinstance(sg, dict) else {}


def _enabled(cfg: dict[str, Any] | None) -> bool:
    enabled = str(_section(cfg).get("enabled", "auto")).strip().lower()
    return enabled in {"1", "true", "yes", "on", "auto"}


def _robustness_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    sg = _section(cfg)
    out = dict(DEFAULT_ROBUSTNESS)
    overrides = sg.get("robustness", {}) or {}
    if isinstance(overrides, dict):
        out.update(overrides)
    if sg.get("name"):
        out["name"] = str(sg.get("name"))
    return out


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if text in {"", "nan", "none"}:
        return ""
    return " ".join(text.replace(".", "").split())


def _upper(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    return "" if text in {"", "NAN", "NONE"} else text


def _num_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.full(len(df.index), float(default), dtype="float64"), index=df.index)
    out = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(out, pd.Series):
        out = pd.Series(out, index=df.index)
    arr = np.asarray(out.to_numpy(copy=True), dtype="float64")
    arr[np.isnan(arr)] = float(default)
    return pd.Series(arr, index=df.index)


def _str_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([""] * len(df.index), index=df.index, dtype=object)
    return df[col].map(lambda x: "" if x is None else str(x))


def _status_text(df: pd.DataFrame) -> pd.Series:
    cols = [
        "injury_status",
        "iael_status",
        "player_status",
        "status",
        "availability",
        "injury_designation",
    ]
    out = pd.Series([""] * len(df.index), index=df.index, dtype=object)
    for col in cols:
        if col in df.columns:
            out = (out + " " + _str_col(df, col)).str.strip()
    return out.map(_norm)


def count_games(df: pd.DataFrame) -> int:
    if df is None or len(df) == 0:
        return 0
    if "game_id" in df.columns:
        vals = {_upper(v) for v in df["game_id"] if _upper(v)}
        if vals:
            return len(vals)
    if "team" in df.columns and "opp" in df.columns:
        games: set[tuple[str, str]] = set()
        for team, opp in zip(df["team"], df["opp"]):
            t = _upper(team)
            o = _upper(opp)
            if t and o:
                games.add(tuple(sorted((t, o))))
        if games:
            return len(games)
    return 0


def is_single_game_slate(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> bool:
    if not _enabled(cfg):
        return False
    trigger_max = int(_section(cfg).get("trigger_max_games", 1) or 1)
    games = count_games(df)
    return games > 0 and games <= trigger_max


def apply_single_game_script_annotations(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None,
) -> pd.DataFrame:
    """Add generic single-game robustness columns.

    The public function name is kept for compatibility with the pipeline, but
    this no longer encodes a team/player-specific game script. It applies a
    broad, selection-only robustness layer for one-game slates.
    """

    if df is None or len(df) == 0:
        return df

    out = df.copy()
    sg = _section(cfg)
    robust = _robustness_cfg(cfg)
    games = count_games(out)
    active = _enabled(cfg) and games > 0 and games <= int(sg.get("trigger_max_games", 1) or 1)

    out["single_game_mode_enabled"] = bool(_enabled(cfg))
    out["single_game_slate"] = bool(active)
    # Backward-compatible alias. In robust mode there is no profile gate; if the
    # slate is active, the generic profile is active.
    out["single_game_profile_active"] = bool(active)
    out["single_game_games"] = int(games)
    out["single_game_script_label"] = str(robust.get("name", "single_game_robust_mode"))

    fit = np.zeros(len(out.index), dtype="float64")
    dependency = np.zeros(len(out.index), dtype="float64")
    reasons: list[list[str]] = [[] for _ in range(len(out.index))]

    stats = _str_col(out, "stat").map(_upper)
    directions = _str_col(out, "direction").map(_upper)
    lines = _num_col(out, "line", default=np.nan)
    minutes = _num_col(out, "modeled_minutes", default=np.nan)
    if np.isnan(minutes.to_numpy(copy=False)).all():
        minutes = _num_col(out, "min_mean", default=np.nan)
    if np.isnan(minutes.to_numpy(copy=False)).all():
        minutes = pd.Series(np.zeros(len(out.index), dtype="float64"), index=out.index)

    core_minutes = float(robust.get("core_minutes", 28.0) or 28.0)
    low_minutes = float(robust.get("low_minutes", 18.0) or 18.0)
    fg3m_stats = {_upper(x) for x in robust.get("fg3m_stats", DEFAULT_ROBUSTNESS["fg3m_stats"])}
    role_shooter_stats = {_upper(x) for x in robust.get("role_shooter_stats", DEFAULT_ROBUSTNESS["role_shooter_stats"])}
    non_shooting_volume_stats = {
        _upper(x) for x in robust.get("non_shooting_volume_stats", DEFAULT_ROBUSTNESS["non_shooting_volume_stats"])
    }

    fg3m_over_flag = (directions == "OVER") & stats.isin(fg3m_stats)
    stable_anchor_flag = minutes >= core_minutes
    role_shooter_flag = (
        (directions == "OVER")
        & stats.isin(role_shooter_stats)
        & (~stable_anchor_flag)
        & (minutes < core_minutes)
    )
    non_shooting_volume_flag = (directions == "OVER") & stats.isin(non_shooting_volume_stats) & (~fg3m_over_flag)
    low_minute_bench_flag = (directions == "OVER") & (minutes < low_minutes)
    low_line_noise_flag = _low_line_noise(stats, directions, lines, robust)
    injury_uncertain_flag = _injury_uncertainty(out, robust)
    high_volatility_flag = _threshold_flag(out, "volatility_score", robust, "high_volatility_threshold")
    high_fragility_flag = _threshold_flag(out, "fragility_score", robust, "high_fragility_threshold")
    multi_script_survival_flag = stable_anchor_flag & (~low_line_noise_flag) & (~low_minute_bench_flag)
    slate_severity_score, slate_severity_label = _slate_severity(
        active=active,
        low_line_noise_flag=low_line_noise_flag,
        low_minute_bench_flag=low_minute_bench_flag,
        role_shooter_flag=role_shooter_flag,
        injury_uncertain_flag=injury_uncertain_flag,
        stable_anchor_flag=stable_anchor_flag,
    )

    def _add(mask: pd.Series | np.ndarray, amount: float, reason: str, *, dependency_amount: float = 0.0) -> None:
        if float(amount) == 0.0 and float(dependency_amount) == 0.0:
            return
        mask_arr = np.asarray(mask, dtype=bool)
        fit[mask_arr] += float(amount)
        if dependency_amount:
            dependency[mask_arr] += float(dependency_amount)
        for idx in np.flatnonzero(mask_arr):
            reasons[int(idx)].append(reason)

    if active:
        _add(stable_anchor_flag, float(robust.get("core_minutes_stability_bonus", 0.02)), "core_minutes_stability")
        _add(
            multi_script_survival_flag,
            float(robust.get("multi_script_survival_bonus", 0.03)),
            "multi_script_survival",
        )
        _add(
            non_shooting_volume_flag,
            float(robust.get("non_shooting_volume_bonus", 0.02)),
            "non_shooting_volume_floor",
        )
        _add(
            role_shooter_flag,
            -float(robust.get("fragile_shooter_over_penalty", 0.05)),
            "fragile_shooter_over",
            dependency_amount=float(robust.get("fragile_shooter_over_penalty", 0.05)),
        )
        _add(
            low_minute_bench_flag,
            -float(robust.get("low_minutes_role_penalty", 0.08)),
            "low_minutes_role",
            dependency_amount=float(robust.get("low_minutes_role_penalty", 0.08)),
        )
        _add(
            low_line_noise_flag,
            -float(robust.get("low_line_noise_penalty", 0.03)),
            "low_line_noise",
            dependency_amount=float(robust.get("low_line_noise_penalty", 0.03)),
        )
        _add(
            injury_uncertain_flag,
            -float(robust.get("injury_uncertainty_penalty", 0.06)),
            "injury_uncertainty",
            dependency_amount=float(robust.get("injury_uncertainty_penalty", 0.06)),
        )
        _add(
            high_volatility_flag,
            -float(robust.get("high_volatility_penalty", 0.03)),
            "high_volatility",
            dependency_amount=float(robust.get("high_volatility_penalty", 0.03)),
        )
        _add(
            high_fragility_flag,
            -float(robust.get("high_fragility_penalty", 0.03)),
            "high_fragility",
            dependency_amount=float(robust.get("high_fragility_penalty", 0.03)),
        )

    max_delta = float(robust.get("max_abs_selection_delta", 0.12) or 0.12)
    if max_delta > 0.0:
        fit = np.clip(fit, -max_delta, max_delta)

    robustness_score = np.clip(0.50 + fit - dependency, 0.0, 1.0)

    out["single_game_script_fit"] = fit
    out["single_game_script_reasons"] = [";".join(x) for x in reasons]
    out["single_game_branch_label"] = "robust_mode" if active else ""
    out["single_game_fox_state"] = ""
    out["single_game_harper_state"] = ""
    out["single_game_fox_uncertain"] = 0
    out["single_game_harper_uncertain"] = 0
    out["single_game_robustness_score"] = robustness_score
    out["single_game_script_dependency_score"] = dependency
    out["single_game_slate_severity_score"] = float(slate_severity_score)
    out["single_game_slate_severity_label"] = slate_severity_label
    out["single_game_robustness_reasons"] = out["single_game_script_reasons"]
    out["single_game_anchor_flag"] = stable_anchor_flag.astype(int)
    # Backward-compatible aliases. These no longer mean team-specific MIN/SAS
    # branches; consumers should prefer the explicit robustness columns.
    out["single_game_min_glass_flag"] = 0
    out["single_game_sas_core_flag"] = 0
    out["single_game_role_shooter_over_flag"] = role_shooter_flag.astype(int)
    out["single_game_fg3m_over_flag"] = fg3m_over_flag.astype(int)
    out["single_game_non_shooting_volume_flag"] = non_shooting_volume_flag.astype(int)
    out["single_game_low_minute_bench_over_flag"] = low_minute_bench_flag.astype(int)
    out["single_game_low_line_noise_flag"] = low_line_noise_flag.astype(int)
    out["single_game_multi_script_survival_flag"] = multi_script_survival_flag.astype(int)
    out["single_game_injury_uncertainty_flag"] = injury_uncertain_flag.astype(int)
    return out


def apply_single_game_selection_surface(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None,
    *,
    score_col: str,
    clip_score: bool,
) -> pd.DataFrame:
    if df is None or len(df) == 0 or score_col not in df.columns:
        return df

    out = apply_single_game_script_annotations(df, cfg)
    sg = _section(cfg)
    surface = sg.get("selection_surface", {}) or {}
    if not isinstance(surface, dict) or not bool(surface.get("enabled", False)):
        out["single_game_selection_delta"] = 0.0
        return out
    if not bool(out["single_game_slate"].iloc[0]):
        out["single_game_selection_delta"] = 0.0
        return out

    weight = float(surface.get("robustness_weight", surface.get("script_fit_weight", 1.0)) or 0.0)
    delta = pd.to_numeric(out["single_game_script_fit"], errors="coerce").fillna(0.0) * weight
    base = pd.to_numeric(out[score_col], errors="coerce").fillna(0.0)
    out[f"{score_col}_pre_single_game"] = base
    adjusted = base + delta
    if clip_score:
        adjusted = adjusted.clip(0.0, 1.0)
    out[score_col] = adjusted
    out["single_game_selection_delta"] = delta
    return out


def single_game_slip_rule_status(
    rows: list[pd.Series],
    cfg: dict[str, Any] | None,
    *,
    n_legs: int,
) -> tuple[bool, list[str], dict[str, Any]]:
    sg = _section(cfg)
    rules = sg.get("slip_rules", {}) or {}
    if not isinstance(rules, dict) or not bool(rules.get("enabled", False)):
        return True, [], {}
    if not rows:
        return True, [], {}

    single_game = any(bool(r.get("single_game_profile_active", False)) or bool(r.get("single_game_slate", False)) for r in rows)
    if not single_game:
        return True, [], {}

    def _count_flag(name: str) -> int:
        total = 0
        for r in rows:
            try:
                total += int(float(r.get(name, 0) or 0) > 0)
            except Exception:
                pass
        return total

    def _avg(name: str) -> float:
        vals: list[float] = []
        for r in rows:
            try:
                value = float(r.get(name, 0.0) or 0.0)
                if value == value:
                    vals.append(value)
            except Exception:
                pass
        return float(sum(vals) / len(vals)) if vals else 0.0

    metrics = {
        "single_game_anchor_legs": _count_flag("single_game_anchor_flag"),
        "single_game_min_glass_legs": _count_flag("single_game_min_glass_flag"),
        "single_game_sas_core_legs": _count_flag("single_game_sas_core_flag"),
        "single_game_role_shooter_overs": _count_flag("single_game_role_shooter_over_flag"),
        "single_game_fg3m_overs": _count_flag("single_game_fg3m_over_flag"),
        "single_game_under_legs": sum(
            1 for r in rows if str(r.get("direction", "")).strip().upper() == "UNDER"
        ),
        "single_game_non_shooting_volume_legs": _count_flag("single_game_non_shooting_volume_flag"),
        "single_game_low_minute_bench_overs": _count_flag("single_game_low_minute_bench_over_flag"),
        "single_game_low_line_noise_legs": _count_flag("single_game_low_line_noise_flag"),
        "single_game_multi_script_survival_legs": _count_flag("single_game_multi_script_survival_flag"),
        "single_game_avg_script_fit": _avg("single_game_script_fit"),
        "single_game_avg_robustness_score": _avg("single_game_robustness_score"),
        "single_game_avg_script_dependency_score": _avg("single_game_script_dependency_score"),
        "single_game_slate_severity_score": _avg("single_game_slate_severity_score"),
    }

    reasons: list[str] = []

    def _rule_value(key: str, default: Any = None) -> Any:
        by_legs = rules.get(f"{key}_by_legs")
        if isinstance(by_legs, dict):
            if int(n_legs) in by_legs:
                return by_legs[int(n_legs)]
            str_key = str(int(n_legs))
            if str_key in by_legs:
                return by_legs[str_key]
        return rules.get(key, default)

    def _max_rule(key: str, metric: str) -> None:
        raw_cap = _rule_value(key)
        if raw_cap is None:
            return
        cap = int(raw_cap or 0)
        if int(metrics.get(metric, 0)) > cap:
            reasons.append(f"{key}_exceeded")

    _max_rule("max_role_shooter_overs", "single_game_role_shooter_overs")
    _max_rule("max_fg3m_overs", "single_game_fg3m_overs")
    _max_rule("max_under_legs", "single_game_under_legs")
    _max_rule("max_low_minute_bench_overs", "single_game_low_minute_bench_overs")
    _max_rule("max_low_line_noise_legs", "single_game_low_line_noise_legs")

    min_anchor = _rule_value("min_stable_anchor_legs")
    if min_anchor is not None:
        if int(metrics["single_game_anchor_legs"]) < int(min_anchor or 0):
            reasons.append("missing_stable_anchor")
    elif bool(rules.get("require_one_stable_anchor", False)) and int(metrics["single_game_anchor_legs"]) <= 0:
        reasons.append("missing_stable_anchor")

    min_volume = _rule_value("min_non_shooting_volume_legs")
    if min_volume is not None:
        if int(metrics["single_game_non_shooting_volume_legs"]) < int(min_volume or 0):
            reasons.append("missing_non_shooting_volume_leg")
    else:
        require_volume_min_legs = int(rules.get("require_non_shooting_volume_min_legs", 0) or 0)
        if require_volume_min_legs > 0 and int(n_legs) >= require_volume_min_legs:
            if int(metrics["single_game_non_shooting_volume_legs"]) <= 0:
                reasons.append("missing_non_shooting_volume_leg")

    min_survival = int(_rule_value("min_multi_script_survival_legs", 0) or 0)
    if min_survival > 0 and int(metrics["single_game_multi_script_survival_legs"]) < min_survival:
        reasons.append("missing_multi_script_survival")

    min_avg_by_legs = rules.get("min_avg_robustness_by_legs", rules.get("min_avg_script_fit_by_legs", {})) or {}
    min_avg = min_avg_by_legs.get(int(n_legs), min_avg_by_legs.get(str(n_legs)))
    if min_avg is not None and float(metrics["single_game_avg_script_fit"]) < float(min_avg):
        reasons.append("robustness_fit_below_floor")

    return len(reasons) == 0, reasons, metrics


def _low_line_noise(stats: pd.Series, directions: pd.Series, lines: pd.Series, robust: dict[str, Any]) -> pd.Series:
    over = directions == "OVER"
    pts = stats == "PTS"
    fg3m = stats.isin({_upper(x) for x in robust.get("fg3m_stats", DEFAULT_ROBUSTNESS["fg3m_stats"])})
    ast = stats == "AST"
    reb = stats == "REB"
    return (
        over
        & (
            (pts & (lines <= float(robust.get("low_line_pts_threshold", 6.5) or 6.5)))
            | (fg3m & (lines <= float(robust.get("low_line_fg3m_threshold", 0.5) or 0.5)))
            | (ast & (lines <= float(robust.get("low_line_ast_threshold", 2.5) or 2.5)))
            | (reb & (lines <= float(robust.get("low_line_reb_threshold", 3.5) or 3.5)))
        )
    )


def _injury_uncertainty(df: pd.DataFrame, robust: dict[str, Any]) -> pd.Series:
    out = pd.Series(False, index=df.index)
    status = _status_text(df)
    if len(status):
        terms = ("questionable", "game time", "game-time", "doubtful", "limited", "soreness")
        out = out | status.map(lambda s: any(term in s for term in terms))
    if "is_questionable" in df.columns:
        out = out | (_num_col(df, "is_questionable", default=0.0) > 0.0)
    if "q_out_frac" in df.columns:
        threshold = float(robust.get("q_out_frac_threshold", 0.10) or 0.10)
        out = out | (_num_col(df, "q_out_frac", default=0.0) > threshold)
    return out


def _threshold_flag(df: pd.DataFrame, column: str, robust: dict[str, Any], config_key: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    threshold = float(robust.get(config_key, 0.0) or 0.0)
    if threshold <= 0.0:
        return pd.Series(False, index=df.index)
    return _num_col(df, column, default=0.0) >= threshold


def _slate_severity(
    *,
    active: bool,
    low_line_noise_flag: pd.Series,
    low_minute_bench_flag: pd.Series,
    role_shooter_flag: pd.Series,
    injury_uncertain_flag: pd.Series,
    stable_anchor_flag: pd.Series,
) -> tuple[float, str]:
    if not active or len(stable_anchor_flag) == 0:
        return 0.0, "inactive"

    def _share(flag: pd.Series) -> float:
        arr = np.asarray(flag, dtype=bool)
        return float(arr.mean()) if len(arr) else 0.0

    score = (
        0.25 * _share(low_line_noise_flag)
        + 0.30 * _share(low_minute_bench_flag)
        + 0.25 * _share(role_shooter_flag)
        + 0.20 * _share(injury_uncertain_flag)
        - 0.10 * _share(stable_anchor_flag)
    )
    score = float(max(0.0, min(1.0, score)))
    if score >= 0.18:
        return score, "extreme"
    if score >= 0.10:
        return score, "fragile"
    return score, "normal"
