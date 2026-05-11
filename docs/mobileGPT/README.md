# Atlas Mobile GPT

This folder is the mobile entry point for Atlas work with ChatGPT, Codex, GitHub, and VS Code.

## Start Here

## First Mobile Prompt

Read `docs/mobileGPT/MOBILE_WORKFLOW.md`, `docs/README.md`, and `ai/AGENT.md`.
Summarize current Atlas context, identify the correct repo for this task, and do not edit files until I approve the plan.
Open [MOBILE_WORKFLOW.md](MOBILE_WORKFLOW.md) first.

That document tells mobile ChatGPT/Codex:

- what Atlas repositories exist
- where to look first for current context
- which actions are safe from mobile
- which actions should wait for desktop/VS Code
- how to recover context after a session reset
- how to turn mobile notes into Codex-ready tasks

## Repo Location

Primary local workspace:

```text
C:\Users\13142\Atlas
```

Core repo:

```text
C:\Users\13142\Atlas\Atlas
```

Dashboard repo:

```text
C:\Users\13142\Atlas\atlas-dashboard
```

When Codex is connected to this project folder, use the core repo as the default working directory unless the task is explicitly about the website/dashboard.

## Quick Context Chain

For mobile context recovery, open these in order:

1. [../CURRENT_STATE_2026-05-10.md](../CURRENT_STATE_2026-05-10.md)
2. [../README.md](../README.md)
3. [../WEBSITE_TODO.md](../WEBSITE_TODO.md)
4. [MOBILE_WORKFLOW.md](MOBILE_WORKFLOW.md)

## Mobile Rule

Mobile is for review, triage, planning, prompts, and lightweight docs.

Desktop/VS Code is for heavy edits, model runs, environment debugging, and production changes.
