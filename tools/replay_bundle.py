from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


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

    # SBX contract: outputs go to data/output/sandbox_runs/<scenario_id>/<ts>/...
    out_dir = (repo_root / "data" / "output" / "sandbox_runs" / scenario_id / ts).resolve()

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

    # Prefer bundled gamelogs, fall back to repo cache
    bundled_gamelogs = data_dir / "gamelogs" / "nba_gamelogs.csv"
    repo_gamelogs = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
    gamelogs_path = bundled_gamelogs if bundled_gamelogs.is_file() else repo_gamelogs
    if not gamelogs_path.is_file():
        print(f"[REPLAY_BUNDLE] Missing gamelogs: {bundled_gamelogs} and {repo_gamelogs}")
        return 2

    env = os.environ.copy()
    env["ATLAS_DATA_DIR"] = str(data_dir)
    env["ATLAS_OUT_DIR"] = str(out_dir)
    env["ATLAS_GAMELOGS_PATH"] = str(gamelogs_path)

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

    print("[REPLAY_BUNDLE] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
