# Atlas — Current Status Snapshot

**Date:** 2026-02-10  
**Status:** ✅ Stable, Clean, Operational  
**Phase:** Post-hardening cleanup & consolidation

---

## Overview

Atlas is a PowerShell-orchestrated Python system that:
- Fetches daily NBA prop data (PrizePicks)
- Builds a canonical “today” board
- Runs a probabilistic model (System + Windfall)
- Produces ranked recommendations
- Publishes filtered outputs to AtlasDashboard (Cloudflare)

The system has been stabilized, simplified, and cleaned of legacy and experimental clutter.

---

## Canonical Execution Path (Authoritative)

There is exactly **one supported execution path**:

atlas.ps1
↓
Invoke-Atlas
↓
Invoke-AtlasRunAllAndPublish
↓
Invoke-AtlasRunTodayAndExport
↓
python.exe run_today.py


Key properties:
- One Python process
- No PowerShell recursion
- No wrapper shell loops
- Known PID, controlled priority & CPU affinity
- BLAS/OpenMP thread caps applied before Python starts

---

## Entrypoints

### PowerShell
- `atlas.ps1` — **canonical CLI entrypoint**
  - Commands: `publish`, `today-export`, `live-publish`
  - All legacy runners removed or archived

### Python
- `run_today.py` — **canonical model entrypoint**
  - Responsible for:
    - Fetch
    - Rebuild today.csv
    - Model execution
    - Output generation
    - Tagging latest outputs

---

## Filesystem (Post-Cleanup)

### Runtime-critical (must exist)
atlas.ps1
run_today.py
requirements.txt
src/Atlas/
tools/
scripts/
data/


### Data semantics
- `data/input/`   — manual / external inputs
- `data/raw/`     — raw fetched API data
- `data/board/`   — intermediate working data
- `data/output/`  — model outputs + publish artifacts
- `data/gamelogs/`— historical stats

### Maintenance
- `tools/Clean-Atlas.ps1` — deterministic cleanup tool
  - Deletes generated junk
  - Quarantines noise
  - Safe to run repeatedly

---

## Stability & Safety

- BLAS/OpenMP thread caps enforced:
  - `OMP_NUM_THREADS=1`
  - `MKL_NUM_THREADS=1`
  - `OPENBLAS_NUM_THREADS=1`
  - `NUMEXPR_NUM_THREADS=1`
  - `BLIS_NUM_THREADS=1`
- Python runs with:
  - BelowNormal priority
  - Restricted CPU affinity
  - Optional timeout guard

Result: **no PC freezes**, stable long runs.

---

## Git

- Atlas is **not** currently a git repository
- AtlasDashboard **is** a git repository and publishes successfully
- This is intentional and acceptable

---

## Known Non-Issues

- No recursion
- No runaway processes
- No hidden dependencies
- No legacy runners in execution path

---

## Current Focus

Next phase is **consolidation and simplification**, not debugging:
- Reduce script surface area
- Clarify responsibility boundaries
- Remove remaining redundancy