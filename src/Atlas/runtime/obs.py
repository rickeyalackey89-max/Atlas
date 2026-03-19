from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from Atlas.runtime.paths import find_repo_root

PROJECT_ROOT = find_repo_root(Path(__file__))
AUDIT_DIR = PROJECT_ROOT / ".atlas_audit"
AUDIT_DIR.mkdir(exist_ok=True)


def _iso_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _json_dumps_stable(obj: Dict[str, Any]) -> str:
    # Stable ordering for diffs / audit
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RunContext:
    run_id: str
    authority: str
    log_path: Path
    audit_dir: Path


def create_run_context(*, authority: str = "production") -> RunContext:
    run_id = _new_run_id()
    log_path = AUDIT_DIR / f"events_{run_id}.jsonl"
    return RunContext(run_id=run_id, authority=authority, log_path=log_path, audit_dir=AUDIT_DIR)


def emit_event(ctx: RunContext, event: str, **payload: Any) -> None:
    record: Dict[str, Any] = {
        "ts": _iso_now(),
        "run_id": ctx.run_id,
        "authority": ctx.authority,
        "event": event,
    }
    record.update(payload)

    with ctx.log_path.open("a", encoding="utf-8") as f:
        f.write(_json_dumps_stable(record) + "\n")


class StageTimer:
    """
    Additive stage timing + start/end events.
    Does not suppress exceptions.
    """

    def __init__(self, ctx: RunContext, stage: str):
        self.ctx = ctx
        self.stage = stage
        self._t0: Optional[float] = None

    def __enter__(self) -> "StageTimer":
        self._t0 = time.perf_counter()
        emit_event(self.ctx, "stage_start", stage=self.stage)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        assert self._t0 is not None
        dur_ms = int((time.perf_counter() - self._t0) * 1000)

        emit_event(
            self.ctx,
            "stage_end",
            stage=self.stage,
            duration_ms=dur_ms,
            status="ok" if exc_type is None else "fail",
            error_type=(exc_type.__name__ if exc_type else None),
            error_message=(str(exc_val) if exc_val else None),
        )
        return False


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()