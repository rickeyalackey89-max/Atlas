from __future__ import annotations

import ast
import random
import re
from datetime import datetime
from pathlib import Path

def find_repo_root(start: Path) -> Path:
    """
    Walk upward until we find the repo root. We define repo root as the directory
    that contains BOTH 'tools' and 'data' (Atlas runtime invariants).
    """
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    # Fallback: old assumption (repo root is 3 levels up from src/Atlas/legacy/*.py)
    return start.resolve().parents[3]

from typing import Any

import pandas as pd
import yaml
from zoneinfo import ZoneInfo

from .external_priors import apply_external_priors
from .matchup_enricher import enrich_with_matchups
from .minutes import minutes_sensitivity
from .optimize import _score_slip
from .payout_tables import FLEX_3, FLEX_4, FLEX_5, POWER_MULT
from .probability import simulate_leg_probability

# -------------------------------------------------------------------
# Paths (absolute, based on project root)
# -------------------------------------------------------------------

PROJECT_ROOT = find_repo_root(Path(__file__))
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

BOARD_PATH = PROJECT_ROOT / "data" / "board" / "today.csv"
LOGS_PATH = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
OUT_DIR = PROJECT_ROOT / "data" / "output"

ROSTER_MAP_PATH = PROJECT_ROOT / "data" / "input" / "roster_map.csv"
SLATE_PATH = PROJECT_ROOT / "data" / "input" / "slate.csv"

LOCAL_TZ = ZoneInfo("America/Chicago")

SLIP_ID_RE = re.compile(r"\[id:(\d+)\]")


