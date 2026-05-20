from mlb.runtime.pipeline import (
    BUNDLE_REPLAY_PIPELINE_STAGES,
    LIVE_PIPELINE_STAGES,
    MLB_PIPELINE_STAGES,
    SINGLE_REPLAY_PIPELINE_STAGES,
)
from mlb.runtime.bundles import expected_bundle_artifacts
from mlb.runtime.preflight import build_preflight_report
from mlb.runtime.publishing import publishing_enabled
from mlb.runtime.inspection import run_inspection_command
from mlb.runtime.live_delegation import live_plan_result
from mlb.runtime.replay_delegation import replay_plan_result
from mlb.runtime.results import render_runtime_result
from mlb.runtime.fidelity import fidelity_policy, normalize_run_mode
from mlb.domain.slips import supported_slip_families


def test_pipeline_starts_with_source_fetches():
    assert MLB_PIPELINE_STAGES[0] == "fetch_prizepicks_raw_snapshots"
    assert MLB_PIPELINE_STAGES[1] == "normalize_prizepicks_board"
    assert MLB_PIPELINE_STAGES[2] == "write_engine_board_inputs"
    assert "build_share_matrix" in MLB_PIPELINE_STAGES
    assert "run_sobol_qmc_simulation" in MLB_PIPELINE_STAGES
    assert "extract_market_probabilities" in MLB_PIPELINE_STAGES
    assert "calibrate_market_probabilities" in MLB_PIPELINE_STAGES
    assert "run_deterministic_anomaly_checks" in LIVE_PIPELINE_STAGES
    assert "run_openai_operator_evaluation" in LIVE_PIPELINE_STAGES
    assert "write_publish_decision" in LIVE_PIPELINE_STAGES
    assert "settle_replay_outcomes" not in LIVE_PIPELINE_STAGES


def test_replay_modes_are_explicitly_separate():
    assert "write_engine_board_inputs" in SINGLE_REPLAY_PIPELINE_STAGES
    assert "settle_replay_outcomes" in SINGLE_REPLAY_PIPELINE_STAGES
    assert "write_operator_report" in SINGLE_REPLAY_PIPELINE_STAGES
    assert "write_corpus_cache" in BUNDLE_REPLAY_PIPELINE_STAGES
    assert "run_openai_bundle_evaluation" in BUNDLE_REPLAY_PIPELINE_STAGES
    assert "write_loso_training_manifest" in BUNDLE_REPLAY_PIPELINE_STAGES


def test_replay_fidelity_policy_is_canonical():
    assert normalize_run_mode("replay") == "replay_single"
    assert normalize_run_mode("replay_bundle") == "replay_corpus"
    policy = fidelity_policy("replay_single")
    assert policy["strict_replay_fidelity"] is True
    assert policy["post_date_context_allowed"] is False
    assert policy["replay_only_model_inputs_allowed"] is False


def test_publishing_is_disabled_in_dev_skeleton():
    assert publishing_enabled() is False


def test_slip_families_keep_dashboard_shape():
    families = supported_slip_families()
    assert "System" in families
    assert "Windfall" in families
    assert "DemonHunter" in families
    assert "Marketed" in families


def test_preflight_report_stays_outside_cli():
    report = build_preflight_report()
    assert report["sport"] == "mlb"
    assert report["legacy_nba_live_cli"] == "removed"
    assert report["publishing_enabled"] is False


def test_inspection_lists_pipeline_without_cli_orchestration():
    result = run_inspection_command("pipeline")
    assert "write_live_run_manifest" in result.payload["stages"]
    assert result.payload["publishing"]["enabled"] is False
    assert "MLB pipeline stages:" in render_runtime_result(result)


def test_inspection_lists_sources():
    result = run_inspection_command("sources")
    keys = {source["key"] for source in result.payload["sources"]}
    assert "prizepicks" in keys
    assert "espn_injuries" in keys


def test_runtime_boundaries_separate_live_and_replay():
    live = live_plan_result()
    replay_single = replay_plan_result("single")
    replay_corpus = replay_plan_result("corpus")
    replay_bundle_alias = replay_plan_result("bundle")
    assert live.payload["mode"] == "live"
    assert replay_single.payload["replay_type"] == "single"
    assert replay_corpus.payload["replay_type"] == "corpus"
    assert replay_bundle_alias.payload["replay_type"] == "corpus"
    assert "settle_replay_outcomes" not in live.payload["stages"]
    assert "settle_replay_outcomes" in replay_single.payload["stages"]
    assert "write_corpus_cache" in replay_corpus.payload["stages"]


def test_bundle_contract_contains_replay_manifests():
    artifacts = expected_bundle_artifacts()
    artifact_names = {artifact.name for artifact in artifacts}
    assert "source_manifest" in artifact_names
    assert "run_manifest" in artifact_names
