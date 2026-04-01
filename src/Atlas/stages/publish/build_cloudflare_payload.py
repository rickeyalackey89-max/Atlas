"""
Build cloudflare_payload.json from slip CSVs.

Called after run_publish_stage to create the dashboard payload.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def _parse_leg(raw: str) -> dict:
    """Parse a leg string like 'LeBron James OVER PTS 23.5 (DEMON) [id:10991881]'"""
    m = re.match(
        r"^(.+?)\s+(OVER|UNDER)\s+(\w+)\s+([\d.]+)\s+\((\w+)\)\s+\[id:(\d+)\]$",
        raw.strip(),
    )
    if not m:
        return {"raw": raw, "player": "?", "dir": "?", "stat": "?", "line": 0, "tier": "?", "id": 0}
    return {
        "raw": raw.strip(),
        "player": m.group(1).strip(),
        "dir": m.group(2),
        "stat": m.group(3),
        "line": float(m.group(4)),
        "tier": m.group(5),
        "id": int(m.group(6)),
    }


def _load_top_slip(csv_path: Path, product: str) -> Optional[dict]:
    """Load top slip (by ev_mult) from a CSV file."""
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return None
        # Sort by ev_mult descending, take top 1
        df = df.sort_values("ev_mult", ascending=False).head(1)
        row = df.iloc[0]
        legs_raw = str(row.get("legs", ""))
        legs_list = [_parse_leg(l) for l in legs_raw.split(" | ")]
        return {
            "product": product,
            "n_legs": int(row.get("n_legs", len(legs_list))),
            "legs": legs_raw,
            "legs_detail": legs_list,
            "hit_prob": float(row.get("hit_prob", 0)),
            "ev_mult": float(row.get("ev_mult", 0)),
            "payout_mult": float(row.get("payout_mult", 0)),
            "avg_fragility": float(row.get("avg_fragility", 0)),
        }
    except Exception:
        return None


def build_cloudflare_payload(run_dir: Path, out_dir: Path) -> Path:
    """
    Build cloudflare_payload.json from the slip CSVs in run_dir.
    
    Args:
        run_dir: The run directory containing System/, Windfall/, demonhunter.csv
        out_dir: Where to write cloudflare_payload.json (usually data/output/dashboard/)
    
    Returns:
        Path to the written payload file.
    """
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")
    
    payload = {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "run_id": run_dir.name,
        "system": [],
        "windfall": [],
        "demonhunter": [],
    }
    
    # System: top 3-leg, 4-leg, 5-leg
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "System" / f"recommended_{n}leg.csv", "System")
        if slip:
            payload["system"].append(slip)
    
    # Windfall: top 3-leg, 4-leg, 5-leg
    for n in [3, 4, 5]:
        slip = _load_top_slip(run_dir / "Windfall" / f"recommended_{n}leg.csv", "Windfall")
        if slip:
            payload["windfall"].append(slip)
    
    # Demonhunter: top 3-leg, 4-leg, 5-leg from single CSV
    demon_csv = run_dir / "demonhunter.csv"
    if demon_csv.exists():
        try:
            df = pd.read_csv(demon_csv)
            for n in [3, 4, 5]:
                subset = df[df["n_legs"] == n]
                if not subset.empty:
                    subset = subset.sort_values("ev_mult", ascending=False).head(1)
                    row = subset.iloc[0]
                    legs_raw = str(row.get("legs", ""))
                    legs_list = [_parse_leg(l) for l in legs_raw.split(" | ")]
                    payload["demonhunter"].append({
                        "product": "Demonhunter",
                        "n_legs": n,
                        "legs": legs_raw,
                        "legs_detail": legs_list,
                        "hit_prob": float(row.get("hit_prob", 0)),
                        "ev_mult": float(row.get("ev_mult", 0)),
                        "payout_mult": float(row.get("payout_mult", 0)),
                        "avg_fragility": float(row.get("avg_fragility", 0)),
                    })
        except Exception:
            pass
    
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cloudflare_payload.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python build_cloudflare_payload.py <run_dir>")
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    out_dir = run_dir.parents[1] / "dashboard"
    result = build_cloudflare_payload(run_dir, out_dir)
    print(f"Wrote: {result}")
