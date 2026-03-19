# Telemetry Calibration Schema V2

This document describes the experimental schema split for telemetry calibration.

## Why V2 Exists

The current calibration files work, but the tuning space has become too crowded:

- policy knobs live beside numeric calibration values
- role-context behavior is buried inside a single payload
- audit-only corrections are hard to keep separate from runtime-safe adjustments

Schema v2 separates those concerns.

The allocator that feeds `role_ctx` is still separate from the calibration payload.
In the v2 experiment template, that lives under an `allocator` block so the share-matrix
builder, blending weights, support floor, and guardrails can be tuned without mixing them
into the calibration JSON itself.

## Layout

A v2 calibration payload uses three parts:

- `policy`: source gating and output caps
- `base`: shared numeric defaults such as shrink and under-penalty
- `families`: named overlays split by role-context or other supported scopes

Example:

```json
{
  "version": 2,
  "generated_at": "2026-03-18T20:24:14Z",
  "policy": {
    "apply_only_p_cal_src_prefixes": ["p_adj"],
    "exclude_p_cal_src_prefixes": [],
    "cap": {"min": 0.01, "max": 0.99}
  },
  "base": {
    "k_shrink": 0.96,
    "standard_under_penalty": 0.98
  },
  "families": [
    {"name": "role_off", "role_ctx": "off", "mult": {...}},
    {"name": "role_on", "role_ctx": "on", "mult": {...}}
  ]
}
```

## Runtime Compatibility

The loader in [src/Atlas/runtime/telemetry_calibration.py](../src/Atlas/runtime/telemetry_calibration.py) accepts both:

- v1 flat payloads
- v2 family-based payloads

That keeps the live path stable while allowing experimentation in the new schema.

## Recommended Use

- Keep runtime-safe adjustments in the v2 payload.
- Keep slice-specific experimentation in audit-only outputs.
- Use [config.telemetry_schema_v2.yaml](../config.telemetry_schema_v2.yaml) as the experiment template when testing new family combinations.
- Tune `allocator.share_matrix`, `allocator.support`, and `allocator.role_guardrails` when the issue is redistribution shape rather than calibration.

## Notes

- Recent-third corrections are currently audit-only because the live engine does not expose a stable runtime equivalent for that slice.
- The main gain from v2 is not a new math transform. It is a cleaner separation between policy, base calibration, and family overlays.
