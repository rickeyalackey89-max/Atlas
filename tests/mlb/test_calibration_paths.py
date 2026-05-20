from pathlib import Path

from mlb.modeling.calibration import _resolve_model_path


def test_resolve_model_path_falls_back_from_stale_absolute_path(tmp_path):
    artifact_dir = tmp_path / "data" / "mlb" / "model" / "cat_v1" / "scale_tuning"
    artifact_dir.mkdir(parents=True)
    model_path = artifact_dir.parent / "model.cbm"
    model_path.write_text("model", encoding="utf-8")
    artifact_path = artifact_dir / "tuned_best_config.json"

    resolved = _resolve_model_path(
        {"model_path": str(Path("C:/stale/repo/data/mlb/model/cat_v1/model.cbm"))},
        artifact_path,
    )

    assert resolved == model_path.resolve()
