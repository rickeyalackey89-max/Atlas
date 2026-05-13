# Late Injury Handling

> **Last updated:** 2026-05-12
> **Status:** Active operating rule for NBA live runs.

---

## Purpose

Late injury news creates two different risks that must not be treated as the same thing:

- **Direct-player risk:** the prop player's own availability is uncertain.
- **Beneficiary uncertainty:** a teammate may be out, which changes the prop player's role, minutes, or usage.

Atlas must separate these risks so it does not either:

- recommend a prop on a player who may not play, or
- wipe out valid beneficiary legs when a teammate's status is uncertain.

---

## Current Decision

### Direct-Player Risk

If the prop player is listed as `OUT` or `DOUBTFUL`:

- The leg must be removed by the IAEL hard filter.
- It must not reach System, Windfall, DemonHunter, Marketed, dashboard, or Discord outputs.

If the prop player is listed as `QUESTIONABLE`:

- The leg is tagged with `is_questionable=1` and `q_out_frac > 0`.
- Premium slip builders exclude it by default:
  - `slip_build.exclude_questionable: true`
  - `marketed_slips.exclude_questionable: true`
  - `exclude_q_out_frac_gt: 0.0`
- This is a risk-control decision, not a probability-calibration claim.

### Beneficiary Uncertainty

If a teammate is `QUESTIONABLE` and the prop player is a possible beneficiary:

- The leg is tagged with `is_questionable=1` and `q_out_frac > 0`.
- The leg may carry role context from `share_matrix.csv` / `role_ctx_outs`.
- Normal multi-game slates exclude this exposure from premium slips under the same `exclude_questionable` rules.
- Single-game slates may keep beneficiary exposure when:
  - `single_game_mode.soft_injury_exposure_not_hard_exclude: true`
  - the row has non-empty `role_ctx_outs`
  - the row passes normal slip quality and single-game script rules

This exists because a one-game slate can otherwise lose an entire team of viable beneficiary props.

---

## Selection Penalties

Injury uncertainty is selection-only unless explicitly documented otherwise.

Current behavior:

- `iael_soft_risk.py` writes `is_questionable` and `q_out_frac`.
- `minute_risk_guard.py` applies `injury_uncertainty_penalty` to selection surfaces.
- `p_cal`, `p_catboost`, and published probability columns are not rewritten by the minute-risk guard.
- Raw slate and CAT defensive guards may use slate-level `q_out_frac` as a trigger, but they write manifests when active.

---

## Required Operator Workflow

For late news inside roughly 60 minutes before tip:

1. Refresh IAEL.
2. Confirm `status_latest.json` and `injury_invalidations_latest.json` are current.
3. Rerun Atlas if a material player changed status.
4. Check the run terminal for:
   - `[IAEL][SOFT]`
   - `[IAEL] Removed ...`
   - `[RAW_SLATE_GUARD]`
   - `[CATBOOST_DEFENSE]`
   - `[POST_RUN_AUDIT]`
5. Inspect the run folder:
   - `scored_legs_deduped.csv`
   - `single_game_mode_manifest.json`
   - `catboost_scale_policy_manifest.json`
   - `raw_slate_fragility_guard_manifest.json`
   - `hard_pipeline_audit.json`

---

## Guardrails

- Do not hard-drop beneficiary legs only because a teammate is questionable on a one-game slate.
- Do not keep direct-player questionable legs in premium slips unless the operator intentionally overrides the policy.
- Do not treat beneficiary role boosts as guaranteed production. They are uncertain until the teammate is officially out.
- Any future change that applies a probability rewrite from late injury state must be replay-audited before promotion.

---

## Code References

| Area | File |
|---|---|
| Soft injury tagging | `src/Atlas/core/iael_soft_risk.py` |
| Hard OUT/DOUBTFUL filter | `src/Atlas/core/iael_filter.py` |
| Selection injury penalty | `src/Atlas/core/minute_risk_guard.py` |
| System/Windfall filtering | `src/Atlas/core/slip_builders.py` |
| Marketed filtering | `src/Atlas/core/marketed_slip_builder.py` |
| Single-game beneficiary exception | `src/Atlas/core/single_game_script.py` |
| Post-run hard audit | `scripts/audits/hard_pipeline_audit.py` |
