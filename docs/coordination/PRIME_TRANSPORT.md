# Prime Delegation Transport

Prime Delegation is stored in GitHub and mirrored locally for Codex execution.

## Remote record

Repository: `rickeyalackey89-max/Atlas`

Branch: `main`

Coordination root: `docs/coordination/`

Chat may read and update this remote record directly through GitHub.

## Local Codex mirror

Canonical local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation`

This is a dedicated sparse checkout of the remote Atlas repository. It is **not** a model repository and it does not own Builder, Live, model, corpus, or statistical authority.

Important: `C:\Users\13142\Atlas` itself is a workspace root, not a usable Git worktree for Prime Delegation. Its empty `.git` directory must not be repaired, initialized, populated, or used as the remote Atlas worktree merely to support Prime.

## One-time bootstrap

Only when `C:\Users\13142\Atlas\PrimeDelegation` does not already exist as a valid Git worktree:

```powershell
$prime = 'C:\Users\13142\Atlas\PrimeDelegation'
if (Test-Path $prime) {
    throw "PRIME_BOOTSTRAP_TARGET_ALREADY_EXISTS: $prime"
}

git clone --filter=blob:none --sparse https://github.com/rickeyalackey89-max/Atlas.git $prime
git -C $prime sparse-checkout set docs/coordination
git -C $prime checkout main
git -C $prime status --short
git -C $prime rev-parse HEAD
```

If the target already exists, do not delete, overwrite, reset, or repurpose it. Inspect and reconcile first.

## Routine sync before Codex execution

Before reading `CODEX_PRIME.md` for an execution delegation:

```powershell
$prime = 'C:\Users\13142\Atlas\PrimeDelegation'

git -C $prime status --short
git -C $prime branch --show-current
git -C $prime fetch origin main
git -C $prime merge --ff-only origin/main
git -C $prime rev-parse HEAD
git -C $prime rev-parse origin/main
```

Require:

- valid Git worktree;
- branch `main`;
- clean worktree before sync;
- fast-forward-only update;
- local HEAD equals `origin/main` after sync.

Never use `git reset --hard`, force updates, broad cleanup, or stash to make Prime sync pass.

## Execution flow

`Chat decision -> GitHub Prime commit -> local Prime sparse sync -> CODEX_PRIME read -> target sport controls reconciled -> Codex execution`

The local Prime mirror is transport/context only. The target sport repository remains authoritative for all execution and evidence.
