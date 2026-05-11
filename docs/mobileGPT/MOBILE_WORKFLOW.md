# Atlas Mobile Workflow

Last updated: 2026-05-11

## 1. Overview

Purpose:

- Provide a concise mobile playbook for Atlas operations.
- Recover context quickly when using ChatGPT on mobile.
- Turn mobile observations into Codex-ready repo tasks.
- Keep GitHub as the source of truth while desktop/VS Code remains the primary development environment.

Use mobile for:

- Reviewing status and daily runs.
- Asking architecture questions.
- Creating Codex tasks.
- Checking PRs, issues, and docs.
- Capturing ideas before desktop work.

Do not use mobile for:

- Heavy refactors.
- Large file edits.
- Local model runs.
- Environment debugging.
- Production deploys without desktop verification.

Relationship:

- ChatGPT mobile: context recovery, planning, review, prompt drafting.
- Codex: repo-aware implementation, audits, tests, commits, PR preparation.
- GitHub: source of truth for branches, PRs, issues, Actions, and review history.
- VS Code desktop: primary workspace for deep development and local validation.

---

## 2. Repository Map

Atlas core repository:

- Local: `C:\Users\13142\Atlas\Atlas`
- Responsibility: NBA model runtime, data pipeline, configs, evals, scripts, trainers, docs.
- Default Codex working directory for model, pipeline, and docs tasks.

atlas-dashboard repository:

- Local: `C:\Users\13142\Atlas\atlas-dashboard`
- Responsibility: website, dashboard UI, Cloudflare data publish surface.
- Use when tasks touch `atlassports.ai`, dashboard rendering, public data, or deploy copy.

Working assumption:

- GitHub is canonical.
- Local repos may have generated daily-run files.
- Codex should inspect `git status` before edits and avoid reverting unrelated changes.

---

## 3. Mobile Safe Operations

Allowed from mobile:

- Read docs and source files.
- Review recent commits and PRs.
- Ask Codex for repo analysis.
- Draft issues, PR descriptions, and task plans.
- Update small Markdown files.
- Check whether scheduled runs completed.
- Ask for status summaries of model/runtime artifacts.
- Making small edits and refactors.

Restricted or high-risk from mobile:

- Promoting models.
- Editing `config.yaml` for production behavior.
- Running trainers or long replays.
- Bulk file moves or deletes.
- Publishing dashboard changes without verification.
- Touching secrets, webhooks, tokens, or credential paths.
- Merging PRs that affect model runtime without tests or replay evidence.

PR review guidance:

- Read the diff first.
- Ask what production surfaces are touched.
- Require validation notes for model, dashboard, Discord, and scheduled-task changes.
- Prefer small PRs with a clear purpose.
- Do not approve model promotion without replay/eval evidence.

Documentation workflow:

- Update docs in the same PR as behavior changes.
- Mark historical docs clearly when they are superseded.
- Prefer links to current state docs instead of duplicating long explanations.
- Keep mobile-facing docs short and scannable.

---

## 4. Codex Workflow

Use Codex for:

- Repo inventory and dependency tracing.
- Implementation plans.
- Scoped code edits.
- Test and validation runs.
- Documentation cleanup.
- PR preparation and commit summaries.

Codex should:

- Start with `git status --short --branch`.
- Read current docs before changing runtime behavior.
- Prefer existing patterns in the repo.
- Explain when a change touches production behavior.
- Avoid reverting unrelated generated files or user edits.
- Commit only the scoped changes requested.

PR-first workflow:

- Use `feature/*` for product/runtime work.
- Use `ai/*` for AI docs, audits, planning, and operator workflow.
- Keep `main` stable and deployable.
- For risky changes, ask Codex to prepare a branch and PR instead of direct push.

Architecture review process:

- Identify the current source of truth.
- Trace inputs, outputs, config, and publish surfaces.
- Name assumptions.
- List risks before recommendations.
- Propose small reversible changes first.

---

## 5. Prompt Templates

Architecture review:

```text
Review the Atlas architecture for <system>. Start from the current docs, trace the source files, list the data flow, identify risks, and recommend the smallest safe improvements. Do not edit files unless I ask.
```

Repo analysis:

```text
Inspect the repo for <topic>. Summarize the relevant files, current behavior, stale docs, and likely next actions. Include file paths and line references where useful.
```

Model inspection:

```text
Inspect the current Atlas model runtime. Compare config, run manifests, and model metadata. Tell me which calibrator is active, what probability chain is used, and whether docs disagree with runtime.
```

Dashboard integration:

```text
Review the dashboard integration for <feature>. Check Atlas payload generation, atlas-dashboard rendering, publish scripts, and live deployed data. Identify what updates the site and what should be preserved.
```

Debugging:

```text
Debug <issue>. Start with logs and recent run artifacts, then trace the responsible scripts. Give me the root cause, whether production is affected, and the smallest safe fix.
```

Technical debt analysis:

```text
Audit <folder/system> for technical debt. Classify findings as stale docs, duplicate code, risky config, unused artifacts, missing tests, or unclear ownership. Recommend a cleanup order.
```

Codex task:

```text
Create a scoped Codex task for <goal>. Include context files, constraints, expected outputs, validation steps, and what should not be touched.
```

