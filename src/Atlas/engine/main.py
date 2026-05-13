from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import yaml
from zoneinfo import ZoneInfo

from ..core.matchup_enricher import enrich_with_matchups
from Atlas.core.share_name_key import share_name_key


def _to_series(val: Any, **kwargs: Any) -> pd.Series:
    """Thin wrapper around pd.to_numeric that tells Pyright the result is a Series."""
    return cast(pd.Series, pd.to_numeric(val, **kwargs))

# -------------------------------------------------------------------
# Repo root finder (runtime invariant: repo root contains tools/ and data/)
# -------------------------------------------------------------------


def find_repo_root(start: Path) -> Path:
    """
    Walk upward until we find the repo root. Repo root is defined as the directory
    that contains BOTH 'tools' and 'data'.
    """
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    return p.parent


# -------------------------------------------------------------------
# Paths (absolute, based on project root)
# -------------------------------------------------------------------

PROJECT_ROOT = find_repo_root(Path(__file__))
CONFIG_PATH = Path(os.environ.get("ATLAS_CONFIG_PATH", str(PROJECT_ROOT / "config.yaml"))).resolve()

DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
OUT_DIR = Path(os.environ.get("ATLAS_OUT_DIR", str(DATA_DIR / "output"))).resolve()

BOARD_PATH = Path(os.environ.get("ATLAS_BOARD_PATH", str(DATA_DIR / "board" / "today.csv"))).resolve()
ROSTER_MAP_PATH = Path(os.environ.get("ATLAS_ROSTER_MAP_PATH", str(DATA_DIR / "input" / "roster_map.csv"))).resolve()
SLATE_PATH = Path(os.environ.get("ATLAS_SLATE_PATH", str(DATA_DIR / "input" / "slate.csv"))).resolve()
LOGS_PATH = Path(os.environ.get("ATLAS_GAMELOGS_PATH", str(DATA_DIR / "gamelogs" / "nba_gamelogs.csv"))).resolve()

IAEL_INVALIDATIONS_PATH = Path(
    os.environ.get("ATLAS_IAEL_INVALIDATIONS_PATH", str(OUT_DIR / "dashboard" / "injury_invalidations_latest.json"))
).resolve()
IAEL_STATUS_PATH = Path(
    os.environ.get("ATLAS_IAEL_STATUS_PATH", str(OUT_DIR / "dashboard" / "status_latest.json"))
).resolve()

LOCAL_TZ = ZoneInfo("America/Chicago")

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def write_csv_clean(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _ensure_col(df: pd.DataFrame, col: str, default: Any) -> None:
    """Ensure df[col] exists; default can be scalar (broadcast) or Series-like."""
    if col not in df.columns:
        df[col] = default


def _combo_under_midq_telemetry_blend_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    combo_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    return (
        ~use_role.fillna(False).astype(bool)
        & under_relief_applied.fillna(False).astype(bool)
        & stat.isin(combo_stats)
        & direction.eq("UNDER")
        & q_blowout.gt(0.20)
        & q_blowout.le(0.30)
    )


def _apply_combo_under_midq_telemetry_blend(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
    retain: float = 0.40,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.0))
    blend_mask = _combo_under_midq_telemetry_blend_mask(
        out,
        use_role=use_role,
        under_relief_applied=under_relief_applied,
    )
    out["telemetry_combo_under_midq_blend_applied"] = blend_mask.astype(bool)
    out["telemetry_combo_under_midq_blend_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _combo_under_highq_telemetry_blend_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    combo_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    return (
        ~use_role.fillna(False).astype(bool)
        & under_relief_applied.fillna(False).astype(bool)
        & stat.isin(combo_stats)
        & direction.eq("UNDER")
        & q_blowout.gt(0.30)
    )


def _apply_combo_under_highq_telemetry_blend(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
    retain: float = 0.68,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.0))
    blend_mask = _combo_under_highq_telemetry_blend_mask(
        out,
        use_role=use_role,
        under_relief_applied=under_relief_applied,
    )
    out["telemetry_combo_under_highq_blend_applied"] = blend_mask.astype(bool)
    out["telemetry_combo_under_highq_blend_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _combo_under_lowmidq_telemetry_blend_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    combo_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    return (
        ~use_role.fillna(False).astype(bool)
        & under_relief_applied.fillna(False).astype(bool)
        & stat.isin(combo_stats)
        & direction.eq("UNDER")
        & q_blowout.gt(0.10)
        & q_blowout.le(0.20)
    )


def _apply_combo_under_lowmidq_telemetry_blend(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
    retain: float = 0.55,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.0))
    blend_mask = _combo_under_lowmidq_telemetry_blend_mask(
        out,
        use_role=use_role,
        under_relief_applied=under_relief_applied,
    )
    out["telemetry_combo_under_lowmidq_blend_applied"] = blend_mask.astype(bool)
    out["telemetry_combo_under_lowmidq_blend_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _combo_under_midq_ra_trim_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    return (
        ~use_role.fillna(False).astype(bool)
        & under_relief_applied.fillna(False).astype(bool)
        & stat.eq("RA")
        & direction.eq("UNDER")
        & q_blowout.gt(0.20)
        & q_blowout.le(0.30)
    )


def _apply_combo_under_midq_ra_trim(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    under_relief_applied: pd.Series,
    retain: float = 0.35,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.0))
    blend_mask = _combo_under_midq_ra_trim_mask(
        out,
        use_role=use_role,
        under_relief_applied=under_relief_applied,
    )
    out["telemetry_combo_under_midq_ra_trim_applied"] = blend_mask.astype(bool)
    out["telemetry_combo_under_midq_ra_trim_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _under_reb_lowmidq_no_relief_trim_mask(
    scored: pd.DataFrame,
    *,
    under_relief_applied: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    return (
        ~under_relief_applied.fillna(False).astype(bool)
        & stat.eq("REB")
        & direction.eq("UNDER")
        & q_blowout.gt(0.10)
        & q_blowout.le(0.20)
    )


def _apply_under_reb_lowmidq_no_relief_trim(
    scored: pd.DataFrame,
    *,
    under_relief_applied: pd.Series,
    retain: float = 1.0,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.5))
    blend_mask = _under_reb_lowmidq_no_relief_trim_mask(
        out,
        under_relief_applied=under_relief_applied,
    )
    out["telemetry_under_reb_lowmidq_no_relief_trim_applied"] = blend_mask.astype(bool)
    out["telemetry_under_reb_lowmidq_no_relief_trim_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _reb_over_midq_trim_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    return (
        ~use_role.fillna(False).astype(bool)
        & stat.eq("REB")
        & direction.eq("OVER")
        & q_blowout.gt(0.20)
        & q_blowout.le(0.30)
    )


def _apply_reb_over_midq_trim(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    retain: float = 1.0,
) -> pd.DataFrame:
    out = scored.copy()
    retain_f = float(np.clip(retain, 0.0, 1.0))
    blend_mask = _reb_over_midq_trim_mask(out, use_role=use_role)
    out["telemetry_reb_over_midq_trim_applied"] = blend_mask.astype(bool)
    out["telemetry_reb_over_midq_trim_retain"] = np.where(blend_mask, retain_f, 1.0)
    if not blend_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    blended = p_adj + ((p_cal - p_adj) * retain_f)
    out.loc[blend_mask, "p_cal"] = blended.loc[blend_mask].clip(0.0, 1.0)
    return out