# -------------------------------------------------------------------
# Config + IO
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

    # UNDER should not exist for DEMON/GOBLIN (pipeline invariant)
    bad_tier_under = out[(out["direction"] == "UNDER") & (out["tier"].isin(["DEMON", "GOBLIN"]))]
    if not bad_tier_under.empty:
        sample = bad_tier_under.head(10)[["player", "stat", "line", "tier", "direction"]]
        raise ValueError(
            "today.csv contains invalid rows: UNDER present for DEMON/GOBLIN.\n"
            + sample.to_string(index=False)
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
# Probabilities + modifiers
# -------------------------------------------------------------------

def ensure_p_adj(scored: pd.DataFrame) -> pd.DataFrame:
    """
    Apply production modifiers to create p_adj.

    Keeps:
      - Under penalty (STANDARD UNDER)
      - Goblin 3PT low-line tightening: 0.5 line uses 0.91 multiplier (requested)
      - Goblin 1.5 uses 0.95
      - Demon noisy-stat haircut (small)
      - Non-star fragility amplification (if present)
    """
    out = scored.copy()

    if "p" not in out.columns:
        out["p"] = 0.50
    out["p"] = pd.to_numeric(out["p"], errors="coerce").fillna(0.50).clip(0, 1)

    if "p_adj" not in out.columns:
        out["p_adj"] = out["p"].copy()
    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(out["p"]).fillna(0.50).clip(0, 1)

    out["tier"] = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    out["stat"] = out.get("stat", "").astype(str).str.upper().str.strip()
    out["direction"] = out.get("direction", "").astype(str).str.upper().str.strip()
    out["line"] = pd.to_numeric(out.get("line"), errors="coerce")

    # UNDER penalty (STANDARD only)
    UNDER_PENALTY = 0.90
    m_under = (out["direction"] == "UNDER") & (out["tier"] == "STANDARD")
    if m_under.any():
        out.loc[m_under, "p_adj"] = (out.loc[m_under, "p_adj"] * UNDER_PENALTY).clip(0, 1)

    # Goblin 3PT tightening
    m_gob = out["tier"] == "GOBLIN"
    m_3pt = out["stat"].isin(["FG3M", "3PM"])
    m_05 = m_gob & m_3pt & out["line"].notna() & (out["line"] <= 0.5)
    m_15 = m_gob & m_3pt & out["line"].notna() & (out["line"] > 0.5) & (out["line"] <= 1.5)

    if m_05.any():
        out.loc[m_05, "p_adj"] = (out.loc[m_05, "p_adj"] * 0.91).clip(0, 1)
    if m_15.any():
        out.loc[m_15, "p_adj"] = (out.loc[m_15, "p_adj"] * 0.95).clip(0, 1)

    # Demon noisy stats haircut (small)
    noisy_stats = {"AST", "PA", "PR", "PRA", "RA", "PTS_AST", "REB_AST"}
    m_demon_noisy = (out["tier"] == "DEMON") & (out["stat"].isin(noisy_stats))
    if m_demon_noisy.any():
        out.loc[m_demon_noisy, "p_adj"] = (out.loc[m_demon_noisy, "p_adj"] * 0.96).clip(0, 1)

    # Non-star fragility amplification (optional, only if columns exist)
    if "fragility" in out.columns and "is_star" in out.columns:
        frag = pd.to_numeric(out["fragility"], errors="coerce").fillna(0.0).clip(0, 1)
        is_star = out["is_star"].astype(bool)
        m_role = (~is_star) & (frag >= 0.10)
        if m_role.any():
            out.loc[m_role, "p_adj"] = (out.loc[m_role, "p_adj"] * (1.0 - 0.20 * frag[m_role])).clip(0, 1)

    out["p_adj"] = pd.to_numeric(out["p_adj"], errors="coerce").fillna(0.50).clip(0, 1)
    return out


def dedupe_over_under(scored: pd.DataFrame) -> pd.DataFrame:
    out = scored.copy()
    out["direction"] = out.get("direction", "").astype(str).str.upper().str.strip()
    out["tier"] = out.get("tier", "STANDARD").astype(str).str.upper().str.strip()

    out["prop_key"] = (
        out.get("player", "").astype(str).str.strip()
        + "|"
        + out.get("stat", "").astype(str).str.strip()
        + "|"
        + pd.to_numeric(out.get("line", pd.Series([pd.NA] * len(out))), errors="coerce").astype(str)
        + "|"
        + out.get("tier", "STANDARD").astype(str).str.strip()
    )

    out["p_adj"] = pd.to_numeric(out.get("p_adj", out.get("p", 0.50)), errors="coerce").fillna(0.50).clip(0, 1)
    out = out.sort_values(by=["prop_key", "p_adj"], ascending=[True, False], na_position="last")
    return out.drop_duplicates(subset=["prop_key"], keep="first")


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
    out = out.drop_duplicates(subset=["slip_key"], keep="first")
    return out


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


def _system_mix_ok(n_legs: int, legs: Any) -> bool:
    # YOUR RULES:
    # 3: 1G + 2S
    # 4: 2G + 2S
    # 5: 3G + 2S
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

def build_slips_by_tier_buckets(
    *,
    legs_df: pd.DataFrame,
    n_legs: int,
    top_n: int,
    payout_power_mult: Any,
    payout_flex: Any,
    seed: int = 7,
    per_tier: int = 500,
    max_attempts: int = 400000,
    mixes: dict[int, dict[str, int]],
    required_tiers: list[str],
    mix_ok_fn,
) -> pd.DataFrame:
    if legs_df is None or len(legs_df) == 0:
        return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])

    if n_legs not in mixes:
        return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])
    mix = mixes[n_legs]

    df = legs_df.copy().reset_index(drop=True)

    if "projection_id" not in df.columns and "id" in df.columns:
        df = df.rename(columns={"id": "projection_id"})
    df["projection_id"] = pd.to_numeric(df.get("projection_id"), errors="coerce").astype("Int64")

    df["tier"] = df.get("tier", "STANDARD").astype(str).str.upper().str.strip()

    # p_eff used by optimize/_score_slip path (stable)
    if "p_eff" not in df.columns:
        df["p_eff"] = pd.to_numeric(df.get("p_adj", 0.50), errors="coerce").fillna(0.50).clip(0, 1)
    else:
        df["p_eff"] = pd.to_numeric(df["p_eff"], errors="coerce").fillna(
            pd.to_numeric(df.get("p_adj", 0.50), errors="coerce").fillna(0.50)
        ).clip(0, 1)

    df["edge_score"] = pd.to_numeric(df.get("edge_score", df["p_eff"] - 0.5), errors="coerce").fillna(df["p_eff"] - 0.5)

    tier_counts = df["tier"].value_counts(dropna=False).to_dict()
    print(f"[BUILDER][DEBUG] leg_df tier counts: {tier_counts}")

    for needed in required_tiers:
        if tier_counts.get(needed, 0) == 0:
            return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])

    # Within-tier ranking
    df = df.sort_values(["tier", "edge_score", "p_eff"], ascending=[True, False, False]).reset_index(drop=True)

    buckets: dict[str, list[pd.Series]] = {}
    for t in required_tiers:
        sub = df[df["tier"] == t].head(int(per_tier)).reset_index(drop=True)
        buckets[t] = [sub.iloc[i] for i in range(len(sub))]

    for t, need in mix.items():
        if len(buckets.get(t, [])) < int(need):
            return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])

    rng = random.Random(int(seed))
    slips: list[dict[str, Any]] = []
    seen: set[str] = set()

    attempts = 0
    while attempts < int(max_attempts) and len(slips) < int(top_n) * 10:
        attempts += 1

        chosen: list[pd.Series] = []
        for t, need in mix.items():
            chosen.extend(rng.sample(buckets[t], int(need)))

        # Unique projection_id and unique player within slip
        pids = []
        players = []
        ok = True
        for r in chosen:
            pid = r.get("projection_id")
            if pid is None or pd.isna(pid):
                ok = False
                break
            pids.append(int(pid))
            players.append(str(r.get("player", "")).strip().lower())

        if not ok:
            continue
        if len(pids) != len(set(pids)):
            continue
        if len(players) != len(set(players)):
            continue

        scored = _score_slip(chosen, n_legs, payout_power_mult, payout_flex)
        legs_str = scored.get("legs", "")

        if not mix_ok_fn(n_legs, legs_str):
            continue

        key = scored.get("slip_key") or legs_str
        if key in seen:
            continue
        seen.add(key)
        slips.append(scored)

    if not slips:
        return pd.DataFrame(columns=["n_legs", "legs", "hit_prob", "ev_mult", "avg_p", "avg_fragility", "slip_key"])

    out = pd.DataFrame(slips)
    out["n_legs"] = int(n_legs)
    out["hit_prob"] = pd.to_numeric(out.get("hit_prob", 0.0), errors="coerce").fillna(0.0)
    out["ev_mult"] = pd.to_numeric(out.get("ev_mult", 0.0), errors="coerce").fillna(0.0)
    out = out.sort_values(["ev_mult", "hit_prob"], ascending=[False, False]).reset_index(drop=True)
    out = dedupe_slips_by_key(out).head(int(top_n)).reset_index(drop=True)
    return out


