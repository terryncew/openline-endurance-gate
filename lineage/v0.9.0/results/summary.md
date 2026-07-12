# OpenLine Endurance Gate — Powered Sequence Run

**Claim label:** `POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_AND_COLLISION_SPACING`
**Theory status:** `MIXED_SYNTHETIC_RESULT`
**Pre-registered gates:** 8/10 passed
**Primary observations:** 8320
**Held-out seeds:** 20

## Primary load-order witness

- Paired differences: 80
- Median low→high minus high→low: 1.500 cycles
- 95% bootstrap interval: [0.0, 3.0]
- Exact sign-flip p: 2.44366e-05
- Classification: `INCONCLUSIVE_EFFECT_INTERVAL`

## Other discriminating witnesses

- Matched amplitude low-high median: 2.000 cycles; p=8.88178e-16
- Receipt ancestry median gain: 3.000 cycles; p=2.69916e-12
- Damage log-loss gain over current CD: 0.0051720029
- Damage log-loss gain over cycle + operational baseline: 0.0000000000

## Gate results

- `endurance/amplitude_endurance_gradient`: **PASS**
- `endurance/damage_adds_heldout_prediction`: **PASS**
- `endurance/fresh_subcritical_calibration`: **PASS**
- `endurance/load_order_noncommutativity`: **FAIL**
- `endurance/receipt_handoff_advantage`: **PASS**
- `tip_capture/first_contact_frontier_concentration`: **PASS**
- `tip_capture/geometry_adds_heldout_prediction`: **PASS**
- `tip_capture/null_geometry_specificity`: **PASS**
- `tip_capture/receipt_ancestry_root_recovery`: **PASS**
- `tip_capture/tip_targeted_repair_yield`: **FAIL**

## Boundary

The endurance world and the execution-graph world are seeded mechanism tests. The first-contact treatment uses a lattice random walk independent of the reported exposure heuristic, while uniform attachment is the null. Passing shows the instruments recover declared mechanisms and reject nulls where preregistered; it does not show deployed agents obey material fatigue or DLA.

A passing simulation earns a real-agent experiment. It does not validate the physical analogy.

# OpenLine Collision-Aware Spacing — Exploratory Synthetic Run

**Claim label:** `COLLISION_AWARE_SPACING_EXPLORATORY`
**Status:** `EXPLORATORY_NULL_OR_MIXED`
**Exploratory gates:** 5/7 passed
**Held-out seeds:** 80

## Main contrasts

- Random sparse minus Ulam collision burden: -0.020149; p=0.359243
- Random sparse minus Ulam damage AUC: -0.798048; p=0.0329398
- Random sparse minus Ulam failures: 0.000000; p=0.303293
- Random sparse minus conflict-aware collision burden: 0.187671; p=4.99998e-06
- Random sparse minus conflict-aware damage AUC: 1.244472; p=4.99998e-06

## Exploratory gate results

- `matched_spacing_design`: **PASS**
- `clustered_positive_control`: **PASS**
- `random_sparse_null_specificity`: **PASS**
- `ulam_collision_reduction`: **FAIL**
- `ulam_damage_reduction`: **FAIL**
- `conflict_graph_collision_reduction`: **PASS**
- `conflict_graph_damage_reduction`: **PASS**

## Boundary

This is a synthetic timing experiment. Ulam positions supply an irregular clock; the conflict graph is declared from overlapping requirement dependencies. A signal would justify testing real agent traces. It would not establish that Ulam numbers have semantic intelligence or that deployed agents repair during idle time according to this simulator.

# OpenLine Generational Endurance — Exploratory Synthetic Run

**Status:** `MIXED_EXPLORATORY_GENERATIONAL_RESULT`
**Exploratory gates:** 5/7 passed
**Maximum verified horizon:** 80 cycles
**Held-out seeds:** 80

## Horizon and context witness

