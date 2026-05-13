# Atlas CLI Listener

The Atlas CLI listener is a local, file-backed bridge for mobile ChatGPT,
humans, GitHub automation, and future agents.

It watches an inbox for JSON tasks and executes only allowlisted Atlas actions.
It does not run arbitrary shell commands.

## Paths

- Inbox: `data/automation/cli_listener/inbox`
- Processing: `data/automation/cli_listener/processing`
- Outbox: `data/automation/cli_listener/outbox`
- Failed: `data/automation/cli_listener/failed`
- Logs: `data/automation/cli_listener/logs`
- Codex handoffs: `data/automation/cli_listener/codex_handoffs`
- Latest status: `data/automation/cli_listener/status.json`

## Start Listener

```powershell
.\scripts\automation\atlas_cli_listener.ps1 listen
```

Process queued tasks once:

```powershell
.\scripts\automation\atlas_cli_listener.ps1 once
```

## Submit Tasks

Dry-run the 6 AM eval:

```powershell
.\scripts\automation\atlas_cli_listener.ps1 submit run_6am_eval --dry-run --reason "mobile smoke test"
.\scripts\automation\atlas_cli_listener.ps1 once
```

Queue the 8 AM live run:

```powershell
.\scripts\automation\atlas_cli_listener.ps1 submit run_live --slot 8am --reason "manual mobile trigger"
```

Create a Codex handoff:

```powershell
.\scripts\automation\atlas_cli_listener.ps1 submit codex_handoff --prompt "Review the latest run and summarize slip risk."
```

## Supported Actions

- `status`
- `latest_run`
- `git_status`
- `run_6am_eval`
- `run_live`
- `publish_dashboard`
- `codex_handoff`

## JSON Task Format

```json
{
  "id": "run_8am_live_manual",
  "action": "run_live",
  "slot": "8am",
  "requested_by": "mobile_chatgpt",
  "reason": "Manual operator trigger",
  "dry_run": false,
  "timeout_seconds": 7200
}
```

## Safety Rules

- No arbitrary command execution.
- Commands are mapped to known Atlas scripts.
- Secrets are redacted in task result JSON.
- Failed or rejected tasks are retained in `failed/`.
- Long-running command output is streamed to the listener terminal and written to `logs/`.

## Mobile Workflow

1. Ask ChatGPT to produce a listener JSON task.
2. Put that JSON into `data/automation/cli_listener/inbox`.
3. Run the listener, or leave it running.
4. Check `status.json` or the matching file in `outbox/`.

For Codex work, use `codex_handoff`. It writes a durable Markdown task that Codex can pick up from the repo without granting broad automation permissions.
