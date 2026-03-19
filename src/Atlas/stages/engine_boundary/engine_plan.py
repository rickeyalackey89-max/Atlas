from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Literal


EngineKind = Literal["subprocess", "direct"]


@dataclass(frozen=True)
class EnginePlan:
    """
    Permanent engine boundary contract.

    Phase 6: kind='subprocess' with module invocation plan.
    Later:  kind='direct' with staged callable plan, without changing orchestrator.
    """
    kind: EngineKind
    exe: str
    argv: List[str]
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None

    def to_cmdline(self) -> str:
        # Useful for audit logging
        parts = [self.exe] + self.argv
        return " ".join([_quote_if_needed(p) for p in parts])


def _quote_if_needed(s: str) -> str:
    if any(c.isspace() for c in s):
        return f'"{s}"'
    return s