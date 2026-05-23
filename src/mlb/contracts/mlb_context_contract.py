"""Contracts for passive MLB baseball-context artifacts."""

from __future__ import annotations

BASEBALL_CONTEXT_SCHEMA_VERSION = "mlb_baseball_context_v1"
BASEBALL_CONTEXT_ARTIFACT_VERSION = "mlb_baseball_context_artifacts_v1"

GATE_OK = "ok"
GATE_CAUTION = "caution"
GATE_SUPPRESS = "suppress"

GATE_LEVELS = (GATE_OK, GATE_CAUTION, GATE_SUPPRESS)

CONTEXT_PACKET_REQUIRED_FIELDS = (
    "projection_id",
    "player_name",
    "team",
    "opponent",
    "market",
    "side",
    "line",
    "tier",
    "market_group",
    "lineup_status",
    "pitcher_status",
    "gate_level",
    "public_publish_ok",
    "tags",
    "gate_reasons",
)

CONTEXT_ARTIFACT_FILENAMES = {
    "context_csv": "mlb_scored_legs_context.csv",
    "gate_report": "mlb_publication_gate_report.json",
    "pick_packets": "mlb_pick_context_packets.json",
}

