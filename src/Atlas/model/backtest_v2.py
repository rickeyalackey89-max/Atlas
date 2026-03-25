from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from Atlas.core.share_name_key import share_name_key
from Atlas.stages.rebuild.rebuild_today import run_rebuild


DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_OUTPUT_ROOT = Path("data/output/backtests")
DEFAULT_GAMLOGS_PATH = Path("data/gamelogs/nba_gamelogs.csv")
DEFAULT_NORMALIZED_INJURY_DIR = Path("data/output/injury/normalized")

PROP_KEY_COLS = ["player_key", "stat", "line", "direction", "tier", "game_id", "game_date"]
HARD_INVALID_STATUSES = {"OUT", "DOUBTFUL"}


class BacktestV2Error(RuntimeError):
    pass


@dataclass
class BacktestArgs:
    raw_path: Path
    logs_path: Path
    out_dir: Optional[Path]
    config_path: Path
    gamelogs_path: Path
    injury_dir: Path
    write_eval: bool
    strict_fidelity: bool


@dataclass
class BacktestMeta:
    raw_path: str
    raw_stem: str
    logs_path: str
    config_path: str
    gamelogs_path: str
    injury_dir: str
    run_dir: str
    created_at_utc: str
    slate_date: Optional[str] = None
    replay_snapshot_path: Optional[str] = None
    injury_snapshot_path: Optional[str] = None
    injury_invalidations_path: Optional[str] = None
    injury_status_path: Optional[str] = None
    today_csv_path: Optional[str] = None
    scored_legs_path: Optional[str] = None
    scored_legs_deduped_path: Optional[str] = None
    eval_legs_path: Optional[str] = None
    engine_run_dir: Optional[str] = None
    fidelity_passed: bool = False
    duplicate_prop_keys_passed: bool = False
    today_rows: Optional[int] = None
    scored_rows: Optional[int] = None
    scored_deduped_rows: Optional[int] = None
    eval_rows: Optional[int] = None
    notes: Optional[str] = None


