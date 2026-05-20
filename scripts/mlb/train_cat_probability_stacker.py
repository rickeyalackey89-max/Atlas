"""Train a fair LODO CatBoost probability stacker for MLB.

This is a second-stage probability kernel: it consumes an existing CAT residual
kernel's training corpus and LODO predictions, trains a date-held-out classifier
on the same feature contract, then evaluates logit-space blends against the
base CAT probability. The fair score is the leave-one-date-out blend.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool  # type: ignore[import-untyped]
from scipy.special import expit, logit  # type: ignore[import-untyped]

LEAKAGE_COLUMN_NAMES = {
    "p_cal",
    "p_cal_marketed",
    "model_probability",
    "adjusted_over_probability",
    "stacked_over_probability",
    "stacker_over_probability",
    "cat_adjusted_target_over_probability",
    "p_catboost",
    "p_catboost_residual",
}

LEAKAGE_PREFIXES = (
    "cat_",
    "stacker_",
    "stacked_",
    "p_catboost",
)


def _assert_no_leakage_columns(
    columns: list[str] | tuple[str, ...] | set[str],
    *,
    context: str,
    allow: set[str] | None = None,
) -> None:
    allow = allow or set()
    bad: list[str] = []
    for column in columns:
        name = str(column)
        lowered = name.lower()
        if lowered in allow:
            continue
        if lowered in LEAKAGE_COLUMN_NAMES or lowered.startswith(LEAKAGE_PREFIXES):
            bad.append(name)
    if bad:
        raise RuntimeError(
            f"CAT stacker leakage guard failed in {context}: prior stacked/calibrated columns are not allowed "
            f"as stacker training inputs: {sorted(set(bad))}"
        )


def _float_list(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _metrics(probability: np.ndarray, outcome: np.ndarray) -> dict[str, float]:
    p = np.clip(probability.astype(float), 0.001, 0.999)
    y = outcome.astype(float)
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    pick = (p >= 0.5).astype(int)
    pick_win_rate = float(np.mean(np.where(pick == 1, y, 1.0 - y)))
    return {
        "brier": round(brier, 8),
        "logloss": round(logloss, 8),
        "pick_win_rate": round(pick_win_rate, 8),
        "probability_mean": round(float(np.mean(p)), 8),
    }


def _blend(base: np.ndarray, stacker: np.ndarray, weight: float) -> np.ndarray:
    base = np.clip(base.astype(float), 0.001, 0.999)
    stacker = np.clip(stacker.astype(float), 0.001, 0.999)
    return expit((1.0 - weight) * logit(base) + weight * logit(stacker))


def _prepare_frame(frame: pd.DataFrame, features: list[str], cat_features: list[str]) -> pd.DataFrame:
    prepared = frame.reindex(columns=features).copy()
    for feature in features:
        if feature in cat_features:
            prepared[feature] = prepared[feature].fillna("").astype(str)
        else:
            prepared[feature] = pd.to_numeric(prepared[feature], errors="coerce").fillna(0.0).astype(float)
            prepared[feature] = prepared[feature].replace([math.inf, -math.inf], 0.0)
    return prepared


def _load_inputs(base_model_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    meta_path = base_model_dir / "best_config.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing base CAT config: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if str(meta.get("schema_version") or "") == "mlb_cat_probability_stacker_training_v1":
        raise RuntimeError("Refusing to train a CAT stacker from a prior stacker artifact")

    corpus_path = Path(meta.get("training_corpus_csv") or base_model_dir / "training_corpus.csv")
    predictions_path = Path(meta.get("lodo_predictions_csv") or base_model_dir / "lodo_predictions.csv")
    if not corpus_path.exists():
        corpus_path = base_model_dir / "training_corpus.csv"
    if not predictions_path.exists():
        predictions_path = base_model_dir / "lodo_predictions.csv"
    if not corpus_path.exists() or not predictions_path.exists():
        raise FileNotFoundError("Base CAT artifact needs training_corpus.csv and lodo_predictions.csv")

    corpus = pd.read_csv(corpus_path, low_memory=False)
    _assert_no_leakage_columns(set(corpus.columns), context="base training corpus")
    lodo_full = pd.read_csv(predictions_path, low_memory=False)
    _assert_no_leakage_columns(
        set(lodo_full.columns),
        context="base LODO predictions",
        allow={"adjusted_over_probability", "cat_residual"},
    )
    lodo = lodo_full[
        ["game_date", "source_projection_id", "base_over_probability", "adjusted_over_probability"]
    ].copy()
    merged = corpus.merge(lodo, on=["game_date", "source_projection_id"], how="inner", suffixes=("", "_lodo"))
    if merged.empty:
        raise RuntimeError("No rows after joining base training corpus to LODO predictions")
    return meta, merged


def _cat_indices(features: list[str], cat_features: list[str]) -> list[int]:
    return [features.index(feature) for feature in cat_features if feature in features]


def _train_classifier(
    train_x: pd.DataFrame,
    train_y: np.ndarray,
    *,
    cat_indices: list[int],
    args: argparse.Namespace,
) -> CatBoostClassifier:
    model = CatBoostClassifier(
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        depth=args.depth,
        l2_leaf_reg=args.l2_leaf_reg,
        min_data_in_leaf=args.min_data_in_leaf,
        loss_function="Logloss",
        eval_metric="BrierScore",
        random_seed=args.random_seed,
        allow_writing_files=False,
        verbose=False,
        thread_count=args.thread_count,
    )
    model.fit(Pool(train_x, train_y, cat_features=cat_indices))
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train fair LODO MLB CatBoost probability stacker")
    parser.add_argument("--base-model-dir", default="data/mlb/model/cat_probability_kernel_v5_reorg_bettingpros_on")
    parser.add_argument("--output-dir", default="data/mlb/model/cat_probability_stacker_v1_lodo_cat_v5")
    parser.add_argument("--version", default="mlb_cat_probability_stacker_v1_lodo_cat_v5")
    parser.add_argument("--iterations", type=int, default=350)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--l2-leaf-reg", type=float, default=8.0)
    parser.add_argument("--min-data-in-leaf", type=int, default=120)
    parser.add_argument("--blend-weights", default="0.1,0.2,0.35,0.5,0.65,0.8,1.0")
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--thread-count", type=int, default=-1)
    args = parser.parse_args()

    root = Path.cwd()
    base_model_dir = (root / args.base_model_dir).resolve()
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    base_meta, rows = _load_inputs(base_model_dir)
    features = [str(item) for item in base_meta["features"]]
    cat_features = [str(item) for item in base_meta.get("cat_features", []) if item in features]
    _assert_no_leakage_columns(features, context="stacker feature contract")
    _assert_no_leakage_columns(cat_features, context="stacker categorical feature contract")
    cat_indices = _cat_indices(features, cat_features)

    frame = _prepare_frame(rows, features, cat_features)
    outcome = rows["actual_over"].astype(int).to_numpy()
    base_probability = np.clip(rows["adjusted_over_probability"].astype(float).to_numpy(), 0.001, 0.999)
    stacker_probability = np.zeros(len(rows), dtype=float)
    dates = sorted(str(item) for item in rows["game_date"].dropna().unique())

    fold_rows: list[dict[str, Any]] = []
    for index, game_date in enumerate(dates, start=1):
        train_mask = (rows["game_date"].astype(str) != game_date).to_numpy()
        test_mask = ~train_mask
        model = _train_classifier(
            frame.loc[train_mask],
            outcome[train_mask],
            cat_indices=cat_indices,
            args=args,
        )
        stacker_probability[test_mask] = model.predict_proba(Pool(frame.loc[test_mask], cat_features=cat_indices))[:, 1]
        fold_metric = _metrics(stacker_probability[test_mask], outcome[test_mask])
        fold_metric.update({
            "game_date": game_date,
            "rows": int(test_mask.sum()),
            "fold_index": index,
            "elapsed_sec": round(time.time() - start, 2),
        })
        fold_rows.append(fold_metric)
        print(json.dumps({"event": "lodo_fold_complete", **fold_metric}, sort_keys=True), flush=True)

    sweep_rows: list[dict[str, Any]] = []
    base_metrics = _metrics(base_probability, outcome)
    stacker_metrics = _metrics(stacker_probability, outcome)
    for weight in _float_list(args.blend_weights):
        blended = _blend(base_probability, stacker_probability, weight)
        metrics = _metrics(blended, outcome)
        sweep_rows.append({
            "sweep_id": f"classifier_blend_{weight:g}",
            "blend_weight": weight,
            "brier_over": metrics["brier"],
            "logloss_over": metrics["logloss"],
            "pick_win_rate": metrics["pick_win_rate"],
            "probability_mean": metrics["probability_mean"],
            "base_brier_over": base_metrics["brier"],
            "base_logloss_over": base_metrics["logloss"],
            "delta_brier_over": round(metrics["brier"] - base_metrics["brier"], 8),
            "delta_logloss_over": round(metrics["logloss"] - base_metrics["logloss"], 8),
            "row_count": int(len(rows)),
            "date_count": int(len(dates)),
        })

    sweep_rows = sorted(sweep_rows, key=lambda row: (row["brier_over"], row["logloss_over"]))
    best = sweep_rows[0]
    best_probability = _blend(base_probability, stacker_probability, float(best["blend_weight"]))

    predictions = rows[[
        "run_id",
        "game_date",
        "source_projection_id",
        "player_name",
        "market",
        "tier",
        "line",
        "actual_over",
    ]].copy()
    predictions["base_over_probability"] = base_probability
    predictions["stacker_over_probability"] = stacker_probability
    predictions["stacked_over_probability"] = best_probability
    predictions.to_csv(output_dir / "lodo_predictions.csv", index=False)
    pd.DataFrame(sweep_rows).to_csv(output_dir / "sweep_results.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(output_dir / "fold_results.csv", index=False)

    final_model = _train_classifier(frame, outcome, cat_indices=cat_indices, args=args)
    model_path = output_dir / f"{args.version}.cbm"
    final_model.save_model(model_path)

    feature_importance = dict(zip(features, [float(value) for value in final_model.get_feature_importance()]))
    best_config = {
        "schema_version": "mlb_cat_probability_stacker_training_v1",
        "version": args.version,
        "base_model_dir": str(base_model_dir),
        "base_model_version": base_meta.get("version"),
        "target": "actual_over",
        "features": features,
        "cat_features": cat_features,
        "row_count": int(len(rows)),
        "date_count": int(len(dates)),
        "dates": dates,
        "iterations": args.iterations,
        "learning_rate": args.learning_rate,
        "depth": args.depth,
        "l2_leaf_reg": args.l2_leaf_reg,
        "min_data_in_leaf": args.min_data_in_leaf,
        "blend_weight": float(best["blend_weight"]),
        "best_lodo": best,
        "base_lodo": base_metrics,
        "stacker_lodo": stacker_metrics,
        "feature_importance": feature_importance,
        "model_path": str(model_path),
        "lodo_predictions_csv": str(output_dir / "lodo_predictions.csv"),
        "sweep_results_csv": str(output_dir / "sweep_results.csv"),
        "fold_results_csv": str(output_dir / "fold_results.csv"),
        "elapsed_sec": round(time.time() - start, 2),
        "trained_at_unix": round(time.time(), 3),
    }
    (output_dir / "best_config.json").write_text(json.dumps(best_config, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"best_lodo": best, "meta_path": str(output_dir / "best_config.json")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
