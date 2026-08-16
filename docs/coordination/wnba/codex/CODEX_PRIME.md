# WNBA Codex Prime

Status: **NO ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Prime transport prerequisite

Codex must read this file from the dedicated local Prime mirror:

`C:\Users\13142\Atlas\PrimeDelegation\docs\coordination\wnba\codex\CODEX_PRIME.md`

Before any future execution, the mirror must be a valid clean Git worktree on branch `main` and must be fast-forwarded to current `origin/main` according to `docs/coordination/PRIME_TRANSPORT.md`.

Do **not** attempt to use or repair `C:\Users\13142\Atlas\.git` for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey the actual WNBA governing controls required by WNBA `AGENTS.md`.

While the WNBA Builder lane is active, `slip-builders` remains the sole workflow controller.

This document:

- does not create a second state machine;
- does not authorize Builder progression on its own;
- does not authorize Live/model/promotion changes;
- does not convert `CHAT_AGENDA.md` ideas into permission;
- must fail closed if it conflicts with WNBA authority.

## Standing result handoff protocol

For every Prime-authorized task that creates or changes repository evidence/code and passes its required validators/tests:

1. stage only exact authorized paths;
2. commit the authorized target-repository changes;
3. push the governing target branch;
4. verify local HEAD == tracking ref == direct remote ref;
5. leave the worktree clean;
6. report the final commit SHA and stop marker.

If the task produces no permanent repository changes, do not invent a commit.

This protocol exists so Chat can review the committed remote evidence directly from GitHub. The preferred user handoff is the final SHA plus a short request to review it.

## Last completed delegation

Task:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_v2_learner_gate_decomposition.md`

WNBA result commit:

`bc71d9442580fe69812d6dbad87545006aabdd4e`

Result reviewed by Chat:

- primary diagnosis: `V2_GATE_DOMINATED_USEFUL_CHALLENGER_SIGNAL`
- no refit / no outer-fold rerun
- validation reads 0
- lockbox reads 0
- no Live/model mutation
- WNBA stop: `BLOCKED_USER_REVIEW_WNBA_3L_V2_LEARNER_GATE_DECOMPOSITION`

## Current status

No new execution is authorized.

Chat strategy is evaluating how to test a predeclared cross-arm agreement gate versus selective pointwise-logistic gating without converting post-settlement discovery findings into promotion evidence.

Do not begin another 3L learner, gate experiment, 4L task, FromDeep task, validation read, or lockbox read until a new user-authorized Prime delegation is published here.