def build_windfall_slips(legs_df: pd.DataFrame, n_legs: int, top_n: int, seed: int) -> pd.DataFrame:
    mixes = {
        3: {"GOBLIN": 1, "STANDARD": 1, "DEMON": 1},
        4: {"GOBLIN": 1, "STANDARD": 2, "DEMON": 1},
        5: {"GOBLIN": 2, "STANDARD": 2, "DEMON": 1},
    }
    return build_slips_by_tier_buckets(
        legs_df=legs_df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex={3: FLEX_3, 4: FLEX_4, 5: FLEX_5}[n_legs],
        seed=seed,
        per_tier=400,
        max_attempts=400000,
        mixes=mixes,
        required_tiers=["GOBLIN", "STANDARD", "DEMON"],
        mix_ok_fn=_windfall_mix_ok,
    )


def build_system_slips(legs_df: pd.DataFrame, n_legs: int, top_n: int, seed: int) -> pd.DataFrame:
    mixes = {
        3: {"GOBLIN": 1, "STANDARD": 2},
        4: {"GOBLIN": 2, "STANDARD": 2},
        5: {"GOBLIN": 3, "STANDARD": 2},
    }
    df = legs_df.copy()
    df["tier"] = df.get("tier", "STANDARD").astype(str).str.upper().str.strip()
    df = df[df["tier"].isin(["GOBLIN", "STANDARD"])].reset_index(drop=True)

    return build_slips_by_tier_buckets(
        legs_df=df,
        n_legs=n_legs,
        top_n=top_n,
        payout_power_mult=POWER_MULT[n_legs],
        payout_flex={3: FLEX_3, 4: FLEX_4, 5: FLEX_5}[n_legs],
        seed=seed,
        per_tier=650,
        max_attempts=500000,
        mixes=mixes,
        required_tiers=["GOBLIN", "STANDARD"],
        mix_ok_fn=_system_mix_ok,
    )


# -------------------------------------------------------------------
# Scoring loop
# -------------------------------------------------------------------

