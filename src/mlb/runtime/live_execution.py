"""Executable live MLB model command.

This module keeps the CLI thin: ``atlas-mlb live`` delegates here, then this
wrapper fetches the live PrizePicks board and runs the live pipeline contract.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.runtime.config import active_mlb_config_manifest
from mlb.runtime.paths import repo_root
from mlb.runtime.pipeline_execution import run_board_pipeline_result
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.source_operations import fetch_prizepicks_result


def run_live_model_result(
    *,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    state_code: str = "MO",
    snapshot_path: Path | None = None,
    normalized_dir: Path | None = None,
    include_all_sports: bool = True,
    refresh_bettingpros_odds: bool = True,
    calibration_artifact_path: Path | None = None,
    emit_progress: Callable[[str], None] | None = None,
    fetch_attempts: int = 3,
    fetch_retry_sleep_s: float = 2.2,
) -> RuntimeCommandResult:
    if snapshot_path and normalized_dir:
        raise ValueError("Pass either snapshot_path or normalized_dir, not both")

    contract = active_mlb_config_manifest(root)
    resolved_calibration_artifact_path = calibration_artifact_path or _active_calibration_artifact_path(
        contract,
        root=root,
    )
    _emit_contract(contract=contract, emit_progress=emit_progress)

    fetch_payload: dict[str, Any] | None = None
    fetch_lines: tuple[str, ...] = ()
    resolved_normalized_dir = normalized_dir
    if snapshot_path is None and resolved_normalized_dir is None:
        fetch_result = _fetch_prizepicks_with_progress(
            root=root,
            state_code=state_code,
            include_all_sports=include_all_sports,
            attempts=fetch_attempts,
            retry_sleep_s=fetch_retry_sleep_s,
            emit_progress=emit_progress,
        )
        fetch_payload = fetch_result.payload
        fetch_lines = fetch_result.lines
        normalized_output_dir = str(((fetch_payload.get("normalized") or {}).get("output_dir") or "")).strip()
        if not normalized_output_dir:
            raise RuntimeError("PrizePicks live fetch did not produce a normalized board directory")
        resolved_normalized_dir = Path(normalized_output_dir)
    elif resolved_normalized_dir is not None:
        _emit_progress(
            emit_progress,
            _banner(
                "USE NORMALIZED BOARD",
                detail=str(resolved_normalized_dir),
            ),
        )
    elif snapshot_path is not None:
        _emit_progress(emit_progress, _banner("USE RAW SNAPSHOT", detail=str(snapshot_path)))

    resolved_run_id = run_id or _default_live_run_id()
    _emit_progress(emit_progress, _canonical_pipeline_banner(resolved_run_id=resolved_run_id))
    pipeline_result = run_board_pipeline_result(
        snapshot_path=snapshot_path,
        normalized_dir=resolved_normalized_dir,
        root=root,
        run_id=resolved_run_id,
        run_mode="live",
        game_date=game_date,
        refresh_context_sources=True,
        refresh_bettingpros_odds=refresh_bettingpros_odds,
        calibration_artifact_path=resolved_calibration_artifact_path,
        emit_progress=emit_progress,
    )
    run_payload = pipeline_result.payload
    _emit_progress(emit_progress, _live_summary(run_payload))
    payload = {
        "command": "live",
        "run_id": run_payload.get("run_id"),
        "run_mode": run_payload.get("run_mode"),
        "game_date_filter": run_payload.get("game_date_filter"),
        "fetch": fetch_payload,
        "run": run_payload,
        "manifest_path": run_payload.get("manifest_path"),
    }
    lines = [
        "Executed Atlas MLB live model:",
        f"  run_id: {payload['run_id']}",
        f"  game_date_filter: {payload['game_date_filter'] or 'snapshot-default'}",
    ]
    if fetch_payload:
        lines.extend(
            [
                f"  prizepicks_snapshot: {fetch_payload.get('snapshot_id')}",
                f"  normalized_dir: {((fetch_payload.get('normalized') or {}).get('output_dir') or '')}",
            ]
        )
    lines.extend(
        [
            f"  engine_board_rows: {run_payload['engine_board']['row_count']}",
            f"  dropped_by_date_filter: {run_payload['engine_board'].get('dropped_by_date_filter_count', 0)}",
            f"  context_sources_refreshed: {run_payload['context_source_refresh']['enabled']}",
            f"  primary_market_source: {run_payload['primary_market_source'].get('status')}",
            f"  scored_legs: {run_payload['score']['row_count']}",
            f"  slip_count: {run_payload['slips']['slip_count']}",
            f"  publish_allowed: {run_payload['operator']['publish_allowed']}",
            f"  run_manifest: {payload['manifest_path']}",
        ]
    )
    if fetch_lines:
        lines = [*lines, "", "Fetch detail:", *fetch_lines]
    return RuntimeCommandResult(name="live_model", payload=payload, lines=tuple(lines))


def _default_live_run_id() -> str:
    return f"live_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def _fetch_prizepicks_with_progress(
    *,
    root: Path | None,
    state_code: str,
    include_all_sports: bool,
    attempts: int,
    retry_sleep_s: float,
    emit_progress: Callable[[str], None] | None,
) -> RuntimeCommandResult:
    resolved_attempts = max(1, int(attempts or 1))
    last_exc: Exception | None = None
    for attempt in range(1, resolved_attempts + 1):
        _emit_progress(
            emit_progress,
            _banner(
                f"FETCH PRIZEPICKS (fresh MLB board) attempt {attempt}/{resolved_attempts}",
                detail=_timestamp(),
            ),
        )
        try:
            result = fetch_prizepicks_result(
                root=root,
                state_code=state_code,
                normalize=True,
                include_all_sports=include_all_sports,
                publish_engine_input=False,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= resolved_attempts:
                _emit_progress(emit_progress, f"[FETCH ERROR] {exc}")
                break
            sleep_for = retry_sleep_s * attempt
            _emit_progress(emit_progress, f"[FETCH ERROR] {exc}. Sleeping {sleep_for:.1f}s")
            time.sleep(sleep_for)
            continue
        payload = result.payload
        normalized = payload.get("normalized") or {}
        all_sports = payload.get("all_sports_snapshot") or {}
        _emit_progress(
            emit_progress,
            "\n".join(
                [
                    f"[PRIZEPICKS] snapshot={payload.get('snapshot_id')}",
                    f"[PRIZEPICKS] all_sports_rows={all_sports.get('record_count', '')}",
                    (
                        "[PRIZEPICKS] "
                        f"normalized_count={normalized.get('normalized_count', 0)} "
                        f"rejected_count={normalized.get('rejected_count', 0)}"
                    ),
                    f"[PRIZEPICKS] normalized_dir={normalized.get('output_dir', '')}",
                ]
            ),
        )
        return result
    raise RuntimeError(f"PrizePicks live fetch failed after {resolved_attempts} attempt(s): {last_exc}") from last_exc


def _active_calibration_artifact_path(contract: dict[str, Any], *, root: Path | None) -> Path | None:
    artifact = str(contract.get("active_calibration_artifact") or "").strip()
    if not artifact:
        return None
    path = Path(artifact)
    if path.is_absolute():
        return path
    return (root or repo_root()) / path


def _emit_contract(*, contract: dict[str, Any], emit_progress: Callable[[str], None] | None) -> None:
    if emit_progress is None:
        return
    manifest = contract
    emit_progress(
        "\n".join(
            [
                (
                    "[CONTRACT] "
                    f"{manifest.get('config_version')} "
                    f"kernel={manifest.get('active_probability_kernel')} "
                    f"calibration={manifest.get('active_calibration_version')}"
                ),
                f"[CONTRACT] market_source={manifest.get('active_market_source')} "
                f"slip_builder={manifest.get('active_slip_builder_version')}",
            ]
        )
    )


def _canonical_pipeline_banner(*, resolved_run_id: str) -> str:
    stages = (
        "publish engine board",
        "refresh Rotowire context",
        "refresh Baseball Savant profiles",
        "refresh ESPN injuries",
        "refresh StatsAPI teams/schedule/rosters/transactions",
        "fetch BettingPros primary market odds",
        "build market/injury/statsapi/roster/player-history/transaction context",
        "build matchup/advanced/weather feature context",
        "apply CAT calibration artifact when configured",
        "score legs",
        "build Marketed/System/Windfall/DemonHunter slips",
        "quote PrizePicks payouts",
        "run operator checks and write live artifacts",
    )
    return "\n".join(
        [
            _banner("RUN LIVE MODEL (canonical pipeline)", detail=f"{_timestamp()}  run_id={resolved_run_id}"),
            *[f"[{index:02d}] {stage}" for index, stage in enumerate(stages, start=1)],
        ]
    )


def _live_summary(run_payload: dict[str, Any]) -> str:
    engine_board = run_payload.get("engine_board") or {}
    coverage = ((run_payload.get("features") or {}).get("source_completeness") or {})
    refresh = run_payload.get("context_source_refresh") or {}
    primary_market = run_payload.get("primary_market_source") or {}
    operator = run_payload.get("operator") or {}
    slips = run_payload.get("slips") or {}
    payout = slips.get("payout_quote_manifest") or {}
    return "\n".join(
        [
            _banner("LIVE MODEL SUMMARY", detail=_timestamp()),
            f"[BOARD] rows={engine_board.get('row_count', 0)} "
            f"dropped_future_or_other_date={engine_board.get('dropped_by_date_filter_count', 0)} "
            f"dropped_started_or_live={engine_board.get('dropped_started_or_live_count', 0)}",
            f"[CONTEXT] refresh_enabled={refresh.get('enabled')} errors={len(refresh.get('errors') or [])}",
            f"[MARKET] status={primary_market.get('status')} "
            f"rows={primary_market.get('row_count', 0)} "
            f"snapshot={primary_market.get('snapshot_id', '')}",
            (
                "[COVERAGE] "
                f"market={_pct(coverage.get('external_market_context_available'))} "
                f"lineup={_pct(coverage.get('lineup_context_available'))} "
                f"statsapi={_pct(coverage.get('statsapi_context_available'))} "
                f"roster={_pct(coverage.get('roster_context_available'))} "
                f"history={_pct(coverage.get('player_history_context_available'))} "
                f"advanced={_pct(coverage.get('advanced_context_available'))} "
                f"weather={_pct(coverage.get('weather_context_available'))}"
            ),
            f"[SLIPS] count={slips.get('slip_count', 0)} "
            f"payout_quotes={payout.get('exact_quote_count', 0)}/{payout.get('quote_count', 0)} exact",
            f"[OPERATOR] severity={operator.get('severity')} "
            f"publish_allowed={operator.get('publish_allowed')} "
            f"anomalies={operator.get('anomaly_count', 0)}",
            f"[MANIFEST] {run_payload.get('manifest_path')}",
        ]
    )


def _banner(title: str, *, detail: str = "") -> str:
    line = "=" * 72
    suffix = f" {detail}" if detail else ""
    return f"\n{line}\n[{title}]{suffix}\n{line}"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _emit_progress(emit_progress: Callable[[str], None] | None, message: str) -> None:
    if emit_progress is not None:
        emit_progress(message)
