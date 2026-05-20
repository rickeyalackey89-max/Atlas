"""Atlas CLI (Phase 4+)

Execution authority surface.

Contract:
- LIVE is canonical production entrypoint:
    python -m Atlas.cli live
  LIVE requires fresh injury pull + IAEL validation and hard-stops pre-score if not proven live for today.

- REPLAY is canonical deterministic sandbox entrypoint:
    python -m Atlas.cli replay --raw <path_to_raw_json>
  REPLAY must never fetch live data, never run injury pull, and must operate only from explicit raw JSON.

- TOOLS are callable only through this CLI surface (not ad-hoc), subject to mode gating:
    python -m Atlas.cli tools list
    python -m Atlas.cli tools run <tool_name> [-- <args...>]

We intentionally keep this file thin and avoid engine logic changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from Atlas.runtime.replay_eval import backfill_latest_replay_eval_legs


# -----------------------------
# Phase 6 — Filesystem enforcement (Level 1)
#
# Controlled by env var:
#   ATLAS_FS_ENFORCE=warn|hard
# Default: warn
#
# Contract for analysis tools:
# - Must not modify data/output
# - Must not modify files outside data/archives
# -----------------------------

_FS_EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache",
}


def _fs_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Return {rel_path: (mtime_ns, size)} for all files under root."""
    snap: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _FS_EXCLUDE_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            snap[rel] = (int(st.st_mtime_ns), int(st.st_size))
    return snap


def _fs_snapshot_repo_other(repo_root: Path) -> dict[str, tuple[int, int]]:
    """Snapshot repo_root excluding data/output and data/archives."""
    snap: dict[str, tuple[int, int]] = {}
    if not repo_root.exists():
        return snap
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dp = Path(dirpath)
        rel_parts = dp.relative_to(repo_root).parts if dp != repo_root else ()
        if rel_parts:
            top = rel_parts[0]
            if top in _FS_EXCLUDE_DIRS:
                dirnames[:] = []
                continue
            if top == "data" and len(rel_parts) >= 2 and rel_parts[1] in ("output", "archives"):
                dirnames[:] = []
                continue
        dirnames[:] = [d for d in dirnames if d not in _FS_EXCLUDE_DIRS]
        for fn in filenames:
            p = dp / fn
            try:
                st = p.stat()
            except OSError:
                continue
            rel = str(p.relative_to(repo_root)).replace("\\", "/")
            snap[rel] = (int(st.st_mtime_ns), int(st.st_size))
    return snap


def _fs_diff(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> dict[str, list[str]]:
    added = [k for k in after.keys() if k not in before]
    removed = [k for k in before.keys() if k not in after]
    modified = [k for k in after.keys() if k in before and after[k] != before[k]]
    added.sort()
    removed.sort()
    modified.sort()
    return {"added": added, "modified": modified, "removed": removed}


def _write_violation_report(repo_root: Path, report: dict) -> Path:
    archives = repo_root / "data" / "archives"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = archives / "tool_violations" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "violation_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def _fs_enforce(repo_root: Path, tool: dict, mode: str, changes: dict[str, dict[str, list[str]]]) -> None:
    enforce = (os.environ.get("ATLAS_FS_ENFORCE") or "warn").strip().lower()
    if enforce not in ("warn", "hard"):
        enforce = "warn"

    writes = set((tool.get("writes_surfaces") or []))
    if "analysis" not in writes:
        return

    violations: list[str] = []

    out_ch = changes.get("data_output", {})
    if out_ch.get("added") or out_ch.get("modified") or out_ch.get("removed"):
        violations.append("FORBIDDEN: tool modified data/output")

    other_ch = changes.get("repo_other", {})
    if other_ch.get("added") or other_ch.get("modified") or other_ch.get("removed"):
        violations.append("FORBIDDEN: tool modified files outside data/archives")

    if not violations:
        return

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "enforcement_mode": enforce,
        "tool_name": tool.get("name"),
        "cli_mode": mode,
        "violations": violations,
        "changes": changes,
    }
    report_path = _write_violation_report(repo_root, report)
    msg = (
        f"[ATLAS_FS_ENFORCE={enforce}] Filesystem violations detected for tool '{tool.get('name')}'.\n"
        f"Wrote violation report: {report_path}"
    )
    if enforce == "hard":
        raise RuntimeError(msg)
    print(msg)


