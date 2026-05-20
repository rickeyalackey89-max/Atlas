"""Durable running state for MLB live and replay operations.

Large run folders are rebuild/debug artifacts. This module keeps the compact
state that should survive artifact compaction: source manifests, market priors,
and settled eval rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from mlb.runtime.paths import ensure_mlb_dirs

RUNTIME_STATE_VERSION = "atlas_mlb_runtime_state_v1"

MARKET_PRIOR_KEY_FIELDS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_name",
    "market",
    "line",
    "tier",
)

EVAL_LEG_KEY_FIELDS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_name",
    "market",
    "line",
    "side",
)

EVAL_SLIP_KEY_FIELDS = (
    "run_id",
    "family",
    "label",
    "slip_id",
)


def publish_run_runtime_state(
    *,
    run_manifest: dict[str, Any] | Path,
    root: Path | None = None,
) -> dict[str, Any]:
    """Publish compact durable state from a completed live/replay run manifest."""

    paths = ensure_mlb_dirs(root)
    manifest = _load_manifest(run_manifest)
    run_id = str(manifest.get("run_id") or "")
    state_root = paths.runtime_state
    state_root.mkdir(parents=True, exist_ok=True)

    writes: dict[str, Any] = {}
    writes["run_summary"] = _append_jsonl_by_key(
        state_root / "runs" / "run_summaries.jsonl",
        [_run_summary_record(manifest)],
        key_field="run_id",
    )

    source_manifest_path = _source_manifest_path(manifest, root=paths.repo_root)
    if source_manifest_path and source_manifest_path.exists():
        source_payload = _load_json(source_manifest_path)
        writes["source_manifest"] = _append_jsonl_by_key(
            state_root / "source_manifests" / "source_manifests_running.jsonl",
            [_source_manifest_record(source_payload, source_manifest_path=source_manifest_path)],
            key_field="run_id",
        )
        _copy_latest(source_manifest_path, state_root / "source_manifests" / "latest_source_selection_manifest.json")

    market_csv = _manifest_path(manifest, "market_context", "csv_path", root=paths.repo_root)
    if market_csv and market_csv.exists():
        writes["market_priors"] = _append_csv_by_key(
            source_csv=market_csv,
            dest_csv=state_root / "market_priors" / "market_priors_running.csv",
            key_fields=MARKET_PRIOR_KEY_FIELDS,
        )
        _copy_latest(market_csv, state_root / "market_priors" / "latest_market_priors.csv")

    eval_manifest = manifest.get("eval") if isinstance(manifest.get("eval"), dict) else None
    if eval_manifest:
        writes["eval"] = publish_eval_runtime_state(eval_manifest=eval_manifest, root=paths.repo_root)

    return _write_runtime_state_manifest(paths.runtime_state, run_id=run_id, writes=writes)


def publish_eval_runtime_state(
    *,
    eval_manifest: dict[str, Any] | Path,
    root: Path | None = None,
) -> dict[str, Any]:
    """Append settled eval rows to durable running eval files."""

    paths = ensure_mlb_dirs(root)
    manifest = _load_manifest(eval_manifest)
    run_id = str(manifest.get("run_id") or "")
    eval_root = paths.runtime_state / "eval"
    writes: dict[str, Any] = {}

    eval_legs_csv = _path_from_manifest(manifest, "csv_path", root=paths.repo_root)
    if eval_legs_csv and eval_legs_csv.exists():
        writes["eval_legs"] = _append_csv_by_key(
            source_csv=eval_legs_csv,
            dest_csv=eval_root / "eval_legs_running.csv",
            key_fields=EVAL_LEG_KEY_FIELDS,
        )
        _copy_latest(eval_legs_csv, eval_root / "latest_eval_legs.csv")

    slip_eval = manifest.get("slip_eval") if isinstance(manifest.get("slip_eval"), dict) else {}
    eval_slips_csv = _path_from_manifest(slip_eval, "eval_slips_csv_path", root=paths.repo_root)
    if eval_slips_csv and eval_slips_csv.exists():
        writes["eval_slips"] = _append_csv_by_key(
            source_csv=eval_slips_csv,
            dest_csv=eval_root / "eval_slips_running.csv",
            key_fields=EVAL_SLIP_KEY_FIELDS,
        )
        _copy_latest(eval_slips_csv, eval_root / "latest_eval_slips.csv")

    summary_path = _path_from_manifest(manifest, "summary_path", root=paths.repo_root)
    if summary_path and summary_path.exists():
        _copy_latest(summary_path, eval_root / "latest_eval_summary.json")

    slip_eval_json = _path_from_manifest(slip_eval, "slip_eval_path", root=paths.repo_root)
    if slip_eval_json and slip_eval_json.exists():
        _copy_latest(slip_eval_json, eval_root / "latest_slip_eval.json")

    writes["daily_summary"] = _append_jsonl_by_key(
        eval_root / "daily_eval_summary.jsonl",
        [_eval_summary_record(manifest)],
        key_field="run_id",
    )
    return _write_runtime_state_manifest(paths.runtime_state, run_id=run_id, writes={"eval": writes})


def _run_summary_record(manifest: dict[str, Any]) -> dict[str, Any]:
    operator = manifest.get("operator") if isinstance(manifest.get("operator"), dict) else {}
    score = manifest.get("score") if isinstance(manifest.get("score"), dict) else {}
    slips = manifest.get("slips") if isinstance(manifest.get("slips"), dict) else {}
    features = manifest.get("features") if isinstance(manifest.get("features"), dict) else {}
    source_selection = manifest.get("source_selection") if isinstance(manifest.get("source_selection"), dict) else {}
    return {
        "run_id": str(manifest.get("run_id") or ""),
        "run_mode": str(manifest.get("run_mode") or ""),
        "game_date": str(manifest.get("game_date_filter") or ""),
        "mlb_config_version": str(manifest.get("mlb_config_version") or _nested(manifest, "mlb_config", "config_version")),
        "calibration_version": str(_nested(manifest, "parameter_calibration", "calibration_version") or ""),
        "score_count": int(score.get("row_count") or 0),
        "slip_count": int(slips.get("slip_count") or 0),
        "source_contract_status": str(source_selection.get("contract_status") or ""),
        "source_contract_warning_count": int(source_selection.get("warning_count") or 0),
        "source_completeness": features.get("source_completeness") if isinstance(features, dict) else {},
        "publish_allowed": bool(operator.get("publish_allowed")),
        "operator_severity": str(operator.get("severity") or ""),
        "run_manifest_path": str(manifest.get("manifest_path") or ""),
        "published_at_utc": _utc_now(),
    }


def _source_manifest_record(payload: dict[str, Any], *, source_manifest_path: Path) -> dict[str, Any]:
    return {
        "run_id": str(payload.get("run_id") or ""),
        "run_mode": str(payload.get("run_mode") or ""),
        "game_date": str(payload.get("game_date") or ""),
        "contract_status": str(payload.get("contract_status") or ""),
        "warning_count": int(payload.get("warning_count") or 0),
        "failure_count": int(payload.get("failure_count") or 0),
        "timing_warning_count": int(payload.get("timing_warning_count") or 0),
        "market_sources": payload.get("market_sources") if isinstance(payload.get("market_sources"), dict) else {},
        "context_sources": payload.get("context_sources") if isinstance(payload.get("context_sources"), dict) else {},
        "source_completeness": payload.get("source_completeness") if isinstance(payload.get("source_completeness"), dict) else {},
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "source_manifest_path": str(source_manifest_path),
        "published_at_utc": _utc_now(),
    }


def _eval_summary_record(manifest: dict[str, Any]) -> dict[str, Any]:
    slip_eval = manifest.get("slip_eval") if isinstance(manifest.get("slip_eval"), dict) else {}
    return {
        "run_id": str(manifest.get("run_id") or ""),
        "source_run_id": str(manifest.get("source_run_id") or ""),
        "dates": manifest.get("dates") if isinstance(manifest.get("dates"), list) else [],
        "row_count": int(manifest.get("row_count") or 0),
        "settled_count": int(manifest.get("settled_count") or 0),
        "metric_count": int(manifest.get("metric_count") or 0),
        "win_rate": _optional_float(manifest.get("win_rate")),
        "brier": _optional_float(manifest.get("brier")),
        "logloss": _optional_float(manifest.get("logloss")),
        "result_counts": manifest.get("result_counts") if isinstance(manifest.get("result_counts"), dict) else {},
        "slip_count": int(slip_eval.get("slip_count") or 0),
        "slip_win_rate": _optional_float(slip_eval.get("win_rate")),
        "slip_result_counts": slip_eval.get("result_counts") if isinstance(slip_eval.get("result_counts"), dict) else {},
        "eval_manifest_path": str(manifest.get("manifest_path") or ""),
        "published_at_utc": _utc_now(),
    }


def _append_csv_by_key(*, source_csv: Path, dest_csv: Path, key_fields: Iterable[str]) -> dict[str, Any]:
    source_rows, source_header = _read_csv(source_csv)
    existing_rows, existing_header = _read_csv(dest_csv) if dest_csv.exists() else ([], [])
    rows_by_key: dict[str, dict[str, str]] = {}
    for row in existing_rows:
        rows_by_key[_row_key(row, key_fields)] = row
    for row in source_rows:
        rows_by_key[_row_key(row, key_fields)] = row

    header = _merge_headers(existing_header, source_header, rows=rows_by_key.values())
    dest_csv.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_csv.with_suffix(dest_csv.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for row in rows_by_key.values():
            writer.writerow({key: row.get(key, "") for key in header})
    tmp.replace(dest_csv)
    return {
        "path": str(dest_csv),
        "source_path": str(source_csv),
        "source_rows": len(source_rows),
        "total_rows": len(rows_by_key),
        "sha256": _sha256(dest_csv),
    }


def _append_jsonl_by_key(path: Path, records: list[dict[str, Any]], *, key_field: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_key: dict[str, dict[str, Any]] = {}
    if path.exists():
        for row in _read_jsonl(path):
            key = str(row.get(key_field) or _stable_json_hash(row))
            rows_by_key[key] = row
    for record in records:
        key = str(record.get(key_field) or _stable_json_hash(record))
        rows_by_key[key] = record
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows_by_key.values():
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return {"path": str(path), "total_rows": len(rows_by_key), "sha256": _sha256(path)}


def _write_runtime_state_manifest(state_root: Path, *, run_id: str, writes: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "runtime_state_version": RUNTIME_STATE_VERSION,
        "run_id": run_id,
        "updated_at_utc": _utc_now(),
        "writes": writes,
        "paths": {
            "run_summaries": str(state_root / "runs" / "run_summaries.jsonl"),
            "source_manifests": str(state_root / "source_manifests" / "source_manifests_running.jsonl"),
            "market_priors": str(state_root / "market_priors" / "market_priors_running.csv"),
            "eval_legs": str(state_root / "eval" / "eval_legs_running.csv"),
            "eval_slips": str(state_root / "eval" / "eval_slips_running.csv"),
            "daily_eval_summary": str(state_root / "eval" / "daily_eval_summary.jsonl"),
        },
    }
    path = state_root / "runtime_state_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {**manifest, "manifest_path": str(path)}


def _source_manifest_path(manifest: dict[str, Any], *, root: Path) -> Path | None:
    source_selection = manifest.get("source_selection") if isinstance(manifest.get("source_selection"), dict) else {}
    path = _path_from_manifest(source_selection, "manifest_path", root=root)
    if path:
        return path
    manifest_path = _path_from_manifest(manifest, "manifest_path", root=root)
    if manifest_path:
        candidate = manifest_path.parent / "source_selection_manifest.json"
        if candidate.exists():
            return candidate
    return None


def _manifest_path(manifest: dict[str, Any], section: str, key: str, *, root: Path) -> Path | None:
    payload = manifest.get(section) if isinstance(manifest.get(section), dict) else {}
    return _path_from_manifest(payload, key, root=root)


def _path_from_manifest(manifest: dict[str, Any], key: str, *, root: Path | None = None) -> Path | None:
    value = str(manifest.get(key) or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return path
    if root is not None:
        rooted = root / value
        if rooted.exists():
            return rooted
        migrated = _migrated_data_path(value, root=root)
        if migrated.exists():
            return migrated
    return path


def _migrated_data_path(value: str, *, root: Path) -> Path:
    parts = value.replace("\\", "/").split("/")
    for index in range(len(parts) - 1):
        if parts[index].lower() == "data" and parts[index + 1].lower() == "mlb":
            return root.joinpath(*parts[index:])
    return root / value


def _load_manifest(value: dict[str, Any] | Path) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return _load_json(value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        return [dict(row) for row in reader], header


def _merge_headers(*headers: list[str], rows: Iterable[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for header in headers:
        for column in header:
            if column and column not in out:
                out.append(column)
    for row in rows:
        for column in row:
            if column and column not in out:
                out.append(column)
    return out


def _row_key(row: dict[str, Any], key_fields: Iterable[str]) -> str:
    parts = [str(row.get(field) or "") for field in key_fields]
    if any(parts):
        return "|".join(parts)
    return _stable_json_hash(row)


def _stable_json_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_latest(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _optional_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