- Capsule survival at 40/80/160: 0.825 / 0.662 / 0.388
- Ordinary-summary survival at 40/80/160: 0.562 / 0.287 / 0.075
- Continuous-history survival at 40/80/160: 0.150 / 0.000 / 0.000
- Capsule active-context ratio versus continuous at 40/80/160: 0.438 / 0.265 / 0.147
- Capsule median life versus summary gain: 60.000 cycles; p=2.05606e-05
- Conflict-aware capsule versus capsule median gain: 0.000 cycles; p=1
- Pressure-disabled capsule minus continuous median life: -41.000 cycles

## Exploratory gate results

- `verified_horizon_40`: **PASS**
- `verified_horizon_80`: **PASS**
- `verified_horizon_160`: **FAIL**
- `capsule_accuracy_noninferiority_40`: **PASS**
- `capsule_vs_summary_endurance`: **PASS**
- `conflict_aware_capsule_advantage`: **FAIL**
- `pressure_disabled_null_specificity`: **PASS**

## Plain-language result

The verified capsule carried a median lineage through 80 cycles while using less than half the active context of continuous history. It did not clear 160 cycles. Conflict-aware ordering lowered omissions and improved accuracy, but it did not add a statistically detectable life extension over the capsule alone.

## Boundary

This seeded toy world tests finite-context inheritance mechanics using the existing Endurance Gate requirement graph. It does not establish that deployed agents possess fatigue, that capsules generalize across models, or that synthetic context pressure matches transformer attention.

# OpenLine State Restoration — Exploratory Synthetic Run

**Status:** `MIXED_EXPLORATORY_STATE_RESTORATION_RESULT`
**Exploratory gates:** 5/9 passed
**Held-out seeds:** 80

## Endurance witness

- Capsule baseline survival at 160/320: 0.637 / 0.438
- Restoration stack survival at 160/320: 0.863 / 0.825
- Stack minus baseline median life: 0.000 cycles; p=2.91038e-11
- Fixed retirement minus baseline median life: 0.000 cycles; p=0.000976562
- Sham retirement minus baseline median life: 0.000 cycles

## Exploratory gate results

- `scheduled_pruning_adds_endurance`: **FAIL**
- `fixed_retirement_adds_endurance`: **FAIL**
- `telemetry_breaker_beats_fixed_schedule`: **FAIL**
- `ecc_digest_adds_endurance`: **FAIL**
- `restoration_stack_reaches_160`: **PASS**
- `restoration_stack_reaches_320`: **PASS**
- `restoration_preserves_checkpoint_accuracy`: **PASS**
- `sham_retirement_specificity`: **PASS**
- `pressure_disabled_null_specificity`: **PASS**

## Boundary

rolling_noise_epsilon, coherence_margin_proxy, and stability_lambda_proxy are declared synthetic observables. They test trigger policies; they are not asserted measurements of physical Coherence Dynamics variables.

This seeded toy world tests whether pruning, verified reconstruction, telemetry-triggered retirement, and digest repair extend continuity beyond an inherited capsule baseline. It does not establish an exact 160-cycle law in deployed models.

# OpenLine Load-Rate Transition — Same Disturbance, Different Speed

**Status:** `MIXED_EXPLORATORY_LOAD_RATE_RESULT`
**Exploratory gates:** 3/4 passed
**Held-out seeds:** 80
**Cycle observations:** 368640

## Primary contrast

- Same perturbations, same order, same total load, same ordinary work, same horizon, and the same context cap.
- Slow minus sudden-burst mean disturbances survived: 3.258333; 95% interval=[2.5166666666666666, 4.0625]; p=6.37738e-17
- Recovery-window minus continuous-burst mean disturbances survived: 2.450000; 95% interval=[1.8083333333333333, 3.1083333333333334]; p=1.16257e-14
- Rate-disabled null mean difference: -0.258333; 95% interval=[-0.4375, -0.0625]

## Exploratory gate results

