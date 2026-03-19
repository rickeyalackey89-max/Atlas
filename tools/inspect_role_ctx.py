import argparse
import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _try_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _pct(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    i = int(math.floor((len(sorted_vals) - 1) * p))
    return sorted_vals[i]


def _summarize(vals: List[float]) -> Dict[str, Any]:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {
        "n": len(s),
        "min": s[0],
        "p10": _pct(s, 0.10),
        "p50": _pct(s, 0.50),
        "p90": _pct(s, 0.90),
        "p99": _pct(s, 0.99),
        "max": s[-1],
    }


def _fmt_summary(name: str, summ: Dict[str, Any]) -> str:
    if summ.get("n", 0) == 0:
        return f"{name}: n=0"
    return (
        f"{name}: n={summ['n']}  min={summ['min']:.3f}  "
        f"p10={summ['p10']:.3f}  p50={summ['p50']:.3f}  "
        f"p90={summ['p90']:.3f}  p99={summ['p99']:.3f}  max={summ['max']:.3f}"
    )


def _parse_outs_list(s: Optional[str]) -> List[str]:
    """Parse role_ctx_outs which is often a python-ish list string like "['A','B']"."""
    if not s:
        return []
    txt = str(s).strip()
    if not txt:
        return []
    # Convert python-ish to JSON-ish by swapping quotes
    txt = txt.replace("'", '"')
    try:
        obj = json.loads(txt)
        if isinstance(obj, list):
            return [str(x) for x in obj if str(x).strip()]
        return []
    except Exception:
        return []


def _parse_by_out(s: Optional[str]) -> List[Dict[str, Any]]:
    """Parse role_ctx_by_out which is often a list of dict-like entries."""
    if not s:
        return []
    txt = str(s).strip()
    if not txt:
        return []
    txt = txt.replace("'", '"')
    try:
        obj = json.loads(txt)
        if isinstance(obj, list):
            out = []
            for x in obj:
                if isinstance(x, dict):
                    out.append(x)
            return out
        return []
    except Exception:
        return []


@dataclass
class Row:
    raw: Dict[str, Any]

    @property
    def player(self) -> str:
        return str(self.raw.get("player", "")).strip()

    @property
    def team(self) -> str:
        return str(self.raw.get("team", "")).strip()

    @property
    def stat(self) -> str:
        return str(self.raw.get("stat", "")).strip()

    @property
    def direction(self) -> str:
        return str(self.raw.get("direction", "")).strip()

    @property
    def line(self) -> str:
        return str(self.raw.get("line", "")).strip()

    @property
    def role_ctx_mult(self) -> Optional[float]:
        return _try_float(self.raw.get("role_ctx_mult"))

    @property
    def role_ctx_mult_raw(self) -> Optional[float]:
        return _try_float(self.raw.get("role_ctx_mult_raw"))

    @property
    def role_ctx_reason(self) -> str:
        return str(self.raw.get("role_ctx_reason", "")).strip()

    @property
    def outs_n(self) -> int:
        return len(_parse_outs_list(self.raw.get("role_ctx_outs")))

    @property
    def matched_n(self) -> int:
        return len(_parse_by_out(self.raw.get("role_ctx_by_out")))


def _find_latest_csv(root: Path, pattern: str) -> Optional[Path]:
    files = list(root.rglob(pattern))
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime)
    return files[-1]


def _read_rows(csv_path: Path) -> List[Row]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [Row(r) for r in reader]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data-root",
        default="data",
        help="Root folder to search for output CSVs (default: data)",
    )
    ap.add_argument(
        "--pattern",
        default="scored_legs_deduped*.csv",
        help="CSV filename glob pattern (default: scored_legs_deduped*.csv)",
    )
    ap.add_argument(
        "--cap",
        type=float,
        default=1.10,
        help="Expected clamp cap for role_ctx_mult (default: 1.10)",
    )
    ap.add_argument(
        "--eps",
        type=float,
        default=1e-6,
        help="Float epsilon for comparisons (default: 1e-6)",
    )
    ap.add_argument(
        "--raw-threshold",
        type=float,
        default=1.10,
        help="Threshold to summarize raw multipliers above (default: 1.10)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=15,
        help="How many extreme rows to print (default: 15)",
    )
    args = ap.parse_args()

    data_root = Path(args.data_root)
    if not data_root.exists():
        print(f"[ERROR] data-root not found: {data_root.resolve()}")
        return 2

    latest = _find_latest_csv(data_root, args.pattern)
    if not latest:
        print(f"[ERROR] no files found under {data_root} matching {args.pattern}")
        return 2

    rows = _read_rows(latest)
    print(f"[OK] Latest CSV: {latest.as_posix()}")
    print(f"[OK] Rows: {len(rows)}")

    # Reason counts
    reason_counts: Dict[str, int] = {}
    for r in rows:
        k = r.role_ctx_reason or "(blank)"
        reason_counts[k] = reason_counts.get(k, 0) + 1
    top_reasons = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    print("\nTop role_ctx_reason:")
    for k, v in top_reasons:
        print(f"  {k:20s} {v}")

    # Collect multipliers
    mult_all = [x for x in (r.role_ctx_mult for r in rows) if x is not None]
    changed = [m for m in mult_all if abs(m - 1.0) > args.eps]
    at_cap = sum(1 for m in changed if abs(m - args.cap) < args.eps)

    print("\nMultipliers:")
    print(_fmt_summary("role_ctx_mult (all)", _summarize(mult_all)))
    print(_fmt_summary("role_ctx_mult (changed)", _summarize(changed)))
    if changed:
        print(f"at cap ({args.cap:.2f}) = {at_cap} / {len(changed)} ({100.0*at_cap/max(1,len(changed)):.1f}%)")

    # Raw multipliers
    raw_all = [x for x in (r.role_ctx_mult_raw for r in rows) if x is not None]
    raw_hi = [x for x in raw_all if x > args.raw_threshold + args.eps]
    print("\nRaw multipliers:")
    print(_fmt_summary("role_ctx_mult_raw (all)", _summarize(raw_all)))
    print(_fmt_summary(f"role_ctx_mult_raw (> {args.raw_threshold:.2f})", _summarize(raw_hi)))

    # Extreme rows
    extremes = [r for r in rows if (r.role_ctx_mult_raw is not None and r.role_ctx_mult_raw > max(args.raw_threshold, 1.5))]
    extremes.sort(key=lambda r: (r.role_ctx_mult_raw or 0.0), reverse=True)

    if extremes:
        print(f"\nTop {min(args.top, len(extremes))} raw extremes (raw>={max(args.raw_threshold, 1.5):.2f}):")
        for r in extremes[: args.top]:
            print(
                f"  {r.player:22s} {r.team:3s} {r.stat:4s} {r.direction:5s} line={r.line:>5s}  "
                f"raw={r.role_ctx_mult_raw:6.3f}  mult={r.role_ctx_mult if r.role_ctx_mult is not None else float('nan'):6.3f}  "
                f"reason={r.role_ctx_reason:10s}  outs_n={r.outs_n:2d} matched_n={r.matched_n:2d}"
            )
    else:
        print("\nNo raw extremes found above threshold.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())