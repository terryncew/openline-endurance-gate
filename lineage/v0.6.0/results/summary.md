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

