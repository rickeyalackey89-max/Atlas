# Small Corpus Under-Relief Result

Date: 2026-03-25
Purpose: compare the current under-relief source-label candidate against a tight control corpus that removes only the `p_adj_under_relief` telemetry source-scale family.

## Corpus Design

Truth-safe bundle set used:

1. `atlas_bundle_20260315_102437.zip`
2. `atlas_bundle_20260316_181146.zip`
3. `atlas_bundle_20260317_060713.zip`
4. `atlas_bundle_20260318_173935.zip`

Control config:

1. [temp_experiments/small_corpus_under_relief_control_20260325/config.yaml](temp_experiments/small_corpus_under_relief_control_20260325/config.yaml)
2. uses [temp_experiments/small_corpus_under_relief_control_20260325/telemetry_calibration.no_under_relief_src.v2.json](temp_experiments/small_corpus_under_relief_control_20260325/telemetry_calibration.no_under_relief_src.v2.json)
3. differs from candidate only by removing the `p_adj_under_relief_cool` family

Candidate config:

1. [temp_experiments/small_corpus_under_relief_candidate_20260325/config.yaml](temp_experiments/small_corpus_under_relief_candidate_20260325/config.yaml)
2. uses the live calibration payload [data/model/telemetry_calibration.v2.json](data/model/telemetry_calibration.v2.json)

Corpus roots created:

1. `temp_experiments/small_corpus_under_relief_20260325/control`
2. `temp_experiments/small_corpus_under_relief_20260325/candidate`

## Overall Corpus Result

Settled rows were identical in both corpora:

1. runs read: `4`
2. settled rows: `15921`
3. mean hit: `0.4249104955718862`
4. mean p_adj: `0.31880797983431186`

Control overall:

1. mean p_cal: `0.39841283268263594`
2. brier p_cal: `0.23172702263034387`
3. logloss p_cal: `0.6550763554462493`

Candidate overall:

1. mean p_cal: `0.3891419263891771`
2. brier p_cal: `0.23139473140617578`
3. logloss p_cal: `0.6543474808154561`

Delta:

1. brier p_cal: `-0.00033229122416809`
2. logloss p_cal: `-0.000728874630793232`

Interpretation:

1. The current candidate is modestly better overall on the four-slate corpus.
2. The gain is real but small.

## Per-Run Result

### 2026-03-15 bundle

Control:

1. brier p_cal: `0.2423346017144931`
2. logloss p_cal: `0.6774279603321623`

Candidate:

1. brier p_cal: `0.24153684605873157`
2. logloss p_cal: `0.6756434367648035`

Result:

1. improved on both metrics

### 2026-03-16 bundle

Control:

1. brier p_cal: `0.22187348650592792`
2. logloss p_cal: `0.6345660907759028`

Candidate:

1. brier p_cal: `0.22163471402004`
2. logloss p_cal: `0.6340227293210987`

Result:

1. improved slightly on both metrics

### 2026-03-17 bundle

Control:

1. brier p_cal: `0.23610503837740413`
2. logloss p_cal: `0.6640749372718147`

Candidate:

1. brier p_cal: `0.23519120072369784`
2. logloss p_cal: `0.6622123090814616`

Result:

1. improved on both metrics

### 2026-03-18 bundle

Control:

1. brier p_cal: `0.2277090761383344`
2. logloss p_cal: `0.6466136275014668`

Candidate:

1. brier p_cal: `0.2280974398213331`
2. logloss p_cal: `0.6473910104362666`

Result:

1. regressed on both metrics

## Recommendation Stability

Across all four bundles:

1. all six recommendation files stayed `10 / 10` overlap between control and candidate
2. winprob recommendation file hit probabilities were unchanged
3. system recommendation files kept the same memberships but their reported hit probabilities increased under the candidate on all four bundles

Interpretation:

1. This remains a probability-surface change, not a selector-membership change.
2. The corpus improvement is therefore coming from better calibrated probabilities on the same settled legs, not from a better chosen slip set.

## Decision

This is not a clean promotion signal yet.

Why:

1. the candidate improves the corpus overall
2. three of four bundles improve
3. one bundle still regresses on both Brier and log loss
4. slip membership does not improve at all on this corpus

## Best Next Step

Investigate the 2026-03-18 regression specifically before treating this candidate as promotable.

Most likely target slices:

1. `p_cal_src = p_adj_under_relief`
2. role-context-on rows
3. stat-direction slices with high under-relief activation

## Whole-Corpus Slice Findings

The candidate should be judged by the full four-slate body, not by one replay alone.

### Stable positive signal

The most repeatable gain is the intended one:

1. `p_cal_src = p_adj_under_relief` improved materially across the corpus.
2. On `1702` under-relief rows:
	- control hit rate: `0.521152`
	- control mean p_cal: `0.578152`
	- candidate mean p_cal: `0.491429`
	- brier: `0.255470 -> 0.252361`
	- logloss: `0.704754 -> 0.697936`
3. The rest of the corpus (`p_cal_src = p_adj`) was unchanged.

Interpretation:

1. The new source-label family is helping the exact slice it was designed to cool.
2. The mean corpus gain is therefore not random drift; it is concentrated in the intended under-relief slice.

### Stable negative signal

The candidate gives some of that gain back in smaller slices with limited sample size.

Most notable cases:

1. low-games bucket `0to4` (`110` rows)
	- brier: `0.221347 -> 0.224258`
	- logloss: `0.632534 -> 0.638493`
