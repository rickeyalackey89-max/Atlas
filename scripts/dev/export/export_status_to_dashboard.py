import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(r"C:\Users\rick\projects\Atlas")

LATEST_ALL_DIR = ROOT / "data" / "output" / "latest" / "all"
WF_DIR = LATEST_ALL_DIR / "Windfall"
SYS_DIR = LATEST_ALL_DIR / "System"

DASH_DIR = ROOT / "data" / "output" / "dashboard"
OUT_JSON = DASH_DIR / "status_latest.json"

INJURY_INV_JSON = DASH_DIR / "injury_invalidations_latest.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_recent(path: Path, max_minutes: int) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return (datetime.now() - mtime) <= timedelta(minutes=max_minutes)
    except Exception:
        return False


def export_status_to_dashboard() -> None:
    """
    Windfall-first dashboard status.

    Important: This exporter must not clobber IAEL flags; and if the flags
    are missing (e.g., after a scrub), it should infer them from dashboard artifacts.
    """

    DASH_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing status if present (best-effort)
    existing = _load_json(OUT_JSON) if OUT_JSON.exists() else {}

    # Windfall readiness
    required = [
        WF_DIR / "recommended_3leg.csv",
        WF_DIR / "recommended_4leg.csv",
        WF_DIR / "recommended_5leg.csv",
    ]
    missing = [str(p) for p in required if not p.exists()]
    ok = len(missing) == 0

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "latest_all_dir": str(LATEST_ALL_DIR),
        "windfall_dir": str(WF_DIR),
        "required_files": [str(p) for p in required],
        "missing_files": missing,
        "notes": (
            "Windfall-first status. System outputs are optional. "
            "If ok=false, check that filter_recommendations_live published "
            "Windfall files into latest/all/Windfall."
        ),
    }

    # Preserve keys if they exist
    PRESERVE_KEYS = [
        "post_iael",
        "post_line_recon",
        "report_datetime",
        "report_datetime_local",
        "pulled_at",
        "pulled_at_local",
        "source",
    ]
    for k in PRESERVE_KEYS:
        if k in existing and k not in payload:
            payload[k] = existing[k]

    # ------------------------------------------------------------------
    # Infer flags if missing (common after scrub / first run)
    # ------------------------------------------------------------------
    if payload.get("post_iael") is None:
        # If the injury invalidations file exists (and is reasonably fresh), IAEL happened.
        if INJURY_INV_JSON.exists() and _is_recent(INJURY_INV_JSON, max_minutes=240):
            payload["post_iael"] = True
        else:
            payload["post_iael"] = False

    if payload.get("post_line_recon") is None:
        # If Windfall required files exist in latest/all, we are post publish/recon for execution.
        payload["post_line_recon"] = ok

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON} (ok={ok})")


if __name__ == "__main__":
    export_status_to_dashboard()