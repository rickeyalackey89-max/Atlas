from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Dict, Optional

@dataclass(frozen=True)
class RunContext:
    mode: str  # "live" | "sandbox"
    run_id: str
    out_root: Path
    variant_config_path: Optional[Path] = None

    def load_variant_config(self) -> Dict[str, Any]:
        if not self.variant_config_path:
            return {}
        p = Path(self.variant_config_path)
        if not p.exists():
            raise FileNotFoundError(f"Variant config not found: {p}")
        return json.loads(p.read_text(encoding="utf-8"))

def resolve_out_root(project_root: Path, mode: str, run_id: str, sandbox_outdir: Optional[str]) -> Path:
    if mode != "sandbox":
        return project_root / "data" / "output"
    if sandbox_outdir:
        return Path(sandbox_outdir)
    return project_root / "data" / "output" / "sandbox_runs" / run_id