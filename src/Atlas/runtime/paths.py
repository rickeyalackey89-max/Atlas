from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """
    Walk upward until we find the repo root. We define repo root as the directory
    that contains BOTH 'tools' and 'data' (Atlas runtime invariants).

    This avoids fragile Path(__file__).parents[n] assumptions.
    """
    p = start.resolve()
    for parent in [p] + list(p.parents):
        if (parent / "tools").is_dir() and (parent / "data").is_dir():
            return parent
    # Fallback: if structure is weird, guess "repo root is 3 levels above src/Atlas/*"
    return start.resolve().parents[3]