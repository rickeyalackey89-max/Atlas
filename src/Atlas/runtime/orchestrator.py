from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from Atlas.runtime.bundles import write_bundle_zip
from Atlas.runtime.obs import RunContext, StageTimer, create_run_context, emit_event, sha256_file
from Atlas.runtime.paths import find_repo_root
from Atlas.stages.engine_boundary.engine_plan import EnginePlan
from Atlas.stages.engine_boundary.new_engine_plan import build_new_engine_plan

logger = logging.getLogger(__name__)

PROJECT_ROOT = find_repo_root(Path(__file__))
TOOLS_DIR = PROJECT_ROOT / "tools"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
RUNS_DIR = OUTPUT_DIR / "runs"


# -----------------------------
# Helpers
# -----------------------------

@dataclass(frozen=True)
class CmdResult:
    ok: bool
    returncode: int
    cmd: List[str]
    stdout: str = ""
    stderr: str = ""


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"[{title}] {_now_stamp()}")
    print("=" * 72)


def _py() -> str:
    return sys.executable


def _truncate(s: str, limit: int = 4000) -> str:
    s = s or ""
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n...[truncated {len(s) - limit} chars]"


def _csv_rowcount_fast(path: Path) -> Optional[int]:
    """Best-effort CSV data row count (excluding header). Returns None if missing/unreadable."""
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            header = f.readline()
            if not header:
                return 0
            n = 0
            for line in f:
                if line.strip():
                    n += 1
            return n
    except Exception:
        return None


def _artifact_fingerprint(ctx: RunContext, label: str, path: Path) -> None:
    """
    Lightweight artifact health metric (additive only)
    - exists
    - sha256 (if exists)
    - csv_rows (if .csv)
    """
    exists = path.exists()
    digest = sha256_file(path) if exists else None
    rows = _csv_rowcount_fast(path) if (exists and path.suffix.lower() == ".csv") else None
    emit_event(
        ctx,
        "artifact_fingerprint",
        label=label,
        path=str(path),
        exists=exists,
        sha256=digest,
        csv_rows=rows,
        size_bytes=(path.stat().st_size if exists else None),
    )


def _csv_has_data_rows(path: Path) -> bool:
    """True if CSV exists and appears to have at least 1 data row."""
    if not path.exists():
        return False
    if path.stat().st_size == 0:
        return False

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            header = f.readline()
            second = f.readline()
    except Exception:
        return False

    if not header or not second:
        return False
    if not second.strip():
        return False
    return True


def _detect_guardrail(stdout: str, stderr: str) -> Tuple[bool, Optional[str]]:
    """
    Detect intentional guardrail stops by text (no exit-code change).
    Conservative and additive only.
    """
    hay = (stdout or "") + "\n" + (stderr or "")
    low = hay.lower()

    patterns = [
        "guardrail",
        "fatal: iael",
        "[iael][fatal]",
        "iael status missing report_date",
        "cannot prove live iael today",
        "production run aborted",
        "no injury report found",
        "report time could not be parsed",
        "dead period",
        "cannot be pulled",
        "could not be pulled",
        "no slate",
        "0 projections",
        "freshness",
        "stale",
        "gamelogs are stale",
        "exception: ❌ gamelogs are stale",
    ]
    for p in patterns:
        if p in low:
            return True, p
    return False, None


def assert_fresh(path: Path, *, max_age_hours: int, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} missing: {path}")
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if age > timedelta(hours=max_age_hours):
        raise RuntimeError(f"{label} is stale ({age}). Not updated this run: {path}")


def assert_fresh_file(path: Path, *, max_age_hours: int, label: str) -> None:
    # Kept for backward compatibility (some call sites may use this name)
    assert_fresh(path, max_age_hours=max_age_hours, label=label)


