from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_PROFILE: dict[str, Any] = {
    "name": "close_spurs_efficiency_wolves_glass",
    "required_teams": ["MIN", "SAS"],
    "fox_player": "De'Aaron Fox",
    "harper_player": "Dylan Harper",
    "stable_anchors": [
        "Anthony Edwards",
        "Victor Wembanyama",
        "Stephon Castle",
        "Rudy Gobert",
        "Julius Randle",
        "Naz Reid",
    ],
    "min_glass_team": "MIN",
    "min_glass_stats": ["REB", "RA", "PR", "PRA"],
    "min_glass_players": [
        "Rudy Gobert",
        "Naz Reid",
        "Julius Randle",
        "Jaden McDaniels",
        "Anthony Edwards",
    ],
    "sas_core_team": "SAS",
    "sas_core_stats": ["PTS", "PA", "PRA", "PR", "REB", "BLK"],
    "sas_core_players": [
        "Victor Wembanyama",
        "Stephon Castle",
        "De'Aaron Fox",
        "Dylan Harper",
        "Devin Vassell",
        "Julian Champagnie",
    ],
    "min_ra_rebound_led_players": [
        "Rudy Gobert",
        "Naz Reid",
        "Julius Randle",
        "Jaden McDaniels",
        "Anthony Edwards",
    ],
    "non_shooting_volume_stats": ["REB", "PR", "PRA", "PA", "RA"],
    "anchor_minutes": 28.0,
    "low_minutes": 18.0,
    "min_glass_score": 0.08,
    "reb_led_ra_score": 0.04,
    "assist_led_ra_penalty": 0.04,
    "sas_core_score": 0.05,
    "anchor_minutes_score": 0.05,
    "low_minutes_penalty": 0.12,
    "role_shooter_score": 0.02,
    "fox_uncertain_player_penalty": 0.08,
    "harper_uncertain_player_penalty": 0.07,
    "fox_uncertain_castle_creation_boost": 0.04,
    "fox_uncertain_wemby_touch_boost": 0.03,
    "sas_double_guard_uncertainty_support_penalty": 0.03,
}


