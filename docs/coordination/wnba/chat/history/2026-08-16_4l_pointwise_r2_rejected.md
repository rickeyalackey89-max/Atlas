# WNBA 4L pointwise R2 review — 2026-08-16

Reviewed WNBA commit:

`b4d85ec3c6d28038831759be502019596c2eb187`

Disposition:

`POINTWISE_4L_PRACTICAL_BAR_NOT_MET`.

Results on the 15 available dates:

- canonical Atlas control: 7 WIN / 7 LOSS / 1 NONBINARY;
- strict causal pointwise: 5 WIN / 9 LOSS / 1 NONBINARY;
- beneficial substitutions: 1;
- harmful substitutions: 3;
- net win change: -2;
- repaired ranking failure: 2026-08-06;
- broken control wins: 2026-06-19, 2026-07-02, 2026-07-06;
- 2026-06-17 and 2026-07-22 ranking failures remained unrepaired;
- four supply-impossible dates remained losses;
- 15 mandatory abstentions remained outside the denominator.

Interpretation:

The fixed 25-feature pointwise architecture is rejected as a wholesale 4L reranker. The failure does not reject 4L. The dominant failure mode is over-aggressive displacement of strong Atlas incumbents, including severe early-history logistic overconfidence.

A strict learned method cannot repair the 2026-06-17 cold-start loss, so the effective learned-method ceiling on the fixed surface is 9-5-1. Hitting the 60% target requires preserving all seven control wins while repairing both 2026-07-22 and 2026-08-06.

Candidate next architecture, not authorized:

`ATLAS_INCUMBENT_PRIOR_ONLY_CONTEXT_CONSENSUS`

- canonical Atlas control is default;
- regenerate the existing fixed linear and interaction context learners with strict settled `t<D` history;
- override only when both learners nominate the exact same challenger;
- no pointwise participation;
- no margin threshold or outcome-fitted gate;
- seal action before target truth.

Protected evaluation remains untouched: validation reads 0, lockbox reads 0.

FromDeep agreed architecture remains unchanged and execution remains unauthorized until 4L is resolved.
