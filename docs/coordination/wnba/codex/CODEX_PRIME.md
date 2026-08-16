# WNBA Codex Prime

Status: **NO ACTIVE EXECUTION DELEGATION**

This file is the narrow execution surface for Prime Delegation.

## Hard authority boundary

Before acting, Codex must read and obey the actual WNBA governing controls required by WNBA `AGENTS.md`.

While the WNBA Builder lane is active, `slip-builders` remains the sole workflow controller.

This document:

- does not create a second state machine;
- does not authorize Builder progression on its own;
- does not authorize Live/model/promotion changes;
- does not convert `CHAT_AGENDA.md` ideas into permission;
- must fail closed if it conflicts with WNBA authority.

## Current status

No new execution is authorized by this file yet.

The next Chat candidate is a cheap V2 learner-versus-override-gate decomposition audit using already-sealed OOS scores and already-open discovery settlement, with no refit and no validation/lockbox reads.

That remains `CANDIDATE_NEXT`, not executable, until the user/Chat publishes an explicit Codex delegation here.

## Required delegation fields

Any future active delegation must state:

- user authorization and decision being implemented;
- source repository/branch/starting SHA;
- governing active Builder row;
- exact purpose/question;
- exact allowed operations;
- exact prohibited operations;
- bound inputs/hashes;
- outcome visibility;
- fitting permission;
- model/Live mutation permission;
- validation/lockbox limits;
- stop conditions;
- required outputs;
- test/validator requirements;
- exact Git handling;
- final stop marker.