def parse_args() -> BacktestArgs:
    parser = argparse.ArgumentParser(description="Backtest v2 replay runner.")
    parser.add_argument("--raw-path", required=True)
    parser.add_argument("--logs-path", required=True, help="Truth/evaluation CSV, e.g. Last10.csv")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--config", dest="config_path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--gamelogs-path", default=str(DEFAULT_GAMLOGS_PATH))
    parser.add_argument("--injury-dir", default=str(DEFAULT_NORMALIZED_INJURY_DIR))
    parser.add_argument("--write-eval", dest="write_eval", action="store_true", default=True)
    parser.add_argument("--no-write-eval", dest="write_eval", action="store_false")
    parser.add_argument("--strict-fidelity", dest="strict_fidelity", action="store_true", default=True)
    parser.add_argument("--no-strict-fidelity", dest="strict_fidelity", action="store_false")
    ns = parser.parse_args()
    return BacktestArgs(
        raw_path=Path(ns.raw_path),
        logs_path=Path(ns.logs_path),
        out_dir=Path(ns.out_dir) if ns.out_dir else None,
        config_path=Path(ns.config_path),
        gamelogs_path=Path(ns.gamelogs_path),
        injury_dir=Path(ns.injury_dir),
        write_eval=bool(ns.write_eval),
        strict_fidelity=bool(ns.strict_fidelity),
    )


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _make_run_id(raw_stem: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"btv2_{ts}__{raw_stem}"


def _resolve_run_dir(args: BacktestArgs) -> Path:
    return args.out_dir if args.out_dir is not None else DEFAULT_OUTPUT_ROOT / _make_run_id(args.raw_path.stem)


def _require_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise BacktestV2Error(f"Missing required {label}: {path}")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _write_meta(meta: BacktestMeta, run_dir: Path) -> Path:
    path = run_dir / "meta.json"
    _write_json(path, asdict(meta))
    return path


def _parse_slate_date_from_raw(raw_path: Path, payload: dict[str, Any]) -> str:
    stem = raw_path.stem
    for tok in stem.split("_"):
        if len(tok) == 8 and tok.isdigit():
            return f"{tok[0:4]}-{tok[4:6]}-{tok[6:8]}"
    data = payload.get("data", []) or []
    for item in data:
        if item.get("type") != "projection":
            continue
        rel = item.get("relationships", {}) or {}
        game_id = (((rel.get("game") or {}).get("data") or {}).get("id"))
        if not game_id:
            continue
        for inc in payload.get("included", []) or []:
            if inc.get("type") == "game" and str(inc.get("id")) == str(game_id):
                start_time = ((inc.get("attributes") or {}).get("start_time"))
                if start_time:
                    return str(start_time)[:10]
    raise BacktestV2Error(f"Unable to resolve slate date from raw: {raw_path}")


def _parse_replay_cutoff_utc(raw_path: Path, payload: dict[str, Any]) -> Optional[datetime]:
    """
    Resolve a cutoff (UTC) for replay gating.
    Order of preference:
      1) explicit pulled_at/pulled_at_utc in payload/meta
      2) file mtime of the raw JSON
      3) filename timestamp interpreted as local (America/Chicago)
      4) None if all fail
    """
    meta = payload.get("meta", {}) or {}

    # 1) Try pulled_at variants (prefer explicit UTC)
    for key in ("pulled_at_utc", "pulled_at", "pulled_at_local"):
        val = meta.get(key) or payload.get(key)
        if not val:
            continue
        try:
            parsed = pd.to_datetime(val, utc=False)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("America/Chicago"))
            return pd.to_datetime(parsed, utc=True).to_pydatetime()
        except Exception:
            continue

    # 2) File mtime (best-effort proxy)
    try:
        mtime = raw_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        pass

    # 3) Filename timestamp as local time (fallback)
    stem = raw_path.stem
    m = re.search(r"(20\d{6})_(\d{6})", stem)
    if m:
        try:
            dt_local = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
            dt_local = dt_local.replace(tzinfo=ZoneInfo("America/Chicago"))
            return dt_local.astimezone(timezone.utc)
        except Exception:
            pass

    return None