def write_daily_games_logged_csv(*, repo_root: Path, game_date: str, run_id: str) -> Path:
    """
    Materialize a daily 'games logged' CSV from rolling nba_gamelogs.csv.

    Behavior:
      - Try the run's `game_date` first (slate date)
      - If zero rows exist (common pre-games), fall back to latest available game_date in the store

    Output:
      data/telemetry/games_logged/YYYY-MM-DD_games_logged.csv
    """
    import pandas as pd

    src = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    if not src.exists():
        raise FileNotFoundError(f"Missing gamelog store: {src}")

    out_dir = repo_root / "data" / "telemetry" / "games_logged"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(src, low_memory=False)

    required = ["game_date", "player", "team", "opp"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"nba_gamelogs.csv missing cols {missing}. Have: {list(df.columns)}")

    # Normalize + filter valid dates
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["game_date"].notna()].copy()

    requested = str(game_date).strip()
    day = df[df["game_date"] == requested].copy()

    used_date = requested
    if len(day) == 0:
        used_date = str(df["game_date"].max())
        day = df[df["game_date"] == used_date].copy()

    day["run_id"] = run_id
    day["slate_game_date"] = requested
    day["games_logged_date"] = used_date

    day = day.sort_values([c for c in ["player", "team", "opp"] if c in day.columns])

    out_path = out_dir / f"{used_date}_games_logged.csv"
    day.to_csv(out_path, index=False)
    return out_path


def run_refresh_nba_gamelogs(repo_root: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    """
    Runs tools/refresh_nba_gamelogs.py as a subprocess (automation-safe).
    - Uses a HARD wall-clock timeout so the orchestrator never gets "stuck".
    - Converts TimeoutExpired into CalledProcessError so run_today can log e.stdout/e.stderr.
    IMPORTANT: do NOT pass --fail-if-stale in automation.
    """
    script = repo_root / "tools" / "refresh_nba_gamelogs.py"

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "refresh_nba_gamelogs.py"),
        "--repo-root", str(PROJECT_ROOT),
        "--run-id", run_id,
        "--days-back", "1",
        "--timeout-sec", "15",
        "--retries", "2",
        "--backoff-sec", "1.0",
    ]
    if os.getenv("ATLAS_GAMELOGS_START_FRESH", "0") == "1":
        cmd.append("--start-fresh")

    def _to_text(x) -> str:
        if x is None:
            return ""
        if isinstance(x, (bytes, bytearray)):
            return x.decode("utf-8", errors="replace")
        return str(x)

    try:
        # HARD wall-clock limit for the whole refresh job
        return subprocess.run(
            cmd,
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,  # ✅ keep short so model isn't blocked
        )
    except subprocess.TimeoutExpired as e:
        out = _to_text(getattr(e, "stdout", None))
        err = _to_text(getattr(e, "stderr", None)) + "\n[orchestrator] refresh_nba_gamelogs timed out and was terminated."
        raise subprocess.CalledProcessError(
            returncode=124,
            cmd=cmd,
            output=out,
            stderr=err,
        )

# -----------------------------
# Subprocess execution (TEE + capture)
# -----------------------------

