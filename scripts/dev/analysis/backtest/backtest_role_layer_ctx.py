#!/usr/bin/env python3
"""
Backtest role-layer context using the NEW probability engine kernel.

Key design:
- No edits to engine/main.py required.
- Calls Atlas.engine.new_probability.simulate_leg_probability_new directly.
- Produces BASE (role disabled) vs ROLE (role enabled) outputs.
- Backtests on directional p_adj (probability of the selected direction hitting).
- Writes a CSV including new diagnostics (q_blowout, minutes_s_close, p_close, fragility, etc.).

Typical usage:
  python scripts/dev/analysis/backtest/backtest_role_layer_ctx.py --start 20260101 --end 20260222
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ============================================================
# Bootstrap import path so "src/Atlas" is importable regardless of CWD
# ============================================================
_THIS = Path(__file__).resolve()
_repo_root = None
for p in _THIS.parents:
    if (p / "src").exists():
        _repo_root = p
        break
if _repo_root is None:
    raise SystemExit(f"Could not find repo root containing 'src' from: {_THIS}")

REPO_ROOT = _repo_root
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# ============================================================
# New engine kernel import
# ============================================================
from Atlas.engine.new_probability import simulate_leg_probability_new  # noqa: E402

# ============================================================
# Defaults / Paths
# ============================================================
PROJECT_ROOT = REPO_ROOT
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "board" / "snapshots"
DEFAULT_LOGS_PATH = PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
DEFAULT_IAEL_DIR = PROJECT_ROOT / "data" / "output" / "injury" / "normalized"

REPORT_ROOT = Path(os.environ.get("ATLAS_TELEMETRY_REPORT_ROOT", str(PROJECT_ROOT / "tools" / "reports")))
REPORT_ROOT.mkdir(parents=True, exist_ok=True)

LEG_KEY = ["player_norm", "stat", "line", "direction"]


# ============================================================
# Helpers
# ============================================================
def _normalize_player(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def _normalize_stat(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def _normalize_direction(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def _norm_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize merge keys on ANY frame that will be merged on LEG_KEY."""
    df = df.copy()
    if "player_norm" in df.columns:
        df["player_norm"] = _normalize_player(df["player_norm"])
    if "stat" in df.columns:
        df["stat"] = _normalize_stat(df["stat"])
    if "direction" in df.columns:
        df["direction"] = _normalize_direction(df["direction"])
    if "line" in df.columns:
        df["line"] = pd.to_numeric(df["line"], errors="coerce").round(3)
    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.normalize()
    return df


def _parse_date_from_filename(path: Path) -> pd.Timestamp | None:
    """
    Expect snapshot names like today_YYYYMMDD.csv or today_YYYYMMDD_*.csv
    """
    name = path.name
    if "today_" not in name:
        return None
    parts = name.split("_")
    if len(parts) < 2:
        return None
    yyyymmdd = parts[1][:8]
    try:
        return pd.to_datetime(yyyymmdd, format="%Y%m%d", errors="raise").normalize()
    except Exception:
        return None


def _coerce_game_date(board: pd.DataFrame, fallback: pd.Timestamp | None) -> pd.DataFrame:
    board = board.copy()
    for c in ["game_date", "GAME_DATE", "date", "DATE"]:
        if c in board.columns:
            board["game_date"] = pd.to_datetime(board[c], errors="coerce").dt.normalize()
            break
    if "game_date" not in board.columns:
        board["game_date"] = pd.NaT
    if fallback is not None:
        board["game_date"] = board["game_date"].fillna(fallback)
    return board


def _expand_directions(board: pd.DataFrame) -> pd.DataFrame:
    b = board.copy()

    if "direction" not in b.columns:
        b["direction"] = ""

    b["direction"] = _normalize_direction(b["direction"])

    already_dir = b["direction"].isin(["OVER", "UNDER"])
    directed = b.loc[already_dir].copy()
    undirected = b.loc[~already_dir].copy()

    if undirected.empty:
        return directed.reset_index(drop=True)

    over = undirected.copy()
    over["direction"] = "OVER"

    under = undirected.copy()
    under["direction"] = "UNDER"

    out = pd.concat([directed, over, under], ignore_index=True)
    return out.reset_index(drop=True)


def _compute_hit(actual: float, line: float, direction: str) -> float:
    if pd.isna(actual) or pd.isna(line):
        return np.nan
    d = (direction or "").upper().strip()
    if d == "OVER":
        return 1.0 if actual > line else 0.0
    if d == "UNDER":
        return 1.0 if actual < line else 0.0
    return np.nan


