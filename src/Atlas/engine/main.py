from __future__ import annotations

import ast
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from zoneinfo import ZoneInfo

from ..core.matchup_enricher import enrich_with_matchups
from Atlas.core.slip_scoring import _score_slip
from Atlas.core.payout_tables import FLEX_3, FLEX_4, FLEX_5, POWER_MULT

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
        df["team_norm"] = df["team"].apply(normalize_team_token)

        if "status" in df.columns:
            df["status"] = df["status"].astype(str).str.upper().str.strip()
        else:
            df["status"] = "OUT"

        df = df.dropna(subset=["player_norm"])
        df = df[df["player_norm"] != ""]
        df = df.drop_duplicates(subset=["team_norm", "player_norm", "status"])

        if status_path.exists():
            try:
                st = json.loads(status_path.read_text(encoding="utf-8"))
                print(f"[IAEL] Loaded invalidations={len(df)}. Report: {st.get('report_datetime_local', '')}")
            except Exception:
                print(f"[IAEL] Loaded invalidations={len(df)}.")
        else:
            print(f"[IAEL] Loaded invalidations={len(df)}.")

        return df[["team_norm", "player_norm", "status"]].reset_index(drop=True)

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

    hard_statuses = hard_statuses or {"OUT", "DOUBTFUL", "QUESTIONABLE"}
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

    _ensure_col(out, "hit_prob", out["p_adj"])
    out["hit_prob"] = pd.to_numeric(out["hit_prob"], errors="coerce").fillna(out["p_adj"]).fillna(0.50).clip(0, 1)

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


def expand_legs(df: pd.DataFrame, max_legs: int) -> pd.DataFrame:
    out = df.copy()
    if "legs" not in out.columns:
        return out

    def to_list(x: Any) -> list[str]:
        if isinstance(x, list):
            return [str(i).strip() for i in x]
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    v = ast.literal_eval(s)
                    if isinstance(v, list):
                        return [str(i).strip() for i in v]
                except Exception:
                    pass
            if " | " in s:
                return [p.strip() for p in s.split(" | ") if p.strip()]
            return [s] if s else []
        return []

    legs_list = out["legs"].apply(to_list)
    for i in range(max_legs):
        out[f"leg_{i+1}"] = legs_list.apply(lambda lst: lst[i] if i < len(lst) else "")
    return out


