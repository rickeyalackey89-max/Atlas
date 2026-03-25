from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Atlas.runtime import orchestrator


class RoleMetricsSourceResolutionTest(unittest.TestCase):
    def test_fetch_role_metrics_snapshot_uses_craftednba_api_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            tools_dir = project_root / "tools"
            tools_dir.mkdir(parents=True, exist_ok=True)
            api_script = tools_dir / "fetch_crafted_player_stats.py"
            api_script.write_text("print('stub')\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ATLAS_ROLE_METRICS_URL": "",
                    "ATLAS_ROLE_METRICS_HTML_PATH": "",
                },
                clear=False,
            ):
                with patch.object(orchestrator, "TOOLS_DIR", tools_dir):
                    with patch.object(orchestrator, "_run") as run_mock:
                        with patch.object(orchestrator, "_extra_env_for_raw", return_value={}):
                            orchestrator.fetch_role_metrics_snapshot(game_date="2026-03-18")

        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertIn("fetch_crafted_player_stats.py", cmd[1])

    def test_uses_local_fetch_capture_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            capture = project_root / "Fetch2.txt"
            capture.write_text("<html>capture</html>", encoding="utf-8")

            with patch.dict(os.environ, {"ATLAS_ROLE_METRICS_URL": "", "ATLAS_ROLE_METRICS_HTML_PATH": ""}, clear=False):
                with patch.object(orchestrator, "PROJECT_ROOT", project_root):
                    source_url, html_path, source_kind = orchestrator._resolve_role_metrics_source()
                    exported_path = os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH")

        self.assertEqual("", source_url)
        self.assertEqual(str(capture), html_path)
        self.assertEqual("local-capture", source_kind)
        self.assertEqual(str(capture), exported_path)

    def test_uses_dashboard_fallback_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            data_dir = Path(tmp_dir)
            dashboard_dir = data_dir / "output" / "dashboard"
            dashboard_dir.mkdir(parents=True, exist_ok=True)
            dashboard_html = dashboard_dir / "role_metrics_latest.html"
            dashboard_html.write_text("<html></html>", encoding="utf-8")

            with patch.dict(os.environ, {"ATLAS_ROLE_METRICS_URL": "", "ATLAS_ROLE_METRICS_HTML_PATH": ""}, clear=False):
                with patch.object(orchestrator, "PROJECT_ROOT", project_root):
                    with patch.object(orchestrator, "DATA_DIR", data_dir):
                        source_url, html_path, source_kind = orchestrator._resolve_role_metrics_source()
                    exported_path = os.environ.get("ATLAS_ROLE_METRICS_HTML_PATH")

        self.assertEqual("", source_url)
        self.assertEqual(str(dashboard_html), html_path)
        self.assertEqual("dashboard-fallback", source_kind)
        self.assertEqual(str(dashboard_html), exported_path)

    def test_prefers_configured_html_path_over_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            data_dir = Path(tmp_dir)
            dashboard_dir = data_dir / "output" / "dashboard"
            dashboard_dir.mkdir(parents=True, exist_ok=True)
            dashboard_html = dashboard_dir / "role_metrics_latest.html"
            dashboard_html.write_text("<html>fallback</html>", encoding="utf-8")

            configured_html = data_dir / "custom_role_metrics.html"
            configured_html.write_text("<html>configured</html>", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ATLAS_ROLE_METRICS_URL": "",
                    "ATLAS_ROLE_METRICS_HTML_PATH": str(configured_html),
                },
                clear=False,
            ):
                with patch.object(orchestrator, "PROJECT_ROOT", project_root):
                    with patch.object(orchestrator, "DATA_DIR", data_dir):
                        source_url, html_path, source_kind = orchestrator._resolve_role_metrics_source()

        self.assertEqual("", source_url)
        self.assertEqual(str(configured_html), html_path)
        self.assertEqual("configured-html", source_kind)


if __name__ == "__main__":
    unittest.main()