#!/usr/bin/env python
"""tools/publish_latest_placeable.py

NEW ENGINE publish step (no legacy wrappers).

Purpose
- Make LIVE a single smooth run that produces *all expected outputs*.
- Specifically, ensure a fresh timestamped IAEL "normalized" JSON exists under:
    data/output/injury/normalized/YYYY-MM-DD_HH_MMPM.json
  every time the model is run.

Notes
- IAEL refresh is handled by src/Atlas/cli.py preflight via tools/refresh_iael_today.py.
- This script is IO-only: it does not fetch network data.
- If a normalized JSON already exists for today, we still emit a new timestamped copy
  so downstream consumers always see a new artifact per run.

Behavior
1) Locate the most recent normalized IAEL JSON under data/output/injury/normalized.
2) Validate it has top-level 'rows' (preferred). If not present, we still copy it.
3) Write a new timestamped JSON copy for "now" in America/Chicago.
4) Also write/update a stable pointer file:
      data/output/injury/normalized/latest.json

If no normalized IAEL JSON exists yet, we create a minimal normalized payload
from dashboard status_latest.json + invalidations_latest.json so the pipeline
never goes dark.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("America/Chicago")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now_stamp_local() -> tuple[str, str]:
    """Return (date_str, stamp_str) like ('2026-02-22', '2026-02-22_11_17AM')."""
    now = datetime.now(LOCAL_TZ)
    date_s = now.strftime("%Y-%m-%d")
    stamp_s = now.strftime("%Y-%m-%d_%I_%M%p")
    # Windows-friendly: drop leading 0 in hour? keep as-is for sorting; your folder uses 08_15AM style.
    return date_s, stamp_s


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _find_latest_norm(norm_dir: Path) -> Path | None:
    if not norm_dir.exists():
        return None
    cands = sorted([p for p in norm_dir.glob("*.json") if p.is_file() and p.name.lower() != "latest.json"], key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _build_minimal_norm(root: Path, today: str) -> dict:
    """Fallback normalized payload if no prior normalized file exists."""
    status_p = root / "data" / "output" / "dashboard" / "status_latest.json"
    inv_p = root / "data" / "output" / "dashboard" / "invalidations_latest.json"

    st = {}
    inv = []
    if status_p.exists():
        try:
            st = _load_json(status_p)
        except Exception:
            st = {}
    if inv_p.exists():
        try:
            inv = json.loads(inv_p.read_text(encoding="utf-8"))
        except Exception:
            inv = []

    # Convert invalidations into normalized rows (best effort)
    rows = []
    if isinstance(inv, list):
        for r in inv:
            if not isinstance(r, dict):
                continue
            rows.append(
                {
                    "player": r.get("player"),
                    "team": r.get("team"),
                    "status": r.get("status"),
                    "reason": r.get("reason"),
                    "game_date": r.get("game_date") or today,
                    "hard_invalid": r.get("hard_invalid"),
                    "source": "invalidations_latest",
                }
            )

    return {
        "schema": "atlas.iael_normalized.v1",
        "report_date": st.get("report_date") or today,
        "report_label": st.get("report_label") or st.get("report_time") or "UNKNOWN",
        "source_url": st.get("source_url"),
        "pdf_sha1": st.get("pdf_sha1"),
        "generated_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "rows": rows,
        "notes": "Auto-generated fallback normalized IAEL payload (no normalized source file found).",
    }


def main() -> int:
    root = repo_root()
    out_dir = root / "data" / "output"
    norm_dir = out_dir / "injury" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)

    today, stamp = _now_stamp_local()
    latest_src = _find_latest_norm(norm_dir)

    if latest_src is None:
        obj = _build_minimal_norm(root, today)
        src_label = "generated_fallback"
    else:
        try:
            obj = _load_json(latest_src)
            src_label = latest_src.name
        except Exception:
            obj = _build_minimal_norm(root, today)
            src_label = "generated_fallback_parse_failed"

    # Add/refresh metadata so every run is auditable
    if isinstance(obj, dict):
        obj.setdefault("schema", "atlas.iael_normalized.v1")
        obj["generated_at"] = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")
        obj["_atlas_publish"] = {
            "published_from": src_label,
            "published_at": obj["generated_at"],
        }

    out_path = norm_dir / f"{stamp}.json"
    _write_json(out_path, obj)

    # Stable pointer
    latest_ptr = norm_dir / "latest.json"
    _write_json(latest_ptr, obj)

    print(f"[PUBLISH] wrote {out_path}")
    print(f"[PUBLISH] updated {latest_ptr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
