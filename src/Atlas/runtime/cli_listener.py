"""File-backed Atlas CLI listener for local operator automation.

The listener intentionally executes a small allowlist of Atlas actions. It is
designed as a bridge for mobile ChatGPT, humans, GitHub automation, or future
agents that can write JSON task files into the listener inbox.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_LISTENER_DIR = Path("data") / "automation" / "cli_listener"
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 7200
MAX_TIMEOUT_SECONDS = 14400
MAX_STDOUT_TAIL_LINES = 200
SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|webhook)", re.IGNORECASE)
TASK_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ListenerPaths:
    root: Path
    base: Path
    inbox: Path
    processing: Path
    outbox: Path
    failed: Path
    logs: Path
    codex_handoffs: Path
    status: Path

    @classmethod
    def from_root(cls, root: Path, base: Path | None = None) -> "ListenerPaths":
        root = root.resolve()
        base_path = base if base is not None else root / DEFAULT_LISTENER_DIR
        if not base_path.is_absolute():
            base_path = root / base_path
        base_path = base_path.resolve()
        return cls(
            root=root,
            base=base_path,
            inbox=base_path / "inbox",
            processing=base_path / "processing",
            outbox=base_path / "outbox",
            failed=base_path / "failed",
            logs=base_path / "logs",
            codex_handoffs=base_path / "codex_handoffs",
            status=base_path / "status.json",
        )

    def ensure(self) -> None:
        for path in (
            self.base,
            self.inbox,
            self.processing,
            self.outbox,
            self.failed,
            self.logs,
            self.codex_handoffs,
        ):
            path.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_task_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        text = f"task_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    sanitized = TASK_ID_RE.sub("_", text).strip("._-")
    return sanitized or f"task_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def load_task(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("task JSON must be an object")
    return data


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def list_json_tasks(inbox: Path) -> list[Path]:
    return sorted(path for path in inbox.glob("*.json") if path.is_file())


def timeout_from_task(task: Mapping[str, Any]) -> int:
    raw = task.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, MAX_TIMEOUT_SECONDS))


def tail_lines(lines: Iterable[str], max_lines: int = MAX_STDOUT_TAIL_LINES) -> list[str]:
    values = list(lines)
    if len(values) <= max_lines:
        return values
    return values[-max_lines:]


def command_text(command: Iterable[str]) -> str:
    return " ".join(str(part) for part in command)


def run_command(
    command: list[str],
    *,
    root: Path,
    log_path: Path,
    timeout_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry_run",
            "returncode": 0,
            "command": command,
            "stdout_tail": [],
            "log_path": str(log_path),
        }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(f"[ATLAS_LISTENER] command={command_text(command)}\n")
        log.flush()
        proc = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                print(line, flush=True)
                log.write(line + "\n")
                lines.append(line)
            returncode = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = proc.wait()
            message = f"[ATLAS_LISTENER] timeout after {timeout_seconds}s"
            print(message, flush=True)
            log.write(message + "\n")
            lines.append(message)
            return {
                "status": "failed",
                "returncode": returncode if returncode else 124,
                "command": command,
                "stdout_tail": tail_lines(lines),
                "log_path": str(log_path),
                "error": message,
            }

    return {
        "status": "completed" if returncode == 0 else "failed",
        "returncode": returncode,
        "command": command,
        "stdout_tail": tail_lines(lines),
        "log_path": str(log_path),
    }


def latest_run_summary(root: Path) -> dict[str, Any]:
    runs_dir = root / "data" / "output" / "runs"
    if not runs_dir.exists():
        return {"runs_dir": str(runs_dir), "latest_run": None}
    runs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    if not runs:
        return {"runs_dir": str(runs_dir), "latest_run": None}
    latest = runs[-1]
    expected_files = [
        "scored_legs.csv",
        "scored_legs_deduped.csv",
        "catboost_scale_policy_manifest.json",
        "raw_slate_fragility_guard_manifest.json",
        "single_game_mode_manifest.json",
        "marketed_slips.csv",
    ]
    family_files = [
        "System/recommended_3leg.csv",
        "System/recommended_4leg.csv",
        "System/recommended_5leg.csv",
        "Windfall/recommended_3leg.csv",
        "Windfall/recommended_4leg.csv",
        "Windfall/recommended_5leg.csv",
        "DemonHunter/recommended_3leg.csv",
        "DemonHunter/recommended_4leg.csv",
        "DemonHunter/recommended_5leg.csv",
    ]
    return {
        "runs_dir": str(runs_dir),
        "latest_run": latest.name,
        "latest_run_path": str(latest),
        "files": {name: (latest / name).exists() for name in expected_files + family_files},
    }


def git_status(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "dirty": bool(proc.stdout.strip()),
        "lines": proc.stdout.splitlines(),
    }


def dashboard_root(root: Path) -> Path:
    return root.parent / "atlas-dashboard"


def dashboard_status(root: Path) -> dict[str, Any]:
    dashboard = dashboard_root(root)
    public_data = dashboard / "public" / "data"
    expected_files = [
        "cloudflare_payload.json",
        "picks_today.json",
        "status_latest.json",
        "injury_invalidations_latest.json",
    ]
    return {
        "dashboard_root": str(dashboard),
        "exists": dashboard.exists(),
        "git_status": git_status(dashboard) if dashboard.exists() else None,
        "publish_script": str(dashboard / "publish-atlas.ps1"),
        "publish_script_exists": (dashboard / "publish-atlas.ps1").exists(),
        "public_data_files": {name: (public_data / name).exists() for name in expected_files},
    }


def read_log_tail(path: Path, max_lines: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return tail_lines([line.rstrip("\n") for line in f], max_lines)
    except OSError:
        return []


def run_status(task: Mapping[str, Any], paths: ListenerPaths) -> dict[str, Any]:
    include_git = bool(task.get("include_git", True))
    payload: dict[str, Any] = {
        "status": "completed",
        "latest_run": latest_run_summary(paths.root),
        "dashboard": dashboard_status(paths.root),
        "iael_log_tail": read_log_tail(paths.root / "data" / "telemetry" / "iael_runs.log"),
    }
    if include_git:
        payload["git_status"] = git_status(paths.root)
    return payload


def command_for_live_slot(root: Path, slot: str) -> list[str]:
    normalized = slot.strip().lower().replace(":", "").replace("-", "").replace("_", "")
    slot_map = {
        "8am": "run_iael_morning.cmd",
        "morning": "run_iael_morning.cmd",
        "11am": "run_iael_11am.cmd",
        "230pm": "run_iael_230pm.cmd",
        "2pm30": "run_iael_230pm.cmd",
        "530pm": "run_iael_530pm.cmd",
        "5pm30": "run_iael_530pm.cmd",
    }
    script = slot_map.get(normalized)
    if script is None:
        allowed = ", ".join(sorted(slot_map))
        raise ValueError(f"unsupported live slot '{slot}'. Allowed aliases: {allowed}")
    return ["cmd.exe", "/c", str(root / "scripts" / script)]


def run_known_command(task: Mapping[str, Any], paths: ListenerPaths, command: list[str], task_id: str) -> dict[str, Any]:
    dry_run = bool(task.get("dry_run", False))
    timeout_seconds = timeout_from_task(task)
    log_path = paths.logs / f"{task_id}.log"
    return run_command(
        command,
        root=paths.root,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )


def run_codex_handoff(task: Mapping[str, Any], paths: ListenerPaths, task_id: str) -> dict[str, Any]:
    prompt = str(task.get("prompt") or task.get("message") or "").strip()
    if not prompt:
        raise ValueError("codex_handoff requires a non-empty 'prompt' or 'message'")
    requested_by = str(task.get("requested_by") or "unknown")
    reason = str(task.get("reason") or "")
    target_repo = str(task.get("target_repo") or task.get("repo") or "atlas").strip().lower()
    if target_repo in {"atlas", "nba", "model"}:
        handoff_dir = paths.codex_handoffs
        resolved_target = "atlas"
    elif target_repo in {"dashboard", "atlas-dashboard", "website", "site"}:
        handoff_dir = dashboard_root(paths.root) / ".codex_handoffs"
        resolved_target = "atlas-dashboard"
    else:
        raise ValueError("codex_handoff target_repo must be 'atlas' or 'atlas-dashboard'")
    handoff_path = handoff_dir / f"{task_id}.md"
    if not bool(task.get("dry_run", False)):
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(
            "\n".join(
                [
                    f"# Codex Handoff: {task_id}",
                    "",
                    f"- requested_by: {requested_by}",
                    f"- created_at: {utc_now()}",
                    f"- target_repo: {resolved_target}",
                    f"- reason: {reason}",
                    "",
                    "## Prompt",
                    "",
                    prompt,
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
    return {
        "status": "dry_run" if bool(task.get("dry_run", False)) else "completed",
        "target_repo": resolved_target,
        "handoff_path": str(handoff_path),
    }


def execute_task(task: Mapping[str, Any], paths: ListenerPaths, task_id: str) -> dict[str, Any]:
    action = str(task.get("action") or "").strip().lower()
    if not action:
        raise ValueError("task is missing required 'action'")

    if action in {"noop", "ping"}:
        return {"status": "completed", "message": "ok"}
    if action in {"status", "latest_status"}:
        return run_status(task, paths)
    if action == "latest_run":
        return {"status": "completed", "latest_run": latest_run_summary(paths.root)}
    if action == "git_status":
        return {"status": "completed", "git_status": git_status(paths.root)}
    if action == "dashboard_status":
        return {"status": "completed", "dashboard": dashboard_status(paths.root)}
    if action == "dashboard_git_status":
        root = dashboard_root(paths.root)
        if not root.exists():
            raise FileNotFoundError(f"dashboard repo not found: {root}")
        return {"status": "completed", "dashboard_git_status": git_status(root)}
    if action == "run_6am_eval":
        return run_known_command(
            task,
            paths,
            ["cmd.exe", "/c", str(paths.root / "scripts" / "run_iael_6am_eval.cmd")],
            task_id,
        )
    if action == "run_live":
        slot = str(task.get("slot") or task.get("run") or "").strip()
        if not slot:
            raise ValueError("run_live requires a 'slot' value")
        return run_known_command(task, paths, command_for_live_slot(paths.root, slot), task_id)
    if action == "publish_dashboard":
        dashboard_script = dashboard_root(paths.root) / "publish-atlas.ps1"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "RemoteSigned",
            "-File",
            str(dashboard_script),
            "-AtlasRoot",
            str(paths.root),
        ]
        return run_known_command(task, paths, command, task_id)
    if action == "codex_handoff":
        return run_codex_handoff(task, paths, task_id)

    raise ValueError(f"unsupported action '{action}'")


def result_payload(
    *,
    task: Mapping[str, Any],
    task_id: str,
    source_path: Path,
    started_at: str,
    finished_at: str,
    result: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": task_id,
        "action": task.get("action"),
        "source_path": str(source_path),
        "started_at": started_at,
        "finished_at": finished_at,
        "request": redact(dict(task)),
    }
    if result is not None:
        payload.update(result)
    if error is not None:
        payload["status"] = "failed"
        payload["error"] = error
    return payload


def process_task_file(path: Path, paths: ListenerPaths) -> dict[str, Any]:
    started_at = utc_now()
    original_path = path
    task_id = sanitize_task_id(path.stem)
    task: dict[str, Any] = {}
    processing_path = paths.processing / path.name
    try:
        task = load_task(path)
        task_id = sanitize_task_id(task.get("id") or path.stem)
        processing_path = paths.processing / f"{task_id}.json"
        shutil.move(str(path), str(processing_path))
        result = execute_task(task, paths, task_id)
        finished_at = utc_now()
        payload = result_payload(
            task=task,
            task_id=task_id,
            source_path=processing_path,
            started_at=started_at,
            finished_at=finished_at,
            result=result,
        )
        write_json(paths.outbox / f"{task_id}.json", payload)
        write_json(paths.status, payload)
        processing_path.unlink(missing_ok=True)
        return payload
    except Exception as exc:
        finished_at = utc_now()
        if path.exists():
            failed_source = paths.failed / path.name
            shutil.move(str(path), str(failed_source))
        elif processing_path.exists():
            failed_source = paths.failed / processing_path.name
            shutil.move(str(processing_path), str(failed_source))
        else:
            failed_source = original_path
        payload = result_payload(
            task=task or {"id": task_id, "action": None},
            task_id=task_id,
            source_path=failed_source,
            started_at=started_at,
            finished_at=finished_at,
            error=str(exc),
        )
        write_json(paths.failed / f"{task_id}.result.json", payload)
        write_json(paths.status, payload)
        return payload


def process_once(paths: ListenerPaths, limit: int | None = None) -> list[dict[str, Any]]:
    paths.ensure()
    tasks = list_json_tasks(paths.inbox)
    if limit is not None:
        tasks = tasks[:limit]
    return [process_task_file(path, paths) for path in tasks]


def listen(paths: ListenerPaths, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> int:
    paths.ensure()
    print(f"[ATLAS_LISTENER] root={paths.root}", flush=True)
    print(f"[ATLAS_LISTENER] inbox={paths.inbox}", flush=True)
    print(
        "[ATLAS_LISTENER] actions=status, latest_run, git_status, dashboard_status, dashboard_git_status, "
        "run_6am_eval, run_live, publish_dashboard, codex_handoff",
        flush=True,
    )
    while True:
        results = process_once(paths)
        for result in results:
            print(
                f"[ATLAS_LISTENER] {result.get('id')} action={result.get('action')} status={result.get('status')}",
                flush=True,
            )
        time.sleep(poll_seconds)


def submit_task(args: argparse.Namespace, paths: ListenerPaths) -> Path:
    paths.ensure()
    task_id = sanitize_task_id(args.id or f"{args.action}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
    task: dict[str, Any] = {
        "id": task_id,
        "action": args.action,
        "requested_by": args.requested_by,
        "reason": args.reason,
    }
    if args.slot:
        task["slot"] = args.slot
    if args.prompt:
        task["prompt"] = args.prompt
    if args.target_repo:
        task["target_repo"] = args.target_repo
    if args.target_repo:
        task["target_repo"] = args.target_repo
    if args.dry_run:
        task["dry_run"] = True
    if args.timeout_seconds is not None:
        task["timeout_seconds"] = args.timeout_seconds
    out_path = paths.inbox / f"{task_id}.json"
    write_json(out_path, task)
    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atlas file-backed CLI listener")
    parser.add_argument("--root", default=os.getcwd(), help="Atlas repo root")
    parser.add_argument("--base", default=None, help="Listener base directory. Defaults to data/automation/cli_listener")
    sub = parser.add_subparsers(dest="command", required=True)

    once = sub.add_parser("once", help="Process currently queued tasks and exit")
    once.add_argument("--limit", type=int, default=None)

    listen_parser = sub.add_parser("listen", help="Run the listener loop")
    listen_parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)

    submit = sub.add_parser("submit", help="Write a task JSON into the listener inbox")
    submit.add_argument("action", help="Allowed listener action")
    submit.add_argument("--id", default=None)
    submit.add_argument("--slot", default=None, help="Live run slot for run_live")
    submit.add_argument("--prompt", default=None, help="Prompt/message for codex_handoff")
    submit.add_argument("--target-repo", default=None, help="Target repo for codex_handoff: atlas or atlas-dashboard")
    submit.add_argument("--target-repo", default=None, help="Target repo for codex_handoff: atlas or atlas-dashboard")
    submit.add_argument("--requested-by", default="local_cli")
    submit.add_argument("--reason", default="")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--timeout-seconds", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root)
    base = Path(args.base) if args.base else None
    paths = ListenerPaths.from_root(root, base)
    if args.command == "once":
        results = process_once(paths, limit=args.limit)
        print(json.dumps(results, indent=2, sort_keys=True), flush=True)
        return 0 if all(result.get("status") not in {"failed"} for result in results) else 1
    if args.command == "listen":
        return listen(paths, poll_seconds=args.poll_seconds)
    if args.command == "submit":
        path = submit_task(args, paths)
        print(path, flush=True)
        return 0
    parser.error(f"unsupported command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
