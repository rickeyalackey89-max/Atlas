"""Write passive baseball-context publication artifacts for MLB runs."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.context.baseball_context import build_context_packets, summarize_context_packets
from mlb.contracts.mlb_context_contract import (
    BASEBALL_CONTEXT_ARTIFACT_VERSION,
    BASEBALL_CONTEXT_SCHEMA_VERSION,
    CONTEXT_ARTIFACT_FILENAMES,
)

CSV_COLUMNS = (
    "projection_id",
    "player_name",
    "team",
    "opponent",
    "event_id",
    "game_date",
    "start_time_utc",
    "market",
    "source_market",
    "market_group",
    "side",
    "line",
    "tier",
    "model_probability",
    "p_cal",
    "lineup_status",
    "batting_order_spot",
    "batting_order_bucket",
    "projected_plate_appearances",
    "pitcher_status",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "matchup_confidence",
    "environment_score",
    "park_factor_confidence",
    "external_market_context_available",
    "line_only_market_context",
    "gate_level",
    "public_publish_ok",
    "tags",
    "gate_reasons",
)

FEATURE_JOIN_FIELDS = (
    "market_group",
    "matchup_context_available",
    "lineup_context_available",
    "probable_pitcher_context_available",
    "weather_context_available",
    "batting_order_slot",
    "lineup_probability",
    "lineup_confirmed",
    "top_order_flag",
    "projected_plate_appearances",
    "plate_appearance_projection",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "matchup_confidence",
    "environment_score",
    "park_factor_confidence",
    "external_market_context_available",
    "market_context_source_type",
    "external_market_context_source",
    "prizepicks_line_only_market_context",
)


def write_baseball_context_artifacts(
    *,
    run_dir: Path,
    legs: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    mirror_latest: bool = True,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    resolved_rows = legs if legs is not None else _load_scored_legs(run_dir)
    packets = build_context_packets([dict(row) for row in resolved_rows])
    summary = summarize_context_packets(packets)
    resolved_run_id = str(run_id or _infer_run_id(run_dir, packets) or run_dir.name)

    context_csv_path = run_dir / CONTEXT_ARTIFACT_FILENAMES["context_csv"]
    gate_report_path = run_dir / CONTEXT_ARTIFACT_FILENAMES["gate_report"]
    packets_path = run_dir / CONTEXT_ARTIFACT_FILENAMES["pick_packets"]
    _write_packets_csv(context_csv_path, packets)

    payload = {
        "schema_version": BASEBALL_CONTEXT_SCHEMA_VERSION,
        "artifact_version": BASEBALL_CONTEXT_ARTIFACT_VERSION,
        "run_id": resolved_run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "row_count": len(packets),
        "summary": summary,
        "artifacts": {
            "context_csv": str(context_csv_path),
            "gate_report": str(gate_report_path),
            "pick_packets": str(packets_path),
        },
        "columns": list(CSV_COLUMNS),
    }
    packets_payload = {
        "schema_version": BASEBALL_CONTEXT_SCHEMA_VERSION,
        "artifact_version": BASEBALL_CONTEXT_ARTIFACT_VERSION,
        "run_id": resolved_run_id,
        "row_count": len(packets),
        "packets": packets,
    }
    gate_report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    packets_path.write_text(json.dumps(packets_payload, indent=2, sort_keys=True), encoding="utf-8")

    latest_outputs = {}
    if mirror_latest and _should_mirror_latest(run_dir):
        latest_outputs = _mirror_latest(run_dir, context_csv_path, gate_report_path, packets_path)
        if latest_outputs:
            payload["latest_artifacts"] = latest_outputs
            gate_report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    return payload


def _write_packets_csv(path: Path, packets: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for packet in packets:
            row = dict(packet)
            row["tags"] = "|".join(str(value) for value in packet.get("tags") or [])
            row["gate_reasons"] = "|".join(str(value) for value in packet.get("gate_reasons") or [])
            writer.writerow(row)


def _load_scored_legs(run_dir: Path) -> list[dict[str, Any]]:
    scored_path = run_dir / "scored_legs.json"
    if not scored_path.exists():
        return []
    payload = json.loads(scored_path.read_text(encoding="utf-8"))
    rows = payload.get("scored_legs") if isinstance(payload, dict) else []
    clean_rows = [row for row in rows if isinstance(row, dict)]
    feature_index = _load_feature_index(payload)
    if not feature_index:
        return clean_rows
    enriched_rows: list[dict[str, Any]] = []
    for row in clean_rows:
        enriched = dict(row)
        feature = feature_index.get(_projection_key(row))
        if feature:
            for field in FEATURE_JOIN_FIELDS:
                if field in feature and field not in enriched:
                    enriched[field] = feature[field]
            enriched["feature_context_joined"] = True
        else:
            enriched["feature_context_joined"] = False
        enriched_rows.append(enriched)
    return enriched_rows


def _load_feature_index(scored_payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(scored_payload, dict):
        return {}
    path_value = scored_payload.get("feature_table_path")
    if not path_value:
        return {}
    feature_path = Path(str(path_value))
    if not feature_path.exists():
        return {}
    rows: list[dict[str, Any]] = []
    if feature_path.suffix.lower() == ".json":
        payload = json.loads(feature_path.read_text(encoding="utf-8"))
        candidate_rows = payload.get("rows") if isinstance(payload, dict) else payload
        if candidate_rows is None and isinstance(payload, dict):
            candidate_rows = payload.get("features") or payload.get("feature_rows")
        if isinstance(candidate_rows, dict):
            candidate_rows = list(candidate_rows.values())
        if isinstance(candidate_rows, list):
            rows = [row for row in candidate_rows if isinstance(row, dict)]
    elif feature_path.suffix.lower() == ".csv":
        with feature_path.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.DictReader(handle)]
    return {key: row for row in rows if (key := _projection_key(row))}


def _projection_key(row: dict[str, Any]) -> str:
    return str(row.get("source_projection_id") or row.get("projection_id") or "").strip()


def _infer_run_id(run_dir: Path, packets: list[dict[str, Any]]) -> str:
    if packets:
        return str(packets[0].get("run_id") or "").strip()
    return run_dir.name


def _mirror_latest(run_dir: Path, context_csv_path: Path, gate_report_path: Path, packets_path: Path) -> dict[str, str]:
    repo_root = _repo_root_for_run_dir(run_dir)
    if not repo_root:
        return {}
    latest_dir = repo_root / "data" / "mlb" / "output" / "context"
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_paths = {
        "context_csv": latest_dir / "latest_mlb_scored_legs_context.csv",
        "gate_report": latest_dir / "latest_mlb_publication_gate_report.json",
        "pick_packets": latest_dir / "latest_mlb_pick_context_packets.json",
    }
    for source, dest in (
        (context_csv_path, latest_paths["context_csv"]),
        (gate_report_path, latest_paths["gate_report"]),
        (packets_path, latest_paths["pick_packets"]),
    ):
        dest.write_bytes(source.read_bytes())
    return {key: str(path) for key, path in latest_paths.items()}


def _should_mirror_latest(run_dir: Path) -> bool:
    parts = {part.lower() for part in run_dir.resolve().parts}
    return "live_runs" in parts


def _repo_root_for_run_dir(run_dir: Path) -> Path | None:
    for parent in run_dir.resolve().parents:
        if (parent / "config" / "sports" / "mlb.yaml").exists():
            return parent
    return None
