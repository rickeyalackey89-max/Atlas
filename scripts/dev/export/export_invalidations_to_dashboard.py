import csv
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\rick\projects\Atlas")

LATEST_ALL_DIR = ROOT / "data" / "output" / "latest" / "all"
DASH_DIR = ROOT / "data" / "output" / "dashboard"
OUT_JSON = DASH_DIR / "invalidations_latest.json"


def export_invalidations_to_dashboard() -> None:
    '''
    Exports invalidations/removals to dashboard JSON.

    If Atlas did not produce an invalidations CSV today, we still write a valid JSON payload
    with an empty data array to keep the dashboard stable.
    '''
    DASH_DIR.mkdir(parents=True, exist_ok=True)

    candidates = [
        LATEST_ALL_DIR / "invalidations.csv",
        LATEST_ALL_DIR / "invalidations_latest.csv",
        LATEST_ALL_DIR / "invalidated_legs.csv",
        LATEST_ALL_DIR / "removed_legs.csv",
    ]

    src = next((p for p in candidates if p.exists() and p.stat().st_size > 0), None)

    rows = []
    source = None

    if src:
        with src.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        source = str(src)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_csv": source,
        "row_count": len(rows),
        "data": rows,
        "notes": "If no invalidations file exists, payload is empty but valid.",
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON} (rows={len(rows)})")


if __name__ == "__main__":
    export_invalidations_to_dashboard()
