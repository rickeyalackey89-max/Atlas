# Atlas Prime Delegation

Prime Delegation is the Atlas human–Chat–Codex coordination layer.

Its purpose is to preserve strategic continuity while keeping execution authority narrow and explicit.

## Roles

- **Chat** owns theory, strategy, interpretation, research direction, durable agendas, and continuity across conversation threads.
- **Codex** owns implementation and execution of an explicitly authorized delegation.
- **Sport/model repositories** retain operational, statistical, runtime, Builder, promotion, and Live authority.
- **Prime Delegation never supersedes repository authority.**

## Hard boundary

Prime Delegation is not a workflow controller, model pointer, Builder state machine, promotion mechanism, or statistical authority.

If a Prime Delegation document conflicts with a sport repository's governing controls, the sport repository wins and execution must stop for reconciliation.

## Structure

Each sport may have a namespace under `docs/coordination/<sport>/` with separate Chat and Codex surfaces.

- `chat/` contains strategic memory and continuity.
- `codex/` contains only execution-ready delegations.

Never treat brainstorming or a parked Chat agenda item as Codex authorization.

## Transport model

The GitHub repository `rickeyalackey89-max/Atlas` on branch `main` is the durable remote record for Prime Delegation.

Codex does **not** read Prime from `C:\Users\13142\Atlas` directly. That directory is a workspace root and is not a valid Prime Git worktree.

Codex uses the dedicated sparse local mirror:

`C:\Users\13142\Atlas\PrimeDelegation`

Before an execution delegation, Codex must safely fast-forward that mirror to `origin/main`, then read the current `CODEX_PRIME.md`.

See `PRIME_TRANSPORT.md` for bootstrap and sync rules.