def score_board(board: pd.DataFrame, logs: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    lookback = int(cfg.get("lookback_games", 20))
    sims = int(cfg.get("simulations", 5000))

    blow = cfg.get("blowout", {}) or {}
    spread_sd = float(blow.get("spread_sd", 9.5))
    threshold = float(blow.get("threshold_margin", 15))

    # Keep your simulator signature stable
    star_drop = float(blow.get("star_minute_drop", 0.12))
    role_drop = float(blow.get("role_minute_drop", 0.20))

    rows: list[dict[str, Any]] = []
    for r in board.itertuples(index=False):
        row = pd.Series(r._asdict())

        # Ensure minutes_s exists (some pipelines do this later; we do it early)
        if "minutes_s" not in row.index:
            row["minutes_s"] = float(minutes_sensitivity(str(row.get("stat", "")).upper()))

        info = simulate_leg_probability(
            gamelogs=logs,
            row=row,
            lookback=lookback,
            sims=sims,
            spread_sd=spread_sd,
            blowout_threshold=threshold,
            star_minute_drop=star_drop,
            role_minute_drop=role_drop,
        )

        # >>> ADDED: per-leg data health flag (minimal)
        # DATA_MISSING is the ONLY allowed state for any downstream p_adj==0.
        games_used = int((info or {}).get("games_used", 0) or 0)
        data_health_flag = "OK" if games_used > 0 else "DATA_MISSING"
        # <<< ADDED

        rows.append({**row.to_dict(), **(info or {}), "data_health_flag": data_health_flag})

    return pd.DataFrame(rows)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main() -> None:
    cfg = load_config()

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

    scored = score_board(board=board, logs=logs, cfg=cfg)
    scored = ensure_p_adj(scored)

    scored_for_optimizer = dedupe_over_under(scored)

    # priors (if configured) apply post p_adj
    scored = apply_external_priors(scored, cfg)
    scored_for_optimizer = apply_external_priors(scored_for_optimizer, cfg)

    # >>> ADDED: HARD INVARIANT (after priors, since priors can touch p_adj)
    # p_adj == 0 is illegal unless explicitly flagged as DATA_MISSING
    if "p_adj" in scored.columns:
        scored["p_adj"] = pd.to_numeric(scored["p_adj"], errors="coerce").fillna(0.0)
        scored["data_health_flag"] = scored.get("data_health_flag", "OK").astype(str)
        illegal = scored[(scored["p_adj"] == 0.0) & (scored["data_health_flag"] != "DATA_MISSING")]
        if not illegal.empty:
            cols = [c for c in ["player", "stat", "direction", "line", "tier", "games_used", "p", "p_adj", "data_health_flag", "projection_id"] if c in illegal.columns]
            sample = illegal[cols].head(25)
            raise RuntimeError(
                "HARD INVARIANT VIOLATION: p_adj == 0.0 for non-DATA_MISSING rows.\n"
                + sample.to_string(index=False)
            )
    # <<< ADDED

    optimizer_cfg = (cfg.get("optimizer", {}) or {})
    top_n = int(optimizer_cfg.get("top_n_slips", 25))
    seed = int(optimizer_cfg.get("seed", 7))

    # Prepare run folder
    ts = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    windfall_dir = run_dir / "Windfall"
    system_dir = run_dir / "System"
    windfall_dir.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)

    # Write scored legs
    write_csv_clean(scored, run_dir / "scored_legs.csv")
    write_csv_clean(scored_for_optimizer, run_dir / "scored_legs_deduped.csv")

    # --------------------------
    # SYSTEM (median ROI)
    # --------------------------
    sys3 = build_system_slips(scored_for_optimizer, 3, top_n, seed)
    sys4 = build_system_slips(scored_for_optimizer, 4, top_n, seed)
    sys5 = build_system_slips(scored_for_optimizer, 5, top_n, seed)

    sys3 = expand_legs(sys3, 3)
    sys4 = expand_legs(sys4, 4)
    sys5 = expand_legs(sys5, 5)

    write_csv_clean(sys3, system_dir / "recommended_3leg.csv")
    write_csv_clean(sys4, system_dir / "recommended_4leg.csv")
    write_csv_clean(sys5, system_dir / "recommended_5leg.csv")

    # --------------------------
    # WINDFALL (risk/reward)
    # --------------------------
    wind3 = build_windfall_slips(scored_for_optimizer, 3, top_n, seed)
    wind4 = build_windfall_slips(scored_for_optimizer, 4, top_n, seed)
    wind5 = build_windfall_slips(scored_for_optimizer, 5, top_n, seed)

    wind3 = expand_legs(wind3, 3)
    wind4 = expand_legs(wind4, 4)
    wind5 = expand_legs(wind5, 5)

    write_csv_clean(wind3, windfall_dir / "recommended_3leg.csv")
    write_csv_clean(wind4, windfall_dir / "recommended_4leg.csv")
    write_csv_clean(wind5, windfall_dir / "recommended_5leg.csv")

    # Legacy “regular output” mirrors SYSTEM (safer)
    write_csv_clean(sys3, run_dir / "recommended_3leg.csv")
    write_csv_clean(sys4, run_dir / "recommended_4leg.csv")
    write_csv_clean(sys5, run_dir / "recommended_5leg.csv")

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


if __name__ == "__main__":
    main()