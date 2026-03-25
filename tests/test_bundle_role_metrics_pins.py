from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from Atlas.runtime.archive_writer import archive_role_metrics_artifacts, resolve_archive_ids
from Atlas.runtime.bundles import write_bundle_zip


class BundleRoleMetricsPinsTest(unittest.TestCase):
    def test_bundle_includes_pinned_role_metrics_when_run_dashboard_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            data_dir = repo_root / "data"
            run_id = "20260325_123456"

            latest_json = data_dir / "output" / "dashboard" / "role_metrics_latest.json"
            latest_html = data_dir / "output" / "dashboard" / "role_metrics_latest.html"
            latest_manifest = data_dir / "output" / "dashboard" / "role_metrics_snapshot_manifest.json"
            latest_json.parent.mkdir(parents=True, exist_ok=True)
            latest_json.write_text(json.dumps({"rows": []}), encoding="utf-8")
            latest_html.write_text("<html></html>", encoding="utf-8")
            latest_manifest.write_text(json.dumps({"snapshot_id": "abc"}), encoding="utf-8")

            archive_role_metrics_artifacts(
                repo_root=repo_root,
                role_metrics_latest_json=latest_json,
                role_metrics_latest_html=latest_html,
                role_metrics_manifest=latest_manifest,
                ids=resolve_archive_ids(run_id=run_id, snapshot_id="20260325_123456Z", date_dashed="2026-03-25"),
            )

            run_dir = data_dir / "output" / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            zip_path = write_bundle_zip(
                repo_root=repo_root,
                data_dir=data_dir,
                run_id=run_id,
                ok=True,
                engine_entry="python -m Atlas.cli live",
                run_dir=run_dir,
            )

            with zipfile.ZipFile(zip_path, "r") as bundle_zip:
                names = set(bundle_zip.namelist())

            self.assertIn("dashboard/role_metrics_latest.json", names)
            self.assertIn("dashboard/role_metrics_latest.html", names)
            self.assertIn("dashboard/role_metrics_snapshot_manifest.json", names)


if __name__ == "__main__":
    unittest.main()