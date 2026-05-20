"""Shared runtime command result types."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeCommandResult:
    name: str
    payload: dict[str, Any]
    lines: tuple[str, ...]


def render_runtime_result(result: RuntimeCommandResult, *, as_json: bool = False) -> str:
    """Render a runtime result for stdout."""

    if as_json:
        return json.dumps(result.payload, indent=2)
    return "\n".join(result.lines)

