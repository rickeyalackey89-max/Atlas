# Automation Helpers

Operator-facing automation helpers that are not Windows Task Scheduler entrypoints live here.

Keep scheduled IAEL `.cmd` and `task_*.xml` files at the root of `scripts/` because external scheduler definitions may reference those exact paths.

## CLI Listener

`atlas_cli_listener.ps1` starts the local file-backed automation bridge.

Common commands:

```powershell
.\scripts\automation\atlas_cli_listener.ps1 listen
.\scripts\automation\atlas_cli_listener.ps1 submit status
.\scripts\automation\atlas_cli_listener.ps1 submit run_live --slot 8am --dry-run
.\scripts\automation\atlas_cli_listener.ps1 once
```

Full contract: `docs/CLI_LISTENER.md`.