# -----------------------------
# Data structures
# -----------------------------
@dataclass(frozen=True)
class IaelStatus:
    dead_period: bool
    report_date: str


# -----------------------------
# Path + time helpers
# -----------------------------
def _repo_root() -> Path:
    # src/Atlas/cli.py -> src -> repo root
    return Path(__file__).resolve().parents[2]


def _today_yyyy_mm_dd() -> str:
    # Match run.ps1: (Get-Date).ToString("yyyy-MM-dd") in local time.
    return datetime.now().strftime("%Y-%m-%d")


# -----------------------------
# IAEL helpers (LIVE only)
# -----------------------------
def _load_iael_status(repo_root: Path) -> IaelStatus:
    dash_status = repo_root / "data" / "output" / "dashboard" / "status_latest.json"
    if not dash_status.exists():
        raise RuntimeError(f"FATAL: IAEL status_latest.json not found at {dash_status}")
    try:
        st = json.loads(dash_status.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"FATAL: Could not parse IAEL status_latest.json: {e}") from e

    dead_period = bool(st.get("dead_period", False))
    report_date = str(st.get("report_date") or "").strip()
    return IaelStatus(dead_period=dead_period, report_date=report_date)


def _invoke_dead_period_bundle(repo_root: Path, run_id: str) -> None:
    """Emit a DEAD_PERIOD bundle via the Python bundler (Phase 7C).

    Contract:
    - Bundling must never block LIVE preflight.
    - Zip-only output under: data/bundles/atlas_bundle_<run_id>__DEAD_PERIOD.zip
    """
    try:
        from Atlas.runtime.bundles import write_bundle_zip  # local import
        data_dir = repo_root / "data"
        iael_dir = data_dir / "iael"
        audit_dir = data_dir / "output" / "runs" / run_id / ".atlas_audit"
        if not audit_dir.exists():
            audit_dir = None
        write_bundle_zip(
            repo_root=repo_root,
            data_dir=data_dir,
            run_id=run_id,
            ok=False,
            raw_path=None,
            iael_live_dir=iael_dir if iael_dir.exists() else None,
            runs_dir=(data_dir / "output" / "runs"),
            audit_dir=audit_dir,
            engine_entry="python -m Atlas.cli live",
            extra_manifest={
                "bundle_mode": "DEAD_PERIOD",
                "termination_reason": "IAEL_DEAD_PERIOD",
            },
        )
        print(f"[BUNDLE] DEAD_PERIOD zip written: data/bundles/atlas_bundle_{run_id}__DEAD_PERIOD.zip")
    except Exception as e:
        print(f"⚠️ DEAD_PERIOD bundling failed: {e}", file=sys.stderr)


def _latest_run_id(repo_root: Path) -> str | None:
    """Return newest run_id directory under data/output/runs by mtime."""
    runs_dir = repo_root / "data" / "output" / "runs"
    if not runs_dir.exists():
        return None
    dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    return dirs[0].name


def _archive_run_to_telemetry(repo_root: Path, run_id: str) -> None:
    """Copy key run artifacts into data/telemetry/ so every live run is tracked."""
    try:
        run_dir = repo_root / "data" / "output" / "runs" / run_id
        telem_live = repo_root / "data" / "telemetry" / "live_runs" / run_id
        telem_live.mkdir(parents=True, exist_ok=True)

        for name in ("scored_legs_deduped.csv", "scored_board.csv", "meta.json", "slip_results.csv"):
            src = run_dir / name
            if src.exists():
                shutil.copy2(src, telem_live / name)

        bundles_dir = repo_root / "data" / "bundles"
        telem_bundles = repo_root / "data" / "telemetry" / "bundles"
        telem_bundles.mkdir(parents=True, exist_ok=True)
        bundle_name = f"atlas_bundle_{run_id}.zip"
        bundle_src = bundles_dir / bundle_name
        if bundle_src.exists():
            shutil.copy2(bundle_src, telem_live / bundle_name)
            shutil.copy2(bundle_src, telem_bundles / bundle_name)

        print(f"[TELEM] Archived run {run_id} to {telem_live}")
    except Exception as e:
        print(f"[TELEM] Archive failed (non-fatal): {e}", file=sys.stderr)


