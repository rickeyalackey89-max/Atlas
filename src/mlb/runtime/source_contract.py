"""Strict source-contract guards for MLB live-fidelity replay artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.runtime.fidelity import normalize_run_mode


def enforce_replay_source_contract(source_manifest: dict[str, Any], *, context: str = "") -> None:
    """Raise when a replay run does not satisfy the live-fidelity source contract."""
    run_mode = normalize_run_mode(str(source_manifest.get("run_mode") or "replay_single"))
    if run_mode == "live":
        return
    if str(source_manifest.get("contract_status") or "") != "fail":
        return
    run_id = str(source_manifest.get("run_id") or "")
    failures = [
        warning
        for warning in source_manifest.get("warnings", [])
        if isinstance(warning, dict) and warning.get("severity") != "timing_warning"
    ]
    failure_codes = _summarize_failures(failures)
    manifest_path = str(source_manifest.get("manifest_path") or "")
    suffix = f" ({context})" if context else ""
    raise RuntimeError(
        "MLB replay fidelity source contract failed"
        f"{suffix}: run_id={run_id or 'unknown'} status=fail "
        f"failures={len(failures)} top={failure_codes} manifest={manifest_path}"
    )


def enforce_corpus_source_contracts(corpus_dir: Path, *, root: Path | None = None) -> None:
    """Reject corpus aggregation/training if any member run has a failed source contract."""
    failed: list[str] = []
    run_paths = sorted(corpus_dir.glob("replay_single_*.run.json"))
    if not run_paths and any(corpus_dir.glob("replay_single_*.eval.json")):
        raise RuntimeError(
            "MLB corpus rejected by strict replay fidelity source contract: "
            f"no run manifests with source_selection were found in {corpus_dir}"
        )
    for run_path in run_paths:
        payload = _load_json(run_path)
        source_manifest = _source_manifest_from_run_payload(payload, run_path=run_path, root=root)
        if not source_manifest:
            failed.append(f"{run_path.name}: missing source_selection")
            continue
        if str(source_manifest.get("contract_status") or "") == "fail":
            failures = [
                warning
                for warning in source_manifest.get("warnings", [])
                if isinstance(warning, dict) and warning.get("severity") != "timing_warning"
            ]
            failed.append(
                f"{run_path.name}: failures={len(failures)} top={_summarize_failures(failures)}"
            )
    if failed:
        preview = "; ".join(failed[:8])
        extra = f"; +{len(failed) - 8} more" if len(failed) > 8 else ""
        raise RuntimeError(
            "MLB corpus rejected by strict replay fidelity source contract: "
            f"{len(failed)} failed member(s): {preview}{extra}"
        )


def _source_manifest_from_run_payload(
    payload: dict[str, Any],
    *,
    run_path: Path,
    root: Path | None,
) -> dict[str, Any] | None:
    source_manifest = payload.get("source_selection")
    if isinstance(source_manifest, dict) and source_manifest:
        return source_manifest
    candidate_paths: list[Path] = []
    manifest_path = str((source_manifest or {}).get("manifest_path") if isinstance(source_manifest, dict) else "")
    if manifest_path:
        candidate_paths.append(_resolve_path(manifest_path, root=root))
    run_id = str(payload.get("run_id") or run_path.name.removesuffix(".run.json"))
    candidate_paths.append(run_path.parent / run_id / "source_selection_manifest.json")
    candidate_paths.append(run_path.parent / "source_selection_manifest.json")
    for path in candidate_paths:
        if path.exists():
            return _load_json(path)
    return None


def _resolve_path(value: str, *, root: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute() or root is None:
        return path
    return root / path


def _summarize_failures(failures: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for failure in failures:
        code = str(failure.get("code") or "unknown")
        source = str(failure.get("source") or "")
        key = f"{code}:{source}" if source else code
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "none"
    return ",".join(f"{key}={value}" for key, value in sorted(counts.items())[:8])


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return dict(json.loads(raw.decode(encoding)))
        except (UnicodeDecodeError, ValueError, TypeError):
            continue
    return dict(json.loads(raw.decode("utf-8", errors="replace")))
