import json

from Atlas.runtime.cli_listener import ListenerPaths, process_once, submit_task


class SubmitArgs:
    def __init__(
        self,
        action: str,
        *,
        task_id: str | None = None,
        slot: str | None = None,
        prompt: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self.action = action
        self.id = task_id
        self.slot = slot
        self.prompt = prompt
        self.requested_by = "pytest"
        self.reason = "test"
        self.dry_run = dry_run
        self.timeout_seconds = None


def test_listener_rejects_unknown_action(tmp_path):
    paths = ListenerPaths.from_root(tmp_path)
    paths.ensure()
    task_path = paths.inbox / "bad.json"
    task_path.write_text(json.dumps({"id": "bad", "action": "unknown_action"}), encoding="utf-8")

    results = process_once(paths)

    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert "unsupported action" in results[0]["error"]
    assert (paths.failed / "bad.result.json").exists()


def test_listener_dry_run_live_action(tmp_path):
    paths = ListenerPaths.from_root(tmp_path)
    submit_task(SubmitArgs("run_live", task_id="dry_live", slot="8am", dry_run=True), paths)

    results = process_once(paths)

    assert len(results) == 1
    assert results[0]["status"] == "dry_run"
    assert "run_iael_morning.cmd" in " ".join(results[0]["command"])
    assert (paths.outbox / "dry_live.json").exists()


def test_listener_codex_handoff_writes_prompt(tmp_path):
    paths = ListenerPaths.from_root(tmp_path)
    submit_task(
        SubmitArgs("codex_handoff", task_id="handoff", prompt="Review the latest run.", dry_run=False),
        paths,
    )

    results = process_once(paths)

    assert len(results) == 1
    assert results[0]["status"] == "completed"
    handoff_path = paths.codex_handoffs / "handoff.md"
    assert handoff_path.exists()
    assert "Review the latest run." in handoff_path.read_text(encoding="utf-8")
