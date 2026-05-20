"""Aggregate MLB replay slip evaluation artifacts by builder family."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, help="Replay sweep output directory.")
    parser.add_argument("--eval-root", default="data/mlb/eval")
    parser.add_argument("--run-root", default="data/mlb/test_runs")
    parser.add_argument(
        "--min-slate-games",
        type=int,
        default=3,
        help="Minimum distinct events for optimization-focused summaries.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    eval_root = Path(args.eval_root)
    run_root = Path(args.run_root)
    run_ids = _run_ids(input_dir)

    slip_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    slate_event_counts = {run_id: _distinct_event_count(run_root / run_id / "scored_legs.csv") for run_id in run_ids}

    for run_id in run_ids:
        eval_slips_path = eval_root / run_id / "eval_slips.csv"
        if not eval_slips_path.exists():
            continue
        for row in _read_csv(eval_slips_path):
            slate_event_count = slate_event_counts.get(run_id, 0)
            normalized = _normalize_slip_row(row, slate_event_count=slate_event_count)
            slip_rows.append(normalized)
            for leg in _parse_leg_results(row.get("leg_results")):
                leg_rows.append(_normalize_leg_row(leg, normalized))

    family_summary = _summary(slip_rows, keys=("family",))
    family_label_summary = _summary(slip_rows, keys=("family", "label"))
    family_label_eligible_summary = _summary(
        [row for row in slip_rows if int(row["slate_event_count"]) >= args.min_slate_games],
        keys=("family", "label"),
    )
    leg_segment_summary = _leg_summary(leg_rows, keys=("family", "tier", "market", "side"))

    payload = {
        "corpus_id": input_dir.name,
        "run_count": len(run_ids),
        "slip_count": len(slip_rows),
        "leg_count": len(leg_rows),
        "min_slate_games": args.min_slate_games,
        "slate_event_counts": slate_event_counts,
        "family_summary": family_summary,
        "family_label_summary": family_label_summary,
        "family_label_eligible_summary": family_label_eligible_summary,
        "leg_segment_summary": leg_segment_summary,
    }

    json_path = input_dir / "slip_builder_summary.json"
    family_csv_path = input_dir / "slip_builder_family_summary.csv"
    family_label_csv_path = input_dir / "slip_builder_family_label_summary.csv"
    eligible_csv_path = input_dir / "slip_builder_family_label_eligible_summary.csv"
    legs_csv_path = input_dir / "slip_builder_leg_segment_summary.csv"
    slip_rows_path = input_dir / "slip_builder_slip_rows.csv"

    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(family_csv_path, family_summary)
    _write_csv(family_label_csv_path, family_label_summary)
    _write_csv(eligible_csv_path, family_label_eligible_summary)
    _write_csv(legs_csv_path, leg_segment_summary)
    _write_csv(slip_rows_path, slip_rows)

    print(
        json.dumps(
            {
                "summary_path": str(json_path),
                "family_csv_path": str(family_csv_path),
                "family_label_csv_path": str(family_label_csv_path),
                "eligible_csv_path": str(eligible_csv_path),
                "legs_csv_path": str(legs_csv_path),
                "slip_rows_path": str(slip_rows_path),
                "slip_count": len(slip_rows),
                "leg_count": len(leg_rows),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_ids(input_dir: Path) -> list[str]:
    run_ids = []
    for eval_path in sorted(input_dir.glob("replay_single_*.eval.json")):
        run_ids.append(eval_path.name.removesuffix(".eval.json"))
    return run_ids


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _distinct_event_count(scored_legs_path: Path) -> int:
    if not scored_legs_path.exists():
        return 0
    events = set()
    with scored_legs_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            event_id = str(row.get("event_id") or "").strip()
            if event_id:
                events.add(event_id)
    return len(events)


def _normalize_slip_row(row: dict[str, Any], *, slate_event_count: int) -> dict[str, Any]:
    leg_count = _int(row.get("leg_count"))
    settled_leg_count = _int(row.get("settled_leg_count"))
    win_count = _int(row.get("win_count"))
    loss_count = _int(row.get("loss_count"))
    push_count = _int(row.get("push_count"))
    result = str(row.get("result") or "")
    return {
        "run_id": str(row.get("run_id") or ""),
        "date": _date_from_run_id(str(row.get("run_id") or "")),
        "family": str(row.get("family") or ""),
        "label": str(row.get("label") or ""),
        "slip_id": str(row.get("slip_id") or ""),
        "slate_event_count": slate_event_count,
        "target_leg_count": _int(row.get("target_leg_count")),
        "leg_count": leg_count,
        "settled_leg_count": settled_leg_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "push_count": push_count,
        "unsettled_count": _int(row.get("unsettled_count")),
        "result": result,
        "is_win": 1 if result == "win" else 0,
        "is_loss": 1 if result == "loss" else 0,
        "is_push": 1 if result == "push" else 0,
        "is_unsettled": 1 if result == "unsettled" else 0,
        "all_legs_settled": 1 if leg_count > 0 and settled_leg_count == leg_count else 0,
        "leg_win_rate": round(win_count / settled_leg_count, 6) if settled_leg_count else None,
        "hit_prob": _float(row.get("hit_prob")),
        "payout_mult": _float(row.get("payout_mult")),
        "ev": _float(row.get("ev")),
        "brier": _float(row.get("brier")),
        "logloss": _float(row.get("logloss")),
    }


def _normalize_leg_row(leg: dict[str, Any], slip: dict[str, Any]) -> dict[str, Any]:
    result = str(leg.get("result") or "")
    return {
        "run_id": slip["run_id"],
        "date": slip["date"],
        "family": slip["family"],
        "label": slip["label"],
        "slip_id": slip["slip_id"],
        "slate_event_count": slip["slate_event_count"],
        "tier": str(leg.get("tier") or ""),
        "market": str(leg.get("market") or ""),
        "side": str(leg.get("side") or ""),
        "player_name": str(leg.get("player_name") or ""),
        "event_id": str(leg.get("event_id") or ""),
        "model_probability": _float(leg.get("model_probability")),
        "result": result,
        "is_win": 1 if result == "win" else 0,
        "is_loss": 1 if result == "loss" else 0,
        "is_push": 1 if result == "push" else 0,
        "is_settled": 1 if result in {"win", "loss", "push"} else 0,
    }


def _parse_leg_results(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [row for row in parsed if isinstance(row, dict)]


def _summary(rows: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row.get(key, "") for key in keys)].append(row)
    output = []
    for bucket_key, bucket_rows in sorted(buckets.items()):
        slip_count = len(bucket_rows)
        settled_slips = [row for row in bucket_rows if row["result"] in {"win", "loss", "push"}]
        settled_count = len(settled_slips)
        leg_settled = sum(int(row["settled_leg_count"]) for row in bucket_rows)
        leg_wins = sum(int(row["win_count"]) for row in bucket_rows)
        item = {key: bucket_key[index] for index, key in enumerate(keys)}
        item.update(
            {
                "slip_count": slip_count,
                "settled_slip_count": settled_count,
                "slip_win_count": sum(int(row["is_win"]) for row in bucket_rows),
                "slip_loss_count": sum(int(row["is_loss"]) for row in bucket_rows),
                "slip_push_count": sum(int(row["is_push"]) for row in bucket_rows),
                "slip_unsettled_count": sum(int(row["is_unsettled"]) for row in bucket_rows),
                "slip_win_rate": _ratio(sum(int(row["is_win"]) for row in bucket_rows), settled_count),
                "all_legs_settled_rate": _mean(row["all_legs_settled"] for row in bucket_rows),
                "leg_settled_count": leg_settled,
                "leg_win_count": leg_wins,
                "leg_loss_count": sum(int(row["loss_count"]) for row in bucket_rows),
                "leg_push_count": sum(int(row["push_count"]) for row in bucket_rows),
                "leg_win_rate": _ratio(leg_wins, leg_settled),
                "avg_slate_event_count": _mean(row["slate_event_count"] for row in bucket_rows),
                "avg_hit_prob": _mean(row["hit_prob"] for row in bucket_rows),
                "avg_payout_mult": _mean(row["payout_mult"] for row in bucket_rows),
                "avg_ev": _mean(row["ev"] for row in bucket_rows),
                "avg_brier": _mean(row["brier"] for row in bucket_rows),
                "avg_logloss": _mean(row["logloss"] for row in bucket_rows),
            }
        )
        output.append(item)
    return output


def _leg_summary(rows: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row.get(key, "") for key in keys)].append(row)
    output = []
    for bucket_key, bucket_rows in sorted(buckets.items()):
        settled = [row for row in bucket_rows if row["is_settled"]]
        settled_count = len(settled)
        win_count = sum(int(row["is_win"]) for row in settled)
        item = {key: bucket_key[index] for index, key in enumerate(keys)}
        item.update(
            {
                "leg_count": len(bucket_rows),
                "settled_count": settled_count,
                "win_count": win_count,
                "loss_count": sum(int(row["is_loss"]) for row in settled),
                "push_count": sum(int(row["is_push"]) for row in settled),
                "win_rate": _ratio(win_count, settled_count),
                "avg_model_probability": _mean(row["model_probability"] for row in settled),
                "avg_slate_event_count": _mean(row["slate_event_count"] for row in bucket_rows),
            }
        )
        output.append(item)
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _date_from_run_id(run_id: str) -> str:
    marker = "replay_single_"
    if marker not in run_id:
        return ""
    raw = run_id.split(marker, 1)[1][:8]
    if len(raw) != 8:
        return ""
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _mean(values) -> float | None:
    collected = [value for value in (_float(value) for value in values) if value is not None]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 6)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    parsed = _float(value)
    return int(parsed) if parsed is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
