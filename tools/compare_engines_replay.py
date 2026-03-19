from __future__ import annotations

"""
compare_engines_replay.py (NewEngine-compatible)

Legacy retirement note:
This tool originally compared "legacy vs new" engines in-memory.
Legacy is being retired; the TOOL stays.

NewEngine version:
- Compare two *run artifacts* (e.g., LIVE vs REPLAY) by hashing and (optionally) bounded numeric drift checks.
- Archives-only outputs rule is preserved.

Typical usage:
  py -m Atlas.cli tools run compare_engines_replay -- --a-run-id 20260219_060943 --b-run-id 20260219_125744 --out-dir data/archives/bundles/COMPARE_.../analysis

Or compare explicit directories:
  py -m Atlas.cli tools run compare_engines_replay -- --a-dir <path> --b-dir <path> --out-dir <archives/.../analysis>

What it compares:
- All *.csv, *.json under each directory (recursively), excluding huge raw snapshots by default.
- Emits per-file hashes + quick structural stats.
- For CSVs that exist on both sides, emits a column-aware diff summary (shape, columns, max abs drift for numeric cols if epsilon set).

This does NOT mutate any engine logic.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ensure_archives_out_dir(repo_root: Path, out_dir: Path) -> Path:
    out_dir = out_dir.expanduser().resolve()
    archives_root = (repo_root / "data" / "archives").resolve()
    try:
        out_dir.relative_to(archives_root)
    except Exception:
        raise SystemExit(f"FATAL: --out-dir must be under {archives_root} (archives-only rule). Got: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _resolve_run_dir(repo_root: Path, run_id: str) -> Path:
    p = repo_root / "data" / "output" / "runs" / run_id
    if not p.exists():
        raise SystemExit(f"Run folder not found: {p}")
    return p


def _list_files(root: Path, *, include_raw: bool) -> List[Path]:
    exts = {".csv", ".json"}
    out: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        if not include_raw:
            # skip raw snapshots + very large json blobs by convention
            s = str(p).replace("\\", "/").lower()
            if "/data/raw/" in s or "/raw/" in s:
                continue
        out.append(p)
    out.sort(key=lambda x: str(x).lower())
    return out


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _hash_file(p: Path) -> str:
    return _sha256_bytes(_read_bytes(p))


def _csv_profile(p: Path) -> Dict[str, Any]:
    try:
        df = pd.read_csv(p)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "rows": int(len(df)),
        "cols": int(len(df.columns)),
        "columns": list(df.columns),
    }


def _csv_max_abs_drift(a: Path, b: Path, epsilon: float) -> Dict[str, Any]:
    try:
        da = pd.read_csv(a)
        db = pd.read_csv(b)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    out: Dict[str, Any] = {"ok": True, "shape_a": list(da.shape), "shape_b": list(db.shape)}
    if da.shape != db.shape:
        out["ok"] = False
        out["reason"] = "shape_mismatch"
        return out

    # align columns exactly
    if list(da.columns) != list(db.columns):
        out["ok"] = False
        out["reason"] = "column_mismatch"
        out["cols_a"] = list(da.columns)
        out["cols_b"] = list(db.columns)
        return out

    max_abs: Dict[str, float] = {}
    for c in da.columns:
        sa = da[c]
        sb = db[c]
        # numeric-only drift
        a_num = pd.to_numeric(sa, errors="coerce")
        b_num = pd.to_numeric(sb, errors="coerce")
        if a_num.notna().sum() == 0 and b_num.notna().sum() == 0:
            continue
        diff = (a_num.fillna(0.0) - b_num.fillna(0.0)).abs()
        m = float(diff.max())
        max_abs[c] = m

    out["max_abs"] = max_abs
    out["epsilon"] = float(epsilon)
    out["ok"] = all(v <= epsilon for v in max_abs.values()) if max_abs else True
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)

    ap.add_argument("--out-dir", required=False, default=None, help="Archives-only output dir. Default: data/archives/bundles/ENGINE_COMPARE_<stamp>/analysis")
    ap.add_argument("--a-run-id", default=None, help="Run id under data/output/runs for side A.")
    ap.add_argument("--b-run-id", default=None, help="Run id under data/output/runs for side B.")
    ap.add_argument("--a-dir", default=None, help="Explicit directory for side A.")
    ap.add_argument("--b-dir", default=None, help="Explicit directory for side B.")
    ap.add_argument("--include-raw", action="store_true", help="Include raw snapshot JSONs in the comparison.")
    ap.add_argument("--epsilon", type=float, default=0.0, help="If >0, compute max abs drift for CSVs and flag if any numeric column exceeds epsilon.")

    args = ap.parse_args(argv)

    repo_root = _repo_root()
    if args.out_dir:
        out_dir = _ensure_archives_out_dir(repo_root, Path(args.out_dir))
    else:
        out_dir = _ensure_archives_out_dir(repo_root, repo_root / "data" / "archives" / "bundles" / f"ENGINE_COMPARE_{_utc_stamp()}" / "analysis")

    if args.a_dir:
        a_root = Path(args.a_dir).expanduser().resolve()
    elif args.a_run_id:
        a_root = _resolve_run_dir(repo_root, args.a_run_id)
    else:
        raise SystemExit("Provide --a-dir or --a-run-id")

    if args.b_dir:
        b_root = Path(args.b_dir).expanduser().resolve()
    elif args.b_run_id:
        b_root = _resolve_run_dir(repo_root, args.b_run_id)
    else:
        raise SystemExit("Provide --b-dir or --b-run-id")

    files_a = _list_files(a_root, include_raw=bool(args.include_raw))
    files_b = _list_files(b_root, include_raw=bool(args.include_raw))

    map_a = {_rel(a_root, p): p for p in files_a}
    map_b = {_rel(b_root, p): p for p in files_b}

    keys = sorted(set(map_a) | set(map_b))
    rows: List[Dict[str, Any]] = []

    drift_reports: Dict[str, Any] = {}

    for k in keys:
        pa = map_a.get(k)
        pb = map_b.get(k)

        ra = {"exists": pa is not None, "sha256": _hash_file(pa) if pa else None, "path": str(pa) if pa else None}
        rb = {"exists": pb is not None, "sha256": _hash_file(pb) if pb else None, "path": str(pb) if pb else None}

        row = {"rel_path": k, "a": ra, "b": rb, "same_hash": (ra["sha256"] == rb["sha256"]) if ra["sha256"] and rb["sha256"] else False}

        # lightweight CSV profiles
        if k.lower().endswith(".csv"):
            if pa:
                row["a_csv"] = _csv_profile(pa)
            if pb:
                row["b_csv"] = _csv_profile(pb)

            if pa and pb and args.epsilon and args.epsilon > 0:
                drift_reports[k] = _csv_max_abs_drift(pa, pb, epsilon=float(args.epsilon))

        rows.append(row)

    summary = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "a_root": str(a_root),
        "b_root": str(b_root),
        "include_raw": bool(args.include_raw),
        "epsilon": float(args.epsilon),
        "files_total": int(len(keys)),
        "files_a": int(len(files_a)),
        "files_b": int(len(files_b)),
        "files_common": int(len(set(map_a) & set(map_b))),
        "hash_equal_common": int(sum(1 for r in rows if r.get("same_hash"))),
        "hash_diff_common": int(sum(1 for r in rows if (r.get("a", {}).get("sha256") and r.get("b", {}).get("sha256") and not r.get("same_hash")))),
        "only_in_a": int(sum(1 for r in rows if r.get("a", {}).get("exists") and not r.get("b", {}).get("exists"))),
        "only_in_b": int(sum(1 for r in rows if r.get("b", {}).get("exists") and not r.get("a", {}).get("exists"))),
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "files.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    if drift_reports:
        (out_dir / "drift.json").write_text(json.dumps(drift_reports, indent=2), encoding="utf-8")

    print(f"Wrote: {out_dir / 'summary.json'}")
    print(f"Wrote: {out_dir / 'files.json'}")
    if drift_reports:
        print(f"Wrote: {out_dir / 'drift.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
