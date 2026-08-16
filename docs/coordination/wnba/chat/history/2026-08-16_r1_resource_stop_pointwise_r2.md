# WNBA 3L — R1 Resource Stop and Pointwise R2 Decision

## R1 reviewed result

WNBA commit:

`6789f0a595bf3956f42146e8742005febd7cc080`

R1 correctly stopped at the 900-second resource boundary.

Accepted findings:

- strict `t < D` causal regeneration completed and sealed for `2026-06-20`, `2026-06-24`, and `2026-06-27`;
- temporal leakage detected: false;
- G3 can score the pointwise proposal even when relational nominees differ;
- pointwise state is shared between G2/G3 and A/B/D states are shared between G1/G3 without duplicate G3 fitting;
- the final `2026-08-13` relational parity probe did not complete because the pre-fit watchdog stopped the task at approximately 904.8 seconds;
- current measured full A/B/D regeneration topology projects to approximately 18,232 seconds (~5.1 hours);
- current measured G3 topology projects to approximately 18,365 seconds (~5.1 hours);
- full causal pointwise sequence projects to approximately 132.5 seconds (~2.2 minutes) for 29 fits.

Strategic interpretation:

`CAUSAL_MECHANISM_VALID_RELATIONAL_EXECUTION_TOO_EXPENSIVE_AS_CURRENTLY_IMPLEMENTED`

R1 is not a scientific rejection of relational witnesses. It is a runway rejection of spending ~5 hours before the cheap causal pointwise benchmark is known.

## User-authorized next step

The user explicitly authorized the complete causal pointwise historical-as-of benchmark.

Prime work order:

`docs/coordination/wnba/codex/archive/2026-08-16_3l_historical_asof_pointwise_r2.md`

Execution tier:

`R2_BOUNDED_PILOT`

Purpose:

Determine whether the stored grouped-date pointwise signal survives strict chronological reconstruction where each target D is fit only from settled `t < D` history.

Hard boundaries:

- pointwise only;
- fixed existing pointwise feature/method contract;
- `2026-06-17` cold-start Atlas control;
- expected 29 pointwise fits thereafter;
- no relational regeneration;
- no G1/G3;
- no gate or threshold tuning;
- final-date pointwise parity required;
- hard runtime budget 10 minutes;
- validation reads 0;
- lockbox reads 0;
- no Live/model mutation;
- no promotion authority;
- stop for user/Chat review after committed evidence.

If the causal pointwise signal does not survive, further G3 spend loses much of its rationale. If it survives, the next likely cheap step is a relational execution-cost audit before any full G1/G3 replay is considered.
