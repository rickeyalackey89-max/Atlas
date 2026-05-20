"""Build empirical PrizePicks payout fallback table from exact live quotes."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "atlas_prizepicks_empirical_payout_fallback_v1"
TOOL_VERSION = "build_prizepicks_empirical_payouts_v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/mlb/model/prizepicks_empirical_payouts.json"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    manifests = sorted((root / "data" / "mlb" / "live_runs").glob("**/slips/payout_quote_manifest.json"))
    rows = _exact_quote_rows(manifests)
    tables = {
        "family_label": _build_table(rows, lambda row: f"{_key(row['family'])}|{_key(row['label'])}"),
        "family_n_legs": _build_table(rows, lambda row: f"{_key(row['family'])}|{row['n_legs']}"),
        "n_legs": _build_table(rows, lambda row: str(row["n_legs"])),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "root": str(root),
            "manifest_count": len(manifests),
            "exact_quote_count": len(rows),
            "source_glob": "data/mlb/live_runs/**/slips/payout_quote_manifest.json",
        },
        "selection_rules": {
            "only_live_runs": True,
            "only_exact_prizepicks_quotes": True,
            "estimate": "median_all_correct_multiplier",
            "fallback_order": ["family_label", "family_n_legs", "n_legs", "static_power_table"],
        },
        "tables": tables,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Exact live quotes: {len(rows)}")
    for table_name, table in tables.items():
        print(f"{table_name}: {len(table)} buckets")
    return 0


def _exact_quote_rows(manifests: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(manifest.get("run_mode") or "").lower() != "live":
            continue
        for quote in manifest.get("quotes", []) or []:
            if not isinstance(quote, dict):
                continue
            chosen = quote.get("chosen") if isinstance(quote.get("chosen"), dict) else {}
            if not bool(chosen.get("payout_is_exact")):
                continue
            multiplier = _float(chosen.get("all_correct"))
            n_legs = int(quote.get("n_legs") or 0)
            if multiplier <= 0 or n_legs <= 0:
                continue
            rows.append(
                {
                    "manifest": str(manifest_path),
                    "family": str(quote.get("family") or ""),
                    "label": str(quote.get("label") or ""),
                    "n_legs": n_legs,
                    "all_correct": multiplier,
                }
            )
    return rows


def _build_table(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if key.strip("|"):
            grouped[key].append(float(row["all_correct"]))
    return {key: _stats(values) for key, values in sorted(grouped.items())}


def _stats(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 6),
        "median": round(statistics.median(ordered), 6),
        "min": round(ordered[0], 6),
        "max": round(ordered[-1], 6),
        "q25": round(_percentile(ordered, 0.25), 6),
        "q75": round(_percentile(ordered, 0.75), 6),
        "values": [round(value, 6) for value in ordered],
    }


def _percentile(ordered: list[float], pct: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * pct
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    weight = idx - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
