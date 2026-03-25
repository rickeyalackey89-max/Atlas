from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_BUNDLE_PATH = PROJECT_ROOT / "tools" / "replay_bundle.py"

spec = importlib.util.spec_from_file_location("replay_bundle", REPLAY_BUNDLE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load replay_bundle from {REPLAY_BUNDLE_PATH}")
replay_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay_bundle)


class ReplayBundleRoleMetricsFallbackTest(unittest.TestCase):
    def test_prefers_archived_role_metrics_before_replay_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)

            archive_dir = repo_root / "data" / "archives" / "iael" / "2026" / "2026-03-17" / "20260317_060000Z"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_json = archive_dir / "role_metrics_latest.json"
            archive_json.write_text(json.dumps({"fetched_at": "2026-03-17T06:00:00+00:00", "rows": []}), encoding="utf-8")
            (archive_dir / "role_metrics_snapshot_manifest.json").write_text(
                json.dumps({"fetched_at": "2026-03-17T06:00:00+00:00"}),
                encoding="utf-8",
            )

            replay_dash = repo_root / "data" / "telemetry" / "replay_runs" / "sample" / "dashboard"
            replay_dash.mkdir(parents=True, exist_ok=True)
            replay_json = replay_dash / "role_metrics_latest.json"
            replay_json.write_text(json.dumps({"fetched_at": "2026-03-24T16:28:20+00:00", "rows": []}), encoding="utf-8")
            (replay_dash / "role_metrics_snapshot_manifest.json").write_text(
                json.dumps({"fetched_at": "2026-03-24T16:28:20+00:00"}),
                encoding="utf-8",
            )

            artifacts = replay_bundle._find_best_role_metrics_artifacts(
                repo_root,
                datetime(2026, 3, 17, 6, 7, 13, tzinfo=timezone.utc),
            )

            self.assertEqual(artifacts["ATLAS_ROLE_METRICS_PATH"], archive_json.resolve())

    def test_falls_back_to_replay_dashboard_when_no_archive_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)

            replay_dash = repo_root / "data" / "telemetry" / "replay_runs" / "sample" / "dashboard"
            replay_dash.mkdir(parents=True, exist_ok=True)
            replay_json = replay_dash / "role_metrics_latest.json"
            replay_json.write_text(json.dumps({"fetched_at": "2026-03-24T16:28:20+00:00", "rows": []}), encoding="utf-8")
            replay_manifest = replay_dash / "role_metrics_snapshot_manifest.json"
            replay_manifest.write_text(
                json.dumps({"fetched_at": "2026-03-24T16:28:20+00:00"}),
                encoding="utf-8",
            )

            artifacts = replay_bundle._find_best_role_metrics_artifacts(
                repo_root,
                datetime(2026, 3, 17, 6, 7, 13, tzinfo=timezone.utc),
            )

            self.assertEqual(artifacts["ATLAS_ROLE_METRICS_PATH"], replay_json.resolve())
            self.assertEqual(artifacts["ATLAS_ROLE_METRICS_MANIFEST_PATH"], replay_manifest.resolve())

    def test_prefers_game_date_match_over_dashboard_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)

            dashboard_dir = repo_root / "data" / "output" / "dashboard"
            dashboard_dir.mkdir(parents=True, exist_ok=True)
            dashboard_json = dashboard_dir / "role_metrics_latest.json"
            dashboard_manifest = dashboard_dir / "role_metrics_snapshot_manifest.json"
            dashboard_json.write_text(json.dumps({"game_date": "2026-03-24", "fetched_at": "2026-03-24T22:52:54+00:00", "rows": []}), encoding="utf-8")
            dashboard_manifest.write_text(json.dumps({"game_date": "2026-03-24", "fetched_at": "2026-03-24T22:52:54+00:00"}), encoding="utf-8")

            replay_dash = repo_root / "data" / "telemetry" / "replay_runs" / "sample" / "dashboard"
            replay_dash.mkdir(parents=True, exist_ok=True)
            replay_json = replay_dash / "role_metrics_latest.json"
            replay_manifest = replay_dash / "role_metrics_snapshot_manifest.json"
            replay_json.write_text(json.dumps({"game_date": "2026-03-17", "fetched_at": "2026-03-24T20:21:07+00:00", "rows": []}), encoding="utf-8")
            replay_manifest.write_text(json.dumps({"game_date": "2026-03-17", "fetched_at": "2026-03-24T20:21:07+00:00"}), encoding="utf-8")

            artifacts = replay_bundle._find_best_role_metrics_artifacts(
                repo_root,
                datetime(2026, 3, 17, 6, 7, 13, tzinfo=timezone.utc),
            )

            self.assertEqual(artifacts["ATLAS_ROLE_METRICS_PATH"], replay_json.resolve())


if __name__ == "__main__":
    unittest.main()