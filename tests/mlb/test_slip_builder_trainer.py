import importlib.util
from pathlib import Path


def _load_trainer_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "mlb" / "train_slip_builder_policy.py"
    spec = importlib.util.spec_from_file_location("train_slip_builder_policy", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probability_overlay_prefers_tuned_probability(tmp_path):
    module = _load_trainer_module()
    overlay_csv = tmp_path / "overlay.csv"
    overlay_csv.write_text(
        "\n".join(
            [
                "run_id,game_date,source_projection_id,tuned_over_probability,adjusted_over_probability,over_probability",
                "run_a,2026-05-18,proj_1,0.71,0.62,0.51",
            ]
        ),
        encoding="utf-8",
    )

    overlay = module._load_probability_overlay(overlay_csv)

    assert overlay[("run_a", "2026-05-18", "proj_1")] == 0.71
    assert overlay[("2026-05-18", "proj_1")] == 0.71
    assert overlay[("proj_1",)] == 0.71


def test_probability_overlay_falls_back_to_adjusted_probability(tmp_path):
    module = _load_trainer_module()
    overlay_csv = tmp_path / "overlay.csv"
    overlay_csv.write_text(
        "\n".join(
            [
                "run_id,game_date,source_projection_id,tuned_over_probability,stacked_over_probability,adjusted_over_probability,over_probability",
                "run_a,2026-05-18,proj_1,,,0.62,0.51",
            ]
        ),
        encoding="utf-8",
    )

    overlay = module._load_probability_overlay(overlay_csv)

    assert overlay[("run_a", "2026-05-18", "proj_1")] == 0.62
