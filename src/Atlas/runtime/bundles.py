from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_write_file(z: zipfile.ZipFile, src: Path, arcname: str) -> Dict[str, object]:
    """
    Write a file to zip and return metadata (sha256, bytes).
    """
    z.write(src, arcname)
    return {"sha256": _sha256_file(src), "bytes": int(src.stat().st_size)}


def _pick_latest_run_id(runs_dir: Path) -> Optional[str]:
    if not runs_dir.exists():
        return None
    best = None
    best_mtime = None
    for d in runs_dir.iterdir():
        if not d.is_dir():
            continue
        try:
            m = d.stat().st_mtime
        except OSError:
            continue
        if best is None or best_mtime is None or m > best_mtime:
            best = d.name
            best_mtime = m
    return best


def _pinned_role_metrics_files(data_dir: Path, run_id: str) -> List[Tuple[Path, str]]:
    pin_dir = data_dir / "archives" / "pins" / run_id
    if not pin_dir.is_dir():
        return []

    pinned: List[Tuple[Path, str]] = []
    for src_name, arc_name in (
        ("role_metrics_latest.json", "dashboard/role_metrics_latest.json"),
        ("role_metrics_latest.html", "dashboard/role_metrics_latest.html"),
        ("role_metrics_snapshot_manifest.json", "dashboard/role_metrics_snapshot_manifest.json"),
    ):
        src = pin_dir / src_name
        if src.exists() and src.is_file():
            pinned.append((src, arc_name))
    return pinned


