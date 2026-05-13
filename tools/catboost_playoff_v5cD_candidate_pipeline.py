#!/usr/bin/env python
"""Build a safe v5cD candidate cache and LODO report.

This keeps production untouched:
- copies the existing 10-date playoff replay corpus into a fresh candidate tag
- replays added dates with CatBoost disabled
- writes a separate cache pickle
- runs the v5cD LODO trainer against that cache
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = ROOT / "data" / "telemetry" / "replay_runs"
MODEL_CANDIDATES = ROOT / "data" / "model" / "candidates"
BASE_CORPUS_TAG = "atlas_replay_postkernel_20260510_130246"

BASE_DATES = [
    "20260430",
    "20260501",
    "20260502",
    "20260503",
    "20260504",
    "20260505",
    "20260506",
    "20260507",
    "20260508",
    "20260509",
]

# Candidate expansion dates. These are the operationally relevant report windows:
# - Sunday 2026-05-10: 2:30pm report window
# - Monday 2026-05-11: 5:30pm weekday report window
ADDED_REPLAYS = {
    "20260510": ROOT / "data" / "bundles" / "atlas_bundle_20260510_142919.zip",
    "20260511": ROOT / "data" / "bundles" / "atlas_bundle_20260511_173253.zip",
}


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("\n" + "=" * 80, flush=True)
    print(" ".join(str(x) for x in cmd), flush=True)
    print("=" * 80, flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def _safe_remove_candidate_dir(path: Path, tag: str) -> None:
    resolved = path.resolve()
    replay_resolved = REPLAY_ROOT.resolve()
    if replay_resolved not in resolved.parents:
        raise RuntimeError(f"Refusing to remove path outside replay root: {resolved}")
    if not path.name.startswith(f"{tag}_"):
        raise RuntimeError(f"Refusing to remove non-candidate path: {resolved}")
    shutil.rmtree(path)


def _copy_base_corpus(tag: str, *, force: bool) -> None:
    print("\n[CANDIDATE] Copying base 10-date corpus into candidate tag", flush=True)
    for date in BASE_DATES:
        src = REPLAY_ROOT / f"{BASE_CORPUS_TAG}_{date}"
        dst = REPLAY_ROOT / f"{tag}_{date}"
        if not src.is_dir():
            raise FileNotFoundError(f"Missing base corpus dir: {src}")
        if dst.exists():
            if force:
                _safe_remove_candidate_dir(dst, tag)
            else:
                raise FileExistsError(f"Candidate dir already exists: {dst} (use --force)")
        print(f"  {date}: {src.name} -> {dst.name}", flush=True)
        shutil.copytree(src, dst)


def _write_cat_off_config(candidate_dir: Path) -> Path:
    cfg_path = ROOT / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    cfg.setdefault("catboost_playoff_calibrator", {})["enabled"] = False
    cfg.setdefault("discord", {})["enabled"] = False
    cfg.setdefault("marketed_slips", {})["publish_to_latest"] = False

    out = candidate_dir / "config.catboost_off.yaml"
    out.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"\n[CANDIDATE] CatBoost-off config: {out}", flush=True)
    return out


def _replay_added_dates(tag: str, config_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import batch_replay_backfill as brb  # type: ignore[import]

    env_backup = os.environ.copy()
    try:
        os.environ["ATLAS_CONFIG_PATH"] = str(config_path)
        os.environ.pop("ATLAS_DISCORD_WEBHOOK", None)
        brb._write_corpus_tag(tag)

        print("\n[CANDIDATE] Replaying added dates with CatBoost disabled", flush=True)
        for date, bundle in ADDED_REPLAYS.items():
            if not bundle.is_file():
                raise FileNotFoundError(f"Missing replay bundle for {date}: {bundle}")
            dst = REPLAY_ROOT / f"{tag}_{date}"
            if dst.exists():
                _safe_remove_candidate_dir(dst, tag)
            print(f"\n[CANDIDATE] Replay {date}: {bundle.name}", flush=True)
            ok, msg = brb._replay_one(date, bundle_path=bundle, tag=tag)
            if not ok:
                raise RuntimeError(f"Replay failed for {date}: {msg}")
    finally:
        os.environ.clear()
        os.environ.update(env_backup)


def _write_manifest(candidate_dir: Path, tag: str, cache_path: Path, lodo_path: Path) -> None:
    payload = {
        "tag": tag,
        "base_corpus_tag": BASE_CORPUS_TAG,
        "base_dates": BASE_DATES,
        "added_replays": {date: str(path.relative_to(ROOT)) for date, path in ADDED_REPLAYS.items()},
        "catboost_disabled_for_added_replays": True,
        "cache_path": str(cache_path.relative_to(ROOT)),
        "lodo_path": str(lodo_path.relative_to(ROOT)),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    out = candidate_dir / "manifest.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[CANDIDATE] Manifest: {out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the v5cD 12-date CatBoost-off candidate experiment.")
    ap.add_argument(
        "--tag",
        default=f"atlas_replay_v5cD_12date_cat_off_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Candidate replay corpus tag.",
    )
    ap.add_argument("--force", action="store_true", help="Replace existing candidate dirs for this tag.")
    ap.add_argument(
        "--train-full",
        action="store_true",
        help="Also train a full-corpus candidate model after LODO. Default is LODO only.",
    )
    args = ap.parse_args()

    candidate_dir = MODEL_CANDIDATES / args.tag
    candidate_dir.mkdir(parents=True, exist_ok=True)
    cache_path = candidate_dir / "_v1_playoff_resim_cache_12date_cat_off.pkl"
    lodo_path = candidate_dir / "catboost_playoff_v5cD_iter600_12date_lodo.json"
    model_path = candidate_dir / "catboost_v5cD_12date_candidate.cbm"
    meta_path = candidate_dir / "catboost_v5cD_12date_candidate.meta.json"

    print("=" * 80, flush=True)
    print("v5cD 12-date candidate pipeline", flush=True)
    print("=" * 80, flush=True)
    print(f"Tag:       {args.tag}", flush=True)
    print(f"Artifacts: {candidate_dir}", flush=True)

    config_path = _write_cat_off_config(candidate_dir)
    _copy_base_corpus(args.tag, force=args.force)
    _replay_added_dates(args.tag, config_path)

    _run([
        sys.executable,
        "tools/build_playoff_resim_cache.py",
        "--prefix",
        f"{args.tag}_",
        "--cache-out",
        str(cache_path),
        "--force",
    ])

    _run([
        sys.executable,
        "tools/catboost_playoff_v5cD_iter600.py",
        "--cache-path",
        str(cache_path),
        "--out-path",
        str(lodo_path),
    ])

    if args.train_full:
        _run([
            sys.executable,
            "tools/catboost_playoff_v5cD_full_corpus.py",
            "--cache-path",
            str(cache_path),
            "--model-out",
            str(model_path),
            "--meta-out",
            str(meta_path),
            "--version",
            "catboost_playoff_v5cD_12date_candidate",
        ])
    else:
        print("\n[CANDIDATE] Full-corpus candidate model was not trained. Use --train-full after LODO passes.", flush=True)

    _write_manifest(candidate_dir, args.tag, cache_path, lodo_path)
    print("\n[CANDIDATE] Done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
