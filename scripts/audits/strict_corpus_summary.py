"""Summarize a strict-fidelity replay corpus before CAT/LODO training."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UNMARKETED_EXACT_STATS = {"FTA"}
REPLAY_RUNS = ROOT / "data" / "telemetry" / "replay_runs"


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default).astype(float)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    values = df[col]
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    return values.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _brier(df: pd.DataFrame, p_col: str) -> float | None:
    if p_col not in df.columns or "hit" not in df.columns:
        return None
    tmp = df[[p_col, "hit"]].copy()
    tmp[p_col] = pd.to_numeric(tmp[p_col], errors="coerce")
    tmp["hit"] = pd.to_numeric(tmp["hit"], errors="coerce")
    tmp = tmp.dropna()
    tmp = tmp[tmp["hit"].isin([0.0, 1.0])]
    if tmp.empty:
        return None
    return float(((tmp[p_col].clip(0.0001, 0.9999) - tmp["hit"]) ** 2).mean())


def _logloss(df: pd.DataFrame, p_col: str) -> float | None:
    if p_col not in df.columns or "hit" not in df.columns:
        return None
    tmp = df[[p_col, "hit"]].copy()
    tmp[p_col] = pd.to_numeric(tmp[p_col], errors="coerce")
    tmp["hit"] = pd.to_numeric(tmp["hit"], errors="coerce")
    tmp = tmp.dropna()
    tmp = tmp[tmp["hit"].isin([0.0, 1.0])]
    if tmp.empty:
        return None
    p = tmp[p_col].clip(0.0001, 0.9999)
    y = tmp["hit"]
    return float((-(y * p.map(math.log) + (1.0 - y) * (1.0 - p).map(math.log))).mean())


def _find_run_dir(corpus_dir: Path) -> Path | None:
    candidates = sorted(corpus_dir.rglob("scored_legs_deduped.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return candidates[0].parent


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _strict_verdict(run_dir: Path) -> tuple[str, int]:
    audit = _read_json(run_dir / "strict_replay_fidelity_audit.json")
    return str(audit.get("verdict") or "MISSING"), len(audit.get("failures") or [])


def _parse_legs_field(legs: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in str(legs or "").split("|"):
        m = re.match(r"^\s*(.+?)\s+(OVER|UNDER)\s+([A-Z0-9]+)\s+([\d.]+)\s+\(([A-Z]+)\)", item.strip())
        if not m:
            continue
        out.append(
            {
                "player": re.sub(r"\s+", " ", m.group(1)).strip().lower(),
                "direction": m.group(2).upper(),
                "stat": m.group(3).upper(),
                "line": float(m.group(4)),
                "tier": m.group(5).upper(),
            }
        )
    return out


def _truth_map(eval_df: pd.DataFrame) -> dict[tuple[str, str, float, str], int]:
    out: dict[tuple[str, str, float, str], int] = {}
    required = {"player", "stat", "line", "direction", "hit"}
    if not required.issubset(eval_df.columns):
        return out
    for _, row in eval_df.iterrows():
        try:
            key = (
                re.sub(r"\s+", " ", str(row["player"])).strip().lower(),
                str(row["stat"]).upper(),
                float(row["line"]),
                str(row["direction"]).upper(),
            )
            hit = pd.to_numeric(pd.Series([row["hit"]]), errors="coerce").iloc[0]
            if pd.notna(hit):
                out[key] = int(float(hit) >= 0.5)
        except Exception:
            continue
    return out


def _score_leg_dicts(legs: list[dict[str, Any]], truth: dict[tuple[str, str, float, str], int]) -> tuple[int, int]:
    hits = 0
    total = 0
    for leg in legs:
        key = (leg["player"], leg["stat"], float(leg["line"]), leg["direction"])
        if key not in truth:
            continue
        total += 1
        hits += int(truth[key])
    return hits, total


def _slip_rows(run_dir: Path, eval_df: pd.DataFrame, date: str) -> list[dict[str, Any]]:
    truth = _truth_map(eval_df)
    rows: list[dict[str, Any]] = []
    family_paths = [
        ("System", run_dir / "System"),
        ("Windfall", run_dir / "Windfall"),
        ("System", run_dir),
    ]
    seen_paths: set[Path] = set()
    for family, folder in family_paths:
        if not folder.is_dir():
            continue
        for csv_path in sorted(folder.glob("recommended_*leg.csv")):
            if csv_path in seen_paths:
                continue
            seen_paths.add(csv_path)
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            if df.empty or "legs" not in df.columns:
                continue
            try:
                n_legs = int(re.search(r"recommended_(\d+)leg", csv_path.name).group(1))  # type: ignore[union-attr]
            except Exception:
                n_legs = 0
            leg_dicts = _parse_legs_field(str(df.iloc[0].get("legs", "")))
            hits, total = _score_leg_dicts(leg_dicts, truth)
            rows.append(
                {
                    "date": date,
                    "family": family,
                    "n_legs": n_legs,
                    "status": "OK" if total == n_legs and n_legs > 0 else f"PARTIAL_{total}_{n_legs}",
                    "legs_hit": hits,
                    "legs_total": total,
                    "slip_won": int(total == n_legs and hits == n_legs and n_legs > 0),
                    "path": str(csv_path.relative_to(ROOT)),
                }
            )

    marketed = run_dir / "marketed_slips.csv"
    if marketed.is_file():
        try:
            mdf = pd.read_csv(marketed)
        except Exception:
            mdf = pd.DataFrame()
        if not mdf.empty and "slip" in mdf.columns:
            for slip_name, group in mdf.groupby("slip"):
                leg_dicts = []
                for _, row in group.iterrows():
                    try:
                        leg_dicts.append(
                            {
                                "player": re.sub(r"\s+", " ", str(row.get("player", ""))).strip().lower(),
                                "stat": str(row.get("stat", "")).upper(),
                                "line": float(row.get("line", 0.0)),
                                "direction": str(row.get("direction", "")).upper(),
                            }
                        )
                    except Exception:
                        continue
                try:
                    n_legs = int(str(slip_name).split("-")[0])
                except Exception:
                    n_legs = len(leg_dicts)
                hits, total = _score_leg_dicts(leg_dicts, truth)
                rows.append(
                    {
                        "date": date,
                        "family": "Marketed",
                        "n_legs": n_legs,
                        "status": "OK" if total == n_legs and n_legs > 0 else f"PARTIAL_{total}_{n_legs}",
                        "legs_hit": hits,
                        "legs_total": total,
                        "slip_won": int(total == n_legs and hits == n_legs and n_legs > 0),
                        "path": str(marketed.relative_to(ROOT)),
                    }
                )
    return rows


def summarize(prefix: str, dates_filter: set[str] | None = None) -> dict[str, Any]:
    date_rows: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []
    scored_frames: list[pd.DataFrame] = []

    for folder in sorted(REPLAY_RUNS.glob(f"{prefix}*")):
        m = re.search(r"(\d{8})$", folder.name)
        if not m:
            continue
        if dates_filter is not None and m.group(1) not in dates_filter:
            continue
        date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
        run_dir = _find_run_dir(folder)
        if run_dir is None:
            date_rows.append({"date": date, "strict_verdict": "MISSING_RUN_DIR"})
            continue
        strict_verdict, strict_failures = _strict_verdict(run_dir)
        scored = pd.read_csv(run_dir / "scored_legs_deduped.csv", low_memory=False)
        eval_path = run_dir / "eval_legs.csv"
        eval_df = pd.read_csv(eval_path, low_memory=False) if eval_path.is_file() else pd.DataFrame()
        if "hit" not in scored.columns and not eval_df.empty:
            merge_cols = [c for c in ["player", "stat", "line", "direction"] if c in scored.columns and c in eval_df.columns]
            if merge_cols and "hit" in eval_df.columns:
                scored = scored.merge(eval_df[merge_cols + ["hit"]].drop_duplicates(merge_cols), on=merge_cols, how="left")

        scored_for_overall = scored.copy()
        scored_for_overall["_corpus_date"] = date
        scored_frames.append(scored_for_overall)
        pcols = [c for c in ["p", "p_role", "p_adj", "p_for_cal", "p_catboost", "p_cal", "p_cal_marketed"] if c in scored.columns]
        stat = scored["stat"].fillna("").astype(str).str.strip().str.upper() if "stat" in scored.columns else pd.Series("", index=scored.index)
        expected_unmarketed = stat.isin(EXPECTED_UNMARKETED_EXACT_STATS)
        market_eligible = ~expected_unmarketed
        prior_n = _num(scored, "external_prior_n")
        exact_market = _bool(scored, "external_prior_exact_market")
        row: dict[str, Any] = {
            "date": date,
            "run_dir": str(run_dir.relative_to(ROOT)),
            "strict_verdict": strict_verdict,
            "strict_failures": strict_failures,
            "rows": int(len(scored)),
            "eval_rows": int(len(eval_df)),
            "external_prior_share": float((prior_n > 0).mean()) if len(scored) else 0.0,
            "exact_market_share": float(exact_market.mean()) if len(scored) else 0.0,
            "market_eligible_rows": int(market_eligible.sum()) if len(scored) else 0,
            "expected_unmarketed_exact_rows": int(expected_unmarketed.sum()) if len(scored) else 0,
            "external_prior_share_market_eligible": float((prior_n[market_eligible] > 0).mean()) if int(market_eligible.sum()) else 0.0,
            "exact_market_share_market_eligible": float(exact_market[market_eligible].mean()) if int(market_eligible.sum()) else 0.0,
            "spread_ok_share": float(_bool(scored, "spread_ok").mean()) if len(scored) else 0.0,
            "game_total_norm_nonzero_share": float(_num(scored, "game_total_norm").ne(0).mean()) if len(scored) else 0.0,
            "role_metrics_snapshot_share": float(scored.get("role_metrics_snapshot_id", pd.Series("", index=scored.index)).fillna("").astype(str).str.len().gt(0).mean()) if len(scored) else 0.0,
            "role_metrics_minutes_share": float(pd.to_numeric(scored.get("role_metrics_minutes_projection", pd.Series(dtype=float)), errors="coerce").notna().mean()) if len(scored) else 0.0,
            "cat_defaulted_features_share": float(scored.get("catboost_defaulted_features", pd.Series("", index=scored.index)).fillna("").astype(str).str.len().gt(0).mean()) if len(scored) else 0.0,
        }
        for pcol in pcols:
            row[f"{pcol}_brier"] = _brier(scored, pcol)
            row[f"{pcol}_logloss"] = _logloss(scored, pcol)
        date_rows.append(row)
        slip_rows.extend(_slip_rows(run_dir, eval_df, date))

    all_scored = pd.concat(scored_frames, ignore_index=True) if scored_frames else pd.DataFrame()
    overall: dict[str, Any] = {"rows": int(len(all_scored)), "dates": sorted({r["date"] for r in date_rows})}
    for pcol in [c for c in ["p", "p_role", "p_adj", "p_for_cal", "p_catboost", "p_cal", "p_cal_marketed"] if c in all_scored.columns]:
        overall[f"{pcol}_brier"] = _brier(all_scored, pcol)
        overall[f"{pcol}_logloss"] = _logloss(all_scored, pcol)
    overall["strict_pass_dates"] = sum(1 for r in date_rows if r.get("strict_verdict") == "PASS")
    overall["strict_total_dates"] = len(date_rows)
    overall["strict_corpus_pass"] = bool(date_rows) and overall["strict_pass_dates"] == overall["strict_total_dates"]

    return {"overall": overall, "dates": date_rows, "slips": slip_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize strict replay corpus metrics.")
    ap.add_argument("--prefix", required=True, help="Replay corpus prefix, including trailing underscore.")
    ap.add_argument("--out-dir", default=None, help="Output directory.")
    ap.add_argument("--dates", nargs="*", help="Optional YYYYMMDD dates to include.")
    args = ap.parse_args()

    payload = summarize(args.prefix, set(args.dates) if args.dates else None)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "model" / "candidates" / f"{args.prefix.rstrip('_')}_summary"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "strict_corpus_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pd.DataFrame(payload["dates"]).to_csv(out_dir / "strict_corpus_date_summary.csv", index=False)
    pd.DataFrame(payload["slips"]).to_csv(out_dir / "strict_corpus_slip_rows.csv", index=False)
    slips = pd.DataFrame(payload["slips"])
    if not slips.empty:
        ok = slips[slips["status"] == "OK"].copy()
        if not ok.empty:
            agg = (
                ok.groupby(["family", "n_legs"], dropna=False)
                .agg(slips=("slip_won", "count"), wins=("slip_won", "sum"), leg_hits=("legs_hit", "sum"), legs=("legs_total", "sum"))
                .reset_index()
            )
            agg["slip_win_rate"] = agg["wins"] / agg["slips"]
            agg["leg_hit_rate"] = agg["leg_hits"] / agg["legs"]
            agg.to_csv(out_dir / "strict_corpus_slip_family_summary.csv", index=False)

    print(json.dumps(payload["overall"], indent=2), flush=True)
    print(f"Wrote summary: {out_dir}", flush=True)
    return 0 if payload["overall"].get("strict_corpus_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