def _fg3m_over_highq_blowout_lift_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    q_blowout = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    return ~use_role.fillna(False).astype(bool) & stat.eq("FG3M") & direction.eq("OVER") & q_blowout.gt(0.35)


def _apply_fg3m_over_highq_blowout_lift(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    factor: float = 0.0,
) -> pd.DataFrame:
    out = scored.copy()
    factor_f = float(np.clip(factor, 0.0, 1.0))
    lift_mask = _fg3m_over_highq_blowout_lift_mask(out, use_role=use_role)
    out["telemetry_fg3m_over_highq_blowout_lift_applied"] = lift_mask.astype(bool)
    out["telemetry_fg3m_over_highq_blowout_lift_factor"] = np.where(lift_mask, factor_f, 0.0)
    if not lift_mask.any() or factor_f <= 0.0:
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_role = _to_series(out.get("p_role", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    lifted = p_cal + ((p_role - p_adj) * factor_f)
    out.loc[lift_mask, "p_cal"] = lifted.loc[lift_mask].clip(0.0, 1.0)
    return out


def _combo_over_high_fragility_lift_mask(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
) -> pd.Series:
    stat = scored.get("stat", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    direction = scored.get("direction", pd.Series("", index=scored.index)).astype(str).str.upper().str.strip()
    fragility = pd.to_numeric(scored.get("fragility", pd.Series(0.0, index=scored.index)), errors="coerce").fillna(0.0)
    combo_stats = {"PTS", "PRA", "PA", "PR", "RA"}
    return (
        ~use_role.fillna(False).astype(bool)
        & stat.isin(combo_stats)
        & direction.eq("OVER")
        & fragility.gt(0.10)
    )


def _apply_combo_over_high_fragility_lift(
    scored: pd.DataFrame,
    *,
    use_role: pd.Series,
    factor: float = 0.36,
) -> pd.DataFrame:
    out = scored.copy()
    factor_f = float(np.clip(factor, 0.0, 1.0))
    lift_mask = _combo_over_high_fragility_lift_mask(out, use_role=use_role)
    out["telemetry_combo_over_high_fragility_lift_applied"] = lift_mask.astype(bool)
    out["telemetry_combo_over_high_fragility_lift_factor"] = np.where(lift_mask, factor_f, 0.0)
    if not lift_mask.any():
        return out

    p_adj = _to_series(out.get("p_adj", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    p_role = _to_series(out.get("p_role", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    p_cal = _to_series(out.get("p_cal", p_adj), errors="coerce").fillna(p_adj).clip(0.0, 1.0)
    lifted = p_cal + ((p_role - p_adj) * factor_f)
    out.loc[lift_mask, "p_cal"] = lifted.loc[lift_mask].clip(0.0, 1.0)
    return out


# -------------------------------------------------------------------
# Gamelog stat helpers (Pylance-safe)
# -------------------------------------------------------------------


def _compute_actual_series(logs: pd.DataFrame, stat: str) -> pd.Series:
    """
    Return a numeric Series for the requested stat from `logs`.
    Supports all stats in ALLOWED_STATS, plus core combo stats.
    """
    stat = (stat or "").upper().strip()
    if logs is None or logs.empty:
        return pd.Series([], dtype="float64")

    def _num(col: str) -> pd.Series:
        if col in logs.columns:
            return pd.to_numeric(logs[col], errors="coerce")
        return pd.Series(np.nan, index=logs.index, dtype="float64")

    pts = _num("pts")
    reb = _num("reb")
    astv = _num("ast")
    fg3m = _num("fg3m")
    blk = _num("blk")
    stl = _num("stl")

    if stat == "PTS":
        return pts
    if stat == "REB":
        return reb
    if stat == "AST":
        return astv
    if stat in ("FG3M", "3PM"):
        return fg3m

    if stat == "PR":
        return pts + reb
    if stat == "PA":
        return pts + astv
    if stat == "RA":
        return reb + astv
    if stat == "PRA":
        return pts + reb + astv

    if stat == "PTS_AST":
        return pts + astv
    if stat == "PTS_REB":
        return pts + reb
    if stat == "REB_AST":
        return reb + astv
    if stat == "BLKS_STLS":
        return blk + stl

    return pd.Series(np.nan, index=logs.index, dtype="float64")


# -------------------------------------------------------------------
# Board sanitization
# -------------------------------------------------------------------

ALLOWED_STATS = {
    "PTS",
    "REB",
    "AST",
    "FG3M",
    "PR",
    "PA",
    "RA",
    "PRA",
    "PTS_AST",
    "PTS_REB",
    "REB_AST",
    "3PM",
    "BLKS_STLS",
    "FTA",
}


def sanitize_board(board: pd.DataFrame) -> pd.DataFrame:
    required = ["player", "stat", "direction", "line"]
    missing = [c for c in required if c not in board.columns]
    if missing:
        raise ValueError(f"today.csv missing required columns: {missing}")

    out = board.copy()
    out["player"] = out["player"].astype(str).str.strip()
    out["stat"] = out["stat"].astype(str).str.strip().str.upper()
    out["direction"] = out["direction"].astype(str).str.strip().str.upper()
    out["line"] = pd.to_numeric(out["line"], errors="coerce")

    if "tier" in out.columns:
        out["tier"] = out["tier"].astype(str).str.strip().str.upper()
    else:
        out["tier"] = "STANDARD"

    for col in ["more_allowed", "less_allowed"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
        else:
            out[col] = 1

    before = len(out)
    out = out.dropna(subset=["line"])
    out = out[out["player"] != ""]
    out = out[out["direction"].isin({"OVER", "UNDER"})]
    out = out[out["stat"].isin(ALLOWED_STATS)]
    dropped = before - len(out)
    if dropped > 0:
        print(f"[DEBUG] Dropped {dropped} invalid rows from today.csv (blank/unknown stat/line)")

    bad_tier_under = out[(out["direction"] == "UNDER") & (out["tier"].isin(["DEMON", "GOBLIN"]))]
    if not bad_tier_under.empty:
        sample = bad_tier_under.head(10)[["player", "stat", "line", "tier", "direction"]]
        raise ValueError(
            "today.csv contains invalid rows: UNDER present for DEMON/GOBLIN.\n" + sample.to_string(index=False)
        )

    return out.reset_index(drop=True)


def drop_combo_name_players(board: pd.DataFrame) -> pd.DataFrame:
    mask = board["player"].astype(str).str.contains(r"\s\+\s", regex=True)
    dropped = int(mask.sum())
    if dropped > 0:
        print(f"[DEBUG] Dropped {dropped} combo-name player rows from today.csv (A + B)")
    return board[~mask].reset_index(drop=True)


def apply_local_game_date(board: pd.DataFrame) -> pd.DataFrame:
    if "start_time" not in board.columns:
        return board
    st = pd.to_datetime(board["start_time"], errors="coerce", utc=True)
    ok = st.notna()
    if ok.any():
        local_dt = st.dt.tz_convert(LOCAL_TZ)
        board = board.copy()
        board.loc[ok, "game_date"] = local_dt.loc[ok].dt.date.astype(str)
    return board


def infer_default_game_date(board: pd.DataFrame) -> str:
    try:
        slate = pd.read_csv(SLATE_PATH)
        for col in ["game_date", "date", "start_date", "slate_date"]:
            if col in slate.columns:
                dt = pd.to_datetime(slate[col], errors="coerce").dropna()
                if len(dt) > 0:
                    return dt.iloc[0].date().isoformat()
        for col in slate.columns:
            dt = pd.to_datetime(slate[col], errors="coerce").dropna()
            if len(dt) > 0:
                return dt.iloc[0].date().isoformat()
    except Exception:
        pass

    if "game_date" in board.columns:
        dt = pd.to_datetime(board["game_date"], errors="coerce").dropna()
        if len(dt) > 0:
            return dt.iloc[0].date().isoformat()

    return datetime.now(LOCAL_TZ).date().isoformat()


# -------------------------------------------------------------------
# Injury / IAEL integration (HARD FILTER)
# -------------------------------------------------------------------

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.IGNORECASE)


def normalize_person_name(name: Any) -> str:
    s = "" if name is None else str(name)
    s = s.strip().lower()
    s = s.replace(",", " ")
    s = s.replace("’", "'")
    s = s.replace(".", " ")
    s = s.replace("-", " ")
    s = re.sub(r"[^\w\s']", " ", s)
    s = _SUFFIX_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    tokens = [t for t in s.split(" ") if t]
    tokens.sort()
    return " ".join(tokens)


def _player_key(name: Any) -> str:
    """Local alias for the shared canonical player join key."""
    return share_name_key(name)


def normalize_team_token(team: Any) -> str:
    return ("" if team is None else str(team)).strip().upper()


def load_iael_invalidations(
    *,
    invalidations_path: Path = IAEL_INVALIDATIONS_PATH,
    status_path: Path = IAEL_STATUS_PATH,
) -> pd.DataFrame:
    if not invalidations_path.exists():
        print(f"[IAEL][WARN] Missing invalidations file: {invalidations_path}")
        return pd.DataFrame()

    try:
        obj = json.loads(invalidations_path.read_text(encoding="utf-8"))
        rows = obj.get("invalidated_players", []) or []
        df = pd.DataFrame(rows)

        # Merge in the run-scoped normalized injury snapshot when available so
        # QUESTIONABLE rows remain visible to soft-risk tagging.
        normalized_rows: list[dict[str, Any]] = []
        normalized_path = (os.environ.get("ATLAS_IAEL_NORMALIZED_PATH") or "").strip()
        if normalized_path:
            cand = Path(normalized_path)
        else:
            snapshot_dir = os.environ.get("ATLAS_IAEL_SNAPSHOT_DIR")
            if not snapshot_dir:
                raise RuntimeError("IAEL normalized snapshot is required for run-scoped injury loading")
            cand = Path(snapshot_dir) / "normalized_latest.json"

        if not cand.exists():
            raise RuntimeError(f"Missing run-scoped injury snapshot: {cand}")

        try:
            norm_obj = json.loads(cand.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to read run-scoped injury snapshot: {cand}") from exc

        if isinstance(norm_obj, dict):
            payload_rows = norm_obj.get("rows", []) or []
            if isinstance(payload_rows, list):
                normalized_rows = [r for r in payload_rows if isinstance(r, dict)]

        if normalized_rows:
            normalized_df = pd.DataFrame(normalized_rows)
            if not normalized_df.empty:
                if "player" not in normalized_df.columns and "name" in normalized_df.columns:
                    normalized_df["player"] = normalized_df["name"]
                if "team" not in normalized_df.columns:
                    normalized_df["team"] = ""
                if "status" not in normalized_df.columns:
                    normalized_df["status"] = "OUT"

                normalized_df["status"] = normalized_df["status"].astype(str).str.upper().str.strip()
                normalized_df = normalized_df[normalized_df["status"].isin({"OUT", "DOUBTFUL", "QUESTIONABLE", "Q", "D", "O"})].copy()
                if not normalized_df.empty:
                    if df.empty:
                        df = normalized_df
                    else:
                        for col in normalized_df.columns:
                            if col not in df.columns:
                                df[col] = ""
                        for col in df.columns:
                            if col not in normalized_df.columns:
                                normalized_df[col] = ""
                        df = pd.concat([df, normalized_df[df.columns]], ignore_index=True)

        if df.empty:
            if status_path.exists():
                try:
                    st = json.loads(status_path.read_text(encoding="utf-8"))
                    print(f"[IAEL] Loaded (0 invalidations). Report: {st.get('report_datetime_local', '')}")
                except Exception:
                    pass
            else:
                print("[IAEL] Loaded (0 invalidations).")
            return pd.DataFrame()

        if "player" not in df.columns:
            return pd.DataFrame()
        if "team" not in df.columns:
            df["team"] = ""

        df["player_norm"] = df["player"].apply(normalize_person_name)
        df["player_key"] = df["player"].apply(_player_key)
        df["team_norm"] = df["team"].apply(normalize_team_token)

        if "status" in df.columns:
            df["status"] = df["status"].astype(str).str.upper().str.strip()
        else:
            df["status"] = "OUT"

        df = df.dropna(subset=["player_norm"])
        df = df[df["player_norm"] != ""]
        df = df.drop_duplicates(subset=["team_norm", "player_key", "status"])

        if status_path.exists():
            try:
                st = json.loads(status_path.read_text(encoding="utf-8"))
                print(f"[IAEL] Loaded invalidations={len(df)}. Report: {st.get('report_datetime_local', '')}")
            except Exception:
                print(f"[IAEL] Loaded invalidations={len(df)}.")
        else:
            print(f"[IAEL] Loaded invalidations={len(df)}.")

        return df[["team_norm", "player_norm", "player_key", "player", "status"]].reset_index(drop=True)

    except Exception as e:
        print(f"[IAEL][ERROR] Failed to parse invalidations JSON: {e!r}")
        return pd.DataFrame()


def apply_iael_hard_filter(
    legs_df: pd.DataFrame,
    iael_df: pd.DataFrame,
    *,
    hard_statuses: set[str] | None = None,
    require_team_match: bool = False,
) -> pd.DataFrame:
    if legs_df is None or legs_df.empty:
        return legs_df
    if iael_df is None or iael_df.empty:
        print("[IAEL][WARN] IAEL invalidations empty -> no injury filtering applied.")
        return legs_df

    hard_statuses = hard_statuses or {"OUT", "DOUBTFUL"}
    iael = iael_df.copy()
    iael = iael[iael["status"].isin({s.upper() for s in hard_statuses})].copy()
    if iael.empty:
        print("[IAEL][DEBUG] IAEL present but no rows in hard statuses; no filtering applied.")
        return legs_df

    df = legs_df.copy()
    _ensure_col(df, "player", "")
    df["player_norm"] = df["player"].apply(normalize_person_name)

    team_col = None
    if require_team_match:
        for c in ["team", "team_abbrev", "team_code", "home_team", "away_team", "opponent_team", "opp_team"]:
            if c in df.columns:
                team_col = c
                break

    before = len(df)

    if require_team_match and team_col is not None:
        df["team_norm"] = df[team_col].apply(normalize_team_token)
        bad = iael[["team_norm", "player_norm"]].drop_duplicates()
        merged = df.merge(bad, on=["team_norm", "player_norm"], how="left", indicator=True)
        removed = int((merged["_merge"] == "both").sum())
        out = merged[merged["_merge"] == "left_only"].copy()
        out.drop(columns=["_merge", "player_norm", "team_norm"], errors="ignore", inplace=True)
    else:
        bad_players = set(iael["player_norm"].astype(str))
        mask_bad = df["player_norm"].astype(str).isin(bad_players)
        removed = int(mask_bad.sum())
        out = df[~mask_bad].copy()
        out.drop(columns=["player_norm"], errors="ignore", inplace=True)

    print(f"[IAEL] Removed {removed} legs out of {before} (statuses={sorted(hard_statuses)})")
    return out.reset_index(drop=True)


# -------------------------------------------------------------------
# Probabilities + modifiers (Pylance-safe)
# -------------------------------------------------------------------


def ensure_power_ev_columns(scored: pd.DataFrame) -> pd.DataFrame:
    out = scored.copy()

    _ensure_col(out, "p", 0.50)
    out["p"] = pd.to_numeric(out["p"], errors="coerce").fillna(0.50).clip(0, 1)

    _ensure_col(out, "p_adj", out["p"])
    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(out["p"]).fillna(0.50).clip(0, 1)

    hit_prob_default = out["p_adj"]
    _ensure_col(out, "hit_prob", hit_prob_default)
    out["hit_prob"] = pd.to_numeric(out["hit_prob"], errors="coerce").fillna(hit_prob_default).fillna(0.50).clip(0, 1)

    if "payout_modifier" not in out.columns:
        for alt in ("payout_mult", "payout_multiplier", "multiplier"):
            if alt in out.columns:
                out["payout_modifier"] = out[alt]
                break

    if "payout_modifier" not in out.columns:
        tier_mod = {"STANDARD": 1.00, "GOBLIN": 0.90, "DEMON": 1.10}
        _ensure_col(out, "tier", "STANDARD")
        out["payout_modifier"] = out["tier"].astype(str).str.upper().map(tier_mod).fillna(1.00)

    out["payout_modifier"] = pd.to_numeric(out["payout_modifier"], errors="coerce").fillna(1.00)

    _ensure_col(out, "ev_mult", out["payout_modifier"] * out["hit_prob"])
    out["ev_mult"] = pd.to_numeric(out["ev_mult"], errors="coerce").fillna(out["payout_modifier"] * out["hit_prob"])

    return out


def dedupe_over_under(scored: pd.DataFrame) -> pd.DataFrame:
    out = scored.copy()

    _ensure_col(out, "player", "")
    _ensure_col(out, "stat", "")
    _ensure_col(out, "tier", "STANDARD")
    _ensure_col(out, "direction", "")
    _ensure_col(out, "line", np.nan)

    out["player"] = out["player"].astype(str).str.strip()
    out["stat"] = out["stat"].astype(str).str.upper().str.strip()
    out["tier"] = out["tier"].astype(str).str.upper().str.strip()
    out["direction"] = out["direction"].astype(str).str.upper().str.strip()
    out["line"] = pd.to_numeric(out["line"], errors="coerce")

    out["prop_key"] = (
        out["player"]
        + "|"
        + out["stat"]
        + "|"
        + out["direction"]
        + "|"
        + out["line"].astype(str)
        + "|"
        + out["tier"]
    )

    if "p" not in out.columns:
        out["p"] = 0.50
    out["p"] = pd.to_numeric(out["p"], errors="coerce").fillna(0.50).clip(0, 1)

    _ensure_col(out, "p_adj", out["p"])
    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(out["p"]).fillna(0.50).clip(0, 1)

    out = out.sort_values(by=["prop_key", "p_adj"], ascending=[True, False], na_position="last")
    return out.drop_duplicates(subset=["prop_key"], keep="first").reset_index(drop=True)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------


def main() -> None:
    cfg = load_config()
    pricing_engine = str(cfg.get("pricing_engine", "atlas") or "atlas")
    _raw_rm = cfg.get("role_metrics")
    role_metrics_cfg: dict[str, Any] = _raw_rm if isinstance(_raw_rm, dict) else {}
    attach_role_metrics = bool(role_metrics_cfg.get("enabled", False))

    require_file(BOARD_PATH, "data/board/today.csv")
    require_file(LOGS_PATH, "data/gamelogs/nba_gamelogs.csv")
    require_file(ROSTER_MAP_PATH, "data/input/roster_map.csv")
    require_file(SLATE_PATH, "data/input/slate.csv")

    board = pd.read_csv(BOARD_PATH)
    logs = pd.read_csv(LOGS_PATH)

    board = sanitize_board(board)
    board = drop_combo_name_players(board)
    board = apply_local_game_date(board)

    game_date = infer_default_game_date(board)
    board = enrich_with_matchups(
        projections=board,
        roster_map_path=str(ROSTER_MAP_PATH),
        slate_path=str(SLATE_PATH),
        default_game_date=game_date,
        role_metrics_path=os.environ.get("ATLAS_ROLE_METRICS_PATH"),
        attach_role_metrics=attach_role_metrics,
    )

    iael_df = load_iael_invalidations()

    # SCORE (NEW ENGINE ONLY; no legacy wrapper)
    from .new_engine import _run_score_board_new

    scored = _run_score_board_new(board=board, logs=logs, cfg=cfg, iael_df=iael_df)

    # POST-SCORE GUARD: GOBLIN/DEMON are structurally OVER-only.
    # Defense-in-depth — board ingest already raises on UNDER+GOBLIN/DEMON, but if any
    # downstream code synthesises tier/direction (alt-line generation, dedupe, etc.) we
    # catch it here before any calibration / slip-building / publishing touches it.
    if {"tier", "direction"}.issubset(scored.columns):
        _t = scored["tier"].astype(str).str.upper().str.strip()
        _d = scored["direction"].astype(str).str.upper().str.strip()
        _bad = scored[(_d == "UNDER") & (_t.isin(["GOBLIN", "DEMON"]))]
        if not _bad.empty:
            _sample = _bad.head(10)[["player", "stat", "line", "tier", "direction"]]
            raise ValueError(
                "scored frame contains invalid rows: UNDER present for DEMON/GOBLIN.\n"
                + _sample.to_string(index=False)
            )

    # CALIBRATION CONTRACT COLUMNS (schema enforcement)
        # p_for_cal: chosen upstream probability for calibration
    # p_cal_src: source of p_for_cal ("p_adj" vs "p_role")
    # p_cal: calibrated probability (identity here unless calibration stage overrides)
    if "role_ctx_outs_used" not in scored.columns:
        scored["role_ctx_outs_used"] = 0
    scored["role_ctx_outs_used"] = pd.to_numeric(scored["role_ctx_outs_used"], errors="coerce").fillna(0).astype(int)

    # IAEL SOFT RISK (QUESTIONABLE) must be available before CAT so live and
    # bundle replay use the same pre-builder probability surface.
    from Atlas.core.iael_soft_risk import apply_iael_soft_risk

    scored = apply_iael_soft_risk(scored, iael_df)

    p_adj = _to_series(scored.get("p_adj", scored.get("p", 0.5)), errors="coerce").fillna(0.5).clip(0, 1)
    p_role = _to_series(scored.get("p_role", p_adj), errors="coerce").fillna(p_adj).clip(0, 1)

    # BLOWOUT TAIL BYPASS (2026-05-10)
    # Validated by scripts/experiments/k4_blowout_bypass_loso.py.
    # At q_blowout < q_lo OR q_blowout >= q_hi, revert p_adj to p_role
    # (skip blowout adjustment because it over-corrects at the tails).
    # keep band [0.15, 0.50): LOSO -0.36 mB, 0/9 regress.
    _bypass_cfg = (cfg.get("kernel_blowout_bypass", {}) or {})
    if bool(_bypass_cfg.get("enabled", False)):
        _q_lo = float(_bypass_cfg.get("q_lo", 0.15))
        _q_hi = float(_bypass_cfg.get("q_hi", 0.50))
        _q = pd.to_numeric(scored.get("q_blowout", pd.Series(0.0, index=scored.index)),
                           errors="coerce").fillna(0.0).to_numpy()
        _bypass = (_q < _q_lo) | (_q >= _q_hi)
        if _bypass.any():
            scored["p_adj_pre_blowout_bypass"] = p_adj.values
            _p_arr = p_adj.to_numpy().copy()
            _p_arr[_bypass] = p_role.to_numpy()[_bypass]
            p_adj = pd.Series(_p_arr, index=p_adj.index).clip(0, 1)
            scored["p_adj"] = p_adj.values
            scored["blowout_bypass_applied"] = _bypass.astype(int)

    # HIGH-PROBABILITY SHRINKAGE (2026-05-10)
    # Per-slate audit found monotone-increasing calibration gap above p_adj=0.70.
    # LOSO-validated (data/model/high_prob_shrink_loso.json):
    #   p_thr=0.75, k=0.0501 — agg -0.22 mB, 0/9 slates regress.
    # Applied at the kernel handoff so all downstream stages (calibrator, slip
    # builder, telemetry) see shrunk p_adj. Raw value preserved as p_adj_pre_shrink.
    _shrink_cfg = (cfg.get("kernel_high_prob_shrink", {}) or {})
    if bool(_shrink_cfg.get("enabled", False)):
        _p_thr = float(_shrink_cfg.get("p_thr", 0.75))
        _k = float(_shrink_cfg.get("k", 1.0))
        scored["p_adj_pre_shrink"] = p_adj.values
        _p_arr = p_adj.to_numpy().copy()
        _mask = _p_arr > _p_thr
        if _mask.any() and _k != 1.0:
            _eps = 1e-6
            _p_clip = np.clip(_p_arr[_mask], _eps, 1 - _eps)
            _z_thr = float(np.log(_p_thr / (1 - _p_thr)))
            _z = np.log(_p_clip / (1 - _p_clip))
            _z_new = _z_thr + _k * (_z - _z_thr)
            _p_arr[_mask] = 1.0 / (1.0 + np.exp(-_z_new))
            p_adj = pd.Series(_p_arr, index=p_adj.index).clip(0, 1)
            scored["p_adj"] = p_adj.values
            scored["high_prob_shrink_applied"] = _mask.astype(int)
        else:
            scored["high_prob_shrink_applied"] = 0

    # SUBSET LOGIT SHIFTS (2026-05-10)
    # Validated by scripts/experiments/loso_subset_shift.py — only LOSO-passing shifts wired in.
    # Currently active: UNDER subset (delta=-0.1651, LOSO -0.08 mB, 0/9 regress).
    _shifts_cfg = cfg.get("kernel_subset_shifts", []) or []
    if _shifts_cfg:
        _delta_arr = np.zeros(len(scored), dtype=float)
        _applied_names: list[str] = []
        for _entry in _shifts_cfg:
            if not bool(_entry.get("enabled", True)):
                continue
            _name = str(_entry.get("name", "unnamed"))
            _delta = float(_entry.get("delta", 0.0))
            if _delta == 0.0:
                continue
            _flt = _entry.get("filter", {}) or {}
            _m = pd.Series(True, index=scored.index)
            for _col, _want in _flt.items():
                if _col not in scored.columns:
                    _m = pd.Series(False, index=scored.index)
                    break
                _vals = scored[_col].astype(str).str.upper().str.strip()
                if isinstance(_want, list):
                    _m &= _vals.isin([str(w).upper().strip() for w in _want])
                else:
                    _m &= (_vals == str(_want).upper().strip())
            _m_arr = _m.to_numpy()
            if _m_arr.any():
                _delta_arr[_m_arr] += _delta
                _applied_names.append(f"{_name}({int(_m_arr.sum())})")
        if np.any(_delta_arr != 0.0):
            scored["p_adj_pre_subset_shift"] = p_adj.values
            _eps = 1e-6
            _p_clip = np.clip(p_adj.to_numpy(), _eps, 1 - _eps)
            _z = np.log(_p_clip / (1 - _p_clip))
            _z_new = _z + _delta_arr
            _p_new = 1.0 / (1.0 + np.exp(-_z_new))
            p_adj = pd.Series(_p_new, index=p_adj.index).clip(0, 1)
            scored["p_adj"] = p_adj.values
            scored["subset_shift_applied"] = ",".join(_applied_names) if _applied_names else ""

    # PROBABILITY FLOORS (2026-05-10)
    # Validated by scripts/experiments/k1_goblin_floor_fixed_loso.py.
    # Currently active: GOBLIN OVER floor=0.40 (LOSO -8.52 mB, 0/9 regress).
    _floors_cfg = cfg.get("kernel_prob_floors", []) or []
    if _floors_cfg:
        _floor_applied: list[str] = []
        for _entry in _floors_cfg:
            if not bool(_entry.get("enabled", True)):
                continue
            _name = str(_entry.get("name", "unnamed"))
            _floor = float(_entry.get("floor", 0.0))
            if _floor <= 0.0:
                continue
            _flt = _entry.get("filter", {}) or {}
            _m = pd.Series(True, index=scored.index)
            for _col, _want in _flt.items():
                if _col not in scored.columns:
                    _m = pd.Series(False, index=scored.index)
                    break
                _vals = scored[_col].astype(str).str.upper().str.strip()
                if isinstance(_want, list):
                    _m &= _vals.isin([str(w).upper().strip() for w in _want])
                else:
                    _m &= (_vals == str(_want).upper().strip())
            _m_arr = _m.to_numpy()
            if _m_arr.any():
                _p_arr = p_adj.to_numpy()
                _below = _m_arr & (_p_arr < _floor)
                if _below.any():
                    _p_arr = _p_arr.copy()
                    _p_arr[_below] = _floor
                    p_adj = pd.Series(_p_arr, index=p_adj.index).clip(0, 1)
                    scored["p_adj"] = p_adj.values
                    _floor_applied.append(f"{_name}({int(_below.sum())})")
        if _floor_applied:
            scored["prob_floor_applied"] = ",".join(_floor_applied)

    # SUBSET LOGIT SHRINKS TOWARD 0.5 (2026-05-10) — variance inflation.
    # Validated by scripts/experiments/k2_combo_shrink_loso.py.
    # Currently active: combo stats (RA/PA/PRA/PR) k=0.90 (LOSO -0.59 mB, 0/9 regress).
    _shrinks_cfg = cfg.get("kernel_logit_shrinks", []) or []
    if _shrinks_cfg:
        _shrink_applied: list[str] = []
        for _entry in _shrinks_cfg:
            if not bool(_entry.get("enabled", True)):
                continue
            _name = str(_entry.get("name", "unnamed"))
            _k = float(_entry.get("k", 1.0))
            if _k == 1.0:
                continue
            _flt = _entry.get("filter", {}) or {}
            _m = pd.Series(True, index=scored.index)
            for _col, _want in _flt.items():
                if _col not in scored.columns:
                    _m = pd.Series(False, index=scored.index)
                    break
                _vals = scored[_col].astype(str).str.upper().str.strip()
                if isinstance(_want, list):
                    _m &= _vals.isin([str(w).upper().strip() for w in _want])
                else:
                    _m &= (_vals == str(_want).upper().strip())
            _m_arr = _m.to_numpy()
            if _m_arr.any():
                _p_arr = p_adj.to_numpy().copy()
                _eps = 1e-6
                _p_clip = np.clip(_p_arr[_m_arr], _eps, 1 - _eps)
                _z = np.log(_p_clip / (1 - _p_clip))
                _p_arr[_m_arr] = 1.0 / (1.0 + np.exp(-_k * _z))
                p_adj = pd.Series(_p_arr, index=p_adj.index).clip(0, 1)
                scored["p_adj"] = p_adj.values
                _shrink_applied.append(f"{_name}({int(_m_arr.sum())})")
        if _shrink_applied:
            scored["logit_shrink_applied"] = ",".join(_shrink_applied)

    # EXTERNAL PRIORS (pre-CAT)
    # v5cD was trained from scored_legs_deduped.p_adj, and that surface carried
    # external-prior nudges/features. Apply them before p_for_cal so CAT sees
    # the same feature/probability contract live that it saw in the cache.
    try:
        from Atlas.core.external_priors import apply_external_priors

        scored = apply_external_priors(scored, cfg, apply_probability=True)
        _prior_applied = int(
            pd.to_numeric(
                scored.get("external_prior_probability_applied", pd.Series(False, index=scored.index)),
                errors="coerce",
            ).fillna(0).astype(bool).sum()
        )
        _prior_n = int(
            (pd.to_numeric(scored.get("external_prior_n", pd.Series(0, index=scored.index)), errors="coerce").fillna(0) > 0).sum()
        )
        if _prior_n:
            print(f"[EXTERNAL_PRIORS] Pre-CAT attached: prior_rows={_prior_n}, nudged_rows={_prior_applied}")
        p_adj = _to_series(scored.get("p_adj", scored.get("p", 0.5)), errors="coerce").fillna(0.5).clip(0, 1)
    except Exception as _prior_err:
        print(f"[EXTERNAL_PRIORS] Pre-CAT skipped: {_prior_err!r}")

    # use_role retained for downstream post-cal blend logic that segments by role context.
    use_role = scored["role_ctx_outs_used"] > 0

    # FORK FIX (2026-05-10): p_for_cal := p_adj universally.
    # The previous fork (np.where(role_ctx_outs_used > 0, p_role, p_adj)) regressed
    # Brier by +2.37 mB on the playoff resim cache and +8.03 mB on the use_role
    # subset. p_role is strictly worse than p_adj on legs where the fork fired.
    # See data/model/engine_fork_diagnostic.json.
    under_relief_applied = _to_series(scored.get("under_relief_applied", False), errors="coerce").fillna(0).astype(bool)
    p_adj_source = np.where(under_relief_applied, "p_adj_under_relief", "p_adj")
    scored["p_for_cal"] = p_adj
    scored["p_cal_src"] = p_adj_source
    scored["p_cal"] = scored["p_for_cal"]

    scored["p_for_cal_src"] = scored["p_cal_src"]

    # RAW SLATE FRAGILITY GUARD
    # Narrow pre-CAT protection for thin, injury-fragile slates where raw p_for_cal
    # overstates high-confidence legs before CAT sees the feature surface.
    try:
        from Atlas.core.raw_slate_fragility_guard import apply_raw_slate_fragility_guard
        scored = apply_raw_slate_fragility_guard(scored, cfg)
    except Exception as _raw_guard_err:
        print(f"[RAW_SLATE_GUARD] Skipped: {_raw_guard_err!r}")

    telemetry_cfg = (cfg.get("telemetry", {}) or {})
    post_calibration_cfg = (telemetry_cfg.get("post_calibration", {}) or {})

    def _post_calibration_float(name: str, default: float) -> float:
        try:
            return float(post_calibration_cfg.get(name, default))
        except Exception:
            return float(default)

    if "p_cal" not in scored.columns:
        scored["p_cal"] = scored["p_for_cal"]

    # Temperature scaling (applied after calibration or identity passthrough)
    temp_scale = float(telemetry_cfg.get("temperature_scaling", 1.0))
    if temp_scale != 1.0:
        import numpy as _np
        _p: "np.ndarray[Any, Any]" = scored["p_cal"].values.astype(float).clip(1e-6, 1 - 1e-6)  # type: ignore[assignment]
        _logit = _np.log(_p / (1 - _p))
        scored["p_cal"] = 1.0 / (1.0 + _np.exp(-_logit / temp_scale))

    # GBM ENSEMBLE CALIBRATION (posthoc calibrator)
    try:
        from Atlas.engine.gbm_ensemble import apply_gbm_ensemble
        scored = apply_gbm_ensemble(scored, logs=logs, cfg=cfg, repo_root=PROJECT_ROOT)
    except Exception as _gbm_err:
        print(f"[GBM_ENSEMBLE] Skipped: {_gbm_err!r}")

    # CATBOOST PLAYOFF CALIBRATOR
    # Applied after GBM (or after p_for_cal identity if GBM disabled).
    # Calls gbm_ensemble.compute_features() internally to build all 33 GBM features
    # + p_for_cal — real feature values regardless of whether GBM is enabled.
    try:
        from Atlas.engine.catboost_calibrator import apply_catboost_calibrator
        scored = apply_catboost_calibrator(scored, logs=logs, cfg=cfg, repo_root=PROJECT_ROOT)
    except Exception as _cat_err:
        print(f"[CATBOOST_CAL] Skipped: {_cat_err!r}")

    # POST-GBM ISOTONIC OVERLAY
    # Applied AFTER GBM so the isotonic corrects GBM p_cal output, not pre-GBM p_for_cal.
    # source_col="p_cal" reads GBM output. JSON uses protected_tier="DEMON" to route DEMON
    # legs through the DEMON-specific curve; non-DEMON legs use the global curve.
    try:
        from Atlas.runtime.telemetry_calibration import apply_calibration_to_column, load_calibration
        if bool(telemetry_cfg.get("apply_active_calibration", False)):
            raw_path = telemetry_cfg.get("active_calibration_path")
            calib_path = None
            if raw_path:
                candidate = Path(str(raw_path))
                calib_path = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
            calib = load_calibration(PROJECT_ROOT, calibration_path=calib_path)
            if calib is not None:
                scored = apply_calibration_to_column(
                    scored,
                    calib,
                    source_col="p_cal",
                    out_col="p_cal",
                    apply_under_penalty=True,
                )
                scored = _apply_combo_under_midq_telemetry_blend(
                    scored,
                    use_role=use_role,
                    under_relief_applied=under_relief_applied,
                    retain=_post_calibration_float("combo_under_midq_blend_retain", 0.40),
                )
                scored = _apply_combo_under_highq_telemetry_blend(
                    scored,
                    use_role=use_role,
                    under_relief_applied=under_relief_applied,
                    retain=_post_calibration_float("combo_under_highq_blend_retain", 0.68),
                )
                scored = _apply_combo_under_lowmidq_telemetry_blend(
                    scored,
                    use_role=use_role,
                    under_relief_applied=under_relief_applied,
                    retain=_post_calibration_float("combo_under_lowmidq_blend_retain", 0.55),
                )
                scored = _apply_combo_under_midq_ra_trim(
                    scored,
                    use_role=use_role,
                    under_relief_applied=under_relief_applied,
                    retain=_post_calibration_float("combo_under_midq_ra_trim_retain", 0.35),
                )
                scored = _apply_under_reb_lowmidq_no_relief_trim(
                    scored,
                    under_relief_applied=under_relief_applied,
                    retain=_post_calibration_float("under_reb_lowmidq_no_relief_retain", 1.0),
                )
                scored = _apply_reb_over_midq_trim(
                    scored,
                    use_role=use_role,
                    retain=_post_calibration_float("reb_over_midq_trim_retain", 1.0),
                )
                scored = _apply_fg3m_over_highq_blowout_lift(
                    scored,
                    use_role=use_role,
                    factor=_post_calibration_float("fg3m_over_highq_blowout_lift_factor", 0.0),
                )
                scored = _apply_combo_over_high_fragility_lift(
                    scored,
                    use_role=use_role,
                    factor=_post_calibration_float("combo_over_high_fragility_lift_factor", 0.36),
                )
    except Exception:
        pass

    # ZERO-DNP POST-CAL OVERRIDE
    # When the zero-DNP minutes correction fired significantly (mult >= threshold),
    # the GBM features (z_line, l20_edge, margin) still reflect backup-role history
    # and will confidently override the MC signal. Blend p_adj back in to prevent
    # the GBM from being overconfident on lines set for a player's backup role.
    _zdnp_cfg = (cfg.get("role_ctx", {}) or {})
    _zdnp_blend_thresh = float(_zdnp_cfg.get("zero_dnp_postcal_blend_thresh", 1.40))
    _zdnp_blend_weight = float(_zdnp_cfg.get("zero_dnp_postcal_blend_weight", 0.70))
    # Track direction-flip legs before blending so we can drop them from the optimizer pool.
    # A direction flip = MC (p_adj) and GBM (p_cal) are on opposite sides of 0.5,
    # or MC is a coin-flip (within 5% of 0.5) while GBM is confident (>8% from 0.5).
    # For these legs we set p_cal = p_adj so the builder sees the correct signal.
    # The OVER counterpart for the same player/stat gets its p_cal blended UP,
    # so the builder reallocates naturally — OVER beats UNDER in the competition.
    scored["_zero_dnp_flip"] = False
    if "zero_dnp_mult" in scored.columns:
        import numpy as _np2
        _zdnp_mult_vals = scored["zero_dnp_mult"].fillna(1.0)
        _zdnp_mask = _zdnp_mult_vals >= _zdnp_blend_thresh
        if _zdnp_mask.any():
            _p_adj_vals = scored.loc[_zdnp_mask, "p_adj"].fillna(0.5).to_numpy(dtype=float)
            _p_cal_vals = scored.loc[_zdnp_mask, "p_cal"].fillna(0.5).to_numpy(dtype=float)
            _direction_disagree = (
                # Hard flip: MC and GBM are on opposite sides of 0.5
                ((_p_adj_vals < 0.5) & (_p_cal_vals >= 0.5)) |
                ((_p_adj_vals >= 0.5) & (_p_cal_vals < 0.5)) |
                # Coin-flip: MC is uncertain (within 5% of 0.5) regardless of GBM confidence
                (_np2.abs(_p_adj_vals - 0.5) < 0.05)
            )
            _blended = _np2.where(
                _direction_disagree,
                _p_adj_vals,   # full override to p_adj — corrects the direction signal
                _zdnp_blend_weight * _p_adj_vals + (1.0 - _zdnp_blend_weight) * _p_cal_vals,
            )
            scored.loc[_zdnp_mask, "p_cal"] = _np2.clip(_blended, 1e-6, 1 - 1e-6)
            flip_indices = scored.index[_zdnp_mask][_direction_disagree]
            scored.loc[flip_indices, "_zero_dnp_flip"] = True
            _n_override = int(_direction_disagree.sum())
            _n_blend = int(_zdnp_mask.sum()) - _n_override
            print(f"[ZERO_DNP] Post-cal: {_n_override} legs direction-corrected to p_adj, {_n_blend} blended (mult>={_zdnp_blend_thresh})")

    # PREP FOR OPTIMIZER (staged)
    from Atlas.stages.prep_for_optimizer.prep_for_optimizer import run_prep_for_optimizer

    scored, scored_for_optimizer = run_prep_for_optimizer(
        scored=scored,
        cfg=cfg,
        iael_df=iael_df,
    )

    # Drop zero-DNP direction-flip legs from the optimizer pool only.
    # scored (full output CSV) retains them with corrected p_cal for diagnostics.
    # These legs are coin-flips or direction-wrong per the MC — removing them lets
    # the builder reallocate to other players rather than picking another backup leg.
    if "_zero_dnp_flip" in scored_for_optimizer.columns:
        _n_flip_dropped = int(scored_for_optimizer["_zero_dnp_flip"].sum())
        if _n_flip_dropped:
            scored_for_optimizer = scored_for_optimizer[~scored_for_optimizer["_zero_dnp_flip"]].copy()
            print(f"[ZERO_DNP] Dropped {_n_flip_dropped} direction-corrected legs from optimizer pool")

    # Report-only risk telemetry for live/replay parity. Selection penalties are
    # applied inside the builders; these columns make the run artifacts auditable.
    from Atlas.core.minute_risk_guard import apply_minute_risk_guard
    from Atlas.core.single_game_script import apply_single_game_script_annotations
    from Atlas.core.volatility_guard import apply_volatility_telemetry

    scored = apply_minute_risk_guard(scored, cfg, score_col=None)
    scored_for_optimizer = apply_minute_risk_guard(scored_for_optimizer, cfg, score_col=None)
    scored = apply_volatility_telemetry(scored, cfg)
    scored_for_optimizer = apply_volatility_telemetry(scored_for_optimizer, cfg)
    scored = apply_single_game_script_annotations(scored, cfg)
    scored_for_optimizer = apply_single_game_script_annotations(scored_for_optimizer, cfg)

    optimizer_cfg = (cfg.get("optimizer", {}) or {})
    top_n = int(optimizer_cfg.get("top_n_slips", 10))
    seed = int(optimizer_cfg.get("seed", 7))
    slip_rank_cfg = (cfg.get("slip_rank", {}) or {}) if isinstance(cfg, dict) else {}
    primary_sort_mode = str(slip_rank_cfg.get("primary_mode", "ev") or "ev").strip().lower()
    if primary_sort_mode in {"win", "winprob", "hit_prob"}:
        primary_sort_mode = "hit"
    elif primary_sort_mode not in {"ev", "hit", "hybrid"}:
        primary_sort_mode = "ev"

    from Atlas.stages.optimize.build_slips_today import run_build_slips

    slips = run_build_slips(
        scored_for_optimizer=scored_for_optimizer,
        top_n=top_n,
        seed=seed,
        pricing_engine=pricing_engine,
        cfg=cfg,
        sort_mode=primary_sort_mode,
    )

    sys3, sys4, sys5 = slips.sys3, slips.sys4, slips.sys5
    wind3, wind4, wind5 = slips.wind3, slips.wind4, slips.wind5
    demonhunter = slips.demonhunter

    from Atlas.core.iael_filter import normalize_person_name

    is_questionable = scored_for_optimizer["is_questionable"] if "is_questionable" in scored_for_optimizer.columns else pd.Series(0, index=scored_for_optimizer.index)
    q_df = scored_for_optimizer[pd.to_numeric(is_questionable, errors="coerce").fillna(0).astype(int) == 1]
    q_set = set(q_df["player"].astype(str).map(normalize_person_name).str.lower())
    q_disp = (
        q_df.assign(_k=q_df["player"].astype(str).map(normalize_person_name).str.lower())
        .dropna(subset=["_k"])
        .groupby("_k")["player"]
        .first()
        .to_dict()
    )

    def _annotate_q_slips(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) == 0:
            return df
        out = df.copy()
        if not q_set:
            out["q_leg_count"] = 0
            out["q_players"] = ""
            return out

        q_counts = []
        q_players_str = []

        for _, r in out.iterrows():
            raw = r.get("players", "[]")
            try:
                plist = ast.literal_eval(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                plist = []

            # Fallback: scan leg_1..leg_5 if players column not found or empty
            if not plist:
                for i in range(1, 6):
                    leg_col = f"leg_{i}"
                    if leg_col in r.index:
                        leg_str = str(r[leg_col]).strip()
                        if leg_str:
                            # Extract player name (prefix before first space or special char)
                            player = leg_str.split()[0] if leg_str else ""
                            if player:
                                plist.append(player)

            hits = []
            for p in plist:
                k = normalize_person_name(p).lower()
                if k in q_set:
                    hits.append(q_disp.get(k, k))

            # unique, stable order
            seen = set()
            uniq = [x for x in hits if not (x in seen or seen.add(x))]

            q_counts.append(len(uniq))
            q_players_str.append(" | ".join(uniq))

        out["q_leg_count"] = q_counts
        out["q_players"] = q_players_str
        return out

    # Apply annotation to EV-sorted slips
    sys3 = _annotate_q_slips(sys3)
    sys4 = _annotate_q_slips(sys4)
    sys5 = _annotate_q_slips(sys5)
    wind3 = _annotate_q_slips(wind3)
    wind4 = _annotate_q_slips(wind4)
    wind5 = _annotate_q_slips(wind5)
    if demonhunter is not None and len(demonhunter) > 0:
        demonhunter = _annotate_q_slips(demonhunter)

    # Secondary "no-kernel" slips for win-prob comparison — skipped when emit_winprob_variants=false
    _emit_winprob = bool((cfg.get("optimizer") or {}).get("emit_winprob_variants", True))
    if _emit_winprob:
        slips_winprob = run_build_slips(
            scored_for_optimizer=scored_for_optimizer,
            top_n=top_n,
            seed=seed,
            cfg=cfg,
            pricing_engine="atlas",
            sort_mode="hit",
        )
        sys3_win = _annotate_q_slips(slips_winprob.sys3)
        sys4_win = _annotate_q_slips(slips_winprob.sys4)
        sys5_win = _annotate_q_slips(slips_winprob.sys5)
        wind3_win = _annotate_q_slips(slips_winprob.wind3)
        wind4_win = _annotate_q_slips(slips_winprob.wind4)
        wind5_win = _annotate_q_slips(slips_winprob.wind5)
    else:
        sys3_win = sys4_win = sys5_win = None
        wind3_win = wind4_win = wind5_win = None

    # --- Marketed Slips (subscriber product) ---
    marketed_slips = []
    if cfg.get("marketed_slips", {}).get("enabled", False):
        try:
            from Atlas.core.marketed_slip_builder import build_marketed_slips
            marketed_slips, _p_cal_marketed = build_marketed_slips(scored_for_optimizer, cfg)
            scored_for_optimizer = scored_for_optimizer.copy()
            scored_for_optimizer["p_cal_marketed"] = _p_cal_marketed
            print(f"Built {len(marketed_slips)} marketed slips")
        except Exception as e:
            print(f"Marketed slips builder failed: {e}")
            marketed_slips = []

    from Atlas.stages.publish.publish_run_outputs import run_publish_stage
    from Atlas.stages.publish.build_cloudflare_payload import build_cloudflare_payload

    run_dir = run_publish_stage(
        LOCAL_TZ=LOCAL_TZ,
        OUT_DIR=OUT_DIR,
        scored=scored,
        scored_for_optimizer=scored_for_optimizer,
        sys3=sys3,
        sys4=sys4,
        sys5=sys5,
        wind3=wind3,
        wind4=wind4,
        wind5=wind5,
        demonhunter=demonhunter,
        
        sys3_winprob=sys3_win,
        sys4_winprob=sys4_win,
        sys5_winprob=sys5_win,
        wind3_winprob=wind3_win,
        wind4_winprob=wind4_win,
        wind5_winprob=wind5_win,
        
        marketed_slips=marketed_slips,
        
        iael_invalidations_path=IAEL_INVALIDATIONS_PATH,
        iael_status_path=IAEL_STATUS_PATH,

        write_csv_clean=write_csv_clean,
        cfg=cfg,
        ensemble_dir=cfg.get("posthoc_calibrator", {}).get("ensemble_dir"),
    )

    # Build dashboard payload from slip CSVs
    try:
        dashboard_dir = OUT_DIR / "dashboard"
        payload_path = build_cloudflare_payload(run_dir, dashboard_dir, marketed_slips=marketed_slips or [], gamelogs_path=LOGS_PATH, include_yesterday_slips=False)
        print(f"Dashboard payload: {payload_path}")
    except Exception as e:
        import sys as _sys
        print(f"Warning: failed to build dashboard payload: {e}", file=_sys.stderr)

    # Discord picks post is handled by the orchestrator (discord_post.py --picks-today).
    # Do not call notify_discord here — it would double-post to the same channel.

if __name__ == "__main__":
    main()
