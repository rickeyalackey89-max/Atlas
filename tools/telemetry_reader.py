#!/usr/bin/env python
"""
tools/telemetry_reader.py

Telemetry/backtest runner wrapper (archives-only).

Goal:
- Provide a single, stable "tool" entrypoint for telemetry analysis.
- Ensure ALL outputs land under archives/bundles/.../analysis/.
- Avoid modifying core engine logic.

Implementation:
- Delegates to scripts/dev/analysis/backtest/backtest_role_layer_ctx.py
- Sets ATLAS_TELEMETRY_REPORT_ROOT to the provided archives analysis directory
  so the underlying script writes there (not tools/reports).

Contract:
- REPLAY-only in practice (it should run against historical artifacts).
- NO network.
"""
from __future__ import annotations

import argparse
import re
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _validate_out_root(repo_root: Path, p: Path) -> tuple[str, Path]:
    """
    Validate --out-dir root.

    Allowed roots:
      1) <repo_root>/data/archives               (legacy)
    2) <repo_root>/data/telemetry/replay_runs  (telemetry replay)

    Returns:
      (mode, resolved_path) where mode is "archives" or "replay_runs".
    """
    p = p.expanduser().resolve()

    archives_root = (repo_root / "data" / "archives").resolve()
    replay_root = (repo_root / "data" / "telemetry" / "replay_runs").resolve()

    def _norm(x: Path) -> str:
        return str(x).replace("\\", "/").lower()

    out_s = _norm(p)
    if out_s.startswith(_norm(archives_root)):
        p.mkdir(parents=True, exist_ok=True)
        return "archives", p
    if out_s.startswith(_norm(replay_root)):
        p.mkdir(parents=True, exist_ok=True)
        return "replay_runs", p

    raise RuntimeError(
        f"--out-dir must be under either {archives_root} or {replay_root}. Got: {p}"
    )


def _infer_date_window_from_snapshots(repo_root: Path) -> tuple[str, str]:
    """Infer (start,end) YYYYMMDD window from snapshot filenames under data/board/snapshots."""
    snap_dir = repo_root / "data" / "board" / "snapshots"
    if not snap_dir.exists():
        raise RuntimeError(f"Snapshot directory not found for date inference: {snap_dir}")

    dates: list[str] = []
    rx = re.compile(r"(?:today|board|snapshot)[_-](\d{8})")
    for p in snap_dir.glob("*"):
        mm = rx.search(p.name)
        if mm:
            dates.append(mm.group(1))
    if not dates:
        raise RuntimeError(f"Could not infer dates: no snapshot files matched under {snap_dir}")

    dates.sort()
    return dates[0], dates[-1]


