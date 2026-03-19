from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from Atlas.stages.rebuild.rebuild_today import run_rebuild


# ----------------------------
# Repo root discovery
# ----------------------------
def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return start.resolve()


# ----------------------------
# Time helpers (match your JSONL "ts" style)
# ----------------------------
def _utc_stamp() -> str:
    # For folder names / scenario timestamp
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_ts_iso_z() -> str:
    # Match: 2026-02-26T15:46:03.069040Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ----------------------------
# Raw snapshot loader
# ----------------------------
def _load_payload(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        if "data" in obj and "included" in obj:
            return obj  # direct PrizePicks payload
        if "payload" in obj and isinstance(obj["payload"], dict):
            return obj["payload"]
        if "prizepicks" in obj and isinstance(obj["prizepicks"], dict):
            return obj["prizepicks"]
    raise ValueError(f"Unsupported raw snapshot JSON schema: {path}")


# ----------------------------
# Minimal inputs writer
# ----------------------------
def _write_min_inputs_from_payload(*, payload: Dict[str, Any], data_dir: Path, is_replay: bool) -> Path:
    """
    Build minimal CSV artifacts needed by the current engine wiring from a raw snapshot payload.
    JSON-first: user provides JSON; we generate plumbing artifacts inside the sandbox workspace.
    """
    board_dir = data_dir / "board"
    input_dir = data_dir / "input"
    raw_dir = data_dir / "raw"

    board_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    df = run_rebuild(payload=payload, is_replay=is_replay)

    today_path = board_dir / "today.csv"
    df.to_csv(today_path, index=False, encoding="utf-8-sig")

    roster_map = df[["player", "team"]].copy().dropna(subset=["player"]).drop_duplicates()
    roster_map_path = input_dir / "roster_map.csv"
    roster_map.to_csv(roster_map_path, index=False, encoding="utf-8-sig")

    slate_path = input_dir / "slate.csv"
    pd.DataFrame(columns=["game_date", "home_team", "away_team"]).to_csv(slate_path, index=False, encoding="utf-8-sig")

    return today_path


def _seed_dashboard_file(*, repo_root: Path, scenario_id: str, out_dir: Path, filename: str) -> Path | None:
    """Copy a matching dashboard artifact into the sandbox output before engine launch."""
    candidates = [
        repo_root / "outputtelem" / "role_off_full_20260318" / "runs" / scenario_id / "dashboard" / filename,
        repo_root / "outputtelem" / "role_off_full_20260318" / scenario_id / "dashboard" / filename,
        repo_root / "outputtelem" / scenario_id / "dashboard" / filename,
    ]

    dst = out_dir / "dashboard" / filename
    for src in candidates:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return dst

    return None


# ----------------------------
# Fingerprint helpers
# ----------------------------
def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _csv_rows(path: Path) -> Optional[int]:
    if not path.exists() or not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
        return int(len(df))
    except Exception:
        return None


def _emit_jsonl(fp, obj: Dict[str, Any]) -> None:
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _copy2(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


# ----------------------------
# Find engine run dir inside OUT_DIR/runs/<RUNID>
# ----------------------------
def _find_engine_run_dir(out_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    runs_root = out_dir / "runs"
    if not runs_root.exists():
        return None, None
    candidates = [p for p in runs_root.iterdir() if p.is_dir()]
    if not candidates:
        return None, None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    return newest, newest.name


def _ensure_contract_artifacts_present(*, engine_run_dir: Path, data_dir: Path) -> Dict[str, Path]:
    """
    Contract artifacts we want validator to see (labels):
      - fetch_board.csv
      - today.csv
      - scored_legs.csv
      - scored_legs_deduped.csv

    scored_legs*.csv are expected to be produced by engine in engine_run_dir.
    today.csv might be only in data_dir/board; we copy it into engine_run_dir for consistency.
    fetch_board.csv may not exist; we backfill it as a copy of today.csv.
    """
    engine_run_dir.mkdir(parents=True, exist_ok=True)

    scored = engine_run_dir / "scored_legs.csv"
    scored_d = engine_run_dir / "scored_legs_deduped.csv"

    today_in_run = engine_run_dir / "today.csv"
    today_src = data_dir / "board" / "today.csv"
    if not today_in_run.exists() and today_src.exists():
        shutil.copy2(today_src, today_in_run)

    fetch_in_run = engine_run_dir / "fetch_board.csv"
    if not fetch_in_run.exists():
        if today_in_run.exists():
            shutil.copy2(today_in_run, fetch_in_run)
        elif today_src.exists():
            shutil.copy2(today_src, fetch_in_run)

    return {
        "fetch_board.csv": fetch_in_run,
        "today.csv": today_in_run,
        "scored_legs.csv": scored,
        "scored_legs_deduped.csv": scored_d,
    }


def _write_sandbox_audit(
    *,
    repo_root: Path,
    run_id: str,  # IMPORTANT: this should be engine_run_id
    scenario_id: str,
    raw_path: Path,
    analysis_root: Path,
    out_dir: Path,
    engine_run_dir: Path,
    data_dir: Path,
) -> Path:
    """
    Writes:
      .atlas_audit/sandbox/<RUNID>/events_<RUNID>.jsonl
      .atlas_audit/sandbox/<RUNID>/flat/{fetch_board,today,scored_legs,scored_legs_deduped}.csv
      .atlas_audit/events_<RUNID>.jsonl  (root copy so validate_artifacts can discover reliably)
    """
    audit_root = repo_root / ".atlas_audit"
    sandbox_root = audit_root / "sandbox" / run_id
    flat_dir = sandbox_root / "flat"
    flat_dir.mkdir(parents=True, exist_ok=True)

    events_path = sandbox_root / f"events_{run_id}.jsonl"
    root_events_path = audit_root / f"events_{run_id}.jsonl"

    artifacts = _ensure_contract_artifacts_present(engine_run_dir=engine_run_dir, data_dir=data_dir)

    # Flat copies of the contract artifacts
    for label, src in artifacts.items():
        _copy2(src, flat_dir / label)

    # Emit events (match your current schema: ts/authority/event/...)
    ts = _utc_ts_iso_z()
    with events_path.open("w", encoding="utf-8") as f:
        _emit_jsonl(
            f,
            {
                "ts": ts,
                "authority": "sandbox",
                "event": "run_start",
                "run_id": run_id,
                "scenario_id": scenario_id,
                "raw_path": str(raw_path),
                "analysis_root": str(analysis_root),
                "out_dir": str(out_dir),
                "engine_run_dir": str(engine_run_dir),
            },
        )

        for label, path in artifacts.items():
            exists = path.exists()
            _emit_jsonl(
                f,
                {
                    "ts": ts,
                    "authority": "sandbox",
                    "event": "artifact_fingerprint",
                    "run_id": run_id,
                    "label": label,
                    "path": str(path),
                    "exists": bool(exists),
                    "sha256": _sha256_file(path) if exists else None,
                    "csv_rows": _csv_rows(path) if exists else None,
                },
            )

        # Also fingerprint the flat copies (optional but useful for your manual debugging)
        for label, _src in artifacts.items():
            flat_label = f"flat/{label}"
            flat_path = flat_dir / label
            exists = flat_path.exists()
            _emit_jsonl(
                f,
                {
                    "ts": ts,
                    "authority": "sandbox",
                    "event": "artifact_fingerprint",
                    "run_id": run_id,
                    "label": flat_label,
                    "path": str(flat_path),
                    "exists": bool(exists),
                    "sha256": _sha256_file(flat_path) if exists else None,
                    "csv_rows": _csv_rows(flat_path) if exists else None,
                },
            )

        _emit_jsonl(
            f,
            {
                "ts": ts,
                "authority": "sandbox",
                "event": "run_end",
                "run_id": run_id,
                "status": "ok",
                "exit_code": 0,
            },
        )

    # Root copy so validator can locate it easily
    root_events_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(events_path, root_events_path)

    return events_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Atlas sandbox replay (Scenario sandbox): JSON snapshot baseline.")
    ap.add_argument("raw_snapshot_json", help="Path to a saved raw PrizePicks snapshot JSON.")
    ap.add_argument("--scenario-id", default="", help="Optional scenario id (used for archives folder naming).")
    ap.add_argument("--asof-date", default="", help="Optional YYYY-MM-DD for labeling (not required).")
    args = ap.parse_args()

    repo_root = find_repo_root(Path(__file__).parent)
    raw_path = Path(args.raw_snapshot_json).expanduser().resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)

    scenario_id = (args.scenario_id or raw_path.stem).replace(" ", "_").strip()
    ts = _utc_stamp()

    analysis_root = repo_root / "archives" / "bundles" / scenario_id / "analysis" / ts
    workspace = analysis_root / "workspace"
    data_dir = workspace / "data"
    # Sandbox outputs
    out_dir = (repo_root / "data" / "output" / "sandbox_runs" / scenario_id / ts).resolve()
    logs_dir = analysis_root / "logs"

    data_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    payload = _load_payload(raw_path)

    # Store raw snapshot in workspace for provenance
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)
    (data_dir / "raw" / raw_path.name).write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")

    _write_min_inputs_from_payload(payload=payload, data_dir=data_dir, is_replay=True)
    seeded_invalidations = _seed_dashboard_file(
        repo_root=repo_root,
        scenario_id=scenario_id,
        out_dir=out_dir,
        filename="injury_invalidations_latest.json",
    )
    if seeded_invalidations is not None:
        print(f"[REPLAY] seeded dashboard invalidations: {seeded_invalidations}")

    seeded_status = _seed_dashboard_file(
        repo_root=repo_root,
        scenario_id=scenario_id,
        out_dir=out_dir,
        filename="status_latest.json",
    )
    if seeded_status is not None:
        print(f"[REPLAY] seeded dashboard status: {seeded_status}")

    repo_gamelogs = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    if not repo_gamelogs.is_file():
        print(f"[REPLAY] Missing repo gamelogs cache: {repo_gamelogs}")
        return 2

    env = os.environ.copy()
    env["ATLAS_DATA_DIR"] = str(data_dir)
    env["ATLAS_OUT_DIR"] = str(out_dir)
    env["ATLAS_GAMELOGS_PATH"] = str(repo_gamelogs)

    cmd = [sys.executable, "-m", "Atlas.engine.main"]
    stdout_path = logs_dir / "engine_stdout.txt"
    stderr_path = logs_dir / "engine_stderr.txt"

    print(f"[REPLAY] scenario_id={scenario_id}")
    print(f"[REPLAY] analysis_root={analysis_root}")
    print(f"[REPLAY] running: {' '.join(cmd)}")

    p = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    stdout_path.write_text(p.stdout or "", encoding="utf-8")
    stderr_path.write_text(p.stderr or "", encoding="utf-8")

    print(f"[REPLAY] exit_code={p.returncode}")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").splitlines()[-60:])
        print("[REPLAY] engine stderr tail:")
        print(tail)
        return p.returncode

    # IMPORTANT: align audit run_id with engine run dir name (not the sandbox ts)
    engine_run_dir, engine_run_id = _find_engine_run_dir(out_dir)
    if engine_run_dir is None or engine_run_id is None:
        print(f"[REPLAY] ERROR: engine produced no runs under {out_dir / 'runs'}")
        return 3

    events_path = _write_sandbox_audit(
        repo_root=repo_root,
        run_id=engine_run_id,
        scenario_id=scenario_id,
        raw_path=raw_path,
        analysis_root=analysis_root,
        out_dir=out_dir,
        engine_run_dir=engine_run_dir,
        data_dir=data_dir,
    )

    print("[REPLAY] OK")
    print(f"[REPLAY] engine_run_id={engine_run_id}")
    print(f"[REPLAY] sandbox events: {events_path}")
    print(f"[REPLAY] root events:    {repo_root / '.atlas_audit' / f'events_{engine_run_id}.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())