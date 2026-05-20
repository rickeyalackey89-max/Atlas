"""Train an MLB CatBoost over-probability residual calibrator.

The model is trained LODO (leave-one-date-out) against replay eval truth and
then fit on the full corpus for runtime use. It calibrates parameter-table
``target_over_probability`` values, which keeps live and replay on the same
engine path.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

from mlb.domain.playability import is_over_only_tier
from mlb.modeling.calibration import (
    join_key,
    prepare_calibration_frame,
    training_feature_row,
)

DEFAULT_FEATURES = [
    "market",
    "source_market",
    "tier",
    "player_team",
    "opponent",
    "player_position",
    "market_group",
    "opportunity_type",
    "distribution",
    "injury_status",
    "statsapi_venue_name",
    "statsapi_player_position",
    "statsapi_bats",
    "statsapi_throws",
    "statsapi_roster_status",
    "bettingpros_recommended_side",
    "bettingpros_streak_type",
    "advanced_profile_source",
    "advanced_profile_match_type",
    "market_line_match_type",
    "base_over_probability",
    "line",
    "is_live",
    "is_combo",
    "projected_opportunity",
    "opportunity_floor",
    "opportunity_ceiling",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "player_history_context_available",
    "plate_appearance_projection",
    "market_context_available",
    "market_source_line",
    "market_line_delta",
    "market_over_probability",
    "market_under_probability",
    "market_n_books",
    "market_target_blend_weight",
    "market_target_shift",
    "lineup_score",
    "starter_matchup_score",
    "bullpen_matchup_score",
    "environment_score",
    "matchup_composite_score",
    "matchup_confidence",
    "matchup_context_available",
    "matchup_target_shift",
    "advanced_context_available",
    "advanced_context_score",
    "advanced_hit_context_score",
    "advanced_power_context_score",
    "advanced_plate_discipline_score",
    "advanced_k_context_score",
    "advanced_contact_quality_score",
    "advanced_sample_confidence",
    "advanced_target_shift",
    "feature_lineup_context_available",
    "feature_probable_pitcher_context_available",
    "feature_injury_context_available",
    "feature_injury_risk_score",
    "feature_weather_context_available",
    "feature_statsapi_context_available",
    "feature_statsapi_is_home",
    "feature_roster_context_available",
    "feature_player_history_context_available",
    "feature_history_games_season",
    "feature_history_games_7d",
    "feature_history_games_14d",
    "feature_season_pa_per_game",
    "feature_recent_pa_per_game_7d",
    "feature_recent_pa_per_game_14d",
    "feature_plate_appearance_projection",
    "feature_history_context_confidence",
    "feature_transaction_source_available",
    "feature_transaction_context_available",
    "feature_recent_transaction_count",
    "feature_recent_callup_count",
    "feature_recent_option_count",
    "feature_recent_injury_status_count",
    "feature_transaction_volatility_score",
    "feature_external_market_context_available",
    "feature_bettingpros_projection_value",
    "feature_bettingpros_projection_probability",
    "feature_bettingpros_projection_expected_value",
    "feature_bettingpros_projection_diff",
    "feature_bettingpros_streak",
    "feature_bettingpros_last_5_over_rate",
    "feature_bettingpros_last_5_under_rate",
    "feature_bettingpros_last_10_over_rate",
    "feature_bettingpros_last_10_under_rate",
    "feature_bettingpros_last_20_over_rate",
    "feature_bettingpros_last_20_under_rate",
    "feature_bettingpros_season_over_rate",
    "feature_bettingpros_season_under_rate",
    "feature_bettingpros_prior_season_over_rate",
    "feature_bettingpros_prior_season_under_rate",
]

CAT_FEATURES = [
    "market",
    "source_market",
    "tier",
    "player_team",
    "opponent",
    "player_position",
    "market_group",
    "opportunity_type",
    "distribution",
    "injury_status",
    "statsapi_venue_name",
    "statsapi_player_position",
    "statsapi_bats",
    "statsapi_throws",
    "statsapi_roster_status",
    "bettingpros_recommended_side",
    "bettingpros_streak_type",
    "advanced_profile_source",
    "advanced_profile_match_type",
    "market_line_match_type",
]

LEAKAGE_COLUMN_NAMES = {
    "p_cal",
    "p_cal_marketed",
    "model_probability",
    "uncalibrated_target_over_probability",
    "cat_adjusted_target_over_probability",
    "adjusted_over_probability",
    "stacked_over_probability",
    "stacker_over_probability",
    "cat_residual",
    "cat_residual_raw",
    "cat_residual_clipped",
    "cat_residual_scaled",
    "p_catboost",
    "p_catboost_residual",
}

LEAKAGE_PREFIXES = (
    "cat_",
    "stacker_",
    "stacked_",
    "p_catboost",
)


def _assert_no_leakage_columns(columns: list[str] | tuple[str, ...] | set[str], *, context: str) -> None:
    bad: list[str] = []
    for column in columns:
        name = str(column)
        lowered = name.lower()
        if lowered in LEAKAGE_COLUMN_NAMES or lowered.startswith(LEAKAGE_PREFIXES) or "catboost" in lowered:
            bad.append(name)
    if bad:
        raise RuntimeError(
            f"CAT leakage guard failed in {context}: prior calibrated/stacked columns are not allowed "
            f"in base CAT training inputs: {sorted(set(bad))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--output-dir", default="data/mlb/model/cat_probability_kernel_v1")
    parser.add_argument("--iterations", default="200,400,600")
    parser.add_argument("--learning-rates", default="0.03,0.06")
    parser.add_argument("--depths", default="4")
    parser.add_argument("--residual-scales", default="0.25,0.35,0.50,0.65")
    parser.add_argument("--residual-clip", type=float, default=0.20)
    parser.add_argument("--p-lo", type=float, default=0.03)
    parser.add_argument("--p-hi", type=float, default=0.97)
    parser.add_argument("--l2-leaf-reg", type=float, default=6.0)
    parser.add_argument("--min-data-in-leaf", type=int, default=80)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--version", default="mlb_cat_over_residual_v1")
    parser.add_argument(
        "--exclude-bettingpros-features",
        action="store_true",
        help="Run an ablation without BettingPros categorical/numeric features.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    corpus_dir = (root / args.corpus_dir).resolve() if not Path(args.corpus_dir).is_absolute() else Path(args.corpus_dir)
    output_dir = (root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    excluded_features = [feature for feature in DEFAULT_FEATURES if "bettingpros" in feature]
    features = [
        feature
        for feature in DEFAULT_FEATURES
        if not (args.exclude_bettingpros_features and "bettingpros" in feature)
    ]
    cat_features = [feature for feature in CAT_FEATURES if feature in features]
    _assert_no_leakage_columns(features, context="feature contract")
    _assert_no_leakage_columns(cat_features, context="categorical feature contract")
    feature_set = "without_bettingpros" if args.exclude_bettingpros_features else "with_bettingpros"
    rows = build_training_rows(root=root, corpus_dir=corpus_dir)
    if not rows:
        raise RuntimeError(f"No training rows found for {corpus_dir}")
    _assert_no_leakage_columns(set().union(*(row.keys() for row in rows)), context="assembled training corpus")

    corpus_csv = output_dir / "training_corpus.csv"
    _write_csv(corpus_csv, rows)

    frame = prepare_calibration_frame(rows, features=features, cat_features=cat_features)
    labels = np.array([float(row["actual_over"]) for row in rows], dtype=float)
    base = np.array([float(row["base_over_probability"]) for row in rows], dtype=float)
    tiers = np.array([str(row.get("tier") or "STANDARD").upper() for row in rows])
    dates = np.array([str(row["game_date"]) for row in rows])
    unique_dates = sorted(set(dates.tolist()))
    baseline = _metrics(labels, base)

    sweep_rows: list[dict[str, Any]] = []
    prediction_payloads: dict[str, dict[str, Any]] = {}
    started = time.time()
    for iterations, learning_rate, depth in product(
        _int_list(args.iterations),
        _float_list(args.learning_rates),
        _int_list(args.depths),
    ):
        config_id = f"iter{iterations}_lr{learning_rate:g}_depth{depth}"
        print(
            json.dumps(
                {
                    "event": "config_start",
                    "feature_set": feature_set,
                    "config_id": config_id,
                    "iterations": iterations,
                    "learning_rate": learning_rate,
                    "depth": depth,
                    "date_count": len(unique_dates),
                    "elapsed_sec": round(time.time() - started, 2),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        pred_residual = np.zeros(len(rows), dtype=float)
        for heldout_date in unique_dates:
            train_mask = dates != heldout_date
            test_mask = dates == heldout_date
            model = _fit_model(
                frame.loc[train_mask],
                labels[train_mask] - base[train_mask],
                cat_features=cat_features,
                iterations=iterations,
                learning_rate=learning_rate,
                depth=depth,
                l2_leaf_reg=args.l2_leaf_reg,
                min_data_in_leaf=args.min_data_in_leaf,
                random_seed=args.random_seed,
            )
            pool = Pool(frame.loc[test_mask], cat_features=[features.index(col) for col in cat_features])
            pred_residual[test_mask] = model.predict(pool)
            print(
                json.dumps(
                    {
                        "event": "lodo_fold_complete",
                        "feature_set": feature_set,
                        "config_id": config_id,
                        "heldout_date": heldout_date,
                        "train_rows": int(np.sum(train_mask)),
                        "test_rows": int(np.sum(test_mask)),
                        "elapsed_sec": round(time.time() - started, 2),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        for residual_scale in _float_list(args.residual_scales):
            adjusted = _apply_residual(
                base,
                pred_residual,
                residual_scale=residual_scale,
                residual_clip=args.residual_clip,
                p_lo=args.p_lo,
                p_hi=args.p_hi,
            )
            over_metrics = _metrics(labels, adjusted)
            pick_metrics = _pick_metrics(labels, adjusted, tiers=tiers)
            sweep_id = f"{config_id}_scale{residual_scale:g}"
            sweep_rows.append(
                {
                    "sweep_id": sweep_id,
                    "iterations": iterations,
                    "learning_rate": learning_rate,
                    "depth": depth,
                    "residual_scale": residual_scale,
                    "brier_over": over_metrics["brier"],
                    "logloss_over": over_metrics["logloss"],
                    "brier_pick": pick_metrics["brier"],
                    "logloss_pick": pick_metrics["logloss"],
                    "pick_win_rate": pick_metrics["win_rate"],
                    "baseline_brier_over": baseline["brier"],
                    "baseline_logloss_over": baseline["logloss"],
                    "delta_brier_over": round(over_metrics["brier"] - baseline["brier"], 8),
                    "delta_logloss_over": round(over_metrics["logloss"] - baseline["logloss"], 8),
                    "row_count": len(rows),
                    "date_count": len(unique_dates),
                }
            )
            print(
                json.dumps(
                    {
                        "event": "sweep_metric",
                        "feature_set": feature_set,
                        "sweep_id": sweep_id,
                        "brier_over": over_metrics["brier"],
                        "logloss_over": over_metrics["logloss"],
                        "brier_pick": pick_metrics["brier"],
                        "logloss_pick": pick_metrics["logloss"],
                        "pick_win_rate": pick_metrics["win_rate"],
                        "delta_brier_over": round(over_metrics["brier"] - baseline["brier"], 8),
                        "elapsed_sec": round(time.time() - started, 2),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            prediction_payloads[sweep_id] = {
                "residual": pred_residual.copy(),
                "adjusted": adjusted.copy(),
            }

    sweep_rows = sorted(sweep_rows, key=lambda row: (row["brier_over"], row["logloss_over"], -row["pick_win_rate"]))
    best = sweep_rows[0]
    sweep_csv = output_dir / "sweep_results.csv"
    _write_csv(sweep_csv, sweep_rows)

    best_predictions = prediction_payloads[str(best["sweep_id"])]
    predictions_csv = output_dir / "lodo_predictions.csv"
    _write_csv(
        predictions_csv,
        [
            {
                "run_id": rows[index]["run_id"],
                "game_date": rows[index]["game_date"],
                "source_projection_id": rows[index]["source_projection_id"],
                "player_name": rows[index]["player_name"],
                "market": rows[index]["market"],
                "tier": rows[index]["tier"],
                "line": rows[index]["line"],
                "actual_over": int(labels[index]),
                "base_over_probability": round(float(base[index]), 8),
                "cat_residual": round(float(best_predictions["residual"][index]), 8),
                "adjusted_over_probability": round(float(best_predictions["adjusted"][index]), 8),
            }
            for index in range(len(rows))
        ],
    )

    final_model = _fit_model(
        frame,
        labels - base,
        cat_features=cat_features,
        iterations=int(best["iterations"]),
        learning_rate=float(best["learning_rate"]),
        depth=int(best["depth"]),
        l2_leaf_reg=args.l2_leaf_reg,
        min_data_in_leaf=args.min_data_in_leaf,
        random_seed=args.random_seed,
    )
    model_path = output_dir / f"{args.version}.cbm"
    final_model.save_model(str(model_path))

    feature_importance = dict(zip(features, [float(value) for value in final_model.get_feature_importance()]))
    meta = {
        "schema_version": "mlb_cat_probability_kernel_training_v1",
        "version": args.version,
        "calibration_version": args.version,
        "trained_at_unix": round(time.time(), 3),
        "corpus_dir": str(corpus_dir),
        "training_corpus_csv": str(corpus_csv),
        "sweep_results_csv": str(sweep_csv),
        "lodo_predictions_csv": str(predictions_csv),
        "model_path": str(model_path),
        "target": "actual_over - target_over_probability",
        "feature_set": feature_set,
        "excluded_features": excluded_features if args.exclude_bettingpros_features else [],
        "features": features,
        "cat_features": cat_features,
        "iterations": int(best["iterations"]),
        "learning_rate": float(best["learning_rate"]),
        "depth": int(best["depth"]),
        "l2_leaf_reg": args.l2_leaf_reg,
        "min_data_in_leaf": args.min_data_in_leaf,
        "residual_scale": float(best["residual_scale"]),
        "residual_clip": args.residual_clip,
        "p_lo": args.p_lo,
        "p_hi": args.p_hi,
        "row_count": len(rows),
        "dates": unique_dates,
        "date_count": len(unique_dates),
        "baseline": baseline,
        "best_lodo": best,
        "feature_importance": feature_importance,
        "elapsed_sec": round(time.time() - started, 2),
    }
    meta_path = output_dir / f"{args.version}.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "best_config.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"meta_path": str(meta_path), "model_path": str(model_path), "best_lodo": best}, indent=2, sort_keys=True))
    return 0


def build_training_rows(*, root: Path, corpus_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_id in _run_ids(corpus_dir):
        eval_rows = _read_csv(root / "data" / "mlb" / "eval" / run_id / "eval_legs.csv")
        parameter_rows = _read_table(root / "data" / "mlb" / "features" / "parameters" / run_id / "parameter_table.json")
        feature_rows = _read_table(root / "data" / "mlb" / "features" / "player_props" / run_id / "feature_table.json")
        parameter_index = {_training_lookup_key(row): row for row in parameter_rows}
        feature_index = {_training_lookup_key(row): row for row in feature_rows}
        parameter_full_key_index = {join_key(row): row for row in parameter_rows}
        feature_full_key_index = {join_key(row): row for row in feature_rows}
        for eval_row in eval_rows:
            if str(eval_row.get("actual_side") or "") not in {"over", "under"}:
                continue
            key = _training_lookup_key(eval_row)
            parameter_row = parameter_index.get(key)
            if not parameter_row:
                parameter_row = parameter_full_key_index.get(join_key(eval_row))
            if not parameter_row:
                continue
            feature_row = feature_index.get(key)
            if not feature_row:
                feature_row = feature_full_key_index.get(join_key(parameter_row))
            feature_data = training_feature_row(parameter_row, feature_row)
            feature_data.update(
                {
                    "run_id": run_id,
                    "source_projection_id": str(eval_row.get("source_projection_id") or ""),
                    "event_id": str(eval_row.get("event_id") or ""),
                    "game_date": str(eval_row.get("game_date") or ""),
                    "player_name": str(eval_row.get("player_name") or ""),
                    "line": _float(eval_row.get("line")),
                    "market": str(eval_row.get("market") or feature_data.get("market") or ""),
                    "tier": str((parameter_row or {}).get("tier") or feature_data.get("tier") or "STANDARD").upper(),
                    "actual_over": 1 if str(eval_row.get("actual_side") or "") == "over" else 0,
                }
            )
            rows.append(feature_data)
    return rows


def _fit_model(
    frame: pd.DataFrame,
    target: np.ndarray,
    *,
    cat_features: list[str],
    iterations: int,
    learning_rate: float,
    depth: int,
    l2_leaf_reg: float,
    min_data_in_leaf: int,
    random_seed: int,
) -> CatBoostRegressor:
    features = list(frame.columns)
    pool = Pool(frame, label=target, cat_features=[features.index(col) for col in cat_features if col in features])
    model = CatBoostRegressor(
        iterations=iterations,
        depth=depth,
        learning_rate=learning_rate,
        l2_leaf_reg=l2_leaf_reg,
        min_data_in_leaf=min_data_in_leaf,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=random_seed,
        allow_writing_files=False,
        verbose=False,
    )
    model.fit(pool)
    return model


def _run_ids(corpus_dir: Path) -> list[str]:
    members_csv = corpus_dir / "aggregate_members.csv"
    if members_csv.exists():
        return [str(row.get("run_id") or "") for row in _read_csv(members_csv) if row.get("run_id")]
    return [path.name.removesuffix(".eval.json") for path in sorted(corpus_dir.glob("replay_single_*_github_csv_fidelity_v1.eval.json"))]


def _read_table(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in payload.get("rows", []) if isinstance(row, dict)]


def _training_lookup_key(row: dict[str, Any]) -> str:
    projection_id = str(row.get("source_projection_id") or "").strip()
    if projection_id:
        return f"projection:{projection_id}"
    event = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip()
    line = f"{_float(row.get('line')):.4f}"
    player = str(row.get("player_id") or row.get("player_name") or "").strip().lower()
    return f"fallback:{event}|{player}|{market}|{line}"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _apply_residual(
    base: np.ndarray,
    residual: np.ndarray,
    *,
    residual_scale: float,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> np.ndarray:
    return np.clip(base + residual_scale * np.clip(residual, -residual_clip, residual_clip), p_lo, p_hi)


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    probabilities = np.clip(probabilities.astype(float), 1e-6, 1.0 - 1e-6)
    return {
        "brier": round(float(np.mean((probabilities - labels) ** 2)), 8),
        "logloss": round(float(np.mean(-(labels * np.log(probabilities) + (1.0 - labels) * np.log(1.0 - probabilities)))), 8),
    }


def _pick_metrics(labels: np.ndarray, probabilities: np.ndarray, *, tiers: np.ndarray | None = None) -> dict[str, float]:
    probabilities = np.clip(probabilities.astype(float), 1e-6, 1.0 - 1e-6)
    pick_is_over = probabilities >= 0.5
    if tiers is not None:
        over_only = np.array([is_over_only_tier(tier) for tier in tiers], dtype=bool)
        pick_is_over = np.where(over_only, True, pick_is_over)
    pick_prob = np.where(pick_is_over, probabilities, 1.0 - probabilities)
    hit = np.where(pick_is_over, labels == 1.0, labels == 0.0).astype(float)
    metrics = _metrics(hit, pick_prob)
    metrics["win_rate"] = round(float(np.mean(hit)), 8)
    return metrics


def _float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
