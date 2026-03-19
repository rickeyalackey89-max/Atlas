import argparse
import json
import os
import re
from datetime import datetime, timezone
import hashlib

STATUSES = {"OUT", "DOUBTFUL", "QUESTIONABLE"}

def norm_status(s: str | None) -> str | None:
    if s is None:
        return None
    s = str(s).strip().upper()
    if s in ("Q", "QUESTION"):
        return "QUESTIONABLE"
    if s in ("D", "DOUBT"):
        return "DOUBTFUL"
    return s

def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--norm", required=True, help="Normalized IAEL JSON (must contain top-level 'rows').")
    ap.add_argument("--seed-stamp", required=True, help="Seed folder stamp (YYYYMMDD_HHMMSS).")
    ap.add_argument("--archive-dir", default=r".\data\archives\iael_seed", help="Archive root dir.")
    args = ap.parse_args()

    norm_path = os.path.abspath(args.norm)
    if not os.path.exists(norm_path):
        raise SystemExit(f"Missing normalized IAEL: {norm_path}")

    stamp = args.seed_stamp
    if not re.match(r"^\d{8}_\d{6}$", stamp):
        raise SystemExit(f"--seed-stamp must be YYYYMMDD_HHMMSS (got {stamp})")

    with open(norm_path, "r", encoding="utf-8") as f:
        norm = json.load(f)

    report_date = norm.get("report_date")
    report_label = norm.get("report_label")

    rows = norm.get("rows") or []
    if not isinstance(rows, list):
        raise SystemExit("Normalized IAEL 'rows' must be a list.")

    invalidations = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        player = r.get("player")
        status = norm_status(r.get("status"))
        if not player or not status:
            continue
        if status in STATUSES:
            invalidations.append({
                "player": str(player).strip(),
                "status": status,
                "team": r.get("team"),
                "reason": r.get("reason"),
                "game_date": r.get("game_date"),
                "hard_invalid": r.get("hard_invalid"),
            })

    year = stamp[:4]
    dest_dir = os.path.abspath(os.path.join(args.archive_dir, year, stamp))
    os.makedirs(dest_dir, exist_ok=True)

    # Write invalidations_latest.json
    inv_path = os.path.join(dest_dir, "injury_invalidations_latest.json")
    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": "atlas.iael_invalidations.v1",
            "report_date": report_date,
            "report_label": report_label,
            "source_norm": norm_path,
            "count": len(invalidations),
            "invalidations": invalidations
        }, f, indent=2)

    # Write status_latest.json (seeded, NOT dead period)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st_path = os.path.join(dest_dir, "status_latest.json")
    with open(st_path, "w", encoding="utf-8") as f:
        json.dump({
            "report_datetime_local": f"{report_date} {report_label}" if report_date and report_label else "UNKNOWN",
            "pulled_at_utc": now_utc,
            "source": "seeded_from_normalized",
            "source_norm": norm_path,
            "source_url": norm.get("source_url"),
            "pdf_sha1": norm.get("pdf_sha1"),
            "post_iael": True,
            "post_line_recon": False,
            "dead_period": False,
            "notes": "Seed built from normalized IAEL (historical) for deterministic sandbox replay.",
            "report_date": report_date,
            "report_label": report_label
        }, f, indent=2)

    # seed_meta.json
    meta_path = os.path.join(dest_dir, "seed_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": "atlas.iael_seed.v1",
            "created_utc": now_utc,
            "seed_stamp": stamp,
            "built_from": norm_path,
            "status_sha256": sha256(st_path),
            "invalidations_sha256": sha256(inv_path),
            "invalidations_count": len(invalidations)
        }, f, indent=2)

    print("✅ Seed written:", dest_dir)
    print("  report_date:", report_date, "label:", report_label)
    print("  invalidations:", len(invalidations))

if __name__ == "__main__":
    main()