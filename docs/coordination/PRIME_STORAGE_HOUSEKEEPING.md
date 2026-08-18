# Prime Storage Housekeeping Protocol

Status: **MANDATORY OPERATIONAL PRE-RUN DOCTRINE**

Purpose: prevent avoidable Builder/model/corpus interruptions caused by stale local storage while preserving scientific authority and protected evidence.

This document is operational coordination doctrine. It is not model, Builder, Live, statistical, validation, or promotion authority. Target-repository authority and active workflow controllers remain governing.

## Core rule

Before any expensive Builder, replay, corpus, model-training, or large evidence operation, Codex must resolve and read the installed `keep-it-tidy` skill and apply it as an operational housekeeping preflight **before** the final resource/storage gate.

If the `keep-it-tidy` skill cannot be resolved or read, fail closed and report that housekeeping could not be performed. Do not improvise a replacement destructive cleanup routine.

Housekeeping is not scientific evidence and does not consume outcome, validation, or lockbox authority.

## Automatic invocation

Prime work orders for expensive operations should bind this protocol and explicitly state that `keep-it-tidy` is automatically authorized for operational housekeeping.

The expected order is:

```text
resolve/read target-repo authority
-> resolve/read keep-it-tidy skill
-> classify protected/current/stale material
-> run safe housekeeping
-> measure free space/resources
-> run normal resource preflight
-> execute scientific operation only if its normal gate passes
```

A low-space resource preflight should not immediately create a multi-turn Builder interruption when safe stale material remains reclaimable under `keep-it-tidy`.

## Protected keep-set

Housekeeping must never delete, rewrite, move, compress in place, or invalidate any of the following merely to create headroom:

- the active target repository's tracked source/config/control files;
- the protected Git stash or any protected worktree state;
- current/frozen Builder evidence or artifacts referenced by active/frozen receipts, manifests, seals, configs, work orders, source bindings, or control state;
- protected validation or lockbox data;
- active or immediately required Live runs;
- immediate replay/corpus data required by the active or next authorized operation;
- authoritative source bindings and manifests;
- current model/Live authority packages;
- Git history;
- active task scratch/checkpoints that are required for restartability;
- any file whose authority/status is ambiguous.

When authority is ambiguous, preserve the material and report it rather than deleting it.

## Authorized stale/reclaimable classes

Subject to the actual `keep-it-tidy` skill contract, Codex is authorized to remove or offload stale non-authority material such as:

- completed/abandoned task-owned scratch no longer referenced by any current receipt or restart path;
- reproducible Python/uv/pip/application/installer/extension caches;
- temporary files and disposable generated intermediates;
- inactive Codex/VS Code/session logs;
- obsolete duplicate local copies that have verified authoritative/hash-bound copies elsewhere;
- stale operational logs and old non-authority run debris unrelated to current testing or the immediate Live/replay/corpus path;
- other material explicitly classified safe by `keep-it-tidy` and unreferenced by current authority.

Prefer hash-verified archive/offload before local deletion when the skill says the material should be retained historically. Purely reproducible caches/temp data need not be archived unless the skill requires it.

## Storage targets

Each scientific work order retains its own hard resource gate. Housekeeping must not weaken that gate.

For disk-bound work, Codex should try to leave a practical buffer above the hard gate when safe reclaimable material exists. The default operational target is:

`desired_free_space >= hard_required_start + 2 GiB`

unless a stricter target-repository rule applies.

Failure to reach the desired buffer is not itself a scientific failure. Execution may proceed if the work order's hard resource gate passes and all other authority checks pass.

If safe housekeeping cannot reach the hard gate, fail closed and report the remaining shortfall.

## Audit requirements

Housekeeping should record, at minimum:

- skill resolved/read successfully;
- pre-housekeeping free space;
- material classes acted on;
- bytes reclaimed/offloaded;
- post-housekeeping free space;
- confirmation that the protected keep-set was untouched;
- confirmation that no scientific/protected evidence was opened or consumed.

Do not make housekeeping artifacts statistical evidence.

## Git safety

`keep-it-tidy` housekeeping does not authorize broad Git cleanup commands.

Do not use `git clean`, `git reset --hard`, force push, broad staging, or protected-stash mutation to create space.

Tracked target-repo changes remain governed by the active workflow's exact-path authorization and staging rules.

## Builder interaction

When `slip-builders` owns an active Builder lane, housekeeping remains operationally subordinate to that lane. It may maintain storage/headroom but may not alter Builder science, controls, evidence, candidate surfaces, method contracts, or protected boundaries.

A housekeeping action alone does not advance a Builder row or create performance authority.

## Completion principle

The intended behavior is:

`keep local workspace healthy continuously -> expensive work starts with headroom -> storage preflight confirms rather than surprises`

not:

`run until C: is full -> stop Builder -> wait for manual cleanup -> publish another resume row`.
