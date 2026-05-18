from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import shutil
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


def _output_root_for_run(ctx: RunContext) -> Path:
    configured = (os.environ.get("ATLAS_OUT_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (RUNS_DIR / ctx.run_id).resolve()


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


def _prepare_iael_run_snapshot(ctx: RunContext, run_root: Path) -> dict[str, Path]:
    """
    Copy the current IAEL artifacts into a run-scoped snapshot directory and
    point the active process at those copies.

    This keeps the run reproducible even if the live IAEL dashboard changes
    while the rest of the pipeline is executing.
    """
    snapshot_dir = run_root.parent.parent / "runs_manifest" / run_root.name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    strict_replay = _strict_replay_enabled()
    if strict_replay:
        sources = {
            "invalidations": _require_env_path("ATLAS_IAEL_INVALIDATIONS_PATH", "IAEL invalidations snapshot"),
            "status": _require_env_path("ATLAS_IAEL_STATUS_PATH", "IAEL status snapshot"),
            "normalized": _require_env_path("ATLAS_IAEL_NORMALIZED_PATH", "IAEL normalized snapshot"),
        }
        role_metrics_path = os.environ.get("ATLAS_ROLE_METRICS_PATH", "").strip()
        role_metrics_html_path = os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH", "").strip()
        role_metrics_manifest_path = os.environ.get("ATLAS_ROLE_METRICS_MANIFEST_PATH", "").strip()
        if role_metrics_path:
            sources["role_metrics"] = Path(role_metrics_path)
        if role_metrics_html_path:
            sources["role_metrics_html"] = Path(role_metrics_html_path)
        if role_metrics_manifest_path:
            sources["role_metrics_manifest"] = Path(role_metrics_manifest_path)
    else:
        source_dir = DATA_DIR / "output" / "dashboard"
        sources = {
            "invalidations": source_dir / "injury_invalidations_latest.json",
            "status": source_dir / "status_latest.json",
            "normalized": DATA_DIR / "output" / "injury" / "normalized" / "latest.json",
            "role_metrics": source_dir / "role_metrics_latest.json",
            "role_metrics_html": source_dir / "role_metrics_latest.html",
            "role_metrics_manifest": source_dir / "role_metrics_snapshot_manifest.json",
        }
        role_metrics_path = str(source_dir / "role_metrics_latest.json")
        role_metrics_html_path = str(source_dir / "role_metrics_latest.html")
        role_metrics_manifest_path = str(source_dir / "role_metrics_snapshot_manifest.json")

    copied: dict[str, Path] = {}
    manifest: dict[str, dict[str, str]] = {}

    for label, src in sources.items():
        if not src.exists() or not src.is_file():
            if strict_replay:
                raise RuntimeError(f"Missing strict replay IAEL snapshot: {src}")
            continue
        if label == "invalidations":
            dst = snapshot_dir / "injury_invalidations_latest.json"
        elif label == "status":
            dst = snapshot_dir / "status_latest.json"
        elif label == "role_metrics":
            dst = snapshot_dir / "role_metrics_latest.json"
        elif label == "role_metrics_html":
            dst = snapshot_dir / "role_metrics_latest.html"
        elif label == "role_metrics_manifest":
            dst = snapshot_dir / "role_metrics_snapshot_manifest.json"
        else:
            dst = snapshot_dir / "normalized_latest.json"

        shutil.copy2(src, dst)
        copied[label] = dst
        manifest[label] = {
            "source": str(src.resolve()),
            "destination": str(dst.resolve()),
            "sha256": sha256_file(dst) or "",
        }

    if not copied:
        emit_event(ctx, "iael_snapshot_missing", source_dir=str(source_dir))
        return {}

    manifest_path = snapshot_dir / "injury_snapshot_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": ctx.run_id,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "artifacts": manifest,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    os.environ["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(copied.get("invalidations", sources["invalidations"]))
    os.environ["ATLAS_IAEL_STATUS_PATH"] = str(copied.get("status", sources["status"]))
    os.environ["ATLAS_IAEL_NORMALIZED_PATH"] = str(copied.get("normalized", sources["normalized"]))
    os.environ["ATLAS_IAEL_SNAPSHOT_DIR"] = str(snapshot_dir)
    if "role_metrics" in copied:
        os.environ["ATLAS_ROLE_METRICS_PATH"] = str(copied["role_metrics"])
    elif role_metrics_path:
        os.environ["ATLAS_ROLE_METRICS_PATH"] = role_metrics_path
    if "role_metrics_html" in copied:
        os.environ["ATLAS_ROLE_METRICS_HTML_PATH"] = str(copied["role_metrics_html"])
    elif role_metrics_html_path:
        os.environ["ATLAS_ROLE_METRICS_HTML_PATH"] = role_metrics_html_path
    if "role_metrics_manifest" in copied:
        os.environ["ATLAS_ROLE_METRICS_MANIFEST_PATH"] = str(copied["role_metrics_manifest"])
    elif role_metrics_manifest_path:
        os.environ["ATLAS_ROLE_METRICS_MANIFEST_PATH"] = role_metrics_manifest_path

    emit_event(
        ctx,
        "iael_snapshot_prepared",
        snapshot_dir=str(snapshot_dir),
        invalidations_path=os.environ["ATLAS_IAEL_INVALIDATIONS_PATH"],
        status_path=os.environ["ATLAS_IAEL_STATUS_PATH"],
        normalized_path=os.environ["ATLAS_IAEL_NORMALIZED_PATH"],
        manifest_path=str(manifest_path),
    )

    _artifact_fingerprint(ctx, "iael_invalidations_latest.json", Path(os.environ["ATLAS_IAEL_INVALIDATIONS_PATH"]))
    _artifact_fingerprint(ctx, "status_latest.json", Path(os.environ["ATLAS_IAEL_STATUS_PATH"]))
    _artifact_fingerprint(ctx, "normalized_latest.json", Path(os.environ["ATLAS_IAEL_NORMALIZED_PATH"]))
    _artifact_fingerprint(ctx, "injury_snapshot_manifest.json", manifest_path)
    if "role_metrics" in copied:
        _artifact_fingerprint(ctx, "role_metrics_latest.json", copied["role_metrics"])
    if "role_metrics_html" in copied:
        _artifact_fingerprint(ctx, "role_metrics_latest.html", copied["role_metrics_html"])
    if "role_metrics_manifest" in copied:
        _artifact_fingerprint(ctx, "role_metrics_snapshot_manifest.json", copied["role_metrics_manifest"])

    return {
        "snapshot_dir": snapshot_dir,
        "manifest_path": manifest_path,
        "invalidations_path": Path(os.environ["ATLAS_IAEL_INVALIDATIONS_PATH"]),
        "status_path": Path(os.environ["ATLAS_IAEL_STATUS_PATH"]),
        "normalized_path": Path(os.environ["ATLAS_IAEL_NORMALIZED_PATH"]),
        **({"role_metrics_path": copied["role_metrics"]} if "role_metrics" in copied else {}),
        **({"role_metrics_html_path": copied["role_metrics_html"]} if "role_metrics_html" in copied else {}),
        **({"role_metrics_manifest_path": copied["role_metrics_manifest"]} if "role_metrics_manifest" in copied else {}),
    }


def _prepare_rotowire_run_snapshot(*, game_date: str) -> Path:
    source = _require_env_path("ATLAS_ROTOWIRE_LINES_PATH", "Rotowire snapshot")
    out_path = DATA_DIR / "input" / "rotowire_lines.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        obj = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read strict replay Rotowire snapshot: {source}") from exc

    source_date = str(obj.get("date", "")).strip()
    if source_date and source_date != game_date:
        raise RuntimeError(f"Strict replay Rotowire date mismatch: expected={game_date} found={source_date}")

    shutil.copy2(source, out_path)
    os.environ["ATLAS_ROTOWIRE_LINES_PATH"] = str(out_path)
    return out_path


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
            safe_line = line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
            if prefix:
                print(prefix + safe_line, end="")
            else:
                print(safe_line, end="")
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


def _strict_replay_enabled() -> bool:
    return (os.environ.get("ATLAS_STRICT_REPLAY") or "").strip() == "1"


def _require_env_path(name: str, label: str) -> Path:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        raise RuntimeError(f"Strict replay requires {label} via {name}")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"Strict replay requires {label} at {path}")
    return path


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

    if _strict_replay_enabled():
        rotowire_path = _prepare_rotowire_run_snapshot(game_date=game_date)
        _banner("REPLAY ROTOWIRE SNAPSHOT (pinned)")
        print(f"[REPLAY] rotowire snapshot copied to: {rotowire_path}")
        return

    extra_env = {
        "ROTOWIRE_GAME_DATE": game_date,
        "ROTOWIRE_BOOK": os.getenv("ROTOWIRE_BOOK", "mgm"),
        "ROTOWIRE_LINES_URL": "",
    }

    _run([_py(), str(script)], "FETCH ROTOWIRE (lines/spreads)", extra_env=extra_env)


def fetch_bettingpros_props(*, game_date: str, raw_path: Optional[str | Path] = None) -> None:
    """Fetch BettingPros NBA player props → external_priors_today.csv (non-fatal)."""
    script = TOOLS_DIR / "fetch_bettingpros_props.py"
    if not script.exists():
        logger.warning("fetch_bettingpros_props.py not found; skipping BettingPros fetch.")
        return

    if _strict_replay_enabled():
        # In replay mode, the pinned external_priors_today.csv from the bundle is used.
        _banner("REPLAY BETTINGPROS (skipped, using pinned priors)")
        return

    extra_env = {
        "BETTINGPROS_GAME_DATE": game_date,
    }

    try:
        _run([_py(), str(script)], "FETCH BETTINGPROS (player props)", extra_env=extra_env)
    except Exception as e:
        # Non-fatal: model can run without BettingPros data
        logger.warning("BettingPros fetch failed (non-fatal): %s", e)
        print(f"⚠️ BettingPros fetch failed (non-fatal): {e}", file=sys.stderr)


def fetch_oddsapi_props(*, game_date: str, raw_path: Optional[str | Path] = None) -> None:
    """Fetch OddsAPI NBA player props → merge into external_priors_today.csv (non-fatal)."""
    script = TOOLS_DIR / "fetch_oddsapi_props.py"
    if not script.exists():
        logger.warning("fetch_oddsapi_props.py not found; skipping OddsAPI fetch.")
        return

    if _strict_replay_enabled():
        _banner("REPLAY ODDSAPI (skipped, using pinned priors)")
        return

    api_key, api_key_source = _load_oddsapi_key()
    if not api_key:
        logger.info("OddsAPI key not found; skipping OddsAPI fetch.")
        return

    extra_env = {
        "ODDSAPI_KEY": api_key,
        "ODDSAPI_GAME_DATE": game_date,
    }
    logger.info("OddsAPI key source: %s length=%s", api_key_source, len(api_key))

    try:
        _run([_py(), str(script)], "FETCH ODDSAPI (player props)", extra_env=extra_env)
    except Exception as e:
        logger.warning("OddsAPI fetch failed (non-fatal): %s", e)
        print(f"⚠️ OddsAPI fetch failed (non-fatal): {e}", file=sys.stderr)


def _market_odds_provider() -> str:
    """Return the live market odds provider.

    BettingPros is the default because it feeds both external priors and the
    website market-odds package without ODDSAPI credits. Set
    ATLAS_MARKET_ODDS_PROVIDER=oddsapi or both to re-enable OddsAPI.
    """
    provider = (
        os.environ.get("ATLAS_MARKET_ODDS_PROVIDER")
        or os.environ.get("ATLAS_ODDS_PROVIDER")
        or "bettingpros"
    )
    return provider.strip().lower()


def _load_oddsapi_key() -> tuple[str, str]:
    explicit_path = (os.environ.get("ODDSAPI_KEY_FILE") or "").strip()
    candidates = [Path(explicit_path)] if explicit_path else []
    candidates.append(PROJECT_ROOT.parent / "OddAPItoken.txt")

    for path in candidates:
        try:
            if path.exists() and path.is_file():
                token = path.read_text(encoding="utf-8").strip()
                if token:
                    return token, f"file:{path.name}"
        except OSError:
            continue

    for name in ("ODDSAPI_KEY", "ODDS_API_KEY"):
        token = (os.environ.get(name) or "").strip()
        if token:
            return token, f"env:{name}"

    return "", "missing"


def _resolve_role_metrics_source() -> tuple[str, str, str]:
    source_url = (os.environ.get("ATLAS_ROLE_METRICS_URL") or "").strip()
    html_path = (os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH") or "").strip()

    if html_path:
        path = Path(html_path).expanduser()
        if path.exists() and path.is_file():
            return "", str(path), "configured-html"

    if source_url:
        return source_url, "", "configured-url"

    local_captures = []
    for candidate in PROJECT_ROOT.glob("Fetch*.txt"):
        if not candidate.is_file():
            continue
        try:
            stat_result = candidate.stat()
        except OSError:
            continue
        local_captures.append((stat_result.st_mtime, candidate.name.lower(), candidate))

    if local_captures:
        _, _, capture_path = max(local_captures)
        resolved = str(capture_path)
        os.environ["ATLAS_ROLE_METRICS_HTML_PATH"] = resolved
        return "", resolved, "local-capture"

    dashboard_html = DATA_DIR / "output" / "dashboard" / "role_metrics_latest.html"
    if dashboard_html.exists() and dashboard_html.is_file():
        resolved = str(dashboard_html)
        os.environ["ATLAS_ROLE_METRICS_HTML_PATH"] = resolved
        return "", resolved, "dashboard-fallback"

    return "", "", "missing"


def _resolve_strict_replay_role_metrics_artifacts() -> tuple[dict[str, str], str]:
    dashboard_dir = DATA_DIR / "output" / "dashboard"

    configured_json = (os.environ.get("ATLAS_ROLE_METRICS_PATH") or "").strip()
    configured_html = (os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH") or "").strip()
    configured_manifest = (os.environ.get("ATLAS_ROLE_METRICS_MANIFEST_PATH") or "").strip()

    json_path = Path(configured_json).expanduser() if configured_json else dashboard_dir / "role_metrics_latest.json"
    html_path = Path(configured_html).expanduser() if configured_html else dashboard_dir / "role_metrics_latest.html"
    manifest_path = Path(configured_manifest).expanduser() if configured_manifest else dashboard_dir / "role_metrics_snapshot_manifest.json"

    if not json_path.exists() or not json_path.is_file():
        raise RuntimeError(
            "Strict replay requires a pinned role-metrics JSON artifact. "
            "Set ATLAS_ROLE_METRICS_PATH or provide data/output/dashboard/role_metrics_latest.json."
        )

    resolved = {
        "ATLAS_ROLE_METRICS_PATH": str(json_path),
    }
    source_kind = "configured" if configured_json else "dashboard-fallback"

    if html_path.exists() and html_path.is_file():
        resolved["ATLAS_ROLE_METRICS_HTML_PATH"] = str(html_path)
        if configured_html:
            source_kind = "configured"

    if manifest_path.exists() and manifest_path.is_file():
        resolved["ATLAS_ROLE_METRICS_MANIFEST_PATH"] = str(manifest_path)
        if configured_manifest:
            source_kind = "configured"

    return resolved, source_kind


def fetch_role_metrics_snapshot(*, game_date: str, raw_path: Optional[str | Path] = None) -> None:
    extra_env = _extra_env_for_raw(raw_path)

    configured_url = os.environ.get("ATLAS_ROLE_METRICS_URL", "").strip()
    configured_html = os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH", "").strip()
    configured_json = os.environ.get("ATLAS_ROLE_METRICS_PATH", "").strip()
    configured_manifest = os.environ.get("ATLAS_ROLE_METRICS_MANIFEST_PATH", "").strip()

    if _strict_replay_enabled():
        resolved_artifacts, source_kind = _resolve_strict_replay_role_metrics_artifacts()
        os.environ.update(resolved_artifacts)
        os.environ.pop("ATLAS_ROLE_METRICS_URL", None)

        if configured_url:
            print("[ROLE_METRICS] Ignoring ATLAS_ROLE_METRICS_URL during strict replay; replay requires pinned artifacts.")

        if source_kind == "configured":
            _banner("REPLAY ROLE METRICS (pinned)")
            print("[ROLE_METRICS] Strict replay will use pinned role-metrics artifacts only.")
        else:
            _banner("REPLAY ROLE METRICS (dashboard fallback)")
            print("[ROLE_METRICS] Strict replay found no explicit role-metrics paths; using pinned dashboard artifacts.")

        print(f"[ROLE_METRICS] JSON: {os.environ['ATLAS_ROLE_METRICS_PATH']}")
        if os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH"):
            print(f"[ROLE_METRICS] HTML: {os.environ['ATLAS_ROLE_METRICS_HTML_PATH']}")
        if os.environ.get("ATLAS_ROLE_METRICS_MANIFEST_PATH"):
            print(f"[ROLE_METRICS] Manifest: {os.environ['ATLAS_ROLE_METRICS_MANIFEST_PATH']}")
        return

    if configured_url or configured_html:
        script = TOOLS_DIR / "fetch_role_metrics.py"
        if not script.exists():
            raise FileNotFoundError(f"Missing tool: {script}")

        source_url, html_path, source_kind = _resolve_role_metrics_source()

        if not source_url and not html_path:
            _banner("ROLE METRICS FETCH (skipped)")
            print("[ROLE_METRICS] No readable configured source was available; skipping metrics snapshot.")
            return

        cmd = [_py(), str(script), "--game-date", game_date]
        if html_path:
            cmd += ["--html-path", html_path]
        elif source_url:
            cmd += ["--url", source_url]

        if source_kind == "dashboard-fallback":
            _banner("ROLE METRICS FETCH (dashboard fallback)")
            print(f"[ROLE_METRICS] No explicit source configured; using local dashboard snapshot: {html_path}")
            print("[ROLE_METRICS] Manual runs can still override this with ATLAS_ROLE_METRICS_URL or ATLAS_ROLE_METRICS_HTML_PATH.")
        elif source_kind == "local-capture":
            _banner("ROLE METRICS FETCH (local capture)")
            print(f"[ROLE_METRICS] No explicit source configured; using local capture: {html_path}")
            print("[ROLE_METRICS] Manual runs can still override this with ATLAS_ROLE_METRICS_URL or ATLAS_ROLE_METRICS_HTML_PATH.")
        _run(cmd, "FETCH ROLE METRICS (role awareness / VORP)", extra_env=extra_env)
        return

    script = TOOLS_DIR / "fetch_crafted_player_stats.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    _banner("ROLE METRICS FETCH (craftednba api)")
    print("[ROLE_METRICS] No explicit HTML source is configured; fetching the daily CraftedNBA API snapshot.")
    print("[ROLE_METRICS] Set ATLAS_ROLE_METRICS_URL or ATLAS_ROLE_METRICS_HTML_PATH to force the legacy HTML parser.")
    _run([_py(), str(script), "--game-date", game_date], "FETCH ROLE METRICS (craftednba api)", extra_env=extra_env)


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


def generate_daily_graphics_csv(ctx: RunContext) -> None:
    """Generate daily graphics CSV for subscriber content after successful run."""
    # Reconfigure stdout/stderr to UTF-8 so subprocess output with emoji can't crash print()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        _banner("GENERATE DAILY GRAPHICS CSV")

        # The engine creates its own timestamped run dir — find the latest one
        # rather than relying on ctx.run_id which is the orchestrator start time.
        if RUNS_DIR.exists():
            run_dirs = sorted(
                [d for d in RUNS_DIR.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            run_output_dir = run_dirs[0] if run_dirs else _output_root_for_run(ctx)
        else:
            run_output_dir = _output_root_for_run(ctx)

        scored_legs_path = run_output_dir / "scored_legs_deduped.csv"
        
        if not scored_legs_path.exists():
            print(f"[GRAPHICS] No scored legs found at {scored_legs_path}, skipping graphics generation")
            emit_event(ctx, "graphics_generation", status="skipped", reason="no_scored_legs")
            return
        
        # Create graphics output directory
        graphics_dir = OUTPUT_DIR / "graphics"
        graphics_dir.mkdir(exist_ok=True)
        
        # Generate today's CSV
        from datetime import datetime
        today_str = datetime.now().strftime("%Y%m%d")
        output_path = graphics_dir / f"daily_top_picks_{today_str}.csv"
        
        # Run the CSV generator
        import subprocess
        csv_cmd = [
            sys.executable, str(TOOLS_DIR / "generate_daily_graphics_csv.py"),
            "--latest",
            "--output", str(output_path)
        ]
        
        import os as _os
        _sub_env = {**_os.environ, "PYTHONIOENCODING": "utf-8"}
        csv_result = subprocess.run(
            csv_cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_sub_env,
            timeout=120
        )
        
        def _safe(s: str) -> str:
            enc = sys.stdout.encoding or "utf-8"
            return s.encode(enc, errors="replace").decode(enc, errors="replace")

        if csv_result.returncode != 0:
            print(f"[GRAPHICS] FAIL CSV generation failed: {_safe(csv_result.stderr)}")
            emit_event(ctx, "graphics_generation", status="csv_failed", error=csv_result.stderr)
            return
            
        print(f"[GRAPHICS] OK Daily picks CSV generated: {output_path}")
        
        # Generate visual graphics
        try:
            marketed_slips_path = run_output_dir / "marketed_slips.csv"
            graphics_cmd = [
                sys.executable, str(TOOLS_DIR / "generate_daily_graphics.py"),
                "--csv", str(output_path),
                "--output-dir", str(graphics_dir)
            ]
            if marketed_slips_path.exists() and marketed_slips_path.stat().st_size > 0:
                graphics_cmd += ["--marketed-slips", str(marketed_slips_path)]
            
            graphics_result = subprocess.run(
                graphics_cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=_sub_env,
                timeout=180
            )
            
            if graphics_result.returncode == 0:
                print(f"[GRAPHICS] Visual graphics generated successfully")
                print(f"[GRAPHICS] Check: {graphics_dir}")
                
                # Copy CSV to latest surface for easy access
                latest_graphics_path = OUTPUT_DIR / "latest" / "daily_top_picks.csv"
                latest_graphics_path.parent.mkdir(exist_ok=True)
                shutil.copy2(output_path, latest_graphics_path)
                
                emit_event(ctx, "graphics_generation", status="success", 
                          csv_path=str(output_path), graphics_dir=str(graphics_dir))
            else:
                print(f"[GRAPHICS] WARN Visual graphics failed: {_safe(graphics_result.stderr)}")
                print(f"[GRAPHICS] CSV still available: {output_path}")
                emit_event(ctx, "graphics_generation", status="csv_only", 
                          csv_path=str(output_path), graphics_error=graphics_result.stderr)
                
        except Exception as graphics_e:
            print(f"[GRAPHICS] WARN Visual graphics exception: {_safe(str(graphics_e))}")
            print(f"[GRAPHICS] CSV still available: {output_path}")
            emit_event(ctx, "graphics_generation", status="csv_only", 
                      csv_path=str(output_path), graphics_exception=str(graphics_e))
            
    except Exception as e:
        enc = sys.stdout.encoding or "utf-8"
        safe_e = str(e).encode(enc, errors="replace").decode(enc, errors="replace")
        print(f"[GRAPHICS] FAIL Graphics generation exception: {safe_e}")
        emit_event(ctx, "graphics_generation", status="error", exception=str(e))


def run_today(
    *,
    scheduled: bool = False,
    authority: str = "production",
    raw_path: Optional[str | Path] = None,
) -> str:
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

    # ── Model contract check (warns on drift, logs to audit) ──
    from Atlas.contracts.model_contract import enforce_contract
    contract_ok = enforce_contract(PROJECT_ROOT, hard_stop=False)
    emit_event(ctx, "contract_check", passed=contract_ok)

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
        return "no_slate"

    _artifact_fingerprint(ctx, "fetch_board.csv", board_path)

    # 1b) Refresh rolling gamelogs only for non-replay runs.
    if not _strict_replay_enabled():
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

    # 2a.5) Fetch role metrics snapshot when configured, before the injury snapshot is frozen.
    with StageTimer(ctx, "fetch_role_metrics_snapshot"):
        fetch_role_metrics_snapshot(game_date=game_date, raw_path=raw_path)

    # 2b) Fetch Rotowire lines/spreads (MUST match game_date)
    with StageTimer(ctx, "fetch_rotowire_lines"):
        fetch_rotowire_lines(game_date=game_date, raw_path=raw_path)

    rotowire_path = DATA_DIR / "input" / "rotowire_lines.json"
    if not _strict_replay_enabled():
        assert_fresh(rotowire_path, max_age_hours=6, label="Rotowire lines")
    _artifact_fingerprint(ctx, "rotowire_lines.json", rotowire_path)

    # 2c) Fetch BettingPros player props → merge into external_priors_today.csv
    with StageTimer(ctx, "fetch_bettingpros_props"):
        fetch_bettingpros_props(game_date=game_date, raw_path=raw_path)

    # 2c-oddsapi) Optional legacy OddsAPI overlay. BettingPros is now the
    # default market odds provider and writes odds_market_today.json itself.
    odds_provider = _market_odds_provider()
    with StageTimer(ctx, "fetch_oddsapi_props"):
        if odds_provider in {"oddsapi", "theoddsapi", "both", "all"}:
            fetch_oddsapi_props(game_date=game_date, raw_path=raw_path)
        else:
            _banner(f"FETCH ODDSAPI (skipped, provider={odds_provider})")

    bp_priors_path = DATA_DIR / "input" / "external_priors_today.csv"
    _artifact_fingerprint(ctx, "external_priors_today.csv", bp_priors_path)
    _artifact_fingerprint(ctx, "odds_market_today.json", DATA_DIR / "input" / "odds_market_today.json")

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

    # 2d) Refresh IAEL snapshot before freezing — ensures injuries reported since
    # the morning cron are captured (e.g. afternoon status-change outs).
    if not _strict_replay_enabled():
        with StageTimer(ctx, "refresh_iael_snapshot"):
            refresh_script = TOOLS_DIR / "refresh_iael_today.py"
            if refresh_script.exists():
                emit_event(ctx, "iael_refresh_start", script=str(refresh_script))
                result = subprocess.run(
                    [_py(), str(refresh_script)],
                    capture_output=False,
                    check=False,
                )
                emit_event(ctx, "iael_refresh_done", returncode=result.returncode)
            else:
                emit_event(ctx, "iael_refresh_missing", script=str(refresh_script))

    # Freeze the injury state for this run before model scoring starts.
    run_root = _output_root_for_run(ctx)
    iael_run_snapshot = _prepare_iael_run_snapshot(ctx, run_root)
    if not iael_run_snapshot:
        raise RuntimeError("IAEL snapshot could not be prepared for this run")

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
        return "guardrail"

    if engine_res.returncode != 0:
        emit_event(ctx, "run_end", status="fail", returncode=engine_res.returncode)
        raise SystemExit(engine_res.returncode)

    # Fingerprint common outputs (best effort)
    output_root = _output_root_for_run(ctx)
    _artifact_fingerprint(ctx, "scored_legs.csv", output_root / "scored_legs.csv")
    _artifact_fingerprint(ctx, "scored_legs_deduped.csv", output_root / "scored_legs_deduped.csv")

    # 5) Generate daily graphics CSV for subscriber content
    with StageTimer(ctx, "generate_daily_graphics"):
        generate_daily_graphics_csv(ctx)

    # 6) Discord picks-today post (best-effort, never blocks the run)
    #    Skipped during replay/backtest to avoid posting historical slates.
    import os as _os_pub_guard
    _suppress_pub = (
        _os_pub_guard.environ.get("ATLAS_STRICT_REPLAY") == "1"
        or _os_pub_guard.environ.get("ATLAS_AUTHORITY", "").lower() in {"replay", "sandbox"}
        or _os_pub_guard.environ.get("ATLAS_SUPPRESS_PUBLISH") == "1"
    )
    _discord_picks_enabled = _os_pub_guard.environ.get("ATLAS_DISCORD_PICKS_POST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    with StageTimer(ctx, "discord_post"):
        if _suppress_pub:
            print("[DISCORD] skipped (replay/sandbox)")
        elif not _discord_picks_enabled:
            print("[DISCORD] skipped (ATLAS_DISCORD_PICKS_POST not enabled)")
        else:
            try:
                import subprocess as _subp
                import os as _os2
                _discord_env = {**_os2.environ, "PYTHONIOENCODING": "utf-8"}
                _discord_result = _subp.run(
                    [sys.executable, str(TOOLS_DIR / "discord_post.py"), "--picks-today"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=_discord_env,
                    timeout=45,
                )
                for _line in (_discord_result.stdout or "").splitlines():
                    print(_line)
                if _discord_result.returncode != 0:
                    print(f"[DISCORD] WARN exit {_discord_result.returncode}: {_discord_result.stderr[:200]}")
            except Exception as _disc_e:
                print(f"[DISCORD] WARN exception (non-fatal): {_disc_e}")

    # 7) Twitter picks-today post (best-effort, never blocks the run)
    with StageTimer(ctx, "twitter_post"):
        if _suppress_pub:
            print("[TWITTER] skipped (replay/sandbox)")
        else:
            try:
                import subprocess as _subp2
                import os as _os3
                _twitter_env = {**_os3.environ, "PYTHONIOENCODING": "utf-8"}
                _twitter_result = _subp2.run(
                    [sys.executable, str(TOOLS_DIR / "twitter_post.py"), "--picks-today"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=_twitter_env,
                    timeout=30,
                )
                for _line in (_twitter_result.stdout or "").splitlines():
                    print(_line)
                if _twitter_result.returncode != 0:
                    print(f"[TWITTER] WARN exit {_twitter_result.returncode}: {_twitter_result.stderr[:200]}")
            except Exception as _tw_e:
                print(f"[TWITTER] WARN exception (non-fatal): {_tw_e}")

    _banner("DONE")
    print("Atlas run complete. latest/{all,early,main,late} updated.")
    emit_event(ctx, "run_end", status="ok")
    return "ok"