def _publish_to_cloudflare_dashboard(repo_root: Path) -> None:
    """Publish dashboard data and git push to trigger Cloudflare deploy.

    The dashboard repo owns the public/data contract. Use its publish script so
    derived files such as picks_today.json stay in sync with cloudflare_payload.
    """
    try:
        dashboard_repo = Path("C:/Users/13142/Atlas/atlas-dashboard")
        if not dashboard_repo.exists():
            print("[DASH] AtlasDashboard repo not found, skipping publish", file=sys.stderr)
            return

        # Copy payload
        src_payload = repo_root / "data" / "output" / "dashboard" / "cloudflare_payload.json"
        dst_payload = dashboard_repo / "public" / "data" / "cloudflare_payload.json"
        if not src_payload.exists():
            print("[DASH] No cloudflare_payload.json to publish", file=sys.stderr)
            return

        import subprocess
        publish_script = dashboard_repo / "publish-atlas.ps1"
        if publish_script.exists():
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-ExecutionPolicy",
                    "RemoteSigned",
                    "-File",
                    str(publish_script),
                    "-AtlasRoot",
                    str(repo_root),
                ],
                cwd=str(dashboard_repo),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.stdout:
                print(result.stdout.rstrip())
            if result.returncode != 0:
                if result.stderr:
                    print(result.stderr.rstrip(), file=sys.stderr)
                raise RuntimeError(f"dashboard publish script failed with exit code {result.returncode}")
            print("[DASH] Published to Cloudflare dashboard")
            return

        # Legacy fallback: copy only the canonical payload when the dashboard
        # publish script is absent. This path does not build homepage picks.
        dst_payload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_payload, dst_payload)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "add", "public/data/cloudflare_payload.json"], cwd=str(dashboard_repo), check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(dashboard_repo))
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Publish data ({ts})"], cwd=str(dashboard_repo), check=True)
            subprocess.run(["git", "push"], cwd=str(dashboard_repo), check=True)
            print("[DASH] Published payload-only fallback to Cloudflare dashboard")
        else:
            print("[DASH] No payload changes to publish")
    except Exception as e:
        print(f"[DASH] Publish failed (non-fatal): {e}", file=sys.stderr)


def _write_full_run_bundle(repo_root: Path, run_id: str) -> None:
    """Best-effort: emit a FULL_RUN bundle via the Python bundler (Phase 7C)."""
    try:
        from Atlas.runtime.bundles import write_bundle_zip  # local import
        data_dir = repo_root / "data"
        iael_dir = data_dir / "iael"
        audit_dir = data_dir / "output" / "runs" / run_id / ".atlas_audit"
        if not audit_dir.exists():
            audit_dir = None
        zp = write_bundle_zip(
            repo_root=repo_root,
            data_dir=data_dir,
            run_id=run_id,
            ok=True,
            raw_path=None,
            iael_live_dir=iael_dir if iael_dir.exists() else None,
            runs_dir=(data_dir / "output" / "runs"),
            audit_dir=audit_dir,
            engine_entry="python -m Atlas.cli live",
            extra_manifest={
                "bundle_mode": "FULL_RUN",
            },
        )
        print(f"[BUNDLE] FULL_RUN zip written: {zp}")
    except Exception as e:
        print(f"⚠️ FULL_RUN bundling failed: {e}", file=sys.stderr)


