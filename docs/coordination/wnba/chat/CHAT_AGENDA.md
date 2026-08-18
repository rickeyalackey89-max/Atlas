# WNBA Chat Agenda

This file preserves strategic topics that should not disappear when attention shifts.

Statuses: `ACTIVE`, `NEXT_AUTHORIZED`, `CANDIDATE_NEXT`, `LATER`, `PARKED`, `REVISIT_ON_TRIGGER`, `REJECTED`, `COMPLETE`.

`CANDIDATE_NEXT` is strategy only. It is not Codex authorization.

| ID | Topic | Status | Revisit trigger | Why retained |
|---|---|---|---|---|
| WNBA-3L-003 | V2 learner-vs-gate decomposition audit | COMPLETE | Completed at `bc71d9442580fe69812d6dbad87545006aabdd4e` | Gate domination diagnosed; relational work parked unless it earns incremental value over frozen causal pointwise |
| WNBA-3L-009 | Historical as-of gate R0 audit | COMPLETE | Completed at `f2e40be6d1beff5db0e6ed1dc178a68d21f9b512` | Established strict `t<D` legality and regeneration requirements |
| WNBA-3L-011 | Historical as-of gate R1 canary | COMPLETE | Completed at `6789f0a595bf3956f42146e8742005febd7cc080` | Causal machinery passed; relational topology projected ~5.1h |
| WNBA-3L-012 | Full causal pointwise benchmark | COMPLETE | Completed at `5eb96d83996e3f65c2ce021a5a3897b43f63da04` | 24-6-0 strict historical-as-of, 29 fits in ~10.1s |
| WNBA-3L-015 | Pointwise freeze-readiness R0 | COMPLETE | Completed at `64ac175dc1a2ec75f39fa5f9f91af4caed711fc2` | `POINTWISE_3L_RESEARCH_FREEZE_READY` |
| WNBA-3L-016 | Execute causal pointwise research/depletion freeze | COMPLETE | Completed at `2b1fca797eebefdb0da190099681460f22036eb1` | 3L frozen for research/depletion only |
| WNBA-3L-017 | Post-2L fresh 3L frontier completeness risk | REVISIT_ON_TRIGGER | Protected validation materially fails with core-family symptoms, or user explicitly reopens before then | Existing 3L evidence filtered a materialized base3 surface after frozen 2L depletion rather than freshly reconstructing the full legal 3L frontier; retain as known rollback risk, not a FromDeep blocker |
| WNBA-4L-003 | Post-pointwise 4L structural/forensic R0 | COMPLETE | Completed at `d6cf1a561e660596cb28d1e2f557290b02b3d4d5` | Old 15-date surface later proven incomplete |
| WNBA-4L-004 | Strict historical-as-of pointwise logistic R1 | COMPLETE | Completed at `fbd986f967c4fb123349ce849bf0f9333ab15d60` | Causal runway passed only on old incomplete surface |
| WNBA-4L-006 | Strict historical-as-of pointwise performance review | COMPLETE | Completed at `b4d85ec3c6d28038831759be502019596c2eb187` | Wholesale pointwise reranker rejected |
| WNBA-4L-008 | Residual leg-supply + candidate-coverage R0 | COMPLETE | Completed at `978cca95d3701737232dc8e507e9a6ba7f04c301` | 23/23 eligible slates had legal 4L witness |
| WNBA-4L-009 | Post-depletion stateful 4L generator canary | COMPLETE | Completed at `1e9930253ca3113842a687e188210321424c2d8a`; rehabilitated by R1A | Canonical stateful generator actionability proven |
| WNBA-4L-012 | Stateful-generator parity adjudication repair R1A | COMPLETE | Completed at `1f71ec936e7b23a7f537336056eaf4ae4209e9c7` | 0 raw/context/scorer mismatches on common identities |
| WNBA-4L-010 | Uniform 23-date stateful 4L candidate surface | COMPLETE | Completed at `fd0df85a70559d830cd2ae5e76a711453a9f4dca` | 23 dates × 96 = 2,208 pretruth-sealed candidates |
| WNBA-OPS-002 | Scheduled-wrapper eval catch-up 2026-08-13 through 2026-08-16 | COMPLETE | Completed | Separated core eval recovery from consumer-performance maintenance |
| WNBA-OPS-003 | Complete Aug13/Aug16 evals from existing scored Live runs | COMPLETE | Completed | All four dates Aug13-16 have complete core evals |
| WNBA-OPS-004 | Aug14/Aug15 consumer-performance hard alerts | LATER | User chooses to repair dashboard/maintenance provenance | Separate maintenance issue; not blocking FromDeep |
| WNBA-4L-011 | Uniform 23-date Atlas control forensic | COMPLETE | Completed at `2d2b4f4db497ce6626d7ae30e6b0eeabc394863f` | Atlas = 14-8-1 / 63.64% binary; winner available 23/23; all 8 losses ranking failures |
| WNBA-GOV-001 | Builder sealed-forensic workflow efficiency amendment | COMPLETE | Implementation `2d2f78e...`; cleanup `1bdebebf...` | One-row forensic lifecycle and preamble dedup active |
| WNBA-GOV-002 | Cross-sport linear Builder SOP | LATER | WNBA FromDeep is frozen and protected validation/any rollback lessons are complete | Convert WNBA lessons into sport-agnostic family-by-family SOP: fresh downstream frontier after every frozen family, outcome-blind supply audit, pretruth seal, method research, freeze, exact selected-leg depletion, repeat, protected validation, earliest-causal rollback |
| WNBA-4L-013 | Atlas incumbent vs first-winning-alternative forensic | COMPLETE | Completed at `cd645ed1fdfe857ec2b84f21a9653e6c2977de2a` | Recurring miss structure exists but no simple absolute-metric winner rule |
| WNBA-4L-005 | Prior-only context regeneration | PARKED | Only revisit if a future protected result explicitly demonstrates need | Old context evidence remains historical only; current challenger test did not add value |
| WNBA-4L-007 | Atlas-incumbent context-consensus challenger | REJECTED | Reopen only by explicit user decision | R1 produced one exact consensus override; R2 showed WIN→WIN and net-neutral, so added method complexity earned no incremental value |
| WNBA-4L-014 | Precision-first challenger R1 selection seal | COMPLETE | Completed at `c9b8ce32fc2557475d3d2f75af9e4feab3c7fe7b` | 22 KEEP_ATLAS, 1 CONSENSUS_OVERRIDE; sole override Aug07 rank16; all 23 selections sealed pretruth |
| WNBA-4L-015 | Precision-first challenger R2 performance grading | COMPLETE | Completed at `61f875e131058627e4adaf6697c54f09aa2a0539` | R1 = 14-8-1, identical to Atlas; sole Aug07 transition WIN→WIN; effect NEUTRAL; challenger rejected as non-incremental |
| WNBA-4L-016 | Freeze canonical Atlas 4L research/depletion method | COMPLETE | Completed at `24c5e29c965f5e808d84470c16146bb18a0b0148` | `WNBA_4L_CANONICAL_ATLAS_RANK1_RESEARCH_DEPLETION_V1`; canonical stateful rank-1 frozen at 14-8-1 development evidence; no Live/promotion authority |
| WNBA-4L-002 | Current post-pointwise 4L research | COMPLETE | Reopen only by explicit user decision or validation-triggered rollback | 4L scientifically closed for current lineage; if 3L is later rebuilt after a validation-triggered rollback, 4L is a true downstream derivative and must be re-adjudicated |
| WNBA-FD-001 | Current-stack FromDeep research | ACTIVE | Complete active R0B1 storage-recovered resume, then review the pretruth seal | Independent full-universe Demon-OVER specialist; core family depletion does not remove FromDeep legs |
| WNBA-FD-002 | FromDeep scored-leg signal atlas architecture | ACTIVE | Governs current FromDeep runway | Market-owned GREEN/RED/GRAY signal atlas; namespace includes usable full-row markets plus zero-support canonical identities proven on formally provenance-excluded dates; probability secondary; honest abstention; strict historical-as-of development |
| WNBA-FD-003 | FromDeep discovery-only runway | ACTIVE | Execute active R0B1, then user/Chat gate the first settlement/win-loss forensic | Planned sequence: provenance + parser actionability -> usable Demon-OVER census + namespace/pretruth seal -> win/loss forensic -> market signal atlas -> procedure -> historical-as-of evaluation -> freeze |
| WNBA-FD-004 | Full Demon-OVER scored-leg universe R0 preflight | COMPLETE | Completed at `c5d3886363d8cce9afceeb2cd5e94a43af6ab3fb` | Correct fail-closed R0: 38/39 physical full-row sources, missing Aug13 exact source, ~1.863 GiB existing capsules, four factual legacy-unlisted markets, zero outcomes/protected reads, no full projection |
| WNBA-FD-005 | FromDeep R0A exact-source / namespace / resource canary | COMPLETE | Completed at `9d752a99700c5311fa71f325883e162829b0381a` | Exact Aug13 bytes not recovered after broad archive search; no semantic regeneration; four labels proven distinct canonical markets, zero aliases; canary correctly not run with incomplete registry |
| WNBA-FD-006 | FromDeep provenance-unavailable exclusion + 3-capsule canary | COMPLETE | Completed at `8e3f9d9e9d18fc814c30e232fc3d07411143deb9` | Aug13 exclusion accepted; smallest full-chain capsule exceeded 300s; faithful extraction-path failure; no outcomes |
| WNBA-FD-008 | Retained Builder-card binding audit + one-source canary | COMPLETE | Completed at `433bd153c11463493a7bd1b0e50687d356bdf345` | 38/38 valid direct bindings; 605.9MB total; retained-card character scanner remained too slow |
| WNBA-FD-009 | Native retained-card parser exact-parity canary | COMPLETE | Completed at `e099482bfb40559c01c0895419e6b1be142fbc7f` | Native parser reproduced exact sealed R0A2 output in ~0.73s with exact repeat parity; infrastructure runway complete |
| WNBA-FD-007 | Usable factual Demon-OVER universe R0B | ACTIVE | Initial attempt stopped at storage preflight `485c3a0f...`; active R0B1 resumes unchanged science after user restored headroom | Project 38 physically sealed retained Builder Cards, derive supported canonical owner union plus zero-support known owners, physically pretruth-seal universe and feature matrices, then stop before outcomes |
| WNBA-FD-010 | R0B1 storage-recovered resume | NEXT_AUTHORIZED | Active Prime work order executes from WNBA `485c3a0f...` and returns final SHA | User reports 7.30 GiB free after non-scientific cleanup; Codex must freshly measure >=7.0 GiB, preserve 6 GiB reserve, then run exact unchanged R0B science; no additional cleanup or outcomes |
| WNBA-VAL-001 | Protected frozen-stack validation | LATER | FromDeep method frozen | Validate completed current-lineage stack first; public/live slips are never validation. Material failure triggers root-cause and earliest-causal rollback |
| WNBA-LOCK-001 | Final lockbox confirmation | LATER | Frozen-stack validation passes with no subsequent method changes | Open lockbox once only after validation |
| WNBA-VAL-002 | New unevaluated-date eligibility census | REVISIT_ON_TRIGGER | Before protected validation begins | Verify pregame seal and non-consumption |
| WNBA-3L-013 | Relational execution-cost audit | PARKED | Frozen pointwise later demonstrates need | ~5.1h topology; incremental value must be justified |
| WNBA-COMBO-001 | Combo-prop probability/math adjustments review | LATER | Core Builder work stabilizes or model-quality review opens | Preserve model-quality agenda |
| WNBA-OPS-001 | Passive long-run observability | LATER | Before next multi-hour learner | Required for expensive work |
| PRIME-001 | Prime Delegation adoption and maintenance | ACTIVE | Ongoing | Keep Chat strategy and Codex execution separate with durable audit trail |