- `burst_causes_earlier_critical_failure`: **PASS**
- `rate_direction_replicates_across_modes`: **PASS**
- `ordinary_work_recovery_windows_reduce_burst_harm`: **PASS**
- `rate_disabled_null_specificity`: **FAIL**

## Boundary

This seeded synthetic experiment tests whether disturbance spacing changes critical-failure life when disturbance identities, order, total load, ordinary work, horizon, random draws, and context cap are matched. It does not claim that AI agents obey fluid mechanics, identify a universal rate threshold, or establish a deployed-agent retirement policy.

Synthetic damage is reported as a secondary diagnostic. It does not decide the primary rate gate.

# OpenLine Load-Rate Transition — Same Disturbance, Different Speed

**Status:** `SURVIVES_ALL_EXPLORATORY_LOAD_RATE_GATES`
**Exploratory gates:** 4/4 passed
**Held-out seeds:** 80
**Cycle observations:** 368640

## Primary contrast

- Same perturbations, same order, same total load, same ordinary work, same horizon, and the same context cap.
- Slow minus sudden-burst mean disturbances survived: 4.579167; 95% interval=[3.845833333333333, 5.341666666666667]; p=1.06385e-32
- Recovery-window minus continuous-burst mean disturbances survived: 4.058333; 95% interval=[3.345833333333333, 4.783333333333333]; p=7.2232e-30
- Rate-disabled null mean difference: 0.041667; 95% interval=[0.0, 0.125]
- Mode-specific null differences: continuous_history=0.112500, ordinary_summary=0.012500, verified_capsule=0.000000

## Exploratory gate results

- `burst_causes_earlier_critical_failure`: **PASS**
- `rate_direction_replicates_across_modes`: **PASS**
- `ordinary_work_recovery_windows_reduce_burst_harm`: **PASS**
- `rate_disabled_null_specificity`: **PASS**

## Boundary

This seeded synthetic experiment tests whether disturbance spacing changes critical-failure life when disturbance identities, order, total load, ordinary work, horizon, random draws, and context cap are matched. Ordinary task scratch context is released after each task so retained-context growth is matched by disturbance index. It does not claim that AI agents obey fluid mechanics, identify a universal rate threshold, or establish a deployed-agent retirement policy.

Synthetic damage is reported as a secondary diagnostic. It does not decide the primary rate gate.

# OpenLine Recovery Intervention — Pass 1

**Status:** `PASSES_ALL_PREREGISTERED_V090_RECOVERY_GATES`
**Preregistered v0.9.0 gates:** 7/7 passed

## Held-out condition measurements

- `continuous_control`: mean n_f=101.000; post-handoff accuracy=0.075856; policy violations=0; mean packet bytes=0.0
- `empty_reset`: mean n_f=80.000; post-handoff accuracy=0.000000; policy violations=352; mean packet bytes=45.0
- `full_history_handoff`: mean n_f=101.500; post-handoff accuracy=0.077412; policy violations=0; mean packet bytes=19880.1
- `unsigned_minimal_handoff`: mean n_f=153.031; post-handoff accuracy=0.345176; policy violations=0; mean packet bytes=1951.6
- `olp_handoff`: mean n_f=153.031; post-handoff accuracy=0.345176; policy violations=0; mean packet bytes=7279.6

## Gates

- `empty_reset_underperforms_state_bearing_handoffs`: **PASS**
- `compact_not_materially_worse_than_full_history`: **PASS**
- `olp_refuses_corrupted_or_incomplete_state`: **PASS**
- `effect_replicates_on_heldout_seeds`: **PASS**
- `not_a_fixed_failure_postponement`: **PASS**
- `clean_unsigned_olp_equivalence`: **PASS**
- `checksum_detects_bit_flip`: **PASS**

## Boundary

In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.

Freshness/replay state, cross-run binding, and signed omission testing are deferred to v0.9.1 with fresh seeds.