def _list_snapshots(start_yyyymmdd: str, end_yyyymmdd: str) -> list[Path]:
    if not SNAPSHOT_DIR.exists():
        raise SystemExit(f"Missing snapshot dir: {SNAPSHOT_DIR}")

    snaps: list[Path] = []
    for p in SNAPSHOT_DIR.glob("today_*.csv"):
        dt = _parse_date_from_filename(p)
        if dt is None:
            continue
        yyyymmdd = dt.strftime("%Y%m%d")
        if start_yyyymmdd <= yyyymmdd <= end_yyyymmdd:
            snaps.append(p)
    snaps.sort(key=lambda x: x.name)
    return snaps


# ============================================================
# Actuals computation
# ============================================================
def _ensure_actual_cols(logs: pd.DataFrame) -> pd.DataFrame:
    logs = logs.copy()
    for c in ["PTS", "REB", "AST", "FG3M"]:
        if c in logs.columns and c.lower() not in logs.columns:
            logs[c.lower()] = logs[c]
    for c in ["pts", "reb", "ast", "fg3m"]:
        if c in logs.columns:
            logs[c] = pd.to_numeric(logs[c], errors="coerce")
    return logs


def _actual_from_logs_row(stat: str, r: Any) -> float:
    s = (stat or "").upper().strip()

    def g(name: str) -> float:
        if hasattr(r, name):
            v = getattr(r, name)
            return float(v) if pd.notna(v) else np.nan
        return np.nan

    pts = g("pts")
    reb = g("reb")
    ast = g("ast")
    fg3m = g("fg3m")

    if s == "PTS":
        return pts
    if s == "REB":
        return reb
    if s == "AST":
        return ast
    if s in ("FG3M", "3PM", "3PTM"):
        return fg3m

    if s in ("PA", "PTS+ASTS", "PTS+AST"):
        return (pts + ast) if np.isfinite(pts) and np.isfinite(ast) else np.nan
    if s in ("PR", "PTS+REBS", "PTS+REB"):
        return (pts + reb) if np.isfinite(pts) and np.isfinite(reb) else np.nan
    if s in ("RA", "REBS+ASTS", "REB+AST"):
        return (reb + ast) if np.isfinite(reb) and np.isfinite(ast) else np.nan
    if s in ("PRA", "PTS+REBS+ASTS", "PTS+REB+AST"):
        return (pts + reb + ast) if np.isfinite(pts) and np.isfinite(reb) and np.isfinite(ast) else np.nan

    return np.nan


# ============================================================
# Loading
# ============================================================
def load_board(path: Path) -> pd.DataFrame:
    board = pd.read_csv(path)

    if "player_norm" not in board.columns:
        if "player" in board.columns:
            board["player_norm"] = _normalize_player(board["player"])
        elif "PLAYER" in board.columns:
            board["player_norm"] = _normalize_player(board["PLAYER"])
        else:
            raise RuntimeError(f"Board missing player/player_norm columns: {path}")

    if "player" not in board.columns:
        board["player"] = board["player_norm"].astype(str)

    if "stat" not in board.columns:
        if "STAT" in board.columns:
            board["stat"] = board["STAT"]
        else:
            raise RuntimeError(f"Board missing stat/STAT column: {path}")
    board["stat"] = _normalize_stat(board["stat"])

    if "line" not in board.columns:
        if "LINE" in board.columns:
            board["line"] = board["LINE"]
        else:
            raise RuntimeError(f"Board missing line/LINE column: {path}")
    board["line"] = pd.to_numeric(board["line"], errors="coerce")

    if "team" not in board.columns:
        for c in ("TEAM", "Team", "tm"):
            if c in board.columns:
                board["team"] = board[c]
                break
    if "team" not in board.columns:
        board["team"] = ""
    board["team"] = board["team"].astype(str).str.upper().str.strip()

    fallback = _parse_date_from_filename(path)
    board = _coerce_game_date(board, fallback)

    return board