def _payload_game_start_map_utc(payload: dict[str, Any]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for inc in payload.get("included", []) or []:
        if inc.get("type") != "game":
            continue
        gid = str(inc.get("id", "")).strip()
        if not gid:
            continue
        start_time = ((inc.get("attributes") or {}).get("start_time"))
        if not start_time:
            continue
        try:
            out[gid] = pd.to_datetime(start_time, utc=True).to_pydatetime()
        except Exception:
            continue
    return out

def _canon_game_id(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s

def _drop_started_games_for_replay(today_df: pd.DataFrame, payload: dict[str, Any], raw_path: Path, meta: BacktestMeta) -> pd.DataFrame:
    cutoff_utc = _parse_replay_cutoff_utc(raw_path, payload)
    if cutoff_utc is None:
        note = "replay_started_game_gate_skipped_no_cutoff"
        meta.notes = f"{meta.notes} | {note}" if meta.notes else note
        return today_df

    if "game_id" not in today_df.columns:
        note = "replay_started_game_gate_skipped_no_game_id"
        meta.notes = f"{meta.notes} | {note}" if meta.notes else note
        return today_df

    start_map = _payload_game_start_map_utc(payload)
    if not start_map:
        note = "replay_started_game_gate_skipped_no_payload_game_starts"
        meta.notes = f"{meta.notes} | {note}" if meta.notes else note
        return today_df

    game_ids = today_df["game_id"].map(_canon_game_id)
    started_ids = {
        _canon_game_id(gid)
        for gid, start_dt in start_map.items()
        if start_dt <= cutoff_utc
    }
    started_ids.discard("")
    if not started_ids:
        note = f"replay_started_game_gate_applied cutoff_utc={cutoff_utc.isoformat()} dropped_rows=0"
        meta.notes = f"{meta.notes} | {note}" if meta.notes else note
        return today_df

    note = (
        f"replay_started_game_gate_debug cutoff_utc={cutoff_utc.isoformat()} "
        f"today_game_ids_sample={','.join(game_ids.drop_duplicates().head(10).tolist())} "
        f"started_ids_sample={','.join(sorted(list(started_ids))[:10])}"
    )
    meta.notes = f"{meta.notes} | {note}" if meta.notes else note

    keep_mask = ~game_ids.isin(started_ids)
    dropped_rows = int((~keep_mask).sum())
    if dropped_rows <= 0:
        note = f"replay_started_game_gate_applied cutoff_utc={cutoff_utc.isoformat()} dropped_rows=0"
        meta.notes = f"{meta.notes} | {note}" if meta.notes else note
        return today_df

    filtered = today_df.loc[keep_mask].copy()
    dropped_games = sorted({gid for gid in game_ids[~keep_mask].tolist() if gid})
    note = (
        f"replay_started_game_gate_applied cutoff_utc={cutoff_utc.isoformat()} "
        f"dropped_rows={dropped_rows} dropped_game_ids={','.join(dropped_games[:20])}"
    )
    meta.notes = f"{meta.notes} | {note}" if meta.notes else note
    return filtered


def _parse_norm_name_dt(path: Path) -> Optional[datetime]:
    stem = path.stem
    try:
        return datetime.strptime(stem, "%Y-%m-%d_%I_%M%p")
    except Exception:
        return None


def _resolve_historical_injury_state(args: BacktestArgs, slate_date: str, run_dir: Path, meta: BacktestMeta) -> tuple[Path, Path]:
    _require_exists(args.injury_dir, "normalized injury directory")
    candidates: list[Path] = []
    for p in sorted(args.injury_dir.glob("*.json")):
        if p.name.lower() == "latest.json":
            continue
        dt = _parse_norm_name_dt(p)
        if dt and dt.strftime("%Y-%m-%d") == slate_date:
            candidates.append(p)
    if not candidates:
        raise BacktestV2Error(f"No normalized injury snapshot found for slate date {slate_date} in {args.injury_dir}")
    selected = sorted(candidates, key=lambda p: (_parse_norm_name_dt(p) or datetime.min, p.name))[-1]
    obj = json.loads(selected.read_text(encoding="utf-8"))
    rows = obj.get("rows", []) or []
    invalidated_players = []
    for row in rows:
        status = str(row.get("status", "")).upper().strip()
        hard_invalid = bool(row.get("hard_invalid", False))
        if hard_invalid or status in HARD_INVALID_STATUSES:
            invalidated_players.append(
                {
                    "team": str(row.get("team", "")).upper().strip(),
                    "player": str(row.get("player", "")).strip(),
                    "status": status or "OUT",
                    "reason": str(row.get("reason", "")).strip(),
                }
            )
    dashboard_dir = run_dir / "dashboard"
    _ensure_dir(dashboard_dir)
    invalidations_path = dashboard_dir / "injury_invalidations_latest.json"
    status_path = dashboard_dir / "status_latest.json"
    _write_json(
        invalidations_path,
        {
            "report_date": obj.get("report_date", slate_date),
            "report_label": obj.get("report_label", ""),
            "pulled_at_local": obj.get("pulled_at_local", ""),
            "invalidated_players_count": len(invalidated_players),
            "invalidated_players": invalidated_players,
            "policy": "backtest_v2_from_normalized",
        },
    )
    _write_json(
        status_path,
        {
            "report_datetime_local": obj.get("pulled_at_local", ""),
            "report_date": obj.get("report_date", slate_date),
            "report_label": obj.get("report_label", ""),
            "norm_path": str(selected.resolve()),
            "generated_by": "backtest_v2",
        },
    )
    meta.injury_snapshot_path = str(selected.resolve())
    meta.injury_invalidations_path = str(invalidations_path.resolve())
    meta.injury_status_path = str(status_path.resolve())
    return invalidations_path, status_path


def _run_rebuild(args: BacktestArgs, payload: dict[str, Any], run_dir: Path, slate_date: str, meta: BacktestMeta) -> Path:
    today_df = run_rebuild(payload=payload, is_replay=True)
    if today_df.empty:
        raise BacktestV2Error("Replay rebuild produced an empty today.csv surface")
    today_df = _drop_started_games_for_replay(today_df=today_df, payload=payload, raw_path=args.raw_path, meta=meta)
    if today_df.empty:
        raise BacktestV2Error("Replay rebuild produced an empty today.csv surface after started-game gating")
    today_path = run_dir / "today.csv"
    today_df.to_csv(today_path, index=False, encoding="utf-8-sig")
    snapshot_dir = run_dir / "snapshots"
    _ensure_dir(snapshot_dir)
    snapshot_path = snapshot_dir / f"replay_{slate_date.replace('-', '')}_{args.raw_path.stem}.csv"
    today_df.to_csv(snapshot_path, index=False, encoding="utf-8-sig")
    meta.today_csv_path = str(today_path.resolve())
    meta.replay_snapshot_path = str(snapshot_path.resolve())
    meta.today_rows = int(len(today_df))
    return today_path


def _validate_today_csv_basic(today_path: Path, meta: BacktestMeta, strict: bool) -> None:
    df = pd.read_csv(today_path)
    if df.empty:
        raise BacktestV2Error("today.csv exists but is empty")
    missing = [c for c in PROP_KEY_COLS if c not in df.columns]
    if missing:
        raise BacktestV2Error(f"today.csv missing prop-key columns: {missing}")

    diag = df.copy()
    for c in PROP_KEY_COLS:
        if c == "line":
            diag[c] = pd.to_numeric(diag[c], errors="coerce")
        else:
            diag[c] = diag[c].astype(str).fillna("").str.strip()

    coarse_dupes = diag.duplicated(subset=PROP_KEY_COLS, keep=False)
    coarse_dup_count = int(coarse_dupes.sum())

    if "projection_id" in df.columns:
        exact_key = ["projection_id"]
    elif "source_projection_id" in df.columns:
        exact_key = ["source_projection_id"]
    else:
        exact_key = PROP_KEY_COLS

    exact = df.copy()
    for c in exact_key:
        if c == "line":
            exact[c] = pd.to_numeric(exact[c], errors="coerce")
        else:
            exact[c] = exact[c].astype(str).fillna("").str.strip()

    exact_dupes = exact.duplicated(subset=exact_key, keep=False)
    meta.duplicate_prop_keys_passed = not bool(exact_dupes.any())

    if strict and exact_dupes.any():
        sample_cols = list(dict.fromkeys(exact_key + PROP_KEY_COLS))
        sample = df.loc[exact_dupes, sample_cols].head(10).to_dict(orient="records")
        raise BacktestV2Error(
            f"today.csv exact-identity duplicates detected on key {exact_key}: {sample}"
        )

    if coarse_dup_count > 0:
        suffix = f"today.csv coarse prop-key duplicate rows observed={coarse_dup_count}; diagnostic only"
        meta.notes = f"{meta.notes} | {suffix}" if meta.notes else suffix

    meta.fidelity_passed = True


def _find_latest_engine_run_dir(out_root: Path) -> Path:
    runs_dir = out_root / "runs"
    _require_exists(runs_dir, "engine runs directory")
    candidates = [p for p in runs_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise BacktestV2Error(f"No engine run directories found under {runs_dir}")
    return sorted(candidates, key=lambda p: p.name)[-1]


def _run_engine_publish(args: BacktestArgs, meta: BacktestMeta, run_dir: Path) -> Path:
    env = os.environ.copy()
    env["ATLAS_CONFIG_PATH"] = str(args.config_path.resolve())
    env["ATLAS_OUT_DIR"] = str(run_dir.resolve())

    today_csv_path = meta.today_csv_path
    injury_invalidations_path = meta.injury_invalidations_path
    injury_status_path = meta.injury_status_path
    if today_csv_path is None or injury_invalidations_path is None or injury_status_path is None:
        raise BacktestV2Error("Missing required replay artifacts for engine publish")

    env["ATLAS_BOARD_PATH"] = str(Path(today_csv_path).resolve())
    env["ATLAS_GAMELOGS_PATH"] = str(args.gamelogs_path.resolve())
    env["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(Path(injury_invalidations_path or "").resolve())
    env["ATLAS_IAEL_STATUS_PATH"] = str(Path(injury_status_path or "").resolve())

    subprocess.run([sys.executable, "-m", "Atlas.engine.main"], check=True, env=env)

    engine_run_dir = _find_latest_engine_run_dir(run_dir)
    meta.engine_run_dir = str(engine_run_dir.resolve())
    scored = engine_run_dir / "scored_legs.csv"
    deduped = engine_run_dir / "scored_legs_deduped.csv"
    _require_exists(scored, "scored_legs.csv")
    _require_exists(deduped, "scored_legs_deduped.csv")
    meta.scored_legs_path = str(scored.resolve())
    meta.scored_legs_deduped_path = str(deduped.resolve())
    meta.scored_rows = int(len(pd.read_csv(scored)))
    meta.scored_deduped_rows = int(len(pd.read_csv(deduped)))
    return engine_run_dir


def _actual_from_row(stat: str, row: Any) -> float:
    stat = str(stat or "").upper().strip()
    def g(name: str) -> float:
        v = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        return float(v) if pd.notna(v) else float("nan")
    pts = g("pts")
    reb = g("reb")
    astv = g("ast")
    fg3m = g("fg3m")
    blk = g("blk")
    stl = g("stl")
    if stat == "PTS":
        return pts
    if stat == "REB":
        return reb
    if stat == "AST":
        return astv
    if stat in {"FG3M", "3PM", "3PTM"}:
        return fg3m
    if stat == "PR":
        return pts + reb if pd.notna(pts) and pd.notna(reb) else float("nan")
    if stat == "PA":
        return pts + astv if pd.notna(pts) and pd.notna(astv) else float("nan")
    if stat == "RA":
        return reb + astv if pd.notna(reb) and pd.notna(astv) else float("nan")
    if stat == "PRA":
        return pts + reb + astv if pd.notna(pts) and pd.notna(reb) and pd.notna(astv) else float("nan")
    if stat in {"BS", "BLKS+STLS"}:
        return blk + stl if pd.notna(blk) and pd.notna(stl) else float("nan")
    return float("nan")


def _compute_hit(actual: float, line: float, direction: str) -> float:
    if pd.isna(actual) or pd.isna(line):
        return float("nan")
    d = str(direction or "").upper().strip()
    if d == "OVER":
        return 1.0 if actual > line else 0.0 if actual < line else float("nan")
    if d == "UNDER":
        return 1.0 if actual < line else 0.0 if actual > line else float("nan")
    return float("nan")


_EVAL_PROBABILITY_COLUMNS = (
    "p",
    "p_role",
    "p_close",
    "p_close_raw",
    "p_close_role",
    "p_adj_pre_under_relief",
    "p_adj",
    "p_for_cal",
    "p_cal",
)


def _add_eval_score_columns(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.copy()
    line = pd.to_numeric(scored.get("line", pd.Series(float("nan"), index=scored.index)), errors="coerce")
    actual = pd.to_numeric(scored.get("actual", pd.Series(float("nan"), index=scored.index)), errors="coerce")
    scored["actual_delta"] = actual - line
    scored["actual_abs_delta"] = (actual - line).abs()

    if "hit" in scored.columns:
        hit = pd.to_numeric(scored["hit"], errors="coerce")
        for col in _EVAL_PROBABILITY_COLUMNS:
            if col not in scored.columns:
                continue
            pred = pd.to_numeric(scored[col], errors="coerce").clip(0.0, 1.0)
            error_col = f"{col}_error"
            brier_col = f"brier_{col}"
            scored[error_col] = pred - hit
            scored[brier_col] = scored[error_col] ** 2
    return scored


def _write_eval_legs(args: BacktestArgs, meta: BacktestMeta, engine_run_dir: Path) -> Path:
    deduped = pd.read_csv(engine_run_dir / "scored_legs_deduped.csv")
    logs = pd.read_csv(args.logs_path)
    if "player" not in logs.columns:
        raise BacktestV2Error(f"Truth CSV missing player column: {args.logs_path}")
    if "game_date" not in logs.columns:
        raise BacktestV2Error(f"Truth CSV missing game_date column: {args.logs_path}")

    deduped = deduped.copy()
    logs = logs.copy()

    deduped["player_board"] = deduped.get("player", pd.Series("", index=deduped.index)).astype(str)
    deduped["player_key"] = deduped["player_board"].map(share_name_key)

    logs = logs.rename(columns={"player": "player_gamelog"})
    logs["player_key"] = logs["player_gamelog"].astype(str).map(share_name_key)
    deduped["game_date"] = pd.to_datetime(deduped["game_date"], errors="coerce").dt.normalize()
    logs["game_date"] = pd.to_datetime(logs["game_date"], errors="coerce").dt.normalize()
    for col in ["pts", "reb", "ast", "fg3m", "blk", "stl"]:
        if col in logs.columns:
            logs[col] = pd.to_numeric(logs[col], errors="coerce")

    merged = deduped.merge(logs, on=["player_key", "game_date"], how="left", suffixes=("", "_log"))
    merged["player"] = merged.get("player_gamelog", merged.get("player_board"))
    merged["actual"] = [
        _actual_from_row(stat, rec)
        for stat, rec in zip(merged.get("stat", pd.Series("", index=merged.index)), merged.to_dict(orient="records"))
    ]
    merged["hit"] = [
        _compute_hit(a, l, d)
        for a, l, d in zip(
            merged["actual"],
            pd.to_numeric(merged.get("line", pd.Series(float("nan"), index=merged.index)), errors="coerce"),
            merged.get("direction", pd.Series("", index=merged.index)),
        )
    ]
    merged["push"] = merged["hit"].isna().astype(int)
    eval_df = _add_eval_score_columns(merged[merged["hit"].notna()].copy())
    eval_path = engine_run_dir / "eval_legs.csv"
    eval_df.to_csv(eval_path, index=False, encoding="utf-8-sig")
    meta.eval_legs_path = str(eval_path.resolve())
    meta.eval_rows = int(len(eval_df))
    return eval_path


def main() -> int:
    args = parse_args()
    _require_exists(args.raw_path, "raw JSON")
    _require_exists(args.logs_path, "logs/truth CSV")
    _require_exists(args.config_path, "config file")
    _require_exists(args.gamelogs_path, "gamelogs CSV")

    run_dir = _resolve_run_dir(args)
    _ensure_dir(run_dir)
    meta = BacktestMeta(
        raw_path=str(args.raw_path.resolve()),
        raw_stem=args.raw_path.stem,
        logs_path=str(args.logs_path.resolve()),
        config_path=str(args.config_path.resolve()),
        gamelogs_path=str(args.gamelogs_path.resolve()),
        injury_dir=str(args.injury_dir.resolve()),
        run_dir=str(run_dir.resolve()),
        created_at_utc=_utc_now_iso(),
        notes="Backtest v2 full best-effort runner: rebuild -> verified replay board -> engine publish -> eval legs.",
    )
    try:
        payload = json.loads(args.raw_path.read_text(encoding="utf-8"))
        slate_date = _parse_slate_date_from_raw(args.raw_path, payload)
        meta.slate_date = slate_date
        _resolve_historical_injury_state(args, slate_date, run_dir, meta)
        today_path = _run_rebuild(args, payload, run_dir, slate_date, meta)
        _validate_today_csv_basic(today_path, meta, args.strict_fidelity)
        engine_run_dir = _run_engine_publish(args, meta, run_dir)
        if args.write_eval:
            _write_eval_legs(args, meta, engine_run_dir)
    finally:
        _write_meta(meta, run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
