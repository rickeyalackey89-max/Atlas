"""Read-only runtime inspection commands for Atlas MLB.

Inspection commands report status, paths, market coverage, pipeline shape, and
guardrails. They do not execute live or replay work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mlb.domain.markets import MARKET_GROUPS, PRIZEPICKS_MARKET_ALIASES
from mlb.runtime.paths import mlb_paths
from mlb.runtime.pipeline import MLB_PIPELINE_STAGES
from mlb.evaluation.workflow import operator_evaluation_plan_result
from mlb.runtime.bundles import bundle_plan
from mlb.runtime.preflight import build_preflight_report
from mlb.runtime.publishing import publishing_status
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.source_operations import source_catalog_result


INSPECTION_COMMANDS = (
    "doctor",
    "markets",
    "paths",
    "sources",
    "pipeline",
    "bundles",
    "operator",
    "publishing",
)


def list_inspection_commands() -> tuple[str, ...]:
    """Return available zero-side-effect inspection commands."""

    return INSPECTION_COMMANDS


def run_inspection_command(name: str, root: Path | None = None) -> RuntimeCommandResult:
    """Build the runtime result for a read-only inspection command."""

    if name == "doctor":
        payload = build_preflight_report(root)
        return RuntimeCommandResult(name=name, payload=payload, lines=_dict_lines(payload))
    if name == "markets":
        return _markets_result()
    if name == "paths":
        return _paths_result(root)
    if name == "sources":
        return source_catalog_result()
    if name == "pipeline":
        return _pipeline_result()
    if name == "bundles":
        return _bundles_result()
    if name == "operator":
        return operator_evaluation_plan_result()
    if name == "publishing":
        return _publishing_result()
    raise ValueError(f"Unknown MLB inspection command: {name}")


def _markets_result() -> RuntimeCommandResult:
    lines: list[str] = []
    for group, markets in MARKET_GROUPS.items():
        lines.append(f"{group.title()} markets:")
        lines.extend(f"  - {market}" for market in markets)
    lines.append(f"PrizePicks aliases: {len(PRIZEPICKS_MARKET_ALIASES)}")
    return RuntimeCommandResult(
        name="markets",
        payload={
            "groups": {group: list(markets) for group, markets in MARKET_GROUPS.items()},
            "prizepicks_alias_count": len(PRIZEPICKS_MARKET_ALIASES),
        },
        lines=tuple(lines),
    )


def _paths_result(root: Path | None) -> RuntimeCommandResult:
    paths = mlb_paths(root)
    payload = {name: str(value) for name, value in paths.__dict__.items()}
    return RuntimeCommandResult(name="paths", payload=payload, lines=tuple(_dict_lines(payload)))


def _pipeline_result() -> RuntimeCommandResult:
    publishing = publishing_status()
    lines = ["MLB pipeline stages:"]
    lines.extend(f"  - {stage}" for stage in MLB_PIPELINE_STAGES)
    lines.append(f"publishing_enabled: {publishing['enabled']}")
    return RuntimeCommandResult(
        name="pipeline",
        payload={
            "stages": list(MLB_PIPELINE_STAGES),
            "stage_count": len(MLB_PIPELINE_STAGES),
            "publishing": publishing,
        },
        lines=tuple(lines),
    )


def _bundles_result() -> RuntimeCommandResult:
    payload = bundle_plan()
    lines = ["MLB expected bundle artifacts:"]
    lines.extend(
        f"  - {artifact['name']} ({artifact['phase']}): {artifact['path_template']}"
        for artifact in payload["artifacts"]
    )
    return RuntimeCommandResult(name="bundles", payload=payload, lines=tuple(lines))


def _publishing_result() -> RuntimeCommandResult:
    payload = publishing_status()
    lines = [
        f"publishing_enabled: {payload['enabled']}",
        f"mode: {payload['mode']}",
        f"reason: {payload['reason']}",
        "publishing stages:",
    ]
    lines.extend(f"  - {stage}" for stage in payload["stages"])
    return RuntimeCommandResult(name="publishing", payload=payload, lines=tuple(lines))


def _dict_lines(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(f"{name}: {value}" for name, value in payload.items())