def write_bundle_zip(
    *,
    repo_root: Path,
    data_dir: Path,
    run_id: str,
    ok: bool,
    engine_entry: str,
    raw_path: Optional[Path] = None,
    # Back-compat: callers may pass these names. We honor them if provided.
    iael_live_dir: Optional[Path] = None,
    guardrail_state_path: Optional[Path] = None,
    run_dir: Optional[Path] = None,
    extra_manifest: Optional[dict] = None,
    # Back-compat: ignore unknown kwargs without failing live runs.
    **_ignored: object,
) -> Path:
    """
    Phase 7C: emit a zip-only bundle to data/bundles.

    IMPORTANT: Bundle content is allowlist-only to prevent runaway size.
    Manifest is written exactly once (no duplicate 'manifest.json').
    """
    repo_root = Path(repo_root)
    data_dir = Path(data_dir)

    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)

    suffix = "" if ok else "__DEAD_PERIOD"
    zip_path = bundles_dir / f"atlas_bundle_{run_id}{suffix}.zip"
    tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")

    # Resolve canonical paths (best-effort, allow overrides)
    runs_root = data_dir / "output" / "runs"
    if run_dir is None:
        run_dir = runs_root / run_id
    else:
        run_dir = Path(run_dir)

    iael_live = Path(iael_live_dir) if iael_live_dir is not None else (data_dir / "iael" / "live")

    guardrail_state_candidates: List[Path] = []
    if guardrail_state_path is not None:
        guardrail_state_candidates.append(Path(guardrail_state_path))

    guardrail_state_candidates.extend(
        [
            run_dir / "audit" / "guardrail_state.json",
            run_dir / "guardrail_state.json",
            data_dir / "output" / "dashboard" / "guardrail_state.json",
            data_dir / "output" / "dashboard" / "guardrail_state_latest.json",
        ]
    )

    # Build allowlist (src_path, arcname)
    allow: List[Tuple[Path, str]] = []

    # Raw snapshot: only if explicitly provided and exists
    if raw_path:
        raw_path = Path(raw_path)
        if raw_path.exists() and raw_path.is_file():
            allow.append((raw_path, f"raw/{raw_path.name}"))

    # IAEL live minimal
    iael_status = iael_live / "status.json"
    iael_invalid = iael_live / "injury_invalidations.json"
    if iael_status.exists():
        allow.append((iael_status, "iael/live/status.json"))
    if iael_invalid.exists():
        allow.append((iael_invalid, "iael/live/injury_invalidations.json"))

    # Guardrail state (first existing)
    for cand in guardrail_state_candidates:
        if cand.exists() and cand.is_file():
            allow.append((cand, "audit/guardrail_state.json"))
            break

    # Per-run IAEL snapshot artifacts (live run / replay / backtest compatibility)
    if run_dir.exists():
        dashboard_dir = run_dir / "dashboard"
        for src_name, arc_name in (
            ("injury_invalidations_latest.json", "dashboard/injury_invalidations_latest.json"),
            ("status_latest.json", "dashboard/status_latest.json"),
            ("injury_snapshot_manifest.json", "dashboard/injury_snapshot_manifest.json"),
            ("role_metrics_latest.json", "dashboard/role_metrics_latest.json"),
            ("role_metrics_latest.html", "dashboard/role_metrics_latest.html"),
            ("role_metrics_snapshot_manifest.json", "dashboard/role_metrics_snapshot_manifest.json"),
        ):
            src = dashboard_dir / src_name
            if src.exists() and src.is_file():
                allow.append((src, arc_name))

    # Role-metrics fallback: package the run-pinned snapshot when the run dashboard copy is absent.
    allow.extend(_pinned_role_metrics_files(data_dir, run_id))


    # Minimal deterministic inputs for strict replay (small allowlist)
    # Note: these are inputs, not "outputs". Run CSV artifacts remain under data/output/runs only.
    # replay_bundle.py expects these filenames (found via rglob), so any arcname is acceptable.
    inputs_allow = [
        (data_dir / "board" / "today.csv", "data/board/today.csv"),
        (data_dir / "gamelogs" / "nba_gamelogs.csv", "data/gamelogs/nba_gamelogs.csv"),
        (data_dir / "input" / "roster_map.csv", "data/input/roster_map.csv"),
        (data_dir / "input" / "slate.csv", "data/input/slate.csv"),
    ]
    for p, arc in inputs_allow:
        if p.exists() and p.is_file():
            allow.append((p, arc))

    # If external priors are present, include them (small, improves determinism)
    for p in (
        data_dir / "input" / "external_priors_today.yaml",
        data_dir / "input" / "external_priors_today.csv",
        data_dir / "input" / "bettingpros_props_today.csv",
        data_dir / "input" / "odds_market_today.json",
        data_dir / "input" / "rotowire_lines.json",
    ):
        if p.exists() and p.is_file():
            allow.append((p, f"data/input/{p.name}"))

    # FULL_RUN artifacts
    # Intentionally NOT bundled:
    # - output/runs/<run_id>/* (rebuilable, large, belongs in data/output/runs)
    # - scored_legs / recommended slips
    # Bundles are atomic telemetry units (inputs + minimal state only).

    # DEAD_PERIOD artifacts: keep minimal (already: iael + guardrail)
    # Do NOT include any audit directory tree, import traces, modifiers maps, etc.

    # De-dupe allowlist by arcname (keep first)
    seen_arc = set()
    allow2: List[Tuple[Path, str]] = []
    for src, arc in allow:
        if arc == "manifest.json":
            # never allow manifest from disk
            continue
        if arc in seen_arc:
            continue
        seen_arc.add(arc)
        allow2.append((src, arc))

    files_meta: Dict[str, Dict[str, object]] = {}

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        # Write all allowlisted files first, collecting hashes
        for src, arc in allow2:
            try:
                files_meta[arc] = _zip_write_file(z, src, arc)
            except Exception:
                # Best-effort: skip any missing/unreadable file
                continue

        # Manifest last, exactly once
        manifest = {
            "schema_version": 2,
            "generated_at_utc": _now_utc_iso(),
            "bundle_id": zip_path.name,
            "run_id": run_id,
            "ok": bool(ok),
            "engine_entry": engine_entry,
            "paths": {
                "data_dir": str(data_dir),
            },
            "files": files_meta,
        }
        if raw_path:
            manifest["paths"]["raw_snapshot"] = str(raw_path)
            manifest["paths"]["raw_snapshot_arc"] = f"raw/{Path(raw_path).name}"
        if extra_manifest:
            manifest.update(extra_manifest)

        z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    if zip_path.exists():
        zip_path.unlink()
    tmp_path.replace(zip_path)
    return zip_path