def _get_raw_json_files(raw_dir: Path, limit: int) -> list[Path]:
    """Glob prizepicks_*.json files, sort by mtime (newest first), return up to limit."""
    if not raw_dir.exists():
        raise RuntimeError(f"Raw directory not found: {raw_dir}")
    
    files = [p for p in raw_dir.glob("prizepicks_*.json") if not p.name.startswith("prizepicks_20260312_")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _parse_date_from_filename(p: Path):
    """Parse YYYYMMDD from board snapshot filename and return a date (or None)."""
    m = re.search(r"(?:today|board|snapshot)[_-](\d{8})", p.name, re.I)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except Exception:
        return None

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument(
        "--out-dir",
        required=True,
        help=(
            "Output root under either data/archives (legacy) or data/telemetry/replay_runs "
            "(telemetry replay)."
        ),
    )

    # Date selection
    ap.add_argument("--days", type=int, default=7, help="Bulk mode: last N calendar days ending today (default: 7).")
    ap.add_argument("--date", default=None, help="Forensic day mode: YYYYMMDD (runs that single day).")
    ap.add_argument("--start", default=None, help="Bulk mode override: start YYYYMMDD.")
    ap.add_argument("--end", default=None, help="Bulk mode override: end YYYYMMDD.")
    ap.add_argument(
        "--snapshot",
        action="append",
        default=None,
        help="Forensic snapshot mode: today_YYYYMMDD_HHMMSS.csv (bare filename) or full path. Repeatable.",
    )

    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    mode, out_root = _validate_out_root(repo_root, Path(args.out_dir))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Flatten for replay_runs: <out_root>/<stamp>/...
    # Legacy archives layout: <out_root>/backtest_telemetry/<stamp>/...
    if mode == "replay_runs":
        out_dir = out_root / stamp
    else:
        out_dir = out_root / "backtest_telemetry" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve selection mode priority:
    # 1) --snapshot (exact files, repeatable)
    # 2) --date (single calendar day)
    # 3) --start/--end (explicit window)
    # 4) --days (last N days ending today)

    snapshot_args = args.snapshot or []

    # Helper: resolve bare filename to snapshot dir
    snapshot_dir = (repo_root / "data" / "board" / "snapshots").resolve()

    def _resolve_snapshot(s: str) -> Path:
        p = Path(s)
        if p.is_absolute() or str(p).startswith(".") or ("/" in s) or ("\\" in s):
            rp = p.expanduser().resolve()
        else:
            rp = (snapshot_dir / s).expanduser().resolve()
        if not rp.exists():
            raise RuntimeError(f"Snapshot not found: {s} -> {rp}")
        return rp

    resolved_snaps: list[Path] = []
    if snapshot_args:
        resolved_snaps = [_resolve_snapshot(s) for s in snapshot_args]

    if resolved_snaps:
        # Snapshot-forensic mode: run exactly the resolved snapshot file(s)
        start = None
        end = None
    elif args.date:
        # Single-day mode
        start = args.date
        end = args.date
    else:
        # Range / bulk mode
        start = args.start
        end = args.end
        if not start or not end:
            # Default: last N calendar days ending today (local date)
            today = datetime.now().date()
            days = int(args.days or 7)
            if days < 1:
                raise RuntimeError("--days must be >= 1")
            start_d = today - timedelta(days=days - 1)
            start = start_d.strftime("%Y%m%d")
            end = today.strftime("%Y%m%d")

    # At this point, start/end are either both strings (bulk/date mode) or both None (snapshot mode).
    if (start is None) != (end is None):
        raise RuntimeError("Internal error: start/end mismatch")

    script = repo_root / "scripts" / "dev" / "analysis" / "backtest" / "backtest_role_layer_ctx.py"
    if not script.exists():
        raise RuntimeError(f"Telemetry script not found: {script}")

    env = os.environ.copy()
    env["ATLAS_TELEMETRY_REPORT_ROOT"] = str(out_dir)

    # Build list of snapshots used (for transparency / bundling)
    used_snaps: list[Path] = []
    if resolved_snaps:
        used_snaps = resolved_snaps
    else:
        # Mirror backtest script's snapshot selection rules for manifest
        if start is None or end is None:
            raise RuntimeError("Internal error: manifest date-window requires start/end")
        snap_glob = (repo_root / "data" / "board" / "snapshots").glob("today_*.csv")
        for p in snap_glob:
            dt = _parse_date_from_filename(p)
            if dt is None:
                continue
            yyyymmdd = dt.strftime("%Y%m%d")
            if start <= yyyymmdd <= end:
                used_snaps.append(p.resolve())
        used_snaps.sort()

    manifest = out_dir / "used_snapshots.txt"
    manifest.write_text("\n".join(str(p) for p in used_snaps) + ("\n" if used_snaps else ""), encoding="utf-8")

    if not used_snaps:
        print(f"No board snapshots found for selection window. Nothing to replay.")
        print(f"Wrote telemetry to: {out_dir} (manifest empty)")
        return 0

    if resolved_snaps:
        cmd = [sys.executable, str(script)]
        for p in resolved_snaps:
            cmd += ["--snapshot", str(p)]
    else:
        if start is None or end is None:
            raise RuntimeError("Internal error: bulk/date mode requires start/end")
        cmd = [sys.executable, str(script), "--start", str(start), "--end", str(end)]
    print("Running:", " ".join(cmd))
    rc = subprocess.run(cmd, cwd=str(repo_root), env=env).returncode
    if rc != 0:
        raise RuntimeError(f"Telemetry runner failed. ExitCode={rc}")

    print(f"Wrote telemetry to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())