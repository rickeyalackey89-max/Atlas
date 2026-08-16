# WNBA Prime Delegation

This directory preserves WNBA strategic continuity without creating a second Builder controller.

## Authority boundary

The WNBA repository remains authoritative for:

- `AGENTS.md`
- `docs/model_development/ACTIVE_BUILDER_LANE.json`
- `slip-builders`
- builder goal/work order/state/evidence/process controls
- model champion pointers
- Live runtime artifacts
- corpus and label seals
- protected validation/lockbox state
- Git branch/commit authority

Prime Delegation records context and user/Chat decisions only.

## Chat read order

When recovering or continuing WNBA strategy:

1. `chat/CHAT_HANDOFF.md`
2. `chat/CHAT_PRIME.md`
3. `chat/state/CURRENT_STATE.json`
4. `chat/CHAT_AGENDA.md`
5. `chat/CHAT_DECISIONS.md`
6. newest relevant file under `chat/history/`
7. verify the current Atlas-WNBA repository authority before giving operational advice

## Codex read order

Codex should read `codex/CODEX_PRIME.md` only after reading the actual WNBA governing controls required by WNBA `AGENTS.md`.

`CODEX_PRIME.md` may delegate one authorized task, but it cannot authorize progression beyond `slip-builders`, change Live/model authority, or convert Chat theory into execution permission.

## Update ownership

- Chat/user decisions update Chat coordination files.
- Codex should not edit Chat strategy files unless the user explicitly delegates that administrative task.
- Codex evidence belongs in the appropriate model repository.
- Chat reviews committed evidence, then updates Prime Delegation.