def _section(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    sg = cfg.get("single_game_mode", {}) or {}
    return sg if isinstance(sg, dict) else {}


def _enabled(cfg: dict[str, Any] | None) -> bool:
    enabled = str(_section(cfg).get("enabled", "auto")).strip().lower()
    return enabled in {"1", "true", "yes", "on", "auto"}


def _profile(cfg: dict[str, Any] | None) -> dict[str, Any]:
    sg = _section(cfg)
    profile = dict(DEFAULT_PROFILE)
    overrides = sg.get("profile", {}) or {}
    if isinstance(overrides, dict):
        profile.update(overrides)
    if sg.get("primary_script"):
        profile["name"] = str(sg.get("primary_script"))
    return profile


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


def _set(values: Iterable[Any] | None) -> set[str]:
    return {_norm(v) for v in (values or []) if _norm(v)}


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


def _teams_present(df: pd.DataFrame) -> set[str]:
    teams: set[str] = set()
    for col in ("team", "opp"):
        if col not in df.columns:
            continue
        teams.update({_upper(v) for v in df[col] if _upper(v)})
    return teams


def _player_state(df: pd.DataFrame, players: pd.Series, player_name: str) -> str:
    player_key = _norm(player_name)
    if not player_key:
        return "clear"

    player_mask = players == player_key
    status = _status_text(df)

    out_terms = ("out", "inactive", "will not play")
    q_terms = ("questionable", "game time", "game-time", "doubtful", "limited", "soreness")

    role_out_text = ""
    if "role_ctx_outs" in df.columns:
        role_out_text = " ".join(_str_col(df, "role_ctx_outs").map(_norm).tolist())
    if player_key in role_out_text:
        return "out_context"

    if player_mask.any():
        player_status = status[player_mask]
        if any(any(term in s for term in out_terms) for s in player_status):
            return "out_context"

        if "is_questionable" in df.columns:
            q_vals = pd.to_numeric(df.loc[player_mask, "is_questionable"], errors="coerce")
            if isinstance(q_vals, pd.Series) and bool((q_vals.fillna(0.0) > 0.0).any()):
                return "questionable"

        if any(any(term in s for term in q_terms) for s in player_status):
            return "questionable"

    return "clear"


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
    """Add reportable single-game script-fit columns.

    This is intentionally selection-only/reporting metadata. It does not remove
    legs or block slip sizes by itself.
    """

    if df is None or len(df) == 0:
        return df

    out = df.copy()
    sg = _section(cfg)
    profile = _profile(cfg)
    games = count_games(out)
    active = _enabled(cfg) and games > 0 and games <= int(sg.get("trigger_max_games", 1) or 1)
    required_teams = {_upper(x) for x in profile.get("required_teams", []) if _upper(x)}
    teams_present = _teams_present(out)
    profile_active = active and (not required_teams or required_teams.issubset(teams_present))

    out["single_game_mode_enabled"] = bool(_enabled(cfg))
    out["single_game_slate"] = bool(active)
    out["single_game_profile_active"] = bool(profile_active)
    out["single_game_games"] = int(games)
    out["single_game_script_label"] = str(profile.get("name", ""))

    fit = np.zeros(len(out.index), dtype="float64")
    reasons: list[list[str]] = [[] for _ in range(len(out.index))]

    players = _str_col(out, "player").map(_norm)
    teams = _str_col(out, "team").map(_upper)
    stats = _str_col(out, "stat").map(_upper)
    directions = _str_col(out, "direction").map(_upper)
    minutes = _num_col(out, "modeled_minutes", default=np.nan)
    if np.isnan(minutes.to_numpy(copy=False)).all():
        minutes = _num_col(out, "min_mean", default=0.0)

    anchors = _set(profile.get("stable_anchors"))
    min_glass_players = _set(profile.get("min_glass_players"))
    sas_core_players = _set(profile.get("sas_core_players"))
    min_ra_rebound_led_players = _set(profile.get("min_ra_rebound_led_players"))
    min_glass_team = _upper(profile.get("min_glass_team", "MIN"))
    sas_core_team = _upper(profile.get("sas_core_team", "SAS"))
    min_glass_stats = {_upper(x) for x in profile.get("min_glass_stats", [])}
    sas_core_stats = {_upper(x) for x in profile.get("sas_core_stats", [])}
    non_shooting_volume_stats = {_upper(x) for x in profile.get("non_shooting_volume_stats", [])}

    anchor_flag = players.map(lambda p: p in anchors).to_numpy(dtype=bool)
    min_glass_flag = (
        (teams == min_glass_team)
        & (directions == "OVER")
        & stats.isin(min_glass_stats)
        & players.map(lambda p: p in min_glass_players)
    ).to_numpy(dtype=bool)
    sas_core_flag = (
        (teams == sas_core_team)
        & (directions == "OVER")
        & stats.isin(sas_core_stats)
        & players.map(lambda p: p in sas_core_players)
    ).to_numpy(dtype=bool)

    role_shooter_stats = {_upper(x) for x in sg.get("role_shooter_stats", ["FG3M", "3PM", "3PTM", "PTS"])}
    fg3m_stats = {"FG3M", "3PM", "3PTM", "3PT MADE", "THREES"}
    fg3m_over_flag = (directions == "OVER") & stats.isin(fg3m_stats)
    role_shooter_flag = (
        (directions == "OVER")
        & stats.isin(role_shooter_stats)
        & (~pd.Series(anchor_flag, index=out.index))
        & (minutes < float(profile.get("anchor_minutes", 28.0) or 28.0))
    )
    non_shooting_volume_flag = (directions == "OVER") & stats.isin(non_shooting_volume_stats) & (~fg3m_over_flag)

    low_min = float(profile.get("low_minutes", 18.0) or 18.0)
    low_minute_bench_flag = (directions == "OVER") & (minutes < low_min)

    fox_state = _player_state(out, players, str(profile.get("fox_player", "De'Aaron Fox")))
    harper_state = _player_state(out, players, str(profile.get("harper_player", "Dylan Harper")))
    fox_uncertain = fox_state != "clear"
    harper_uncertain = harper_state != "clear"
    if fox_uncertain and harper_uncertain:
        branch_label = "fox_harper_uncertain"
    elif fox_uncertain:
        branch_label = "fox_uncertain"
    elif harper_uncertain:
        branch_label = "harper_uncertain"
    else:
        branch_label = "base"

    def _add(mask: np.ndarray, amount: float, reason: str) -> None:
        fit[mask] += float(amount)
        for idx in np.flatnonzero(mask):
            reasons[int(idx)].append(reason)

    if profile_active:
        _add(min_glass_flag, float(profile.get("min_glass_score", 0.08)), "min_glass_counterpunch")
        _add(sas_core_flag, float(profile.get("sas_core_score", 0.05)), "sas_core_efficiency")

        ra_min = (teams == min_glass_team) & (directions == "OVER") & (stats == "RA")
        if "reb_share_of_ra" in out.columns:
            reb_share = _num_col(out, "reb_share_of_ra", default=np.nan)
            reb_led = (ra_min & (reb_share >= 0.65)).to_numpy(dtype=bool)
            assist_led = (ra_min & (reb_share < 0.65)).to_numpy(dtype=bool)
            _add(reb_led, float(profile.get("reb_led_ra_score", 0.04)), "rebound_led_ra")
            _add(assist_led, -float(profile.get("assist_led_ra_penalty", 0.04)), "assist_led_ra")
        else:
            reb_led = (ra_min & players.map(lambda p: p in min_ra_rebound_led_players)).to_numpy(dtype=bool)
            assist_led = (ra_min & ~players.map(lambda p: p in min_ra_rebound_led_players)).to_numpy(dtype=bool)
            _add(reb_led, float(profile.get("reb_led_ra_score", 0.04)), "rebound_led_ra_profile")
            _add(assist_led, -float(profile.get("assist_led_ra_penalty", 0.04)), "assist_led_ra_profile")

        anchor_minutes = float(profile.get("anchor_minutes", 28.0) or 28.0)
        _add((minutes >= anchor_minutes).to_numpy(dtype=bool), float(profile.get("anchor_minutes_score", 0.05)), "close_game_minutes")
        _add((minutes < low_min).to_numpy(dtype=bool), -float(profile.get("low_minutes_penalty", 0.12)), "low_minutes_risk")
        _add(role_shooter_flag.to_numpy(dtype=bool), float(profile.get("role_shooter_score", 0.02)), "role_shooter_one_allowed")

        fox_player = _norm(profile.get("fox_player", "De'Aaron Fox"))
        harper_player = _norm(profile.get("harper_player", "Dylan Harper"))
        if fox_uncertain:
            _add(
                (players == fox_player).to_numpy(dtype=bool),
                -float(profile.get("fox_uncertain_player_penalty", 0.08)),
                f"fox_{fox_state}_penalty",
            )
            castle_creation = (
                (teams == sas_core_team)
                & (players == _norm("Stephon Castle"))
                & stats.isin({"AST", "PA", "PRA", "PR"})
            ).to_numpy(dtype=bool)
            _add(
                castle_creation,
                float(profile.get("fox_uncertain_castle_creation_boost", 0.04)),
                f"fox_{fox_state}_castle_creation",
            )
            wemby_touch = (
                (teams == sas_core_team)
                & (players == _norm("Victor Wembanyama"))
                & stats.isin({"PTS", "PA", "PRA", "PR", "REB", "BLK"})
            ).to_numpy(dtype=bool)
            _add(
                wemby_touch,
                float(profile.get("fox_uncertain_wemby_touch_boost", 0.03)),
                f"fox_{fox_state}_wemby_touch",
            )
        if harper_uncertain:
            _add(
                (players == harper_player).to_numpy(dtype=bool),
                -float(profile.get("harper_uncertain_player_penalty", 0.07)),
                f"harper_{harper_state}_penalty",
            )
        if fox_uncertain and harper_uncertain:
            sas_support = (
                (teams == sas_core_team)
                & (directions == "OVER")
                & (~players.isin({_norm("Victor Wembanyama"), _norm("Stephon Castle")}))
            ).to_numpy(dtype=bool)
            _add(
                sas_support,
                -float(profile.get("sas_double_guard_uncertainty_support_penalty", 0.03)),
                "sas_double_guard_uncertainty_support",
            )

    out["single_game_script_fit"] = fit
    out["single_game_script_reasons"] = [";".join(x) for x in reasons]
    out["single_game_branch_label"] = branch_label if profile_active else ""
    out["single_game_fox_state"] = fox_state if profile_active else ""
    out["single_game_harper_state"] = harper_state if profile_active else ""
    out["single_game_fox_uncertain"] = int(profile_active and fox_uncertain)
    out["single_game_harper_uncertain"] = int(profile_active and harper_uncertain)
    out["single_game_anchor_flag"] = anchor_flag.astype(int)
    out["single_game_min_glass_flag"] = min_glass_flag.astype(int)
    out["single_game_sas_core_flag"] = sas_core_flag.astype(int)
    out["single_game_role_shooter_over_flag"] = role_shooter_flag.astype(int)
    out["single_game_fg3m_over_flag"] = fg3m_over_flag.astype(int)
    out["single_game_non_shooting_volume_flag"] = non_shooting_volume_flag.astype(int)
    out["single_game_low_minute_bench_over_flag"] = low_minute_bench_flag.astype(int)
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

    weight = float(surface.get("script_fit_weight", 1.0) or 0.0)
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

    single_game = any(bool(r.get("single_game_profile_active", False)) for r in rows)
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

    fits: list[float] = []
    for r in rows:
        try:
            v = float(r.get("single_game_script_fit", 0.0) or 0.0)
            if v == v:
                fits.append(v)
        except Exception:
            pass

    metrics = {
        "single_game_anchor_legs": _count_flag("single_game_anchor_flag"),
        "single_game_min_glass_legs": _count_flag("single_game_min_glass_flag"),
        "single_game_sas_core_legs": _count_flag("single_game_sas_core_flag"),
        "single_game_role_shooter_overs": _count_flag("single_game_role_shooter_over_flag"),
        "single_game_fg3m_overs": _count_flag("single_game_fg3m_over_flag"),
        "single_game_non_shooting_volume_legs": _count_flag("single_game_non_shooting_volume_flag"),
        "single_game_low_minute_bench_overs": _count_flag("single_game_low_minute_bench_over_flag"),
        "single_game_avg_script_fit": float(sum(fits) / len(fits)) if fits else 0.0,
    }

    reasons: list[str] = []

    def _max_rule(key: str, metric: str) -> None:
        if key in rules:
            cap = int(rules.get(key, 0) or 0)
            if int(metrics.get(metric, 0)) > cap:
                reasons.append(f"{key}_exceeded")

    _max_rule("max_role_shooter_overs", "single_game_role_shooter_overs")
    _max_rule("max_fg3m_overs", "single_game_fg3m_overs")
    _max_rule("max_low_minute_bench_overs", "single_game_low_minute_bench_overs")

    if bool(rules.get("require_one_stable_anchor", False)) and int(metrics["single_game_anchor_legs"]) <= 0:
        reasons.append("missing_stable_anchor")
    if bool(rules.get("require_one_min_glass_or_counterweight", False)) and int(metrics["single_game_min_glass_legs"]) <= 0:
        reasons.append("missing_min_glass_counterweight")
    if bool(rules.get("require_one_sas_core", False)) and int(metrics["single_game_sas_core_legs"]) <= 0:
        reasons.append("missing_sas_core")

    require_volume_min_legs = int(rules.get("require_non_shooting_volume_min_legs", 0) or 0)
    if require_volume_min_legs > 0 and int(n_legs) >= require_volume_min_legs:
        if int(metrics["single_game_non_shooting_volume_legs"]) <= 0:
            reasons.append("missing_non_shooting_volume_leg")

    min_avg_by_legs = rules.get("min_avg_script_fit_by_legs", {}) or {}
    min_avg = min_avg_by_legs.get(int(n_legs), min_avg_by_legs.get(str(n_legs)))
    if min_avg is not None and float(metrics["single_game_avg_script_fit"]) < float(min_avg):
        reasons.append("script_fit_below_floor")

    return len(reasons) == 0, reasons, metrics
