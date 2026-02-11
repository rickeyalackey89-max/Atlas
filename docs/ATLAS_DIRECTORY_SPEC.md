# Atlas Directory Spec

## Runtime boundary (must stay small)

### Entrypoint
- `run_today.py` is the only runtime entrypoint.

### Runtime tools
- `tools/` is runtime-only.
- Anything in `tools/` must be directly invoked by `run_today.py`, OR be explicitly allowlisted (rare).
- Tools should be thin wrappers / CLIs only; real logic lives in `src/Atlas/`.

### Core logic
- `src/Atlas/` contains all importable logic, business rules, data processing, orchestration modules.

## Non-runtime boundary (dev + experiments)

- `scripts/dev/` contains experiments, one-offs, debug scripts.
- `scripts/dev/tools_quarantine/` is the holding area for scripts removed from runtime.
- `.atlas_audit/` is generated output only (reports).

## Invariants (enforced)
- `pwsh -File tools/Wiring-Audit.ps1 -IncludeToolsInventory -FailOnMissingEntrypoints -FailOnUnwiredTools` must pass.