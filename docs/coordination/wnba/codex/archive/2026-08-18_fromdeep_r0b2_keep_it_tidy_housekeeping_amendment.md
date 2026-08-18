# WNBA FromDeep R0B2 — Keep-It-Tidy Housekeeping Amendment

Status: **ACTIVE SCOPE AMENDMENT TO R0B2 BEFORE EXECUTION**

User authorization in Chat on 2026-08-18:

> “You need to make sure you give codex the go ahead to remove all stale data unrelated to our testing or immediate live/replay/corpus data by using the keep-it-tidy skill so these long breaks do not happen anymore. Those skills should be used automatically or in the control documents.”

## Purpose

Prevent repeated storage-only interruptions by authorizing operational housekeeping before R0B2's final storage measurement while preserving the exact R0B scientific method and all protected/current authority.

This amendment supersedes only the R0B2 work order's prior `no cleanup operation` / `do not perform cleanup in this delegation` restriction. Every scientific and protected-evidence boundary remains unchanged.

## Required housekeeping authority

Before the final R0B2 storage preflight, Codex must:

1. Read `docs/coordination/PRIME_STORAGE_HOUSEKEEPING.md` from the synced Prime mirror.
2. Resolve and read the Codex-installed `keep-it-tidy` skill.
3. If `keep-it-tidy` cannot be resolved/read, fail closed and report that the authorized housekeeping mechanism is unavailable; do not invent a destructive substitute.
4. Use `keep-it-tidy` to classify and remove/offload stale **non-authority** material unrelated to current testing and the immediate Live/replay/corpus path.
5. Record pre/post free C-drive space and bytes reclaimed/offloaded.
6. After housekeeping, freshly measure C: and apply the unchanged R0B hard start gate of `>= 7.0 GiB`.

Housekeeping should aim for a practical buffer of at least `hard gate + 2 GiB` when safe reclaimable material exists, but failure to reach that preferred buffer does not block R0B if the hard 7.0 GiB gate passes.

If the hard gate still cannot be reached after `keep-it-tidy` exhausts safe stale candidates, fail closed before any retained-card/member read.

## R0B2 protected keep-set

Do not delete, move, rewrite, compress in place, or invalidate:

- any current/frozen WNBA Builder evidence referenced by receipts, manifests, seals, configs, source bindings, or control state;
- the protected stash;
- tracked WNBA source/config/control files;
- current model or Live authority packages;
- active or immediately required Live runs;
- immediate replay/corpus data required for current Builder/R0B work;
- the 38 R0A2-bound retained Builder Cards or their source manifests/bindings;
- R0/R0A/R0A1/R0A2/R0A3 evidence;
- the two completed R0B/R0B1 fail-closed commits/receipts;
- protected validation/lockbox data;
- current task scratch/checkpoints needed for restartability;
- Git history;
- any ambiguous artifact whose authority cannot be proven stale.

## Authorized reclaimable classes

Subject to the actual `keep-it-tidy` skill contract, the user authorizes cleanup/offload of stale non-authority material such as:

- inactive historical Codex/VS Code/session logs;
- completed or abandoned task-owned scratch no longer referenced by current authority or restart paths;
- reproducible Python/uv/pip/application/installer/extension caches;
- disposable temporary files and generated intermediates;
- obsolete duplicate local copies with verified authoritative/hash-bound copies elsewhere;
- stale operational logs and run debris unrelated to current testing or the immediate Live/replay/corpus path;
- other material the skill proves stale, unreferenced, and safe.

Prefer hash-verified archive/offload before deletion where historical retention is appropriate. Reproducible cache/temp data may be removed directly when permitted by the skill.

## Scientific method unchanged

After housekeeping and a passing storage gate, execute the exact same R0B scientific contract in `2026-08-18_fromdeep_r0b2_storage_recovered_resume.md`.

Housekeeping may not alter:

- source population;
- Demon-OVER eligibility;
- parser semantics;
- source identities;
- market namespace rules;
- feature topology;
- pretruth sealing semantics;
- core-family depletion semantics;
- outcome/protected evidence boundaries.

## Protected reads

During housekeeping and R0B2 pretruth execution:

- outcome reads = `0`
- truth reads = `0`
- settlement reads = `0`
- validation reads = `0`
- lockbox reads = `0`

## Git safety

This amendment does not authorize `git clean`, `git reset --hard`, force push, broad staging, or protected-stash mutation.

Tracked WNBA changes remain governed by the active `slip-builders` exact-path authorization rules.

## Required final stop

R0B2's required final stop remains unchanged:

`BLOCKED_USER_REVIEW_WNBA_FROMDEEP_R0B_UNIVERSE_PRETRUTH_SEAL`

No settlement join, signal research, or follow-on scientific experiment is authorized.
