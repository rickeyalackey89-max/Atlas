"""Train/evaluate MLB slip-builder policy variants from completed replay runs.

This is intentionally a slip-layer trainer: it reuses scored legs and settled
eval rows from a completed corpus, rebuilds slips under candidate policy
variants, and writes family/label hit-rate summaries. It does not rerun the
probability model, so the CAT kernel stays fixed during builder tuning.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import tempfile
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import mlb.runtime.slip_builders as slip_builder_registry
import mlb.runtime.slips as slips_runtime
from mlb.runtime.replay_eval import _EvalLegIndex, _evaluate_slip, _load_slip_specs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument(
        "--output-dir",
        default="data/mlb/model/slip_builder_policy_v1_bettingpros_v4",
    )
    parser.add_argument("--run-root", default="data/mlb/replay_runs")
    parser.add_argument("--eval-root", default="data/mlb/eval")
    parser.add_argument(
        "--probability-overlay-csv",
        default="",
        help=(
            "Optional LODO/challenger probability CSV. When supplied, scored legs are "
            "copied into the temporary replay run with model_probability/over_probability/"
            "under_probability replaced by held-out tuned/stacked/adjusted over probabilities."
        ),
    )
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)
    run_root = Path(args.run_root)
    eval_root = Path(args.eval_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    original_policies = dict(slip_builder_registry.FAMILY_BUILDER_POLICIES)
    variants = _policy_variants(original_policies)
    run_ids = _run_ids(corpus_dir)
    if not run_ids:
        raise RuntimeError(f"No replay members found in {corpus_dir}")
    probability_overlay = _load_probability_overlay(Path(args.probability_overlay_csv)) if args.probability_overlay_csv else {}
    overlay_stats = {"candidate_count": len(probability_overlay), "matched_leg_count": 0, "missed_leg_count": 0}

    summary_rows: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []
    run_root.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="_builder_policy_training_", dir=str(run_root)))
    try:
        for variant_name, policies in variants.items():
            slip_builder_registry.FAMILY_BUILDER_POLICIES = policies
            evaluated: list[dict[str, Any]] = []
            for run_id in run_ids:
                source_run_dir = run_root / run_id
                scored_path = source_run_dir / "scored_legs.json"
                eval_path = eval_root / run_id / "eval_legs.json"
                if not scored_path.exists() or not eval_path.exists():
                    continue
                work_run_dir = temp_root / variant_name / run_id
                work_run_dir.mkdir(parents=True, exist_ok=True)
                if probability_overlay:
                    payload = json.loads(scored_path.read_text(encoding="utf-8"))
                    stats = _write_scored_payload_with_probability_overlay(
                        payload,
                        output_path=work_run_dir / "scored_legs.json",
                        run_id=run_id,
                        overlay=probability_overlay,
                    )
                    overlay_stats["matched_leg_count"] += stats["matched_leg_count"]
                    overlay_stats["missed_leg_count"] += stats["missed_leg_count"]
                else:
                    shutil.copy2(scored_path, work_run_dir / "scored_legs.json")
                slips_runtime.build_slip_families_from_scored_run(work_run_dir)
                eval_rows = _eval_rows(eval_path)
                eval_index = _EvalLegIndex(eval_rows)
                for spec in _load_slip_specs(work_run_dir):
                    row = _evaluate_slip(spec, eval_index=eval_index, run_id=run_id)
                    row["variant"] = variant_name
                    row["source_run_id"] = run_id
                    evaluated.append(row)
                    slip_rows.append(_flat_slip_row(row))
                if not args.keep_temp:
                    shutil.rmtree(work_run_dir, ignore_errors=True)

            summary_rows.extend(_summary_rows(variant_name, evaluated))
    finally:
        slip_builder_registry.FAMILY_BUILDER_POLICIES = original_policies
        if not args.keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)

    variant_rows = _variant_rows(summary_rows)
    best = max(variant_rows, key=lambda row: float(row["objective_score"])) if variant_rows else {}
    _write_csv(output_dir / "variant_summary.csv", variant_rows)
    _write_csv(output_dir / "family_label_summary.csv", summary_rows)
    _write_csv(output_dir / "slip_rows.csv", slip_rows)
    manifest = {
        "schema_version": "atlas_mlb_slip_builder_policy_training_v1",
        "corpus_dir": str(corpus_dir),
        "run_count": len(run_ids),
        "variant_count": len(variants),
        "variants": list(variants),
        "best_variant": best,
        "probability_overlay_csv": str(args.probability_overlay_csv or ""),
        "probability_overlay_stats": overlay_stats,
        "variant_summary_csv": str(output_dir / "variant_summary.csv"),
        "family_label_summary_csv": str(output_dir / "family_label_summary.csv"),
        "slip_rows_csv": str(output_dir / "slip_rows.csv"),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _policy_variants(original: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "baseline": original,
        "marketed_prob_plus": {
            **original,
            "Marketed": _adjust(
                original["Marketed"],
                probability=0.05,
                prior=-0.03,
                edge=-0.02,
                min_probability=0.01,
            ),
        },
        "system_prior_plus": {
            **original,
            "System": _adjust(original["System"], probability=-0.03, prior=0.05, edge=-0.02),
        },
        "windfall_bettingpros_plus": {
            **original,
            "Windfall": _adjust(
                original["Windfall"],
                probability=-0.02,
                prior=-0.02,
                bettingpros=0.05,
                edge=-0.01,
            ),
        },
        "conservative_thresholds": {
            family: _adjust(policy, min_probability=0.02) for family, policy in original.items()
        },
        "demonhunter_prior_plus": {
            **original,
            "DemonHunter": _adjust(
                original["DemonHunter"],
                probability=-0.04,
                prior=0.05,
                bettingpros=0.03,
                edge=-0.04,
            ),
        },
        "marketed_prob_edge_plus": {
            **original,
            "Marketed": _adjust(
                original["Marketed"],
                probability=0.08,
                prior=-0.05,
                bettingpros=-0.01,
                edge=0.03,
                min_probability=0.02,
            ),
        },
        "marketed_bettingpros_plus": {
            **original,
            "Marketed": _adjust(
                original["Marketed"],
                probability=-0.02,
                prior=-0.02,
                bettingpros=0.07,
                edge=-0.01,
            ),
        },
        "system_probability_plus": {
            **original,
            "System": _adjust(
                original["System"],
                probability=0.07,
                prior=-0.03,
                bettingpros=-0.01,
                edge=0.02,
                min_probability=0.01,
            ),
        },
        "system_prior_plus2": {
            **original,
            "System": _adjust(original["System"], probability=-0.05, prior=0.10, edge=-0.03),
        },
        "windfall_bettingpros_plus2": {
            **original,
            "Windfall": _adjust(
                original["Windfall"],
                probability=-0.04,
                prior=-0.04,
                bettingpros=0.10,
                edge=-0.02,
            ),
        },
        "windfall_probability_plus": {
            **original,
            "Windfall": _adjust(
                original["Windfall"],
                probability=0.07,
                bettingpros=-0.02,
                edge=0.02,
                min_probability=0.01,
            ),
        },
        "demonhunter_probability_plus": {
            **original,
            "DemonHunter": _adjust(
                original["DemonHunter"],
                probability=0.08,
                prior=-0.04,
                bettingpros=-0.01,
                edge=0.02,
                min_probability=0.03,
            ),
        },
        "all_strict_thresholds": {
            family: _adjust(policy, min_probability=0.04) for family, policy in original.items()
        },
        "system_prior_windfall_bettingpros_plus": {
            **original,
            "System": _adjust(original["System"], probability=-0.03, prior=0.05, edge=-0.02),
            "Windfall": _adjust(
                original["Windfall"],
                probability=-0.02,
                prior=-0.02,
                bettingpros=0.05,
                edge=-0.01,
            ),
        },
        "marketed_system_probability_plus": {
            **original,
            "Marketed": _adjust(
                original["Marketed"],
                probability=0.05,
                prior=-0.03,
                edge=0.01,
                min_probability=0.01,
            ),
            "System": _adjust(
                original["System"],
                probability=0.07,
                prior=-0.03,
                bettingpros=-0.01,
                edge=0.02,
                min_probability=0.01,
            ),
        },
        "family_best_context_combo": {
            **original,
            "Marketed": _adjust(
                original["Marketed"],
                probability=-0.02,
                prior=-0.02,
                bettingpros=0.07,
                edge=-0.01,
            ),
            "System": _adjust(
                original["System"],
                probability=0.07,
                prior=-0.03,
                bettingpros=-0.01,
                edge=0.02,
                min_probability=0.01,
            ),
            "Windfall": _adjust(
                original["Windfall"],
                probability=0.07,
                bettingpros=-0.02,
                edge=0.02,
                min_probability=0.01,
            ),
        },
    }


def _adjust(
    policy: Any,
    *,
    probability: float = 0.0,
    prior: float = 0.0,
    bettingpros: float = 0.0,
    edge: float = 0.0,
    min_probability: float = 0.0,
) -> Any:
    min_by_tier = {
        key: round(float(value) + min_probability, 6)
        for key, value in policy.min_probability_by_tier.items()
    }
    return replace(
        policy,
        probability_weight=round(policy.probability_weight + probability, 6),
        prior_weight=round(policy.prior_weight + prior, 6),
        bettingpros_weight=round(policy.bettingpros_weight + bettingpros, 6),
        edge_weight=round(policy.edge_weight + edge, 6),
        min_probability_by_tier=min_by_tier,
    )


def _run_ids(corpus_dir: Path) -> list[str]:
    members_path = corpus_dir / "aggregate_members.csv"
    if members_path.exists():
        with members_path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [row["run_id"] for row in csv.DictReader(handle) if row.get("run_id")]
    return [path.name.removesuffix(".eval.json") for path in sorted(corpus_dir.glob("replay_single_*.eval.json"))]


def _eval_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in payload.get("rows", []) if isinstance(row, dict)]


def _load_probability_overlay(path: Path) -> dict[tuple[str, ...], float]:
    if not path.exists():
        raise FileNotFoundError(f"Probability overlay CSV does not exist: {path}")
    overlay: dict[tuple[str, ...], float] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            probability = _parse_probability(
                row.get("tuned_over_probability")
                or row.get("stacked_over_probability")
                or row.get("adjusted_over_probability")
                or row.get("over_probability")
            )
            if probability is None:
                continue
            run_id = str(row.get("run_id") or "").strip()
            game_date = str(row.get("game_date") or "").strip()
            projection_id = str(row.get("source_projection_id") or "").strip()
            if not projection_id:
                continue
            if run_id and game_date:
                overlay[(run_id, game_date, projection_id)] = probability
            if game_date:
                overlay[(game_date, projection_id)] = probability
            overlay[(projection_id,)] = probability
    return overlay


def _write_scored_payload_with_probability_overlay(
    payload: dict[str, Any],
    *,
    output_path: Path,
    run_id: str,
    overlay: dict[tuple[str, ...], float],
) -> dict[str, int]:
    matched = 0
    missed = 0
    rows = payload.get("scored_legs")
    if not isinstance(rows, list):
        rows = []
    patched_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        patched = dict(row)
        probability = _lookup_overlay_probability(patched, run_id=run_id, overlay=overlay)
        if probability is None:
            missed += 1
        else:
            matched += 1
            _apply_over_probability(patched, probability)
        patched_rows.append(patched)

    patched_payload = dict(payload)
    patched_payload["scored_legs"] = patched_rows
    manifest = dict(patched_payload.get("probability_overlay") or {})
    manifest.update(
        {
            "source": "lodo_probability_overlay",
            "matched_leg_count": matched,
            "missed_leg_count": missed,
        }
    )
    patched_payload["probability_overlay"] = manifest
    output_path.write_text(json.dumps(patched_payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return {"matched_leg_count": matched, "missed_leg_count": missed}


def _lookup_overlay_probability(
    row: dict[str, Any],
    *,
    run_id: str,
    overlay: dict[tuple[str, ...], float],
) -> float | None:
    projection_id = str(row.get("source_projection_id") or row.get("projection_id") or "").strip()
    if not projection_id:
        return None
    game_date = str(row.get("game_date") or "").strip()
    for key in (
        (run_id, game_date, projection_id),
        (game_date, projection_id),
        (projection_id,),
    ):
        if key in overlay:
            return overlay[key]
    return None


def _apply_over_probability(row: dict[str, Any], over_probability: float) -> None:
    over_probability = _clamp(over_probability, 1e-6, 1.0 - 1e-6)
    under_probability = 1.0 - over_probability
    side = str(row.get("side") or row.get("direction") or "").strip().lower()
    model_probability = over_probability if side == "over" else under_probability
    row["over_probability"] = round(over_probability, 6)
    row["under_probability"] = round(under_probability, 6)
    row["model_probability"] = round(model_probability, 6)
    row["p_cal"] = round(model_probability, 6)
    row["p_adj"] = round(model_probability, 6)
    row["edge"] = round(model_probability - 0.5, 6)
    row["fair_decimal"] = round(1.0 / max(model_probability, 1e-6), 4)
    row["fair_price"] = _american_price(model_probability)
    flags = row.get("flags")
    if isinstance(flags, list) and "lodo_probability_overlay" not in flags:
        row["flags"] = [*flags, "lodo_probability_overlay"]
    row["probability_overlay_applied"] = True


def _parse_probability(value: Any) -> float | None:
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(probability):
        return None
    return _clamp(probability, 1e-6, 1.0 - 1e-6)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _american_price(probability: float) -> int:
    probability = _clamp(probability, 1e-6, 1.0 - 1e-6)
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def _summary_rows(variant: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    buckets_by_family: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[(str(row.get("family") or ""), str(row.get("label") or ""))].append(row)
        buckets_by_family[(str(row.get("family") or ""), "ALL")].append(row)
    output: list[dict[str, Any]] = []
    for (family, label), bucket in sorted({**buckets, **buckets_by_family}.items()):
        output.append(_bucket_summary(variant, family, label, bucket))
    return output


def _bucket_summary(variant: str, family: str, label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if row.get("result") in {"win", "loss", "push"}]
    wins = sum(1 for row in settled if row.get("result") == "win")
    losses = sum(1 for row in settled if row.get("result") == "loss")
    pushes = sum(1 for row in settled if row.get("result") == "push")
    unsettled = sum(1 for row in rows if row.get("result") == "unsettled")
    leg_settled = sum(int(row.get("settled_leg_count") or 0) for row in rows)
    leg_wins = sum(int(row.get("win_count") or 0) for row in rows)
    return {
        "variant": variant,
        "family": family,
        "label": label,
        "slip_count": len(rows),
        "settled_slip_count": len(settled),
        "win_count": wins,
        "loss_count": losses,
        "push_count": pushes,
        "unsettled_count": unsettled,
        "slip_win_rate": _ratio(wins, len(settled)),
        "leg_settled_count": leg_settled,
        "leg_win_count": leg_wins,
        "leg_win_rate": _ratio(leg_wins, leg_settled),
        "avg_brier": _mean(row.get("brier") for row in settled),
        "avg_logloss": _mean(row.get("logloss") for row in settled),
        "avg_ev": _mean(row.get("ev") for row in rows),
    }


def _variant_rows(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = sorted({row["variant"] for row in summary_rows})
    output = []
    weights = {"Marketed": 0.30, "System": 0.30, "Windfall": 0.30, "DemonHunter": 0.10}
    for variant in variants:
        rows = [row for row in summary_rows if row["variant"] == variant and row["label"] == "ALL"]
        score = 0.0
        settled = 0
        slips = 0
        for row in rows:
            family = str(row["family"])
            slip_win_rate = float(row["slip_win_rate"] or 0.0)
            settled_rate = _ratio(float(row["settled_slip_count"]), float(row["slip_count"])) or 0.0
            score += weights.get(family, 0.0) * slip_win_rate * settled_rate
            settled += int(row["settled_slip_count"])
            slips += int(row["slip_count"])
        output.append(
            {
                "variant": variant,
                "objective_score": round(score, 6),
                "slip_count": slips,
                "settled_slip_count": settled,
                "settled_rate": _ratio(settled, slips),
                "family_count": len(rows),
            }
        )
    return sorted(output, key=lambda row: float(row["objective_score"]), reverse=True)


def _flat_slip_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant": row.get("variant"),
        "run_id": row.get("source_run_id"),
        "family": row.get("family"),
        "label": row.get("label"),
        "result": row.get("result"),
        "target_leg_count": row.get("target_leg_count"),
        "leg_count": row.get("leg_count"),
        "settled_leg_count": row.get("settled_leg_count"),
        "win_count": row.get("win_count"),
        "loss_count": row.get("loss_count"),
        "push_count": row.get("push_count"),
        "unsettled_count": row.get("unsettled_count"),
        "hit_prob": row.get("hit_prob"),
        "payout_mult": row.get("payout_mult"),
        "ev": row.get("ev"),
        "brier": row.get("brier"),
        "logloss": row.get("logloss"),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _mean(values) -> float | None:
    clean = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            clean.append(float(value))
        except (TypeError, ValueError):
            continue
    if not clean:
        return None
    return round(sum(clean) / len(clean), 6)


if __name__ == "__main__":
    raise SystemExit(main())
