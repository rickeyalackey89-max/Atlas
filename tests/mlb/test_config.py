from pathlib import Path

from mlb.runtime.config import active_mlb_config_manifest, load_active_mlb_config


def test_active_mlb_config_manifest_identifies_live_contract():
    root = Path(__file__).resolve().parents[2]

    config = load_active_mlb_config(root)
    manifest = active_mlb_config_manifest(root)

    assert config["schema_version"] == "atlas_mlb_operational_config_v1"
    assert config["kernels"]["cat_residual"]["active_version"] == "mlb_cat_over_residual_v6_23date_live_context_scale_tuned"
    assert config["market_sources"]["primary"] == "bettingpros_mlb_props"
    assert config["slips"]["active_builder_version"] == "atlas_mlb_public_slip_ranker_v18_market_source_context"
    assert manifest["exists"] is True
    assert manifest["sha256"]
    assert manifest["active_market_source"] == "bettingpros_mlb_props"
