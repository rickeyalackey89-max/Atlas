"""Path helpers for the Atlas MLB development workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MlbPaths:
    repo_root: Path
    data_root: Path
    raw: Path
    staged: Path
    features: Path
    models: Path
    runs: Path
    replay_runs: Path
    corpus_replays: Path
    test_runs: Path
    live_runs: Path
    eval: Path
    archives: Path
    runtime_state: Path


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return current.parents[5]


def mlb_paths(root: Path | None = None) -> MlbPaths:
    base = root or repo_root()
    data_root = base / "data" / "mlb"
    return MlbPaths(
        repo_root=base,
        data_root=data_root,
        raw=data_root / "raw",
        staged=data_root / "staged",
        features=data_root / "features",
        models=data_root / "model",
        runs=data_root / "replay_runs",
        replay_runs=data_root / "replay_runs",
        corpus_replays=data_root / "corpus_replays",
        test_runs=data_root / "test_runs",
        live_runs=data_root / "live_runs",
        eval=data_root / "eval",
        archives=data_root / "archives",
        runtime_state=data_root / "runtime_state",
    )


def output_runs_dir(paths: MlbPaths, run_mode: str | None = None) -> Path:
    """Return the run artifact root for a live or replay/test run."""

    return paths.live_runs if str(run_mode or "").strip().lower() == "live" else paths.replay_runs


def candidate_run_dirs(paths: MlbPaths) -> tuple[Path, ...]:
    """Return run roots in lookup order, including the legacy development path."""

    legacy_runs = paths.data_root / "runs"
    candidates = (paths.replay_runs, paths.live_runs, paths.test_runs, legacy_runs)
    return tuple(dict.fromkeys(candidates))


def ensure_mlb_dirs(root: Path | None = None) -> MlbPaths:
    paths = mlb_paths(root)
    for path in (
        paths.raw,
        paths.staged,
        paths.features,
        paths.models,
        paths.replay_runs,
        paths.corpus_replays,
        paths.test_runs,
        paths.live_runs,
        paths.eval,
        paths.archives,
        paths.runtime_state,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths
