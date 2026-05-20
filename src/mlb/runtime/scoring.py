"""Runtime scoring command helpers for Atlas MLB."""

from __future__ import annotations

from pathlib import Path

from mlb.modeling.engine import score_engine_board
from mlb.runtime.results import RuntimeCommandResult


def score_board_result(
    *,
    engine_board_path: Path | None = None,
    parameter_table_path: Path | None = None,
    feature_table_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    scored = score_engine_board(
        engine_board_path=engine_board_path,
        parameter_table_path=parameter_table_path,
        feature_table_path=feature_table_path,
        root=root,
        run_id=run_id,
    )
    lines = [
        "Scored MLB engine board:",
        f"  run_id: {scored['run_id']}",
        f"  source_run_id: {scored['source_run_id']}",
        f"  row_count: {scored['row_count']}",
        f"  parameter_matches: {scored['parameter_row_match_count']}",
        f"  parameter_missing: {scored['parameter_row_missing_count']}",
        f"  feature_matches: {scored['feature_row_match_count']}",
        f"  feature_missing: {scored['feature_row_missing_count']}",
        f"  probability_min: {scored['model_probability_min']}",
        f"  probability_max: {scored['model_probability_max']}",
        f"  csv: {scored['csv_path']}",
        f"  json: {scored['json_path']}",
        f"  manifest: {scored['manifest_path']}",
        f"  simulation_manifest: {scored['simulation_manifest_path']}",
    ]
    return RuntimeCommandResult(name="score_board", payload=scored, lines=tuple(lines))