---

## 6. Recovery Workflow

When session continuity is lost:

1. Open [../CURRENT_STATE_2026-05-10.md](../CURRENT_STATE_2026-05-10.md).
2. Open [../README.md](../README.md).
3. Open [../WEBSITE_TODO.md](../WEBSITE_TODO.md) for dashboard/Discord work.
4. Check the latest GitHub commits and open PRs.
5. Ask Codex to run `git status --short --branch`.
6. Ask Codex to summarize recent run artifacts if the task is operational.
7. Continue only after confirming the newest user request.

Operational recovery checklist:

- Confirm current branch.
- Confirm dirty files.
- Confirm active model version.
- Confirm latest live run and dashboard payload.
- Confirm whether any scheduled task failed.
- Decide whether work belongs in `Atlas` or `atlas-dashboard`.

---

## 7. Branch Strategy

`main`:

- Stable production branch.
- Direct commits only for low-risk docs or explicitly approved operational fixes.
- Must remain deployable.

`feature/*`:

- Runtime features.
- Dashboard changes.
- Pipeline changes.
- Anything that should receive PR review.

`ai/*`:

- AI workflows.
- Documentation audits.
- Codex/mobile playbooks.
- Planning notes and non-runtime cleanup.

Safety rules:

- Do not mix generated run data with unrelated code cleanup unless the task is operational preservation.
- Do not promote model artifacts from a docs branch.
- Do not merge config changes without validation notes.
- Keep branch names descriptive and short.

---

## 8. Active Systems

Current model version:

- NBA: CatBoost playoff v5cD.
- Reference: [../CURRENT_STATE_2026-05-10.md](../CURRENT_STATE_2026-05-10.md).

Active pipelines:

- 6AM eval backfill and website performance update.
- 8AM live IAEL run.
- 11AM live IAEL run.
- 2:30PM live IAEL run.
- 4:30PM weekday free-slip job.
- 5:30PM live IAEL run.

Replay systems:

- Strict replay via `python -m Atlas.cli replay --raw <raw_json>`.
- Replay output root: `data/telemetry/replay_runs/`.

Deployment targets:

- Core repo: GitHub `Atlas`.
- Website repo: GitHub `atlas-dashboard`.
- Public site: `https://atlassports.ai`.
- Dashboard data: `https://atlassports.ai/data/cloudflare_payload.json`.

Dashboard status:

- Live data published from `data/output/dashboard/cloudflare_payload.json`.
- 6AM eval owns `performance` windows and yesterday slip results.
- Live runs update current picks/site data without rewriting 6AM eval results.

---

## 9. Quick Links

GitHub:

- Atlas core: `https://github.com/rickeyalackey89-max/Atlas`
- atlas-dashboard: `https://github.com/rickeyalackey89-max/atlas-dashboard`

PRs:

- Atlas PRs: `https://github.com/rickeyalackey89-max/Atlas/pulls`
- Dashboard PRs: `https://github.com/rickeyalackey89-max/atlas-dashboard/pulls`

Issues:

- Atlas issues: `https://github.com/rickeyalackey89-max/Atlas/issues`
- Dashboard issues: `https://github.com/rickeyalackey89-max/atlas-dashboard/issues`

Actions:

- Atlas Actions: `https://github.com/rickeyalackey89-max/Atlas/actions`
- Dashboard Actions: `https://github.com/rickeyalackey89-max/atlas-dashboard/actions`

Deployments:

- Cloudflare Pages: `<add Cloudflare deployment URL>`
- Dashboard publish notes: [../WEBSITE_TODO.md](../WEBSITE_TODO.md)

Monitoring:

- Telemetry log: `data/telemetry/iael_runs.log`
- Latest dashboard payload: `data/output/dashboard/cloudflare_payload.json`
- Latest live runs: `data/output/runs/`

Dashboards:

- Public dashboard: `https://atlassports.ai/dashboard/`
- Data payload: `https://atlassports.ai/data/cloudflare_payload.json`

---

## 10. AI Operational Rules

Reproducibility:

- Prefer pinned inputs for replay.
- Preserve run manifests and eval artifacts.
- Record command, branch, and artifact paths for meaningful changes.

Replay integrity:

- Do not let replay fetch fresh live inputs unless explicitly testing that behavior.
- Replay output belongs under `data/telemetry/replay_runs/`.
- Live output belongs under `data/output/`.

Model baseline protection:

- Treat CatBoost playoff v5cD as current production until a newer current-state doc supersedes it.
- Treat v18 LightGBM as historical baseline.
- Do not change model promotion paths without replay/eval evidence.
- Protect the May 10 Brier improvement from casual tuning.

PR workflows:

- Keep changes scoped.
- Include validation steps.
- Mention dashboard, Discord, model, and scheduled-task impact when relevant.
- Prefer PR review for production logic.

Documentation requirements:

- Update docs when behavior changes.
- Mark superseded docs clearly.
- Keep mobile docs concise.
- Link to current state rather than duplicating long technical history.

Validation before deployment:

- Run targeted tests or syntax checks.
- Verify generated payloads when dashboard behavior changes.
- Check live site/data URLs after publish.
- Confirm `git status` is clean or explain remaining generated files.