def dedupe_slips_by_key(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0 or "legs" not in df.columns:
        return df
    out = df.copy()
    out["slip_key"] = out["legs"].astype(str)
    return out.drop_duplicates(subset=["slip_key"], keep="first")


# -------------------------------------------------------------------
# Tier mix contracts
# -------------------------------------------------------------------


def _tier_counts_from_legs(x: Any) -> dict[str, int]:
    if x is None:
        return {"STANDARD": 0, "GOBLIN": 0, "DEMON": 0}
    s = str(x).upper()
    return {"STANDARD": s.count("(STANDARD)"), "GOBLIN": s.count("(GOBLIN)"), "DEMON": s.count("(DEMON)")}


def _windfall_mix_ok(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
    if n_legs == 3:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 1 and c["DEMON"] == 1
    if n_legs == 4:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 2 and c["DEMON"] == 1
    if n_legs == 5:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 2 and c["DEMON"] == 1
    return True


def _system_mix(n_legs: int, legs: Any) -> bool:
    c = _tier_counts_from_legs(legs)
    if n_legs == 3:
        return c["GOBLIN"] == 1 and c["STANDARD"] == 2 and c["DEMON"] == 0
    if n_legs == 4:
        return c["GOBLIN"] == 2 and c["STANDARD"] == 2 and c["DEMON"] == 0
    if n_legs == 5:
        return c["GOBLIN"] == 3 and c["STANDARD"] == 2 and c["DEMON"] == 0
    return True


# -------------------------------------------------------------------
# Builders
# -------------------------------------------------------------------

_EMPTY_SLIPS_COLS = ["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"]


def build_slips_by_tier_buckets(
    *,
    legs_df: pd.DataFrame,
    n_legs: int,
    top_n: int,
    payout_power_mult: Any,
    pricing_engine: str,
    cfg: dict[str, Any],
    seed: int = 7,
    per_tier: int = 500,
    max_attempts: int = 400000,
    mixes: dict[int, dict[str, int]],
    required_tiers: list[str],
    mix_ok_fn,
) -> pd.DataFrame:
    if legs_df is None or len(legs_df) == 0:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    if n_legs not in mixes:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)
    mix = mixes[n_legs]

    df = legs_df.copy().reset_index(drop=True)

    if "projection_id" not in df.columns and "id" in df.columns:
        df = df.rename(columns={"id": "projection_id"})

    pid_series: pd.Series | None = None
    if "projection_id" in df.columns:
        pid_series = df["projection_id"]
    elif "source_projection_id" in df.columns:
        pid_series = df["source_projection_id"]

    if pid_series is None:
        df["projection_id"] = ""
    else:
        if "source_projection_id" in df.columns:
            num = pd.to_numeric(pid_series, errors="coerce")
            if float(num.isna().mean()) > 0.50:
                pid_series = df["source_projection_id"]
        df["projection_id"] = pid_series.astype(str).str.strip()

    _ensure_col(df, "tier", "STANDARD")
    df["tier"] = df["tier"].astype(str).str.upper().str.strip()

    # --- p_eff (Pylance-safe, runtime-safe) ---
    if "p_adj" not in df.columns:
        df["p_adj"] = 0.50  # broadcast scalar -> Series

    p_adj_s = pd.to_numeric(df["p_adj"], errors="coerce")
    p_adj_s = p_adj_s.fillna(0.50).clip(0.0, 1.0)

    if "p_eff" not in df.columns:
        df["p_eff"] = p_adj_s
    else:
        df["p_eff"] = pd.to_numeric(df["p_eff"], errors="coerce").fillna(p_adj_s).clip(0.0, 1.0)

    if "edge_score" not in df.columns:
        df["edge_score"] = df["p_eff"] - 0.5
    else:
        df["edge_score"] = pd.to_numeric(df["edge_score"], errors="coerce").fillna(df["p_eff"] - 0.5)

    tier_counts = df["tier"].value_counts(dropna=False).to_dict()
    if os.getenv("ATLAS_DEBUG_BUILDER") == "1":
        print(f"[BUILDER][DEBUG] leg_df tier counts: {tier_counts}")

    for needed in required_tiers:
        if tier_counts.get(needed, 0) == 0:
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    df = df.sort_values(["tier", "edge_score", "p_eff"], ascending=[True, False, False]).reset_index(drop=True)

    buckets: dict[str, list[pd.Series]] = {}
    for t in required_tiers:
        sub = df[df["tier"] == t].head(int(per_tier)).reset_index(drop=True)
        buckets[t] = [sub.iloc[i] for i in range(len(sub))]

    for t, need in mix.items():
        if len(buckets.get(t, [])) < int(need):
            return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    rng = random.Random(int(seed))
    slips: list[dict[str, Any]] = []
    seen: set[str] = set()

    attempts = 0
    target_pool = max(int(top_n) * 10, int(top_n))

    while attempts < int(max_attempts) and len(slips) < target_pool:
        attempts += 1

        chosen: list[pd.Series] = []
        for t, need in mix.items():
            chosen.extend(rng.sample(buckets[t], int(need)))

        pids: list[str] = []
        players: list[str] = []
        ok = True

        for r in chosen:
            if "projection_id" not in r.index:
                ok = False
                break

            pid = str(r["projection_id"]).strip()
            if not pid or pid.lower() == "nan":
                ok = False
                break
            pids.append(pid)

            player_name = str(r["player"]).strip().lower() if "player" in r.index else ""
            players.append(player_name)

        if not ok:
            continue

        if len(pids) != len(set(pids)):
            continue
        if len(players) != len(set(players)):
            continue

        scored = _score_slip(
            chosen,
            n_legs,
            payout_power_mult,
            pricing_engine=str(pricing_engine or "atlas"),
            cfg=cfg,
        )

        legs_str = scored.get("legs", "")
        if not mix_ok_fn(n_legs, legs_str):
            continue

        key = scored.get("slip_key") or legs_str
        if key in seen:
            continue

        seen.add(key)
        slips.append(scored)

    # If we didn't build any slips, return an empty frame with expected columns
    if not slips:
        return pd.DataFrame(columns=_EMPTY_SLIPS_COLS)

    out = pd.DataFrame(slips)
    out["n_legs"] = int(n_legs)

    # Ensure columns exist before numeric ops (avoid scalar -> .fillna issues)
    if "hit_prob" not in out.columns:
        out["hit_prob"] = 0.0
    if "ev_mult" not in out.columns:
        out["ev_mult"] = 0.0

    out["hit_prob"] = pd.to_numeric(out["hit_prob"], errors="coerce").fillna(0.0)
    out["ev_mult"] = pd.to_numeric(out["ev_mult"], errors="coerce").fillna(0.0)

    out = out.sort_values(["ev_mult", "hit_prob"], ascending=[False, False]).reset_index(drop=True)
    out = dedupe_slips_by_key(out).head(int(top_n)).reset_index(drop=True)
    return out


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------


def main() -> None:
    cfg = load_config()
    pricing_engine = str(cfg.get("pricing_engine", "atlas") or "atlas")

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
    )

    iael_df = load_iael_invalidations()

    # SCORE (NEW ENGINE ONLY; no legacy wrapper)
    from .new_engine import _run_score_board_new

    scored = _run_score_board_new(board=board, logs=logs, cfg=cfg, iael_df=iael_df)

    # CALIBRATION CONTRACT COLUMNS (schema enforcement)
    # p_for_cal: chosen upstream probability for calibration
    # p_cal_src: source of p_for_cal ("p_adj" vs "p_role")
    # p_cal: calibrated probability (identity here unless calibration stage overrides)
    if "role_ctx_outs_used" not in scored.columns:
        scored["role_ctx_outs_used"] = 0
    scored["role_ctx_outs_used"] = pd.to_numeric(scored["role_ctx_outs_used"], errors="coerce").fillna(0).astype(int)

    p_adj = pd.to_numeric(scored.get("p_adj", scored.get("p", 0.5)), errors="coerce").fillna(0.5).clip(0, 1) # type: ignore
    p_role = pd.to_numeric(scored.get("p_role", p_adj), errors="coerce").fillna(p_adj).clip(0, 1)

    use_role = scored["role_ctx_outs_used"] > 0
    scored["p_for_cal"] = np.where(use_role, p_role, p_adj)
    scored["p_cal_src"] = np.where(use_role, "p_role", "p_adj")
    scored["p_cal"] = scored["p_for_cal"]

    # TELEMETRY CALIBRATION OVERLAY (late overlay on p_cal; additive only)
    try:
        from Atlas.runtime.telemetry_calibration import load_calibration, apply_calibration_to_column

        project_root = Path(__file__).resolve().parents[3]
        tele_cal = load_calibration(project_root)

        _ensure_col(scored, "stat", "")
        _ensure_col(scored, "direction", "")
        stat = scored["stat"].astype(str).str.upper().str.strip()
        direction = scored["direction"].astype(str).str.upper().str.strip()
        scored["telemetry_cal_key"] = (stat + "|" + direction).astype(str)
        scored["telemetry_k_shrink"] = 1.0
        scored["telemetry_under_penalty"] = 0.9
        scored["telemetry_mult"] = 1.0
        scored["telemetry_cal_applied"] = False

        if tele_cal is not None and "p_cal" in scored.columns:
            scored = apply_calibration_to_column(scored, tele_cal, source_col="p_cal", out_col="p_cal")
            applied_mask = scored["telemetry_cal_applied"].astype(bool)
            if applied_mask.any():
                scored.loc[applied_mask, "p_cal_src"] = scored.loc[applied_mask, "p_cal_src"].astype(str) + "+telemetry"
    except Exception:
        pass

    # PREP FOR OPTIMIZER (staged)
    from Atlas.stages.prep_for_optimizer.prep_for_optimizer import run_prep_for_optimizer

    scored, scored_for_optimizer = run_prep_for_optimizer(
        scored=scored,
        cfg=cfg,
        iael_df=iael_df,
    )

    optimizer_cfg = (cfg.get("optimizer", {}) or {})
    top_n = int(optimizer_cfg.get("top_n_slips", 25))
    seed = int(optimizer_cfg.get("seed", 7))

    from Atlas.stages.optimize.build_slips_today import run_build_slips

    slips = run_build_slips(
        scored_for_optimizer=scored_for_optimizer,
        top_n=top_n,
        seed=seed,
        pricing_engine=pricing_engine,
        cfg=cfg,
        sort_mode="ev",
    )

    sys3, sys4, sys5 = slips.sys3, slips.sys4, slips.sys5
    wind3, wind4, wind5 = slips.wind3, slips.wind4, slips.wind5

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

    # Secondary "no-kernel" slips for win-prob comparison (default outputs remain unchanged)
    slips_winprob = run_build_slips(
        scored_for_optimizer=scored_for_optimizer,
        top_n=top_n,
        seed=seed,
        cfg=cfg,
        pricing_engine="atlas",
        sort_mode="hit",
    )

    # Apply annotation to win-prob slips
    sys3_win = _annotate_q_slips(slips_winprob.sys3)
    sys4_win = _annotate_q_slips(slips_winprob.sys4)
    sys5_win = _annotate_q_slips(slips_winprob.sys5)
    wind3_win = _annotate_q_slips(slips_winprob.wind3)
    wind4_win = _annotate_q_slips(slips_winprob.wind4)
    wind5_win = _annotate_q_slips(slips_winprob.wind5)

    from Atlas.stages.publish.publish_run_outputs import run_publish_stage

    run_publish_stage(
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
        
        sys3_winprob=sys3_win,
        sys4_winprob=sys4_win,
        sys5_winprob=sys5_win,
        wind3_winprob=wind3_win,
        wind4_winprob=wind4_win,
        wind5_winprob=wind5_win,

        write_csv_clean=write_csv_clean,
    )

if __name__ == "__main__":
    main()