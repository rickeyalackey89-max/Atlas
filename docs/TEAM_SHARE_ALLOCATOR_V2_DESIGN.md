# Team Share Allocator V2 Design

## Goal
Rebuild the team share allocator and share matrix internals so they better match the injury redistribution philosophy while keeping the downstream schema stable.

The allocator should model:
- star injuries causing meaningful redistribution of minutes, usage, and stat share
- role-player injuries often producing little redistribution on deep teams
- capped redistribution so the injured player is not fully replaced
- stronger shifts when the injured player is high-usage or high-minutes
- smaller shifts when the team is deep or the injured player is low leverage
- multi-out cases without letting redistribution explode

## Non-Goals
- Do not change the downstream share-matrix schema unless a field is clearly unused and safe to add
- Do not change the engine-side contract that reads `share_matrix.csv`
- Do not add a second allocator path that can diverge silently
- Do not tune the model before the allocator math is made coherent

## Current Contract To Preserve
The engine expects a prepared share matrix with these logical fields:
- `team_u`
- `stat_u`
- `out_canon`
- `ben_canon`
- `games`
- `weight`

The builder currently writes `share_matrix.csv`, and `new_probability.py` loads it as a cached dataframe.

That contract stays intact.

## V2 Architecture

### 1. Build a clean allocator core
Create a new internal allocator that produces a normalized redistribution plan from three inputs:
- injury severity of the outgoing player
- team depth / resilience
- beneficiary availability and role capacity

The core should output a structured allocation object with:
- outgoing player key
- beneficiary player keys
- stat family
- raw redistribution weights
- cap / attenuation factor
- support metadata

### 2. Make team depth explicit
Team depth should be a first-class input, not an emergent side effect.
Use team-level signals such as:
- rotation depth
- usage concentration
- minutes concentration
- historical response to missing players

Depth should reduce redistribution for teams that can absorb the absence.

### 3. Separate injury severity from beneficiary capacity
The current philosophy needs two distinct ideas:
- how much value leaves the injured player
- how much of that value can be absorbed by each teammate

For example:
- a star out should export a larger pool of value
- a bench out should export a smaller pool
- a high-capacity teammate can absorb more of that pool
- a low-capacity teammate can absorb less, even if present in the matrix

### 4. Add a redistribution cap
Never assume 100% of the injured player is redistributed.
Use a capped transfer model such as:
- base transfer fraction by role bucket
- depth attenuation by team
- role-cap attenuation by injured player class
- final normalization over eligible beneficiaries

This cap is the main protection against overfitting and unrealistic inflation.

### 5. Handle multiple outs as a combined state
Multiple injuries should not be treated as independent copies of the same event.
Instead:
- aggregate outs into a team outage state
- compute marginal contribution per out
- apply overlap correction when two outs compete for the same beneficiaries
- avoid double-counting the same redistribution channel

### 6. Rebuild share matrix after allocator
The share matrix should become a derived artifact from the allocator output, not the source of truth.
Suggested flow:
1. derive team outage state from gamelogs and injuries
2. run allocator core
3. emit normalized share-matrix rows
4. persist CSV contract for the engine

That means the share matrix is a compiled artifact from allocator logic, not the allocator itself.

## Proposed Build Flow

### Step A: Canonicalize inputs
- Normalize team, player, stat, and date keys
- Resolve player name keys once
- Collapse duplicate or noisy injury labels into canonical team-outage buckets

### Step B: Classify outgoing player
Assign each outgoing player into a severity class such as:
- star
- core rotation
- role
- bench

This classification should be based on usage, minutes, and stat burden.

### Step C: Compute team redistributable pool
Estimate the pool of minutes / usage / stat share that can actually move.
This should depend on:
- outgoing player class
- team depth
- team concentration
- number of outs already on the team

### Step D: Allocate to beneficiaries
Build beneficiary weights using:
- role capacity
- minutes capacity
- usage capacity
- historical share response
- cap on total absorbed share

### Step E: Emit share matrix rows
Write rows in the current downstream schema, including the current schema keys plus any safe metadata columns if needed.

### Step F: Validate against held-out injury cases
Check whether the allocator:
- increases surrounding-player weights when a star is out
- leaves deep-team role-player injuries mostly muted
- avoids double-counting when multiple players are out
- produces stable totals across similar slates

## Recommended Internal Modules

### `team_share_allocator_v2.py`
Responsibilities:
- classify outgoing players
- compute redistributable pools
- compute beneficiary capacity
- resolve multi-out interactions
- emit normalized allocation output

### `share_matrix_contract.py`
Responsibilities:
- define the required CSV schema
- validate weights, games, and duplicate-key integrity
- give the engine and builder a shared contract check

### `share_matrix_builder_v2.py`
Responsibilities:
- call the allocator
- convert allocations into CSV rows
- preserve the existing contract
- write diagnostics / summary stats

## Validation Rules
The new allocator should fail loudly if:
- totals do not normalize
- a beneficiary weight becomes negative
- team-level redistribution exceeds the configured cap
- required schema columns are missing
- multi-out overlap is double-counted beyond tolerance

## Suggested Initial Acceptance Criteria
- The engine still reads `share_matrix.csv` without code changes to the consumer path
- Same schema, same file name, same key columns
- Star-out cases show stronger redistribution than role-player cases
- Deep teams show less redistribution than shallow teams
- Multiple outs do not create runaway inflation
- Current replay corpus improves or at least does not regress materially on the role-sensitive slices

## Implementation Order
1. Freeze the current schema and add a validator
2. Build the v2 allocator core
3. Build the v2 matrix emitter
4. Swap the builder CLI to the new implementation behind the same output file
5. Compare replays on current and patchtest corpora
6. Tune only after the allocator shape is coherent

## First Cut Behavior
- Star injuries should map to higher transfer fractions than role injuries.
- Team depth should reduce the effective transfer fraction.
- Multiple outs should reduce, not multiply, the absorbed share.
- The CSV output should still look identical to the engine: same columns, same file path, same load behavior.

## Opinion
This is the right move if the current problem is structural rather than purely parameter tuning.
The philosophy you wrote is coherent, but the current implementation appears to mix severity, depth, and beneficiary capacity in ways that are too indirect.
A schema-preserving rebuild gives you a cleaner way to express the same idea without creating a new downstream debugging surface.
