from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from Atlas.runtime.replay_eval import backfill_eval_legs_for_run, backfill_latest_replay_eval_legs, find_latest_replay_run_dir


class ReplayEvalTest(unittest.TestCase):
    def test_find_latest_replay_run_dir_prefers_runs_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            runs_root = output_root / "runs"
            older = runs_root / "older"
            newer = runs_root / "newer"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")
            (newer / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")

            newer.touch()

            self.assertEqual(find_latest_replay_run_dir(output_root), newer.resolve())

    def test_find_latest_replay_run_dir_supports_single_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            (output_root / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")

            self.assertEqual(find_latest_replay_run_dir(output_root), output_root.resolve())

    def test_backfill_eval_legs_for_run_skips_when_eval_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            run_dir = repo_root / "run"
            run_dir.mkdir(parents=True)
            (run_dir / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")
            eval_path = run_dir / "eval_legs.csv"
            eval_path.write_text("ok\n", encoding="utf-8")
            (run_dir / "eval_legs_reconstruction_report.json").write_text(
                '{"report": {"matched_rows": 5}}',
                encoding="utf-8",
            )
            gamelogs_path = repo_root / "nba_gamelogs.csv"
            gamelogs_path.write_text("game_date,player,team,opp\n", encoding="utf-8")

            out = backfill_eval_legs_for_run(run_dir=run_dir, gamelogs_path=gamelogs_path, repo_root=repo_root)

            self.assertEqual(out, eval_path.resolve())

    def test_backfill_latest_replay_eval_legs_invokes_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            tool_path = repo_root / "tools" / "create_eval_leg_backtestv2.py"
            tool_path.parent.mkdir(parents=True)
            tool_path.write_text("# placeholder\n", encoding="utf-8")

            output_root = repo_root / "data" / "telemetry" / "replay_runs" / "sample"
            run_dir = output_root / "runs" / "20260324_000000"
            run_dir.mkdir(parents=True)
            (run_dir / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")

            gamelogs_path = repo_root / "data" / "gamelogs" / "nba_gamelogs.csv"
            gamelogs_path.parent.mkdir(parents=True)
            gamelogs_path.write_text("game_date,player,team,opp\n", encoding="utf-8")

            def fake_run(cmd: list[str], cwd: str, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd[1], str(tool_path))
                self.assertIn("--run-dir", cmd)
                self.assertIn(str(run_dir), cmd)
                self.assertEqual(cwd, str(repo_root))
                (run_dir / "eval_legs.csv").write_text("ok\n", encoding="utf-8")
                (run_dir / "eval_legs_reconstruction_report.json").write_text(
                    '{"report": {"matched_rows": 10}}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

            with mock.patch("Atlas.runtime.replay_eval.subprocess.run", side_effect=fake_run) as patched:
                eval_path = backfill_latest_replay_eval_legs(
                    output_root=output_root,
                    gamelogs_path=gamelogs_path,
                    repo_root=repo_root,
                    python_executable=sys.executable,
                )

            self.assertEqual(patched.call_count, 1)
            self.assertEqual(eval_path, (run_dir / "eval_legs.csv").resolve())

    def test_backfill_eval_legs_for_run_falls_back_until_matched_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            tool_path = repo_root / "tools" / "create_eval_leg_backtestv2.py"
            tool_path.parent.mkdir(parents=True)
            tool_path.write_text("# placeholder\n", encoding="utf-8")

            run_dir = repo_root / "run"
            run_dir.mkdir(parents=True)
            (run_dir / "scored_legs_deduped.csv").write_text("x\n1\n", encoding="utf-8")

            bad_gamelogs = repo_root / "bad.csv"
            good_gamelogs = repo_root / "good.csv"
            bad_gamelogs.write_text("game_date,player,team,opp\n", encoding="utf-8")
            good_gamelogs.write_text("game_date,player,team,opp\n", encoding="utf-8")

            def fake_run(cmd: list[str], cwd: str, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
                candidate = Path(cmd[-1])
                (run_dir / "eval_legs.csv").write_text("ok\n", encoding="utf-8")
                matched_rows = 0 if candidate == bad_gamelogs else 12
                (run_dir / "eval_legs_reconstruction_report.json").write_text(
                    '{"report": {"matched_rows": ' + str(matched_rows) + '}}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

            with mock.patch("Atlas.runtime.replay_eval.subprocess.run", side_effect=fake_run) as patched:
                eval_path = backfill_eval_legs_for_run(
                    run_dir=run_dir,
                    gamelogs_path=[bad_gamelogs, good_gamelogs],
                    repo_root=repo_root,
                    python_executable=sys.executable,
                )

            self.assertEqual(patched.call_count, 2)
            self.assertEqual(eval_path, (run_dir / "eval_legs.csv").resolve())


if __name__ == "__main__":
    unittest.main()