# Atlas Entry Points (Authoritative)
Last Updated: 2026-02-14

## Goal
Reduce runtime ambiguity: one production entrypoint, one sandbox entrypoint.
All other entrypoints are labeled legacy/dev-only. No refactors in Phase 1.

---

## ✅ Production Entrypoint (ONLY)
### run.ps1
**Status:** AUTHORITATIVE (PRODUCTION)

**Purpose:** Full daily run orchestration.
- Calls injury pull/parse + gamelogs refresh
- Runs `run_today.py`
- Generates wiring + audit artifacts

**Invocation:**
pwsh -NoProfile -File .\run.ps1

---

## ✅ Sandbox Entrypoint (ONLY)
### tools/Run-Sandbox.ps1
**Status:** AUTHORITATIVE (SANDBOX)

**Purpose:** Isolated experimental runs.
- Snapshots inputs
- Runs CONTROL + VARIANT
- Produces `scored_diff.csv`
- Writes only into `data/output/sandbox_runs/...`

**Invocation:**
pwsh -NoProfile -File .\tools\Run-Sandbox.ps1 ...

---

## ⚠️ Secondary / Delegated (NOT direct authority)
### run_today.py
**Status:** DELEGATED (called by run.ps1)
**Role:** Python entry called by production orchestrator.
Do not run directly unless you understand required args and paths.

### atlas.ps1
**Status:** LEGACY OR WRAPPER (not authoritative)
**Role:** Convenience wrapper only, must not become a second production path.

### src/Atlas/Public/Invoke-AtlasRunAllAndPublish.ps1
**Status:** PUBLISH PIPELINE (not runtime authority)
**Role:** Publishing/deployment workflow. Not the daily modeling entrypoint.

### tools/Invoke-RunAllAndPublish.ps1
**Status:** LEGACY/UTILITY
**Role:** Tooling wrapper. Not authoritative.

---

## 🔒 Phase 1 Rule
Nothing is refactored in Phase 1.
We only label entrypoints to remove ambiguity at the top of the system.