def _run(
    cmd: List[str],
    title: str,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> CmdResult:
    print("\n" + "=" * 72)
    print(f"[{title}] {_now_stamp()}")
    print("CMD:", " ".join(cmd))
    print("=" * 72)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    ok = (p.returncode == 0)
    if check and not ok:
        raise SystemExit(p.returncode)
    return CmdResult(ok=ok, returncode=p.returncode, cmd=cmd)


def _tee_stream_to_console_and_buffer(stream, buffer: list[str], prefix: str = "") -> None:
    """Reads a subprocess stream line-by-line, prints it live, and appends to buffer."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            buffer.append(line)
            if prefix:
                print(prefix + line, end="")
            else:
                print(line, end="")
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_plan(plan: EnginePlan, title: str, check: bool = True) -> CmdResult:
    """
    Executes an EnginePlan.
    EnginePlan contract:
      cmd_list = [plan.exe] + plan.argv
    plan.env is merged onto os.environ.
    """
    from shutil import which

    if getattr(plan, "kind", None) != "subprocess":
        raise RuntimeError(f"Unsupported EnginePlan.kind: {getattr(plan, 'kind', None)}")

    cmd_list: list[str] = [str(plan.exe)] + list(plan.argv)
    cwd = str(plan.cwd) if getattr(plan, "cwd", None) is not None else None

    env = os.environ.copy()
    plan_env = getattr(plan, "env", None)
    if isinstance(plan_env, dict) and plan_env:
        env.update({str(k): str(v) for k, v in plan_env.items() if v is not None})

    if os.getenv("ATLAS_DEBUG_SUBPROCESS", "") == "1":
        print("\n" + "=" * 72)
        print(f"[{title}] {_now_stamp()}")
        print("CMDLINE:", plan.to_cmdline())
        print("CMDLIST:", cmd_list)
        print("CWD:", cwd)
        keys = ["PYTHONPATH", "PATH", "VIRTUAL_ENV", "CONDA_PREFIX"]
        env_snip = {k: env.get(k) for k in keys if env.get(k) is not None}
        print("ENV:", env_snip)
        print("=" * 72)

    try:
        p = subprocess.Popen(
            cmd_list,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError:
        exe = cmd_list[0] if cmd_list else None
        exe_exists = Path(exe).exists() if exe else None
        exe_which = which(exe) if exe else None
        print("[ERROR] subprocess launch failed (FileNotFoundError / WinError 2)")
        print(f"[ERROR] exe={exe!r} exe_exists={exe_exists} which={exe_which!r}")
        print(f"[ERROR] full_cmdlist={cmd_list}")
        raise

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    t_out = threading.Thread(
        target=_tee_stream_to_console_and_buffer,
        args=(p.stdout, stdout_chunks, ""),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_tee_stream_to_console_and_buffer,
        args=(p.stderr, stderr_chunks, ""),
        daemon=True,
    )

    t_out.start()
    t_err.start()

    returncode = p.wait()
    t_out.join(timeout=2.0)
    t_err.join(timeout=2.0)

    ok = (returncode == 0)
    if check and not ok:
        raise SystemExit(returncode)

    return CmdResult(
        ok=ok,
        returncode=returncode,
        cmd=cmd_list,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


# -----------------------------
# Pipeline steps
# -----------------------------

def _extra_env_for_raw(raw_path: Optional[str | Path]) -> dict[str, str]:
    env: dict[str, str] = {}
    if raw_path:
        env["ATLAS_REPLAY_RAW"] = str(Path(raw_path))
    return env


def fetch_raw_only(*, raw_path: Optional[str | Path] = None, max_attempts: int = 3, sleep_s: float = 1.0) -> None:
    script = TOOLS_DIR / "fetch_apis.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    extra_env = _extra_env_for_raw(raw_path)

    last_err: Optional[int] = None
    for i in range(1, max_attempts + 1):
        if raw_path:
            _banner(f"REPLAY RAW LOAD (attempt {i}/{max_attempts})")
        else:
            _banner(f"FETCH (fresh PrizePicks data) attempt {i}/{max_attempts}")

        cmd = [_py(), str(script), "--raw-only"]
        p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env={**os.environ, **extra_env})
        if p.returncode == 0:
            return
        last_err = p.returncode
        if i < max_attempts:
            time.sleep(float(sleep_s))

    raise SystemExit(last_err or 1)


def rebuild_today(*, raw_path: Optional[str | Path] = None) -> None:
    script = TOOLS_DIR / "rebuild_today_from_any_raw.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    extra_env = _extra_env_for_raw(raw_path)
    _run([_py(), str(script)], "REBUILD (canonical today.csv)", extra_env=extra_env)


def fetch_rotowire_lines(*, game_date: str, raw_path: Optional[str | Path] = None) -> None:
    script = TOOLS_DIR / "fetch_rotowire_lines.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    extra_env = {
        "ROTOWIRE_GAME_DATE": game_date,
        "ROTOWIRE_BOOK": os.getenv("ROTOWIRE_BOOK", "mgm"),
        "ROTOWIRE_LINES_URL": "",
    }

    _run([_py(), str(script)], "FETCH ROTOWIRE (lines/spreads)", extra_env=extra_env)


def build_share_matrix(*, raw_path: Optional[str | Path] = None) -> None:
    script = TOOLS_DIR / "build_share_matrix.py"
    if not script.exists():
        return

    extra_env = _extra_env_for_raw(raw_path)
    _run([_py(), str(script)], "BUILD SHARE MATRIX (role context)", extra_env=extra_env)


def model_all(ctx: RunContext) -> CmdResult:
    plan = build_new_engine_plan(
        python_exe=_py(),
        repo_root=str(PROJECT_ROOT),
        args=None,
        extra_env=None,
    )

    emit_event(
        ctx,
        "engine_invoke",
        engine_entry="python -m Atlas.engine.main",
        cmd=plan.to_cmdline(),
        cwd=str(plan.cwd) if plan.cwd else None,
    )

    result = _run_plan(plan, "MODEL (legacy main)", check=False)

    out_path = ctx.audit_dir / f"legacy_main_{ctx.run_id}_stdout.txt"
    err_path = ctx.audit_dir / f"legacy_main_{ctx.run_id}_stderr.txt"
    out_path.write_text(result.stdout, encoding="utf-8", errors="replace")
    err_path.write_text(result.stderr, encoding="utf-8", errors="replace")

    guardrail_detected, guardrail_pattern = _detect_guardrail(result.stdout, result.stderr)

    emit_event(
        ctx,
        "engine_result",
        engine_entry="python -m Atlas.engine.main",
        returncode=result.returncode,
        ok=result.ok,
        stdout_path=str(out_path),
        stderr_path=str(err_path),
        stdout_snip=_truncate(result.stdout),
        stderr_snip=_truncate(result.stderr),
        guardrail_detected=guardrail_detected,
        guardrail_pattern=guardrail_pattern,
    )

    return result


def filter_latest_for_tags(*, scheduled: bool) -> None:
    module = "Atlas.stages.filter.filter_recommendations_live"

    tags = ["all", "early", "main", "late"]
    _banner(f"TAGS: Updating latest folders for: {', '.join(tags)}")

    bucket_min_minutes = 0 if scheduled else 30

    src_dir = str(PROJECT_ROOT / "src")
    existing_pp = os.environ.get("PYTHONPATH", "")
    py_path = src_dir if not existing_pp else (src_dir + os.pathsep + existing_pp)

    _run(
        [
            _py(),
            "-m",
            module,
            "--tag",
            "all",
            "--min-minutes-to-start",
            "0",
            "--match-mode",
            "any",
        ],
        "FILTER (live placeable/all)",
        extra_env={"PYTHONPATH": py_path},
    )

    for tag in ["early", "main", "late"]:
        _run(
            [
                _py(),
                "-m",
                module,
                "--tag",
                tag,
                "--min-minutes-to-start",
                str(bucket_min_minutes),
                "--match-mode",
                "strict",
            ],
            f"FILTER (live placeable/{tag})",
            check=True,
            extra_env={"PYTHONPATH": py_path},
        )


# -----------------------------
# Public orchestration API
# -----------------------------

def _infer_game_date_from_today_csv(today_path: Path) -> Optional[str]:
    try:
        import csv
        from collections import Counter

        if not today_path.exists():
            return None

        with today_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return None

            candidates = [c for c in ("game_date", "date", "slate_date") if c in reader.fieldnames]
            if not candidates:
                return None

            values: list[str] = []
            for row in reader:
                for c in candidates:
                    v = (row.get(c) or "").strip()
                    if v:
                        values.append(v)

            if not values:
                return None

            return Counter(values).most_common(1)[0][0]

    except Exception:
        return None


def run_today(
    *,
    scheduled: bool = False,
    authority: str = "production",
    raw_path: Optional[str | Path] = None,
) -> None:
    import json

    ctx = create_run_context(authority=authority)
    emit_event(
        ctx,
        "run_start",
        scheduled=scheduled,
        authority=authority,
        raw_path=str(raw_path) if raw_path else None,
    )
    print(f"[OBS] audit log: {ctx.log_path}")

    # 1) Fetch raw board (live or seeded)
    with StageTimer(ctx, "fetch_raw_only"):
        fetch_raw_only(raw_path=raw_path, max_attempts=3, sleep_s=1.0)

    # 1a) No-slate check
    board_path = DATA_DIR / "board" / "fetch_board.csv"
    if not _csv_has_data_rows(board_path):
        emit_event(ctx, "no_slate_detected", board_path=str(board_path))
        _banner("NO SLATE DETECTED")
        print("PrizePicks returned 0 projections (fetch_board.csv has no data rows). Exiting cleanly.")
        emit_event(ctx, "run_end", status="no_slate")
        return

    _artifact_fingerprint(ctx, "fetch_board.csv", board_path)

    # 1b) Refresh rolling gamelogs (best-effort; must not block run)
    try:
        p = run_refresh_nba_gamelogs(PROJECT_ROOT, ctx.run_id)
        logger.info("Gamelog refresh OK.\nSTDOUT:\n%s\nSTDERR:\n%s", p.stdout, p.stderr)
    except subprocess.CalledProcessError as e:
        logger.error(
            "Gamelog refresh failed; continuing.\nSTDOUT:\n%s\nSTDERR:\n%s",
            e.stdout,
            e.stderr,
        )

    # 2) Rebuild canonical today.csv (live or seeded)
    with StageTimer(ctx, "rebuild_today"):
        rebuild_today(raw_path=raw_path)

    today_path = DATA_DIR / "board" / "today.csv"
    _artifact_fingerprint(ctx, "today.csv", today_path)

    # 2a) Establish ONE authoritative game_date for the run
    env_game_date = (os.getenv("ATLAS_GAME_DATE") or "").strip()
    csv_game_date = _infer_game_date_from_today_csv(today_path)
    game_date = env_game_date or csv_game_date or datetime.now().strftime("%Y-%m-%d")

    emit_event(
        ctx,
        "game_date_selected",
        game_date=game_date,
        source=("env" if env_game_date else ("today_csv" if csv_game_date else "local_now")),
    )

    os.environ.pop("ROTOWIRE_LINES_URL", None)
    os.environ["ATLAS_GAME_DATE"] = game_date

    # 2b) Fetch Rotowire lines/spreads (MUST match game_date)
    with StageTimer(ctx, "fetch_rotowire_lines"):
        fetch_rotowire_lines(game_date=game_date, raw_path=raw_path)

    rotowire_path = DATA_DIR / "input" / "rotowire_lines.json"
    assert_fresh(rotowire_path, max_age_hours=6, label="Rotowire lines")
    _artifact_fingerprint(ctx, "rotowire_lines.json", rotowire_path)

    # Extra safety: fresh-but-wrong-slate is still wrong
    try:
        rw_obj = json.loads(rotowire_path.read_text(encoding="utf-8"))
    except Exception as e:
        emit_event(ctx, "rotowire_parse_failed", error=str(e))
        raise

    rw_date = str(rw_obj.get("date", "")).strip()
    if rw_date and rw_date != game_date:
        emit_event(ctx, "rotowire_date_mismatch", expected=game_date, found=rw_date)
        raise SystemExit(f"[rotowire] rotowire_lines.json date mismatch: expected={game_date} found={rw_date}")

    # 3) Run model
    with StageTimer(ctx, "model_all"):
        build_share_matrix(raw_path=raw_path)

    engine_res = model_all(ctx)

    guardrail_detected, guardrail_pattern = _detect_guardrail(engine_res.stdout, engine_res.stderr)
    if guardrail_detected:
        emit_event(ctx, "guardrail_stop_detected", pattern=guardrail_pattern)
        _banner("GUARDRAIL STOP")
        print(f"Legacy engine indicated guardrail stop (pattern: {guardrail_pattern}). Exiting cleanly.")
        emit_event(ctx, "run_end", status="guardrail", pattern=guardrail_pattern, returncode=engine_res.returncode)
        return

    if engine_res.returncode != 0:
        emit_event(ctx, "run_end", status="fail", returncode=engine_res.returncode)
        raise SystemExit(engine_res.returncode)

    # Fingerprint common outputs (best effort)
    _artifact_fingerprint(ctx, "scored_legs.csv", OUTPUT_DIR / "scored_legs.csv")
    _artifact_fingerprint(ctx, "scored_legs_deduped.csv", OUTPUT_DIR / "scored_legs_deduped.csv")

# ---- Calibration post-process (additive) ----
    try:
        import pandas as pd
        from Atlas.engine.calibration_map import apply_calibration_column, get_calibration_path_from_env

        (ctx.audit_dir / "calibration_marker.txt").write_text(
            "ENTERED CALIBRATION TRY BLOCK v3\n",
            encoding="utf-8",
        )

        def _detect_sep(p: Path) -> str:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                head = f.readline()
            return "\t" if "\t" in head else ","

        def _append_cal_log(line: str) -> None:
            (ctx.audit_dir / "calibration_debug.log").open("a", encoding="utf-8").write(line + "\n")

        map_path = get_calibration_path_from_env()
        print(f"[CAL] ATLAS_CAL_MAP={map_path!r}")

        if not map_path or not Path(map_path).exists():
            emit_event(ctx, "calibration_skipped", reason="map_missing_or_unreadable", map_path=map_path)
            print(f"[CAL] skipped: map missing/unreadable: {map_path!r}")
        else:
            paths = [
                pth
                for pth in [OUTPUT_DIR / "scored_legs.csv", OUTPUT_DIR / "scored_legs_deduped.csv"]
                if pth.exists() and pth.is_file() and pth.stat().st_size > 0
            ]

            patched: list[str] = []
            skipped: list[tuple[str, str]] = []

            _append_cal_log(f"[CAL] map_path={map_path}")
            _append_cal_log(
                "[CAL] discovered_paths=" + "; ".join(str(p) for p in paths)
                if paths else "[CAL] discovered_paths=<none>"
            )

            for csv_path in paths:
                if not csv_path.exists():
                    _append_cal_log(f"{csv_path} | MISSING")
                    skipped.append((str(csv_path), "missing"))
                    continue

                sep = _detect_sep(csv_path)

                try:
                    df = pd.read_csv(csv_path, sep=sep, low_memory=False)
                except Exception as e:
                    _append_cal_log(f"{csv_path} | READ_FAIL | sep={repr(sep)} | err={e}")
                    skipped.append((str(csv_path), f"read_failed: {e}"))
                    continue

                if "p_adj" not in df.columns:
                    preview_cols = list(df.columns)[:10]
                    msg = f"p_adj not found (sep={sep!r}); cols_head={preview_cols}"
                    _append_cal_log(f"{csv_path} | SKIP | {msg}")
                    skipped.append((str(csv_path), msg))
                    continue

                # ---- Ensure calibration lineage columns (schema contract) ----
                # p_for_cal: probability actually fed into calibration
                # p_cal_src: label of source column used (prefer p_role)
                # role_ctx_outs_used: explicit outs usage field (copy of role_ctx_outs if present)
                if "p_for_cal" not in df.columns or "p_cal_src" not in df.columns:
                    if "p_role" in df.columns:
                        p_role = pd.to_numeric(df["p_role"], errors="coerce")
                        if "p_close_role" in df.columns:
                            p_role = p_role.fillna(pd.to_numeric(df["p_close_role"], errors="coerce"))
                        if "p_adj" in df.columns:
                            p_role = p_role.fillna(pd.to_numeric(df["p_adj"], errors="coerce"))
                        df["p_for_cal"] = p_role
                        df["p_cal_src"] = "p_role"
                    else:
                        if "data_health_flag" in df.columns:
                            is_healthy = df["data_health_flag"].astype(str).str.lower().eq("healthy")
                        else:
                            is_healthy = pd.Series([True] * len(df), index=df.index)

                        has_p_role = "p_role" in df.columns
                        p_adj_series = df["p_adj"]
                        p_role_series = df["p_role"] if has_p_role else p_adj_series

                        df["p_for_cal"] = p_adj_series.where(is_healthy, p_role_series)
                        df["p_cal_src"] = "p_adj"
                        df.loc[~is_healthy, "p_cal_src"] = "p_role" if has_p_role else "p_adj"

                if "role_ctx_outs_used" not in df.columns:
                    # role_ctx_outs_used must be an integer count, not the outs list/string itself
                    if "role_ctx_outs" in df.columns:
                        import ast

                        def _count_outs(v) -> int:
                            if v is None:
                                return 0
                            # If already a list/tuple/set
                            if isinstance(v, (list, tuple, set)):
                                return int(len(v))
                            # If it's a string representation like "['a','b']"
                            if isinstance(v, str):
                                s = v.strip()
                                if not s:
                                    return 0
                                try:
                                    parsed = ast.literal_eval(s)
                                    if isinstance(parsed, (list, tuple, set)):
                                        return int(len(parsed))
                                except Exception:
                                    return 0
                            return 0

                        df["role_ctx_outs_used"] = df["role_ctx_outs"].apply(_count_outs).astype(int)
                    else:
                        df["role_ctx_outs_used"] = 0

                # Apply calibration to produce p_cal for the current live run outputs only.
                try:
                    df = apply_calibration_column(df, map_path=map_path, in_col="p_for_cal", out_col="p_cal")
                except Exception as e:
                    _append_cal_log(f"{csv_path} | CAL_FAIL | err={e}")
                    skipped.append((str(csv_path), f"cal_failed: {e}"))
                    continue

                try:
                    df.to_csv(csv_path, index=False, sep=sep)
                except Exception as e:
                    _append_cal_log(f"{csv_path} | WRITE_FAIL | sep={repr(sep)} | err={e}")
                    skipped.append((str(csv_path), f"write_failed: {e}"))
                    continue

                patched.append(str(csv_path))
                _append_cal_log(f"{csv_path} | OK | wrote p_cal | sep={repr(sep)}")
                print(f"[CAL] wrote p_cal into {csv_path} (sep={sep!r})")

            emit_event(
                ctx,
                "calibration_applied",
                map_path=map_path,
                in_col="p_for_cal",
                out_col="p_cal",
                patched=patched,
                skipped=skipped,
            )

    except Exception as e:
        emit_event(ctx, "calibration_failed", error=str(e))
        print(f"[WARN] calibration postprocess failed: {e}")

    _banner("DONE")
    print("Atlas run complete. latest/{all,early,main,late} updated.")
    emit_event(ctx, "run_end", status="ok")