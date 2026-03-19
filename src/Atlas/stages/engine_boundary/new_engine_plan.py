from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from Atlas.stages.engine_boundary.engine_plan import EnginePlan


def build_new_engine_plan(
    *,
    python_exe: str,
    repo_root: str,
    args: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> EnginePlan:
    """
    Phase 7B: deterministic plan to invoke the NEW engine entry.

    IMPORTANT:
    - Pure plan construction only (no IO).
    - Mirrors legacy_main_plan semantics (PYTHONPATH=repo_root/src).
    """
    argv = ["-m", "Atlas.engine.main"]
    if args:
        argv.extend(args)

    env = dict(extra_env or {})
    env["PYTHONPATH"] = str(Path(repo_root) / "src")

    return EnginePlan(
        kind="subprocess",
        exe=python_exe,
        argv=argv,
        cwd=repo_root,
        env=env,
    )
