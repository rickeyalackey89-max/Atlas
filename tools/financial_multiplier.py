#!/usr/bin/env python
from __future__ import annotations

"""
financial_multiplier.py (NewEngine-compatible)

This tool was originally wired to Atlas Legacy payout/pricing modules.
Legacy is being retired, but the TOOL stays.

What this tool does (unchanged intent):
1) Report-mode: rank engine-produced recommended CSVs using existing columns (ev_mult / payout_mult / hit_prob).
2) Ad-hoc mode (--in): compute a POWER-style payout multiplier from a slip JSON.

NewEngine note:
- For report-mode, we do NOT recompute multipliers; we just rank what the engine already wrote.
- For ad-hoc mode, we implement a small, explicit POWER multiplier model:
    total = base_mult * Π(leg_factor)
  where base_mult defaults to {3: 5x, 4: 10x, 5: 20x} unless provided in the JSON.

Kernel:
- If --kernel is provided, it may be:
    * a JSON file with {"STANDARD":1.0,"GOBLIN":0.92,"DEMON":1.12} (case-insensitive), or
    * a directory containing pp_kernel.json (we'll attempt to load it).
- If no kernel is provided, we default to neutral factors (all 1.0).
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


POWER_BASE_MULT: Dict[int, float] = {3: 5.0, 4: 10.0, 5: 20.0}


def _require_archives_root(repo_root: Path, p: Path) -> Path:
    p = p.expanduser().resolve()
    expected_root = (repo_root / "data" / "archives").resolve()
    expected_s = str(expected_root).replace("\\", "/").lower()
    out_s = str(p).replace("\\", "/").lower()
    if not out_s.startswith(expected_s):
        raise RuntimeError(f"--out-dir must be under {expected_root}. Got: {p}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_base_mult(n_legs: int) -> float:
    if n_legs not in POWER_BASE_MULT:
        raise RuntimeError(f"No base multiplier for POWER n_legs={n_legs}. Known: {sorted(POWER_BASE_MULT)}")
    return float(POWER_BASE_MULT[n_legs])


def _find_latest_run_dir(repo_root: Path) -> Path:
    runs = repo_root / "data" / "output" / "runs"
    if not runs.exists():
        raise RuntimeError(f"Runs folder not found: {runs}")
    candidates = [p for p in runs.iterdir() if p.is_dir()]
    if not candidates:
        raise RuntimeError(f"No run folders found under: {runs}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_run_dir(repo_root: Path, run_id: Optional[str]) -> Path:
    if not run_id:
        return _find_latest_run_dir(repo_root)
    run_dir = repo_root / "data" / "output" / "runs" / run_id
    if not run_dir.exists():
        raise RuntimeError(f"--run-id not found under data/output/runs: {run_dir}")
    return run_dir


def _read_recommended_csv(run_dir: Path, product_dirname: str, n_legs: int) -> Optional[pd.DataFrame]:
    p = run_dir / product_dirname / f"recommended_{n_legs}leg.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["__source_path"] = str(p)
    return df


def _rank_recommended(df: pd.DataFrame) -> pd.DataFrame:
    cols = df.columns

    if "ev_mult" in cols:
        key = "ev_mult"
    elif "atlas_power_mult" in cols:
        key = "atlas_power_mult"
    elif "payout_mult" in cols:
        key = "payout_mult"
    elif "hit_prob" in cols:
        key = "hit_prob"
    else:
        key = "avg_p" if "avg_p" in cols else None

    if key is None:
        raise RuntimeError("Could not find any ranking column in recommended CSV.")

    df[key] = pd.to_numeric(df[key], errors="coerce")
    df = df.sort_values(by=key, ascending=False).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df.insert(1, "rank_key", key)
    return df


def _write_df(df: pd.DataFrame, path: Path, top_n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.head(top_n).to_csv(path, index=False)


def _normalize_tier(x: Any) -> str:
    if x is None:
        return "STANDARD"
    s = str(x).strip().upper()
    # common aliases
    if s in {"S", "STD", "STANDARD"}:
        return "STANDARD"
    if s in {"G", "GOBLIN"}:
        return "GOBLIN"
    if s in {"D", "DEMON"}:
        return "DEMON"
    return s


def load_kernel(kernel_path: Optional[str]) -> Dict[str, float]:
    """
    Load a kernel mapping tier->factor.

    Accepted shapes:
      {"STANDARD": 1.0, "GOBLIN": 0.92, "DEMON": 1.12}
      {"tiers": {"STANDARD": 1.0, ...}}
    """
    # Neutral default (safe)
    default = {"STANDARD": 1.0, "GOBLIN": 1.0, "DEMON": 1.0}

    if not kernel_path:
        return default

    p = Path(kernel_path).expanduser().resolve()
    if p.is_dir():
        cand = p / "pp_kernel.json"
        if cand.exists():
            p = cand
        else:
            return default

    if not p.exists():
        return default

    try:
        obj = _load_json(p)
    except Exception:
        return default

    if isinstance(obj, dict) and "tiers" in obj and isinstance(obj["tiers"], dict):
        obj = obj["tiers"]

    if not isinstance(obj, dict):
        return default

    out: Dict[str, float] = {}
    for k, v in obj.items():
        try:
            out[_normalize_tier(k)] = float(v)
        except Exception:
            continue

    # ensure required keys exist
    for k, v in default.items():
        out.setdefault(k, v)

    return out


def power_multiplier(base_mult: float, legs: List[Any], kernel: Dict[str, float]) -> float:
    """
    Compute POWER multiplier:
      base_mult * Π(leg_factor)
    leg_factor uses (in priority order):
      1) explicit leg["factor"] or leg["multiplier"] if present
      2) kernel[tier] where tier is inferred from leg["tier"] / leg["type"] / leg["pick_type"]
      3) 1.0
    """
    mult = float(base_mult)

    for leg in legs:
        factor = None

        if isinstance(leg, dict):
            for key in ("factor", "multiplier", "leg_factor", "tier_factor"):
                if key in leg and leg[key] is not None:
                    try:
                        factor = float(leg[key])
                        break
                    except Exception:
                        pass

            if factor is None:
                tier = None
                for key in ("tier", "type", "pick_type", "projection_type", "label"):
                    if key in leg and leg[key] is not None:
                        tier = leg[key]
                        break
                tier_norm = _normalize_tier(tier)
                factor = float(kernel.get(tier_norm, 1.0))
        else:
            # string / unknown shape: best effort tier inference
            s = str(leg)
            tier = "STANDARD"
            if "GOBLIN" in s.upper():
                tier = "GOBLIN"
            elif "DEMON" in s.upper():
                tier = "DEMON"
            factor = float(kernel.get(tier, 1.0))

        mult *= float(factor)

    return mult


def _ad_hoc_single_slip_report(repo_root: Path, archives_root: Path, in_path: Path, kernel_path: Optional[str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = archives_root / "financial_reports" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = _load_json(in_path)

    if isinstance(payload, dict) and "legs" in payload:
        legs = list(payload.get("legs") or [])
        n_legs = int(payload.get("n_legs") or len(legs))
        base_mult = float(payload.get("base_mult") or _infer_base_mult(n_legs))
    elif isinstance(payload, list):
        legs = list(payload)
        n_legs = len(legs)
        base_mult = _infer_base_mult(n_legs)
    else:
        raise RuntimeError("Unsupported input JSON shape for --in.")

    kernel = load_kernel(kernel_path)
    mult = power_multiplier(base_mult=base_mult, legs=legs, kernel=kernel)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "single_slip_json",
        "input_path": str(in_path),
        "n_legs": n_legs,
        "base_mult": base_mult,
        "kernel": kernel,
        "total_multiplier": mult,
        "legs": legs,
    }

    out_path = out_dir / "financial_multiplier_single.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)

    ap.add_argument("--out-dir", required=True, help="Must be under <repo>/data/archives. Tool writes under financial_reports/<stamp>/")
    ap.add_argument("--run-id", default=None, help="Optional run folder under data/output/runs. Defaults to latest by mtime.")
    ap.add_argument("--product", default="both", choices=["system", "windfall", "both"], help="Which product(s) to report.")
    ap.add_argument("--n-legs", default="all", choices=["3", "4", "5", "all"], help="Leg counts to include.")
    ap.add_argument("--top-n", type=int, default=25, help="Rows per report.")
    ap.add_argument("--in", dest="in_path", default=None, help="(Optional) single-slip JSON path for ad-hoc multiplier report.")
    ap.add_argument("--kernel", default=None, help="(Optional) kernel JSON path for ad-hoc single-slip report.")

    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    archives_root = _require_archives_root(repo_root, Path(args.out_dir))

    # Single-slip mode
    if args.in_path:
        in_path = Path(args.in_path).expanduser().resolve()
        if not in_path.exists():
            raise RuntimeError(f"Input JSON not found: {in_path}")
        out_path = _ad_hoc_single_slip_report(repo_root, archives_root, in_path, args.kernel)
        print(f"Wrote: {out_path}")
        return 0

    run_dir = _resolve_run_dir(repo_root, args.run_id)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_base = archives_root / "financial_reports" / stamp
    out_base.mkdir(parents=True, exist_ok=True)

    legs_set = [3, 4, 5] if args.n_legs == "all" else [int(args.n_legs)]
    products: List[Tuple[str, str]] = []
    if args.product in ("system", "both"):
        products.append(("system", "System"))
    if args.product in ("windfall", "both"):
        products.append(("windfall", "Windfall"))

    summary: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "engine_csv_reports",
        "run_dir": str(run_dir),
        "reports": [],
    }

    for product_key, product_dirname in products:
        for n in legs_set:
            df = _read_recommended_csv(run_dir, product_dirname, n)
            if df is None or len(df) == 0:
                summary["reports"].append({
                    "product": product_key,
                    "n_legs": n,
                    "status": "missing_or_empty",
                    "source": str((run_dir / product_dirname / f"recommended_{n}leg.csv")),
                })
                continue

            ranked = _rank_recommended(df)
            out_csv = out_base / f"{product_key}_{n}leg_report.csv"
            _write_df(ranked, out_csv, top_n=args.top_n)

            meta = {
                "product": product_key,
                "n_legs": n,
                "rank_key": str(ranked.iloc[0]["rank_key"]) if "rank_key" in ranked.columns else None,
                "rows_total": int(len(ranked)),
                "rows_written": int(min(args.top_n, len(ranked))),
                "source": str(ranked["__source_path"].iloc[0]) if "__source_path" in ranked.columns else None,
                "output_csv": str(out_csv),
            }
            (out_base / f"{product_key}_{n}leg_report.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

            summary["reports"].append({**meta, "status": "ok"})
            print(f"Wrote: {out_csv}")

    (out_base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {out_base / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