def load_logs(logs_path: Path) -> pd.DataFrame:
    if not logs_path.exists():
        raise SystemExit(f"Missing gamelogs: {logs_path}")

    logs = pd.read_csv(logs_path)

    if "player" not in logs.columns:
        if "PLAYER" in logs.columns:
            logs["player"] = logs["PLAYER"]
        else:
            raise RuntimeError(f"Gamelogs missing player/PLAYER col: {logs_path}")
    logs["player"] = logs["player"].astype(str)
    logs["player_norm"] = _normalize_player(logs["player"])

    if "game_date" in logs.columns:
        logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce").dt.normalize()
    elif "GAME_DATE" in logs.columns:
        logs["game_date"] = pd.to_datetime(logs["GAME_DATE"], errors="coerce").dt.normalize()
    elif "date" in logs.columns:
        logs["game_date"] = pd.to_datetime(logs["date"], errors="coerce").dt.normalize()
    else:
        raise RuntimeError(f"Gamelogs missing game_date column(s): {logs_path}")

    logs = _ensure_actual_cols(logs)
    return logs
def _coerce_iael_frame(obj: Any) -> pd.DataFrame:
    if isinstance(obj, list):
        df = pd.DataFrame(obj)
    elif isinstance(obj, dict):
        if isinstance(obj.get("rows"), list):
            df = pd.DataFrame(obj["rows"])
        elif isinstance(obj.get("data"), list):
            df = pd.DataFrame(obj["data"])
        else:
            df = pd.DataFrame([obj])
    else:
        df = pd.DataFrame()

    if df.empty:
        return df

    # Normalize likely key columns used downstream
    if "player" not in df.columns:
        for c in ("player_name", "name", "PLAYER"):
            if c in df.columns:
                df["player"] = df[c]
                break
    if "player" in df.columns:
        df["player"] = df["player"].astype(str).str.strip()
        df["player_norm"] = _normalize_player(df["player"])

    if "team" not in df.columns:
        for c in ("team_u", "abbr", "TEAM", "team_abbr"):
            if c in df.columns:
                df["team"] = df[c]
                break
    if "team" in df.columns:
        df["team"] = df["team"].astype(str).str.upper().str.strip()
        df["team_u"] = df["team"]

    if "status" in df.columns:
        df["status"] = df["status"].astype(str).str.upper().str.strip()

    if "report_date" in df.columns:
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.normalize()

    return df