2. `FG3M UNDER` (`43` rows)
	- brier: `0.239973 -> 0.246957`
	- logloss: `0.672816 -> 0.687001`

Interpretation:

1. The candidate is probably slightly too aggressive on some thinner or more fragile sub-slices.
2. Those slices are small, so they should not outweigh the whole-corpus mean by themselves.
3. They do matter because they explain why the candidate is not yet a clean promotion.

### Mean-versus-variance view

Per-run deltas:

1. mean delta Brier: `-0.0003905005280892687`
2. mean delta logloss: `-0.0008532825694290425`
3. std delta Brier: `0.0005970453204931803`
4. std delta logloss: `0.001243799215130274`

Interpretation:

1. The mean shift is better.
2. The run-to-run variance is not huge, but it is still large enough that a single bad slate can show up.
3. The correct next move is to soften the under-relief cooling slightly, not to abandon the path or overreact to one replay.

## Recommended Next Tuning Direction

Do not change unrelated logic.

The most defensible next candidate is:

1. keep the `p_adj_under_relief` source labeling
2. keep the current under-relief gating
3. reduce the telemetry source-scale severity from `0.85` to a milder value

Reason:

1. the whole-corpus mean says the direction is right
2. the win is already concentrated on the intended under-relief rows
3. the remaining issue looks like overshoot, not wrong-sign behavior

## Follow-Up Softening Result

Follow-up diagnostics were run on the same four-bundle corpus roots:

1. `temp_experiments/small_corpus_under_relief_20260325/control/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_014700`
2. `temp_experiments/small_corpus_under_relief_20260325/candidate/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_014701`
3. `temp_experiments/small_corpus_under_relief_20260325/soft90/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_014640`
4. `temp_experiments/small_corpus_under_relief_20260325/soft92/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_014644`

### Overall Result

Valid full-corpus comparison:

1. control: brier `0.23172702263034387`, logloss `0.6550763554462493`, mean p_cal `0.39841283268263594`
2. current `0.85`: brier `0.23139473140617578`, logloss `0.6543474808154561`, mean p_cal `0.3891419263891771`
3. `soft90`: brier `0.23132539268653182`, logloss `0.6542125034553467`, mean p_cal `0.39223222848699674`

Interpretation:

1. `soft90` is the best valid challenger on the full four-slate corpus.
2. `soft90` improves on the current `0.85` candidate by brier `-0.00006933871964395766` and logloss `-0.00013497736010947836`.
3. `soft90` also remains better than control by brier `-0.000401629943812043` and logloss `-0.0008638519909026643`.

### Per-Run View Versus Current `0.85`

`soft90 - current 0.85` deltas:

1. 2026-03-15 bundle: brier `+0.000045779749629657256`, logloss `+0.0001121235199462181`
2. 2026-03-16 bundle: brier `-0.00010247117621113901`, logloss `-0.0001997292746464216`
3. 2026-03-17 bundle: brier `+0.00012939024178563088`, logloss `+0.00026026245558299447`
4. 2026-03-18 bundle: brier `-0.00028424049538754114`, logloss `-0.000575901446837543`

Interpretation:

1. `soft90` gives back a small amount on 2026-03-15 and 2026-03-17.
2. `soft90` improves on 2026-03-16.
3. the meaningful improvement is on 2026-03-18, which is enough to make `soft90` the best full-corpus mean.

### Slice Repair Versus Current `0.85`

The previously thin, overshooting slices both moved in the right direction under `soft90`.

`0to4` games-used bucket:

1. current `0.85`: gap `-0.1068256129175349`, brier `0.2242579960317838`, logloss `0.6384930439668618`
2. `soft90`: gap `-0.1033435618455361`, brier `0.2230800760904177`, logloss `0.6360952357769374`

`FG3M UNDER`:

1. current `0.85`: gap `-0.076305173542398`, brier `0.246957320887427`, logloss `0.6870005468863053`
2. `soft90`: gap `-0.0533232445760756`, brier `0.2433586730745018`, logloss `0.6797488109343958`

Intended `p_adj_under_relief` slice:

1. current `0.85`: gap `-0.029722740957956`, brier `0.2523613771999037`, logloss `0.697936038859263`
2. `soft90`: gap `-0.0008151618161311`, brier `0.2517127627724938`, logloss `0.6966734216146668`

Interpretation:

1. `soft90` keeps the intended under-relief gain.
2. `soft90` also repairs the small overshooting slices that made `0.85` less defensible as a promotion.

### `soft92` Status

`soft92` is not a valid corpus comparison result.

Observed state:

1. diagnostic coverage was only `3` runs and `10925` settled rows
2. the `2026-03-18` run is missing from `temp_experiments/small_corpus_under_relief_20260325/soft92/runs`
3. the replay root `data/telemetry/replay_runs/small_corpus_soft92_atlas_bundle_20260318_173935/20260325_013952` exists but is empty

Interpretation:

1. `soft92` cannot be compared fairly against the other three variants.
2. it should not be used for promotion or rejection until the missing replay is materialized.

## Updated Recommendation

The most defensible next candidate is now:

1. keep the `p_adj_under_relief` source labeling
2. keep the current under-relief gating
3. use the milder telemetry source-scale severity represented by `soft90`

Reason:

1. `soft90` is the best valid full-corpus mean on the same four-slate set
2. it preserves the intended under-relief improvement
3. it reduces the two thin-slice regressions that were blocking a clean promotion at `0.85`
4. `soft92` remains unresolved because the fourth replay did not complete