"""Probe PrizePicks slip quotes to infer per-leg market pressure.

This does not submit entries. It repeatedly quotes same-size slips where one
neutral reference leg is replaced by a target leg, then measures how the quoted
payout changes.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Atlas.core.prizepicks_quote import clean_projection_id, quote_prizepicks_payout


@dataclass
class ProbeResult:
    player: str
    team: str
    opp: str
    stat: str
    direction: str
    tier: str
    line: float
    source_projection_id: str
    p_cal: float | None
    p_adj: float | None
    odds_type: str
    samples: int
    quote_successes: int
    pp_pressure_mean: float | None
    pp_pressure_std: float | None
    payout_delta_mean: float | None
    payout_delta_std: float | None
    payout_penalty_pct_mean: float | None
    target_payout_mean: float | None
    baseline_payout_mean: float | None
    reference_tier: str | None
    reference_projection_ids: str
    anchor_projection_ids: str


def _latest_run_dir() -> Path:
    runs = [p for p in (ROOT / "data" / "output" / "runs").iterdir() if p.is_dir()]
    if not runs:
        raise FileNotFoundError("No run directories found under data/output/runs")
    return sorted(runs, key=lambda p: p.stat().st_mtime)[-1]


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _leg(row: pd.Series) -> dict[str, Any]:
    return {
        "source_projection_id": clean_projection_id(row.get("source_projection_id") or row.get("projection_id")),
        "projection_id": clean_projection_id(row.get("source_projection_id") or row.get("projection_id")),
        "direction": str(row.get("direction") or row.get("dir") or "").lower(),
        "player": str(row.get("player") or ""),
        "team": str(row.get("team") or ""),
        "opp": str(row.get("opp") or ""),
        "stat": str(row.get("stat") or ""),
        "line": _safe_float(row.get("line")),
        "tier": str(row.get("tier") or "").upper(),
    }


def _power_mult(quote: dict[str, Any] | None) -> float | None:
    if not quote:
        return None
    power = (quote.get("power") or {}).get("all_correct")
    flex = (quote.get("flex") or {}).get("all_correct")
    chosen = power if power is not None else flex
    return _safe_float(chosen)


def _load_scored(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "direction" not in df.columns and "dir" in df.columns:
        df["direction"] = df["dir"]
    if "source_projection_id" not in df.columns:
        df["source_projection_id"] = df.get("projection_id", "")
    df = df.copy()
    df["source_projection_id"] = df["source_projection_id"].map(clean_projection_id)
    df["direction"] = df["direction"].astype(str).str.lower().str.strip()
    df["tier"] = df["tier"].astype(str).str.upper().str.strip()
    df["p_cal_num"] = pd.to_numeric(df.get("p_cal"), errors="coerce")
    df["p_adj_num"] = pd.to_numeric(df.get("p_adj"), errors="coerce")
    df["line_num"] = pd.to_numeric(df.get("line"), errors="coerce")
    df = df[
        (df["source_projection_id"] != "")
        & df["direction"].isin(["over", "under"])
        & df["line_num"].notna()
    ].copy()
    return df.drop_duplicates(subset=["source_projection_id", "direction"]).reset_index(drop=True)


def _stable_anchor_pool(df: pd.DataFrame) -> pd.DataFrame:
    pool = df[df["tier"].eq("STANDARD")].copy()
    if pool.empty:
        pool = df.copy()
    pool["anchor_score"] = (pool["p_cal_num"].fillna(0.58) - 0.58).abs()
    if "minutes_cv" in pool.columns:
        pool["anchor_score"] += pd.to_numeric(pool["minutes_cv"], errors="coerce").fillna(0.25) * 0.15
    if "fragility" in pool.columns:
        pool["anchor_score"] += pd.to_numeric(pool["fragility"], errors="coerce").fillna(0.0).abs() * 0.05
    return pool.sort_values(["anchor_score", "player", "stat", "line_num"]).reset_index(drop=True)


def _target_rows(df: pd.DataFrame, max_targets: int) -> pd.DataFrame:
    ranked = df.copy()
    ranked["rank_score"] = ranked["p_cal_num"].fillna(0.0)
    return ranked.sort_values(["rank_score", "player", "stat"], ascending=[False, True, True]).head(max_targets)


def _pick_reference(df: pd.DataFrame, target: pd.Series) -> pd.Series | None:
    candidates = df[
        (df["source_projection_id"] != target["source_projection_id"])
        & (df["player"].astype(str) != str(target.get("player")))
    ].copy()
    same_tier = candidates[candidates["tier"].eq(str(target.get("tier")))]
    if not same_tier.empty:
        candidates = same_tier.copy()
    elif not candidates[candidates["tier"].eq("STANDARD")].empty:
        candidates = candidates[candidates["tier"].eq("STANDARD")].copy()
    if candidates.empty:
        return None
    target_p = _safe_float(target.get("p_cal_num")) or 0.58
    candidates["reference_score"] = (candidates["p_cal_num"].fillna(0.58) - target_p).abs()
    return candidates.sort_values(["reference_score", "player", "stat"]).iloc[0]


def _pick_anchors(pool: pd.DataFrame, blocked_ids: set[str], blocked_players: set[str], count: int, offset: int) -> list[pd.Series]:
    anchors: list[pd.Series] = []
    if pool.empty:
        return anchors
    for i in range(len(pool)):
        row = pool.iloc[(i + offset) % len(pool)]
        pid = str(row.get("source_projection_id") or "")
        player = str(row.get("player") or "")
        if pid in blocked_ids or player in blocked_players:
            continue
        anchors.append(row)
        blocked_ids.add(pid)
        blocked_players.add(player)
        if len(anchors) >= count:
            break
    return anchors


def run_probe(
    scored_path: Path,
    out_dir: Path,
    max_targets: int,
    samples: int,
    slip_size: int,
    sleep_seconds: float,
) -> tuple[Path, Path]:
    df = _load_scored(scored_path)
    anchor_pool = _stable_anchor_pool(df)
    targets = _target_rows(df, max_targets=max_targets)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[ProbeResult] = []
    raw_samples: list[dict[str, Any]] = []

    for idx, target in targets.iterrows():
        reference = _pick_reference(df, target)
        if reference is None:
            continue
        target_leg = _leg(target)
        reference_leg = _leg(reference)
        target_mults: list[float] = []
        baseline_mults: list[float] = []
        deltas: list[float] = []
        pressures: list[float] = []
        penalties: list[float] = []
        anchor_ids_seen: list[str] = []

        for sample_idx in range(samples):
            blocked_ids = {target_leg["source_projection_id"], reference_leg["source_projection_id"]}
            blocked_players = {target_leg["player"], reference_leg["player"]}
            anchors = _pick_anchors(
                anchor_pool,
                blocked_ids=blocked_ids,
                blocked_players=blocked_players,
                count=max(0, slip_size - 1),
                offset=(idx * samples + sample_idx) * max(1, slip_size - 1),
            )
            if len(anchors) < slip_size - 1:
                continue
            anchor_legs = [_leg(row) for row in anchors]
            anchor_ids_seen.extend([leg["source_projection_id"] for leg in anchor_legs])

            target_quote = quote_prizepicks_payout([target_leg, *anchor_legs])
            time.sleep(sleep_seconds)
            baseline_quote = quote_prizepicks_payout([reference_leg, *anchor_legs])
            time.sleep(sleep_seconds)

            target_mult = _power_mult(target_quote)
            baseline_mult = _power_mult(baseline_quote)
            raw_samples.append({
                "target_projection_id": target_leg["source_projection_id"],
                "reference_projection_id": reference_leg["source_projection_id"],
                "anchor_projection_ids": [leg["source_projection_id"] for leg in anchor_legs],
                "target_payout": target_mult,
                "baseline_payout": baseline_mult,
                "target_quote_ok": bool(target_quote),
                "baseline_quote_ok": bool(baseline_quote),
            })
            if target_mult is None or baseline_mult is None or baseline_mult <= 0 or target_mult <= 0:
                continue
            target_mults.append(target_mult)
            baseline_mults.append(baseline_mult)
            deltas.append(target_mult - baseline_mult)
            pressures.append(baseline_mult / target_mult)
            penalties.append((baseline_mult - target_mult) / baseline_mult)

        rows.append(ProbeResult(
            player=str(target.get("player") or ""),
            team=str(target.get("team") or ""),
            opp=str(target.get("opp") or ""),
            stat=str(target.get("stat") or ""),
            direction=str(target.get("direction") or "").upper(),
            tier=str(target.get("tier") or "").upper(),
            line=float(target.get("line_num")),
            source_projection_id=str(target.get("source_projection_id") or ""),
            p_cal=_safe_float(target.get("p_cal_num")),
            p_adj=_safe_float(target.get("p_adj_num")),
            odds_type=str(target.get("odds_type") or ""),
            samples=samples,
            quote_successes=len(target_mults),
            pp_pressure_mean=_mean(pressures),
            pp_pressure_std=_std(pressures),
            payout_delta_mean=_mean(deltas),
            payout_delta_std=_std(deltas),
            payout_penalty_pct_mean=_mean(penalties),
            target_payout_mean=_mean(target_mults),
            baseline_payout_mean=_mean(baseline_mults),
            reference_tier=str(reference.get("tier") or "").upper(),
            reference_projection_ids=str(reference.get("source_projection_id") or ""),
            anchor_projection_ids=",".join(sorted(set(anchor_ids_seen))),
        ))

    csv_path = out_dir / "pp_quote_probe.csv"
    json_path = out_dir / "pp_quote_probe.json"
    pd.DataFrame([asdict(row) for row in rows]).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scored_path": str(scored_path),
        "max_targets": max_targets,
        "samples": samples,
        "slip_size": slip_size,
        "rows": [asdict(row) for row in rows],
        "quote_samples": raw_samples,
    }, indent=2), encoding="utf-8")
    return csv_path, json_path


def _mean(values: list[float]) -> float | None:
    return round(float(sum(values) / len(values)), 6) if values else None


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    m = sum(values) / len(values)
    return round(float((sum((x - m) ** 2 for x in values) / (len(values) - 1)) ** 0.5), 6)


def main() -> int:
    parser = argparse.ArgumentParser(description="Infer PP per-leg quote pressure from slip-level payout quotes.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory containing scored_legs_deduped.csv")
    parser.add_argument("--scored", type=Path, default=None, help="Direct path to scored_legs_deduped.csv")
    parser.add_argument("--max-targets", type=int, default=20)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--slip-size", type=int, default=3, choices=[2, 3, 4, 5, 6])
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir or _latest_run_dir()
    scored_path = args.scored or (run_dir / "scored_legs_deduped.csv")
    if not scored_path.exists():
        raise FileNotFoundError(f"Missing scored file: {scored_path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or (ROOT / "data" / "output" / "pp_quote_probe" / stamp)
    csv_path, json_path = run_probe(
        scored_path=scored_path,
        out_dir=out_dir,
        max_targets=args.max_targets,
        samples=args.samples,
        slip_size=args.slip_size,
        sleep_seconds=args.sleep_seconds,
    )
    print(f"[PP_QUOTE_PROBE] wrote {csv_path}")
    print(f"[PP_QUOTE_PROBE] wrote {json_path}")
    df = pd.read_csv(csv_path)
    if not df.empty:
        show_cols = [
            "player",
            "stat",
            "direction",
            "tier",
            "line",
            "pp_pressure_mean",
            "payout_penalty_pct_mean",
            "target_payout_mean",
            "baseline_payout_mean",
        ]
        print(df[show_cols].head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