def _load_iael_json(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    return _coerce_iael_frame(obj)


def _pick_historical_iael_file(iael_dir: Path, snap: Path, board_df: pd.DataFrame) -> Path | None:
    if not iael_dir.exists():
        return None

    snap_dt = None

    # Prefer game_date from board_df
    if "game_date" in board_df.columns:
        vals = pd.to_datetime(board_df["game_date"], errors="coerce").dropna()
        if not vals.empty:
            snap_dt = vals.iloc[0].normalize()

    # Fallback to snapshot filename parsing
    if snap_dt is None:
        snap_dt = _parse_date_from_filename(snap)

    if snap_dt is None:
        return None

    day_str = snap_dt.strftime("%Y-%m-%d")

    # Prefer exact dated normalized snapshots like 2026-03-06_09_15PM.json
    cands = sorted(iael_dir.glob(f"{day_str}_*.json"))
    if cands:
        return cands[-1]

    # Fallback: exact day file without suffix
    p = iael_dir / f"{day_str}.json"
    if p.exists():
        return p

    return None


def load_historical_iael_for_snapshot(iael_dir: Path, snap: Path, board_df: pd.DataFrame) -> pd.DataFrame | None:
    chosen = _pick_historical_iael_file(iael_dir, snap, board_df)
    if chosen is None:
        print(f"[IAEL][BACKTEST] No historical IAEL file found for {snap.name} in {iael_dir}")
        return None

    df = _load_iael_json(chosen)
    if df is None or df.empty:
        print(f"[IAEL][BACKTEST] Historical IAEL file empty: {chosen.name}")
        return None

    print(f"[IAEL][BACKTEST] Using {chosen.name} for {snap.name} rows={len(df)}")
    return df

# ============================================================
# Scoring via New Engine
# ============================================================
def score_board_newengine(
    *,
    board_df: pd.DataFrame,
    logs_df: pd.DataFrame,
    iael_df: pd.DataFrame | None,
    use_role_layer: bool,
    nsims: int,
    seed: int,
    lookback: int,
    spread_sd: float,
    blowout_threshold: float,
    star_minute_drop: float,
    role_minute_drop: float,
) -> pd.DataFrame:
    """
    Score each leg via Atlas.engine.new_probability.simulate_leg_probability_new.

    NOTE: p, p_role, p_adj, p_close are directional hit probabilities for row.direction.
    """
    rng = np.random.default_rng(int(seed) + (0 if use_role_layer else 10_000))
    role_cfg = {"enabled": bool(use_role_layer)}

    needed = {"player", "player_norm", "stat", "line", "direction"}
    missing = needed - set(board_df.columns)
    if missing:
        raise RuntimeError(f"board_df missing required columns: {sorted(missing)}")

    out_rows: list[dict[str, Any]] = []

    board_df = _norm_keys(board_df)

    for _, row in board_df.iterrows():
        info = simulate_leg_probability_new(
            gamelogs=logs_df,
            row=row,
            lookback=int(lookback),
            sims=int(nsims),
            spread_sd=float(spread_sd),
            blowout_threshold=float(blowout_threshold),
            star_minute_drop=float(star_minute_drop),
            role_minute_drop=float(role_minute_drop),
            iael_df=iael_df,
            role_cfg=role_cfg,
            rng=rng,
        )

        rec = dict(info)
        rec["player_norm"] = str(row.get("player_norm", "")).upper().strip()
        rec["stat"] = str(row.get("stat", "")).upper().strip()
        rec["line"] = float(pd.to_numeric(row.get("line", np.nan), errors="coerce"))
        rec["direction"] = str(row.get("direction", "")).upper().strip()

        d = rec["direction"]
        pdir = float(pd.to_numeric(rec.get("p_adj", np.nan), errors="coerce"))
        rec["p_over_adj"] = pdir if d == "OVER" else (1.0 - pdir if np.isfinite(pdir) else np.nan)

        out_rows.append(rec)

    out = pd.DataFrame(out_rows)

    for c in [
        "p", "p_role", "p_adj", "p_close",
        "p_close_raw", "p_close_role",
        "spread", "q_blowout", "minutes_s", "minutes_s_close",
        "fragility", "fragility_abs",
        "min_mean", "min_std", "rate_mean", "rate_std",
        "rate_mean_ctx", "rate_std_ctx",
        "role_ctx_mult", "role_ctx_mult_raw", "role_ctx_sigma_mult",
        "games_used",
    ]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    out = _norm_keys(out)
    return out


# ============================================================
# Metrics
# ============================================================
def brier(y: np.ndarray, p: np.ndarray) -> float:
    y = y.astype(float)
    p = np.clip(p.astype(float), 1e-9, 1.0 - 1e-9)
    return float(np.mean((p - y) ** 2))


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    p = np.clip(p.astype(float), 0.0, 1.0)
    y = y.astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    b = np.digitize(p, edges, right=False) - 1
    b = np.clip(b, 0, bins - 1)

    rows: list[dict[str, Any]] = []
    for i in range(bins):
        mask = b == i
        if not bool(mask.any()):
            rows.append({"bin": i, "n": 0, "avg_p": np.nan, "hit_rate": np.nan, "diff": np.nan})
            continue
        avg_p = float(np.mean(p[mask]))
        hit_rate = float(np.mean(y[mask]))
        rows.append(
            {
                "bin": i,
                "n": int(mask.sum()),
                "avg_p": round(avg_p, 4),
                "hit_rate": round(hit_rate, 4),
                "diff": round(hit_rate - avg_p, 4),
            }
        )
    return pd.DataFrame(rows)




def _safe_brier_frame(df: pd.DataFrame, prob_col: str) -> tuple[int, float | None]:
    if prob_col not in df.columns:
        return 0, None
    mask = df[prob_col].notna() & df["hit"].notna()
    n = int(mask.sum())
    if n == 0:
        return 0, None
    y = df.loc[mask, "hit"].to_numpy(dtype=float)
    p = df.loc[mask, prob_col].to_numpy(dtype=float)
    return n, brier(y, p)


def _format_float(v: Any, digits: int = 6) -> str:
    if v is None or pd.isna(v):
        return ''
    return f"{float(v):.{digits}f}"


def _print_cohort_identity(df_eval: pd.DataFrame) -> None:
    rows = []
    for snap, g in df_eval.groupby("__snapshot", dropna=False):
        rows.append({
            "__snapshot": str(snap),
            "snapshot_date": str(pd.to_datetime(g["snapshot_date"], errors="coerce").dropna().min().date()) if g["snapshot_date"].notna().any() else '',
            "rows": int(len(g)),
            "pushes_excluded": int(g["push"].sum()) if "push" in g.columns else 0,
        })
    out = pd.DataFrame(rows).sort_values(["snapshot_date", "__snapshot"], na_position="last")
    print("\n=== COHORT IDENTITY ===")
    print(f"Snapshots: {out['__snapshot'].nunique()}")
    print(f"Evaluable non-push rows: {len(df_eval)}")
    if not out.empty:
        print(out.to_string(index=False))


def _print_per_snapshot_brier(df_eval: pd.DataFrame) -> None:
    rows = []
    for snap, g in df_eval.groupby("__snapshot", dropna=False):
        n_base, b_base = _safe_brier_frame(g, "p_dir_base")
        n_role, b_role = _safe_brier_frame(g, "p_dir_role")
        rows.append({
            "__snapshot": str(snap),
            "snapshot_date": str(pd.to_datetime(g["snapshot_date"], errors="coerce").dropna().min().date()) if g["snapshot_date"].notna().any() else '',
            "rows": int(len(g)),
            "base_n": n_base,
            "brier_base": None if b_base is None else round(float(b_base), 6),
            "role_n": n_role,
            "brier_role": None if b_role is None else round(float(b_role), 6),
            "delta_brier": None if (b_base is None or b_role is None) else round(float(b_role - b_base), 6),
        })
    out = pd.DataFrame(rows).sort_values(["snapshot_date", "__snapshot"], na_position="last")
    print("\n=== PER-SNAPSHOT BRIER (p_adj, pushes excluded) ===")
    if out.empty:
        print("(no per-snapshot rows)")
    else:
        print(out.to_string(index=False))


def _print_delta_surface(df_eval: pd.DataFrame) -> None:
    if "p_dir_base" not in df_eval.columns or "p_dir_role" not in df_eval.columns:
        print("\n=== ROLE DELTA SURFACE ===")
        print("(missing p_dir_base/p_dir_role)")
        return
    mask = df_eval["p_dir_base"].notna() & df_eval["p_dir_role"].notna()
    if not bool(mask.any()):
        print("\n=== ROLE DELTA SURFACE ===")
        print("(no overlapping BASE/ROLE probabilities)")
        return
    delta = (df_eval.loc[mask, "p_dir_role"] - df_eval.loc[mask, "p_dir_base"]).astype(float)
    abs_delta = delta.abs()
    summary = {
        "rows": int(mask.sum()),
        "mean_delta": round(float(delta.mean()), 6),
        "mean_abs_delta": round(float(abs_delta.mean()), 6),
        "p90_abs_delta": round(float(abs_delta.quantile(0.90)), 6),
        "p95_abs_delta": round(float(abs_delta.quantile(0.95)), 6),
        "p99_abs_delta": round(float(abs_delta.quantile(0.99)), 6),
        "rows_abs_ge_0.001": int((abs_delta >= 0.001).sum()),
        "rows_abs_ge_0.005": int((abs_delta >= 0.005).sum()),
        "rows_abs_ge_0.010": int((abs_delta >= 0.010).sum()),
        "rows_abs_ge_0.020": int((abs_delta >= 0.020).sum()),
    }
    print("\n=== ROLE DELTA SURFACE (p_adj_role - p_adj_base) ===")
    for k, v in summary.items():
        print(f"{k}: {v}")


def _print_bucket_delta(df_eval: pd.DataFrame, by_col: str, title: str) -> None:
    if by_col not in df_eval.columns or "p_dir_base" not in df_eval.columns or "p_dir_role" not in df_eval.columns:
        print(f"\n=== {title} ===")
        print(f"(missing required columns for {by_col})")
        return
    work = df_eval.copy()
    work[by_col] = work[by_col].fillna('(blank)').astype(str)
    work["delta"] = pd.to_numeric(work["p_dir_role"], errors="coerce") - pd.to_numeric(work["p_dir_base"], errors="coerce")
    work = work.loc[work["delta"].notna()].copy()
    if work.empty:
        print(f"\n=== {title} ===")
        print("(no overlapping BASE/ROLE probabilities)")
        return
    grp = (
        work.groupby(by_col, dropna=False)["delta"]
        .agg(rows="size", mean_delta="mean", mean_abs_delta=lambda s: s.abs().mean(), p95_abs_delta=lambda s: s.abs().quantile(0.95))
        .reset_index()
        .sort_values(["rows", "mean_abs_delta"], ascending=[False, False])
    )
    grp["mean_delta"] = grp["mean_delta"].round(6)
    grp["mean_abs_delta"] = grp["mean_abs_delta"].round(6)
    grp["p95_abs_delta"] = grp["p95_abs_delta"].round(6)
    print(f"\n=== {title} ===")
    print(grp.to_string(index=False))


def _snapshot_label(args: argparse.Namespace, snaps: list[Path]) -> str:
    if args.start and args.end:
        return f"{args.start}_{args.end}"
    if len(snaps) == 1:
        return snaps[0].stem
    if snaps:
        return f"snapshots_{len(snaps)}"
    return 'unknown_range'

# ============================================================
# Main
# ============================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="YYYYMMDD (required unless --snapshot is used)")
    ap.add_argument("--end", default=None, help="YYYYMMDD (required unless --snapshot is used)")
    ap.add_argument("--snapshot", action="append", default=None, help="Exact snapshot CSV path(s). Repeatable. If provided, --start/--end are ignored.")
    ap.add_argument("--logs-path", default=str(DEFAULT_LOGS_PATH), help="Path to gamelogs CSV")
    ap.add_argument("--outcomes-csv", default=None, help="Path to outcomes CSV (e.g., data/telemetry/Last 10/Last10.csv). If set, uses this instead of --logs-path.")
    
    # Simulation params
    ap.add_argument("--nsims", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--spread-sd", type=float, default=12.0)
    ap.add_argument("--blowout-threshold", type=float, default=12.0)
    ap.add_argument("--star-minute-drop", type=float, default=6.0)
    ap.add_argument("--role-minute-drop", type=float, default=4.0)

    # ✅ Synthetic spread injection (stress test when historical spreads aren't available)
    ap.add_argument("--synthetic-spread", action="store_true",
                    help="Inject synthetic game_spread to validate blowout math without real spreads")
    ap.add_argument("--synthetic-spread-sd", type=float, default=8.0,
                    help="Std dev for synthetic spread distribution (abs(N(0, sd)))")
    ap.add_argument("--synthetic-spread-max", type=float, default=20.0,
                    help="Cap for synthetic spread values")
    ap.add_argument("--synthetic-spread-seed", type=int, default=1337,
                    help="RNG seed for synthetic spreads")

    ap.add_argument("--out-prefix", default="backtest_role_layer_ctx_new")
    ap.add_argument("--iael-dir", default=str(DEFAULT_IAEL_DIR),
                    help="Directory containing historical normalized IAEL json snapshots")
    ap.add_argument("--disable-iael", action="store_true",
                    help="Force iael_df=None for comparison/debug")
    args = ap.parse_args()

    if args.outcomes_csv:
        logs_path = Path(args.outcomes_csv).expanduser().resolve()
        if not logs_path.exists():
            raise SystemExit(f"Missing outcomes csv: {logs_path}")
        logs = pd.read_csv(logs_path)
    else:
        logs = load_logs(Path(args.logs_path))

    # Normalize to the columns load_logs expects
    if "player" not in logs.columns:
        raise SystemExit(f"Outcomes CSV missing 'player' column: {logs_path}")
    logs["player"] = logs["player"].astype(str)
    logs["player_norm"] = _normalize_player(logs["player"])

    if "game_date" not in logs.columns:
        raise SystemExit(f"Outcomes CSV missing 'game_date' column: {logs_path}")
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce").dt.normalize()

    # Ensure actual stat columns exist and are numeric (your file already has these)
    for c in ["pts", "reb", "ast", "fg3m"]:
        if c in logs.columns:
            logs[c] = pd.to_numeric(logs[c], errors="coerce")
    else:
        logs = load_logs(Path(args.logs_path))

    snaps: list[Path] = []
    if args.snapshot:
        for s in args.snapshot:
            p = Path(s).expanduser()
            # Resolve bare filenames relative to SNAPSHOT_DIR for convenience
            if not p.is_absolute() and ("/" not in s) and ("\\" not in s):
                p = SNAPSHOT_DIR / s
            p = p.resolve()
            if not p.exists():
                raise SystemExit(f"Snapshot not found: {s} -> {p}")
            snaps.append(p)
        snaps = sorted(set(snaps))
    else:
        if not args.start or not args.end:
            raise SystemExit("--start and --end are required unless --snapshot is provided.")
        snaps = _list_snapshots(args.start, args.end)
    print(f"Snapshots in range {args.start}-{args.end}: {len(snaps)}")
    if not snaps:
        raise SystemExit("No board_ snapshots found in range.")

    out_frames: list[pd.DataFrame] = []

    for snap in snaps:
        board = load_board(snap)
        board = _expand_directions(board)

        board = _norm_keys(board)
        merged = board.merge(
            logs,
            on=["player_norm", "game_date"],
            how="left",
            suffixes=("", "_gl"),
        )

        actual = []
        hit = []
        for r in merged.itertuples(index=False):
            a = _actual_from_logs_row(getattr(r, "stat", ""), r)
            actual.append(a)
            hit.append(_compute_hit(a, getattr(r, "line", np.nan), getattr(r, "direction", "")))

        merged["actual"] = pd.to_numeric(pd.Series(actual), errors="coerce")
        merged["hit"] = pd.to_numeric(pd.Series(hit), errors="coerce")
        merged["push"] = merged["actual"].notna() & (merged["actual"] == merged["line"])

        eval_df = merged.loc[merged["hit"].notna()].copy()
        if eval_df.empty:
            continue

        print(f"Scoring snapshot {snap.name} (eval legs={len(eval_df)})")

        keep_cols = ["player", "player_norm", "team", "stat", "line", "direction", "game_date"]

        for c in [
            "spread", "game_spread", "home_spread", "away_spread",
            "closing_spread", "spread_close", "market_spread", "vegas_spread",
        ]:
            if c in eval_df.columns and c not in keep_cols:
                keep_cols.append(c)

        if "minutes_s" in eval_df.columns and "minutes_s" not in keep_cols:
            keep_cols.append("minutes_s")

        sim_board = eval_df[keep_cols].copy()
        iael_df = None
        if not args.disable_iael:
            iael_df = load_historical_iael_for_snapshot(
                Path(args.iael_dir),
                snap,
                sim_board,
            )
        if "player" not in sim_board.columns:
            sim_board["player"] = sim_board["player_norm"].astype(str)

        # ✅ Inject synthetic spreads if requested (so q_blowout varies)
        if args.synthetic_spread:
            rng_syn = np.random.default_rng(args.synthetic_spread_seed)
            syn = np.abs(rng_syn.normal(0.0, args.synthetic_spread_sd, size=len(sim_board)))
            syn = np.clip(syn, 0.0, args.synthetic_spread_max)
            sim_board["game_spread"] = syn  # new_probability._get_spread recognizes this

        base_out = score_board_newengine(
            board_df=sim_board,
            logs_df=logs,
            iael_df=iael_df,
            use_role_layer=False,
            nsims=args.nsims,
            seed=args.seed,
            lookback=args.lookback,
            spread_sd=args.spread_sd,
            blowout_threshold=args.blowout_threshold,
            star_minute_drop=args.star_minute_drop,
            role_minute_drop=args.role_minute_drop,
        )

        role_out = score_board_newengine(
            board_df=sim_board,
            logs_df=logs,
            iael_df=iael_df,
            use_role_layer=True,
            nsims=args.nsims,
            seed=args.seed,
            lookback=args.lookback,
            spread_sd=args.spread_sd,
            blowout_threshold=args.blowout_threshold,
            star_minute_drop=args.star_minute_drop,
            role_minute_drop=args.role_minute_drop,
        )

        keep_diag = [
            "p", "p_role", "p_adj", "p_close",
            "p_close_raw", "p_close_role",
            "spread", "q_blowout", "minutes_s", "minutes_s_close",
            "is_star", "fragility", "fragility_abs",
            "min_mean", "min_std", "rate_mean", "rate_std",
            "rate_mean_ctx", "rate_std_ctx",
            "role_ctx_mult", "role_ctx_mult_raw", "role_ctx_sigma_mult",
            "role_ctx_reason", "games_used",
            "p_over_adj",
        ]

        keep_diag_base = [c for c in keep_diag if c in base_out.columns]
        keep_diag_role = [c for c in keep_diag if c in role_out.columns]

        base_out2 = base_out[LEG_KEY + keep_diag_base].copy()
        role_out2 = role_out[LEG_KEY + keep_diag_role].copy()

        base_out2 = base_out2.rename(columns={c: f"{c}_base" for c in keep_diag_base})
        role_out2 = role_out2.rename(columns={c: f"{c}_role" for c in keep_diag_role})

        eval_df = _norm_keys(eval_df)
        base_out2 = _norm_keys(base_out2)
        role_out2 = _norm_keys(role_out2)

        joined = (
            eval_df
            .merge(base_out2, on=LEG_KEY, how="left")
            .merge(role_out2, on=LEG_KEY, how="left")
        )

        miss_b = float(joined["p_adj_base"].isna().mean()) if "p_adj_base" in joined.columns else 1.0
        miss_r = float(joined["p_adj_role"].isna().mean()) if "p_adj_role" in joined.columns else 1.0
        print(f"Merge missing rates: p_adj_base={miss_b:.2%}, p_adj_role={miss_r:.2%}")

        joined["__snapshot"] = snap.name
        snap_dt = _parse_date_from_filename(snap)
        joined["snapshot_date"] = snap_dt if snap_dt is not None else pd.NaT

        out_frames.append(joined)

    if not out_frames:
        raise SystemExit("No evaluated rows produced (no outcomes matched).")

    df = pd.concat(out_frames, ignore_index=True)

    df_eval = df.loc[~df["push"]].copy()

    if "p_adj_base" in df_eval.columns:
        df_eval["p_dir_base"] = pd.to_numeric(df_eval["p_adj_base"], errors="coerce")
    else:
        df_eval["p_dir_base"] = np.nan

    if "p_adj_role" in df_eval.columns:
        df_eval["p_dir_role"] = pd.to_numeric(df_eval["p_adj_role"], errors="coerce")
    else:
        df_eval["p_dir_role"] = np.nan

    y = df_eval["hit"].to_numpy(dtype=float)
    mask_b = df_eval["p_dir_base"].notna()
    mask_r = df_eval["p_dir_role"].notna()

    print("\n=== ROLE-LAYER BACKTEST SUMMARY (p_adj, pushes excluded) ===")
    print("Legs:", len(df_eval))
    print("BASE legs:", int(mask_b.sum()), "ROLE legs:", int(mask_r.sum()))

    if mask_b.any():
        pb = df_eval.loc[mask_b, "p_dir_base"].to_numpy(dtype=float)
        print("BASE avg p_adj:", round(float(np.mean(pb)), 4))
        print("BASE brier:", round(brier(y[mask_b.to_numpy()], pb), 6))

    if mask_r.any():
        pr = df_eval.loc[mask_r, "p_dir_role"].to_numpy(dtype=float)
        print("ROLE avg p_adj:", round(float(np.mean(pr)), 4))
        print("ROLE brier:", round(brier(y[mask_r.to_numpy()], pr), 6))

    print("\n=== CALIBRATION (10 bins; p_adj; pushes excluded) ===")
    if mask_r.any():
        pr = df_eval.loc[mask_r, "p_dir_role"].to_numpy(dtype=float)
        cal = calibration_table(y[mask_r.to_numpy()], pr, bins=10)
        print(cal.to_string(index=False))
    else:
        print("(no ROLE probabilities available)")

    print("\n=== BY STAT (Brier, p_adj; pushes excluded) ===")
    for stat, g in df_eval.groupby("stat"):
        y_s = g["hit"].to_numpy(dtype=float)
        mb = g["p_dir_base"].notna()
        mr = g["p_dir_role"].notna()
        row: dict[str, Any] = {"stat": stat, "n": int(len(g))}
        if mb.any():
            row["brier_base"] = round(brier(y_s[mb.to_numpy()], g.loc[mb, "p_dir_base"].to_numpy(dtype=float)), 6)
        if mr.any():
            row["brier_role"] = round(brier(y_s[mr.to_numpy()], g.loc[mr, "p_dir_role"].to_numpy(dtype=float)), 6)
        print(row)

    out_prefix = args.out_prefix
    range_label = _snapshot_label(args, snaps)
    out_csv = REPORT_ROOT / f"{out_prefix}_{range_label}.csv"
    df.to_csv(out_csv, index=False)

    meta = {
        "start": args.start,
        "end": args.end,
        "range_label": range_label,
        "snapshots": [p.name for p in snaps],
        "nsims": args.nsims,
        "seed": args.seed,
        "lookback": args.lookback,
        "spread_sd": args.spread_sd,
        "blowout_threshold": args.blowout_threshold,
        "star_minute_drop": args.star_minute_drop,
        "role_minute_drop": args.role_minute_drop,
        "synthetic_spread": bool(args.synthetic_spread),
        "synthetic_spread_sd": float(args.synthetic_spread_sd),
        "synthetic_spread_max": float(args.synthetic_spread_max),
        "synthetic_spread_seed": int(args.synthetic_spread_seed),
        "simulator": "Atlas.engine.new_probability.simulate_leg_probability_new",
        "rows_total": int(len(df)),
        "rows_eval_no_push": int(len(df_eval)),
        "report_root": str(REPORT_ROOT),
        "logs_path": str(Path(args.logs_path).resolve()),
    }
    out_meta = REPORT_ROOT / f"{out_prefix}_{range_label}.meta.json"
    out_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\nWrote: {out_csv}")
    print(f"Wrote: {out_meta}")


if __name__ == "__main__":
    main()