from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from Atlas.runtime.replay_eval import backfill_latest_replay_eval_legs


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return start.resolve()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _resolve_bundle_path(repo_root: Path, bundle: str) -> Path:
    """Resolve a bundle zip path from either a full path, a filename, or a run-id."""
    p = Path(bundle).expanduser()
    if p.suffix.lower() == ".zip" and p.is_file():
        return p.resolve()

    bundles_dir = repo_root / "data" / "bundles"

    # Accept 'atlas_bundle_<id>.zip'
    if bundle.lower().endswith(".zip"):
        cand = bundles_dir / bundle
        if cand.is_file():
            return cand.resolve()

    # Accept bare run id like '20260219_062634'
    cand = bundles_dir / f"atlas_bundle_{bundle}.zip"
    if cand.is_file():
        return cand.resolve()

    raise FileNotFoundError(f"Could not find bundle zip for: {bundle} (looked in {bundles_dir})")


def _extract_bundle(bundle_zip: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_zip, "r") as z:
        z.extractall(dest_dir)


def _find_unique_file(root: Path, filename: str, *, parent_name: str | None = None) -> Path | None:
    matches = [p for p in root.rglob(filename) if p.is_file()]
    if parent_name is not None:
        matches = [p for p in matches if p.parent.name == parent_name]
    if len(matches) == 1:
        return matches[0].resolve()
    return None


def _find_dashboard_snapshot_dir(data_dir: Path) -> Path | None:
    candidates: list[Path] = []
    runs_root = data_dir / "output" / "runs"
    if runs_root.is_dir():
        for run_dir in runs_root.iterdir():
            dash = run_dir / "dashboard"
            if (
                dash.is_dir()
                and (dash / "injury_invalidations_latest.json").is_file()
                and (dash / "status_latest.json").is_file()
                and (dash / "normalized_latest.json").is_file()
            ):
                candidates.append(dash)

    if candidates:
        candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
        return candidates[0].resolve()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Atlas sandbox replay from a FULL_RUN bundle zip (bundle-first, deterministic)."
    )
    ap.add_argument(
        "bundle",
        help=(
            "Bundle id or path. Examples: 20260219_062634, atlas_bundle_20260219_062634.zip, or full path to a .zip"
        ),
    )
    ap.add_argument("--scenario-id", default="", help="Scenario id used for output/archives folder naming.")
    ap.add_argument("--keep-workspace", action="store_true", help="Keep extracted bundle workspace (debug).")
    args = ap.parse_args()

    repo_root = find_repo_root(Path(__file__).parent)
    bundle_zip = _resolve_bundle_path(repo_root, args.bundle)

    scenario_id = (args.scenario_id or bundle_zip.stem).replace(" ", "_")
    ts = _utc_stamp()

    analysis_root = repo_root / "archives" / "bundles" / scenario_id / "analysis" / ts
    workspace = analysis_root / "workspace"
    logs_dir = analysis_root / "logs"

    # Replay contract: outputs go to data/telemetry/replay_runs/<scenario_id>/<ts>/...
    out_dir = (repo_root / "data" / "telemetry" / "replay_runs" / scenario_id / ts).resolve()

    workspace.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    _extract_bundle(bundle_zip, workspace)

    data_dir = workspace / "data"
    if not data_dir.is_dir():
        # Older bundles may nest; try best-effort search
        candidates = [p for p in workspace.rglob("data") if p.is_dir() and (p / "board").is_dir()]
        if candidates:
            data_dir = candidates[0]
        else:
            raise FileNotFoundError(f"Bundle extract missing expected 'data/' folder: {bundle_zip}")

    replay_truth_path = repo_root / "data" / "telemetry" / "Last 10" / "Last10.csv"

    # Prefer bundled gamelogs, fall back to repo cache for reconstruction-only fallback.
    bundled_gamelogs = data_dir / "gamelogs" / "nba_gamelogs.csv"
    repo_gamelogs = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    gamelogs_path = bundled_gamelogs if bundled_gamelogs.is_file() else repo_gamelogs
    if not gamelogs_path.is_file():
        print(f"[REPLAY_BUNDLE] Missing gamelogs: {bundled_gamelogs} and {repo_gamelogs}")
        return 2

    env = os.environ.copy()
    env["ATLAS_AUTHORITY"] = "replay"
    env["ATLAS_STRICT_REPLAY"] = "1"
    env["ATLAS_DATA_DIR"] = str(data_dir)
    env["ATLAS_OUT_DIR"] = str(out_dir)
    env["ATLAS_GAMELOGS_PATH"] = str(gamelogs_path)

    raw_path = _find_unique_file(data_dir, "*.json", parent_name="raw")
    if raw_path is not None:
        env["ATLAS_REPLAY_RAW"] = str(raw_path)

    rotowire_path = _find_unique_file(data_dir, "rotowire_lines.json", parent_name="input")
    if rotowire_path is not None:
        env["ATLAS_ROTOWIRE_LINES_PATH"] = str(rotowire_path)

    snapshot_dir = _find_dashboard_snapshot_dir(data_dir)
    if snapshot_dir is not None:
        env["ATLAS_IAEL_SNAPSHOT_DIR"] = str(snapshot_dir)
        env["ATLAS_IAEL_INVALIDATIONS_PATH"] = str(snapshot_dir / "injury_invalidations_latest.json")
        env["ATLAS_IAEL_STATUS_PATH"] = str(snapshot_dir / "status_latest.json")
        env["ATLAS_IAEL_NORMALIZED_PATH"] = str(snapshot_dir / "normalized_latest.json")

    cmd = [sys.executable, "-m", "Atlas.engine.main"]

    stdout_path = logs_dir / "engine_stdout.txt"
    stderr_path = logs_dir / "engine_stderr.txt"

    print(f"[REPLAY_BUNDLE] bundle={bundle_zip}")
    print(f"[REPLAY_BUNDLE] scenario_id={scenario_id}")
    print(f"[REPLAY_BUNDLE] analysis_root={analysis_root}")
    print(f"[REPLAY_BUNDLE] data_dir={data_dir}")
    print(f"[REPLAY_BUNDLE] out_dir={out_dir}")
    print(f"[REPLAY_BUNDLE] running: {' '.join(cmd)}")

    p = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    stdout_path.write_text(p.stdout or "", encoding="utf-8")
    stderr_path.write_text(p.stderr or "", encoding="utf-8")

    print(f"[REPLAY_BUNDLE] exit_code={p.returncode}")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").splitlines()[-40:])
        print("[REPLAY_BUNDLE] engine stderr tail:")
        print(tail)
        return p.returncode

    eval_path = backfill_latest_replay_eval_legs(
        output_root=out_dir,
        gamelogs_path=[replay_truth_path, bundled_gamelogs, repo_gamelogs],
        repo_root=repo_root,
        python_executable=sys.executable,
    )
    print(f"[REPLAY_BUNDLE] eval_legs={eval_path}")

    print("[REPLAY_BUNDLE] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
