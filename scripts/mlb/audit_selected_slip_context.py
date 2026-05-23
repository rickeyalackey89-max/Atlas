from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.overlays.mlb_publication_overlay import write_baseball_context_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit selected MLB slips against passive baseball-context gates.")
    parser.add_argument("--run-dir", required=True, help="MLB run directory containing scored_legs.json and slip outputs.")
    parser.add_argument("--fail-on-suppress", action="store_true", help="Exit non-zero if a selected leg is suppress-gated.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    manifest = write_baseball_context_artifacts(run_dir=run_dir, run_id=run_dir.name)
    packet_path = Path(manifest["artifacts"]["pick_packets"])
    packets_payload = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_index = {
        str(packet.get("projection_id") or "").strip(): packet
        for packet in packets_payload.get("packets", [])
        if isinstance(packet, dict)
    }

    selected_rows = _selected_slip_rows(run_dir, packet_index)
    summary = _summary(selected_rows)
    output_dir = run_dir / "operator"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "selected_slip_context_audit.json"
    csv_path = output_dir / "selected_slip_context_audit.csv"
    payload = {
        "schema_version": "mlb_selected_slip_context_audit_v1",
        "run_id": run_dir.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "context_artifacts": manifest.get("artifacts"),
        "selected_leg_count": len(selected_rows),
        "summary": summary,
        "selected_legs": selected_rows,
        "audit_path": str(audit_path),
        "csv_path": str(csv_path),
    }
    audit_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(csv_path, selected_rows)

    print(f"[SELECTED_CONTEXT] run={run_dir.name} selected_legs={len(selected_rows)}")
    print(f"[SELECTED_CONTEXT] gate_counts={summary['gate_counts']}")
    print(f"[SELECTED_CONTEXT] suppress_count={summary['suppress_count']} caution_count={summary['caution_count']}")
    print(f"[SELECTED_CONTEXT] top_reasons={summary['top_gate_reasons']}")
    print(f"[SELECTED_CONTEXT] wrote {audit_path}")

    if args.fail_on_suppress and summary["suppress_count"]:
        return 2
    return 0


def _selected_slip_rows(run_dir: Path, packet_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _slip_json_paths(run_dir):
        payload = json.loads(path.read_text(encoding="utf-8"))
        family = _family_from_path(path)
        for slip in _iter_slips(payload, path):
            if not isinstance(slip, dict):
                continue
            label = str(slip.get("label") or path.stem)
            for leg in slip.get("legs", []):
                if not isinstance(leg, dict):
                    continue
                projection_id = str(leg.get("source_projection_id") or leg.get("projection_id") or "").strip()
                packet = packet_index.get(projection_id, {})
                rows.append(
                    {
                        "family": family,
                        "slip": label,
                        "projection_id": projection_id,
                        "player": str(leg.get("player") or leg.get("player_name") or packet.get("player_name") or ""),
                        "team": str(leg.get("team") or packet.get("team") or ""),
                        "opp": str(leg.get("opp") or leg.get("opponent") or packet.get("opponent") or ""),
                        "market": str(leg.get("market") or packet.get("market") or ""),
                        "side": str(leg.get("direction") or leg.get("side") or packet.get("side") or "").lower(),
                        "line": leg.get("line", packet.get("line")),
                        "tier": str(leg.get("tier") or packet.get("tier") or ""),
                        "p_cal": leg.get("p_cal", packet.get("p_cal")),
                        "gate_level": str(packet.get("gate_level") or "missing_context_packet"),
                        "public_publish_ok": bool(packet.get("public_publish_ok")) if packet else False,
                        "lineup_status": str(packet.get("lineup_status") or ""),
                        "batting_order_bucket": str(packet.get("batting_order_bucket") or ""),
                        "pitcher_status": str(packet.get("pitcher_status") or ""),
                        "tags": "|".join(str(value) for value in packet.get("tags", [])),
                        "gate_reasons": "|".join(str(value) for value in packet.get("gate_reasons", [])),
                    }
                )
    return rows


def _iter_slips(payload: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    slips = payload.get("slips")
    if isinstance(slips, list):
        return [slip for slip in slips if isinstance(slip, dict)]
    legs = payload.get("legs")
    if isinstance(legs, list):
        return [
            {
                "label": payload.get("label") or path.stem,
                "legs": legs,
            }
        ]
    return []


def _slip_json_paths(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    names_in_slips_dir: set[str] = set()
    for path in (run_dir / "slips").glob("*.json"):
        if path.name in {"slips_manifest.json", "payout_quote_manifest.json", "payout_formula_audit.json"}:
            continue
        names_in_slips_dir.add(path.name)
        candidates.append(path)
    root_marketed = run_dir / "marketed_slips.json"
    if root_marketed.exists() and root_marketed.name not in names_in_slips_dir:
        candidates.append(root_marketed)
    return sorted(candidates)


def _family_from_path(path: Path) -> str:
    stem = path.stem.lower()
    if stem.startswith("system"):
        return "System"
    if stem.startswith("windfall"):
        return "Windfall"
    if stem.startswith("demonhunter"):
        return "DemonHunter"
    if stem.startswith("marketed"):
        return "Marketed"
    return path.stem


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_counts = Counter(str(row.get("gate_level") or "") for row in rows)
    reason_counts: Counter[str] = Counter()
    family_gate_counts: dict[str, Counter[str]] = {}
    for row in rows:
        family = str(row.get("family") or "")
        family_gate_counts.setdefault(family, Counter()).update([str(row.get("gate_level") or "")])
        for reason in str(row.get("gate_reasons") or "").split("|"):
            if reason:
                reason_counts.update([reason])
    return {
        "gate_counts": dict(sorted(gate_counts.items())),
        "family_gate_counts": {family: dict(sorted(counts.items())) for family, counts in sorted(family_gate_counts.items())},
        "suppress_count": gate_counts.get("suppress", 0) + gate_counts.get("missing_context_packet", 0),
        "caution_count": gate_counts.get("caution", 0),
        "ok_count": gate_counts.get("ok", 0),
        "top_gate_reasons": dict(reason_counts.most_common(12)),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
