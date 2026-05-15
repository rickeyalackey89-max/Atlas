from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from Atlas.runtime.slip_eval import write_eval_slips_for_run


def _normalize_gamelog_candidates(gamelogs_path: Path | list[Path] | tuple[Path, ...]) -> list[Path]:
    if isinstance(gamelogs_path, Path):
        return [gamelogs_path]
    ordered: list[Path] = []
    seen: set[str] = set()
    for path in gamelogs_path:
        key = str(path)
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    return ordered


def _eval_has_matched_rows(run_dir: Path) -> bool:
    report_path = run_dir / "eval_legs_reconstruction_report.json"
    if not report_path.is_file():
        return False
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    report = payload.get("report") or {}
    matched_rows = report.get("matched_rows")
    try:
        return int(matched_rows) > 0
    except Exception:
        return False


def _candidate_run_dirs(output_root: Path) -> list[Path]:
    candidates: list[Path] = []

    if (output_root / "scored_legs_deduped.csv").is_file():
        candidates.append(output_root)

    runs_root = output_root / "runs"
    if runs_root.is_dir():
        for run_dir in runs_root.iterdir():
            if run_dir.is_dir() and (run_dir / "scored_legs_deduped.csv").is_file():
                candidates.append(run_dir)

    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return candidates


def find_latest_replay_run_dir(output_root: Path) -> Path:
    candidates = _candidate_run_dirs(output_root)
    if not candidates:
        raise FileNotFoundError(f"No replay run with scored_legs_deduped.csv found under {output_root}")
    return candidates[0].resolve()


def backfill_eval_legs_for_run(
    *,
    run_dir: Path,
    gamelogs_path: Path | list[Path] | tuple[Path, ...],
    repo_root: Path,
    python_executable: str | None = None,
) -> Path:
    eval_path = run_dir / "eval_legs.csv"
    if eval_path.is_file() and _eval_has_matched_rows(run_dir):
        write_eval_slips_for_run(run_dir)
        return eval_path.resolve()

    scored_path = run_dir / "scored_legs_deduped.csv"
    tool_path = repo_root / "tools" / "create_eval_leg_backtestv2.py"
    report_path = run_dir / "eval_legs_reconstruction_report.json"

    if not scored_path.is_file():
        raise FileNotFoundError(f"Missing scored_legs_deduped.csv in replay run: {run_dir}")
    if not tool_path.is_file():
        raise FileNotFoundError(f"Missing eval reconstruction tool: {tool_path}")

    gamelog_candidates = [path for path in _normalize_gamelog_candidates(gamelogs_path) if path.is_file()]
    if not gamelog_candidates:
        raise FileNotFoundError(f"Missing replay gamelogs for eval reconstruction: {gamelogs_path}")

    failures: list[str] = []
    for candidate in gamelog_candidates:
        if eval_path.exists():
            eval_path.unlink()
        if report_path.exists():
            report_path.unlink()

        cmd = [
            python_executable or sys.executable,
            str(tool_path),
            "--run-dir",
            str(run_dir),
            "--gamelogs-path",
            str(candidate),
        ]
        completed = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            failures.append(f"{candidate}: {detail}")
            continue
        if eval_path.is_file() and _eval_has_matched_rows(run_dir):
            write_eval_slips_for_run(run_dir)
            return eval_path.resolve()
        failures.append(f"{candidate}: reconstruction wrote no matched eval rows")

    raise RuntimeError(f"Replay eval reconstruction failed for {run_dir}: {'; '.join(failures)}")


def backfill_latest_replay_eval_legs(
    *,
    output_root: Path,
    gamelogs_path: Path | list[Path] | tuple[Path, ...],
    repo_root: Path,
    python_executable: str | None = None,
) -> Path:
    run_dir = find_latest_replay_run_dir(output_root)
    return backfill_eval_legs_for_run(
        run_dir=run_dir,
        gamelogs_path=gamelogs_path,
        repo_root=repo_root,
        python_executable=python_executable,
    )