def _hard_live_iael_preflight(repo_root: Path) -> None:
    """Strict IAEL gate (LIVE only), with caching to avoid repeated injury pulls.

    Contract:
    - If IAEL status already proves "live for today", do not re-run injury pull.
    - Otherwise, run the IAEL refresh script and re-validate.
    """
    # Refuse implicit replay/sandbox seeds.
    if (
        os.environ.get("ATLAS_SANDBOX_REPLAY") == "1"
        or os.environ.get("ATLAS_REPLAY_RAW")
        or os.environ.get("ATLAS_RAW_JSON_PATH")
    ):
        raise RuntimeError(
            "FATAL: Replay/sandbox environment variables detected. "
            "Clear ATLAS_SANDBOX_REPLAY / ATLAS_REPLAY_RAW / ATLAS_RAW_JSON_PATH and retry."
        )

    today = _today_yyyy_mm_dd()

    # Fast-path: if status already proves today, skip refresh.
    try:
        st0 = _load_iael_status(repo_root)
        if st0.dead_period:
            print("\n========================================================================")
            print("[GUARDRAIL STOP (DEAD_PERIOD)]")
            print("========================================================================")
            print("IAEL dead_period=true (no live injury report today). Production run will not proceed.")
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            _invoke_dead_period_bundle(repo_root, run_id)
            raise SystemExit(0)

        if st0.report_date == today:
            # Even if report_date is "today", do not accept stale IAEL artifacts.
            latest_norm = repo_root / "data" / "output" / "injury" / "normalized" / "latest.json"

            age_ok = True
            age_minutes = None

            try:
                now_utc = datetime.now(timezone.utc)

                if latest_norm.exists():
                    # Prefer pulled_at_local inside latest.json; fallback to mtime.
                    d = json.loads(latest_norm.read_text(encoding="utf-8"))
                    pulled_at = None
                    if isinstance(d, dict):
                        pulled_at = d.get("pulled_at_local") or d.get("pulled_at")
                    if pulled_at:
                        # Parse ISO with offset if present; if not, assume local -> convert to UTC
                        dt = datetime.fromisoformat(str(pulled_at).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        pulled_utc = dt.astimezone(timezone.utc)
                    else:
                        pulled_utc = datetime.fromtimestamp(latest_norm.stat().st_mtime, tz=timezone.utc)

                    age = now_utc - pulled_utc
                    age_minutes = age.total_seconds() / 60.0
                    age_ok = age <= timedelta(minutes=30)
                else:
                    age_ok = False
            except Exception:
                # If anything about freshness parsing fails, force refresh for safety.
                age_ok = False

            if age_ok:
                print(f"OK: Live IAEL verified for today ({today}). (cached)")
                return

            # Stale despite being "today" -> force refresh
            if age_minutes is None:
                print(f"[IAEL] Cached report_date is today but latest.json freshness unknown. Forcing refresh.")
            else:
                print(f"[IAEL] Cached report_date is today but normalized/latest.json is stale ({age_minutes:.1f} min). Forcing refresh.")
                return
    except Exception:
        # Missing/invalid status -> must refresh below
        pass

    # Refresh IAEL (must succeed)
    refresh_script = repo_root / "tools" / "refresh_iael_today.py"
    if not refresh_script.exists():
        raise RuntimeError(f"Missing IAEL refresh tool: {refresh_script}")

    code = subprocess.run([sys.executable, str(refresh_script)], cwd=str(repo_root)).returncode
    if code != 0:
        raise RuntimeError(f"Step failed (IAEL_REFRESH). ExitCode={code}")

    # Hard production guard: IAEL must prove live for today
    st = _load_iael_status(repo_root)

    if st.dead_period:
        print("\n========================================================================")
        print("[GUARDRAIL STOP (DEAD_PERIOD)]")
        print("========================================================================")
        print("IAEL dead_period=true (no live injury report today). Production run will not proceed.")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _invoke_dead_period_bundle(repo_root, run_id)
        raise SystemExit(0)

    if not st.report_date:
        raise RuntimeError(
            "FATAL: IAEL status missing report_date (cannot prove live IAEL today). Production run aborted."
        )

    if st.report_date != today:
        raise RuntimeError(
            f"FATAL: IAEL report_date={st.report_date} but today={today}. Production run aborted."
        )

    print(f"OK: Live IAEL verified for today ({today}).")


# -----------------------------
# TOOLS registry
# -----------------------------
def _registry_path(repo_root: Path) -> Path:
    return repo_root / "TOOL_REGISTRY.yaml"


def _load_registry(repo_root: Path) -> dict:
    p = _registry_path(repo_root)
    if not p.exists():
        raise RuntimeError(f"Tool registry not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _tool_by_name(reg: dict, name: str) -> dict:
    tools = reg.get("tools") or []
    for t in tools:
        if str(t.get("name", "")).strip() == name:
            return t
    raise RuntimeError(f"Unknown tool: {name}")


def _mode_ok(tool: dict, mode: str) -> bool:
    modes = [m.lower() for m in (tool.get("modes") or [])]
    return "both" in modes or mode in modes


def _assert_analysis_archives_only(tool: dict, repo_root: Path, extra_args: list[str]) -> None:
    """Enforce that analysis tools write only under <repo_root>/data/archives/.

    Phase 5 contract (current):
    - Engine outputs write to data/output only.
    - Tool telemetry/financial/replay outputs write to data/archives only (tool-specific subfolders).
    - Analysis-writing tools MUST be invoked with --out-dir under <repo_root>/data/archives/...
    - Analysis-writing tools MUST NOT write to data/output.
    """
    writes = set((tool.get("writes_surfaces") or []))
    if "analysis" not in writes:
        return

    if "--out-dir" not in extra_args:
        raise RuntimeError(
            f"Tool '{tool['name']}' writes analysis. You MUST pass --out-dir <data/archives/...>."
        )

    idx = extra_args.index("--out-dir") + 1
    if idx >= len(extra_args):
        raise RuntimeError(f"Tool '{tool['name']}': --out-dir requires a value.")

    out_dir = Path(extra_args[idx]).expanduser().resolve()

    expected_root = (repo_root / "data" / "archives").resolve()
    expected_s = str(expected_root).replace("\\", "/").lower()
    out_s = str(out_dir).replace("\\", "/").lower()

    if not out_s.startswith(expected_s):
        raise RuntimeError(
            f"Tool '{tool['name']}': --out-dir must be under {expected_root}. Got: {out_dir}"
        )

    if "/data/output/" in out_s:
        raise RuntimeError(
            f"Tool '{tool['name']}': writing to data/output is forbidden for analysis tools."
        )


def _run_tool(repo_root: Path, tool: dict, mode: str, extra_args: list[str]) -> int:
    # Phase 6 (Level 1): filesystem snapshot before tool run
    data_output_root = repo_root / "data" / "output"
    data_archives_root = repo_root / "data" / "archives"

    before_output = _fs_snapshot(data_output_root)
    before_archives = _fs_snapshot(data_archives_root)
    before_other = _fs_snapshot_repo_other(repo_root)

    kind = str(tool.get("kind") or "").strip().lower()
    path = tool.get("path")

    if kind in ("module", "planned_tool"):
        raise RuntimeError(f"Tool '{tool['name']}' is not runnable as a script (kind={kind}).")

    if kind == "powershell":
        script = repo_root / str(path)
        if not script.exists():
            raise RuntimeError(f"Missing tool script: {script}")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] + extra_args
        rc = subprocess.run(cmd, cwd=str(repo_root)).returncode
    else:
        # python_script or dev_script
        script = repo_root / str(path)
        if not script.exists():
            raise RuntimeError(f"Missing tool script: {script}")
        cmd = [sys.executable, str(script)] + extra_args
        rc = subprocess.run(cmd, cwd=str(repo_root)).returncode

    # Phase 6 (Level 1): filesystem snapshot after tool run + enforcement
    after_output = _fs_snapshot(data_output_root)
    after_archives = _fs_snapshot(data_archives_root)
    after_other = _fs_snapshot_repo_other(repo_root)

    changes = {
        "data_output": _fs_diff(before_output, after_output),
        "data_archives": _fs_diff(before_archives, after_archives),
        "repo_other": _fs_diff(before_other, after_other),
    }
    _fs_enforce(repo_root, tool, mode, changes)
    return rc


# -----------------------------
# CLI entrypoint
# -----------------------------
def _parse_replay_raw_path(argv: list[str]) -> Path:
    if "--raw" not in argv:
        raise RuntimeError("Replay requires --raw <path_to_raw_json>")
    raw_index = argv.index("--raw") + 1
    if raw_index >= len(argv):
        raise RuntimeError("Replay requires --raw <path_to_raw_json>")
    raw_path = Path(argv[raw_index]).expanduser().resolve()
    if not raw_path.exists():
        raise RuntimeError(f"Replay raw file not found: {raw_path}")
    if raw_path.suffix.lower() != ".json":
        raise RuntimeError(f"Replay raw path must be a .json file: {raw_path}")
    return raw_path


def main(argv: Optional[list[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    cmd = (argv[0].lower() if argv else "live")
    if cmd == "run":
        cmd = "live"

    repo_root = _repo_root()

    # LIVE
    if cmd == "live":
        _hard_live_iael_preflight(repo_root)
        from Atlas.runtime.orchestrator import run_today  # local import pre-gate safe
        # Phase 8: LIVE must be a single smooth run that produces all expected outputs.
        # The engine run updates data/output/runs + data/output/latest; publishing creates
        # normalized IAEL snapshots + any additional "latest" JSON artifacts.
        run_status = run_today(authority="production")
        if run_status != "ok":
            print(f"[LIVE] run_status={run_status}; skipping post-run bundle, latest publish, telemetry archive, and dashboard publish.")
            return
        print("[BUNDLE] attempting post-run bundle")
        runs_dir = repo_root / "data" / "output" / "runs"
        run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = run_dirs[0].name
        print(f"[BUNDLE] inferred run_id={run_id}")
        _write_full_run_bundle(repo_root, run_id)
        
        # After a successful engine run, publish "latest placeable" artifacts.
        # This is intentionally implemented as a repo-local tool script (no legacy wrappers).
        publish_script = repo_root / "tools" / "publish_latest_placeable.py"
        if publish_script.exists():
            rc = subprocess.run([sys.executable, str(publish_script)], cwd=str(repo_root)).returncode
            if rc != 0:
                raise RuntimeError(f"Post-run publish step failed. ExitCode={rc} script={publish_script}")
        else:
            raise RuntimeError(f"Missing required publish tool: {publish_script}")

        _archive_run_to_telemetry(repo_root, run_id)
        _publish_to_cloudflare_dashboard(repo_root)
        return

    # REPLAY
    if cmd == "replay":
        raw_path = _parse_replay_raw_path(argv)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.environ["ATLAS_AUTHORITY"] = "replay"
        os.environ["ATLAS_STRICT_REPLAY"] = "1"
        os.environ["ATLAS_OUT_DIR"] = str(repo_root / "data" / "telemetry" / "replay_runs" / run_id)
        from Atlas.runtime.orchestrator import run_today
        run_today(authority="sandbox", raw_path=raw_path)
        output_root = Path(os.environ["ATLAS_OUT_DIR"]).resolve()
        replay_truth_path = repo_root / "data" / "telemetry" / "Last 10" / "Last10.csv"
        gamelogs_path = Path(
            os.environ.get("ATLAS_GAMELOGS_PATH", str(repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"))
        ).resolve()
        eval_path = backfill_latest_replay_eval_legs(
            output_root=output_root,
            gamelogs_path=[replay_truth_path, gamelogs_path],
            repo_root=repo_root,
            python_executable=sys.executable,
        )
        print(f"[REPLAY] eval_legs={eval_path}")
        return

    # TOOLS
    if cmd == "tools":
        if len(argv) < 2:
            raise RuntimeError("Usage: python -m Atlas.cli tools <list|run> ...")
        sub = argv[1].lower()

        reg = _load_registry(repo_root)

        if sub == "list":
            tools = reg.get("tools") or []
            for t in tools:
                name = t.get("name")
                kind = t.get("kind")
                modes = ",".join(t.get("modes") or [])
                net = t.get("network")
                print(f"{name:28s} kind={kind:12s} modes={modes:10s} network={net}")
            return

        if sub == "run":
            if len(argv) < 3:
                raise RuntimeError("Usage: python -m Atlas.cli tools run <tool_name> [-- <args...>]")
            name = argv[2]
            tool = _tool_by_name(reg, name)

            # Determine current mode context by env or default assumption:
            # - If caller wants to run tools in replay context, they should do it from replay workflows.
            # Here, we infer mode from presence of ATLAS_SANDBOX_REPLAY env var.
            mode = "replay" if os.environ.get("ATLAS_SANDBOX_REPLAY") == "1" else "live"

            if not _mode_ok(tool, mode):
                raise RuntimeError(f"Tool '{name}' is not allowed in mode={mode}. Allowed={tool.get('modes')}")

            extra_args = argv[3:]
            # Support: tools run <name> [-- <args...>]
            if extra_args and extra_args[0] == "--":
                extra_args = extra_args[1:]
            _assert_analysis_archives_only(tool, repo_root, extra_args)

            rc = _run_tool(repo_root, tool, mode, extra_args)
            if rc != 0:
                raise RuntimeError(f"Tool '{name}' failed. ExitCode={rc}")
            return

        raise RuntimeError("Usage: python -m Atlas.cli tools <list|run> ...")

    raise RuntimeError(f"Unknown command: {cmd}. Supported: live | replay --raw <path> | tools <list|run>.")


if __name__ == "__main__":
    main()
