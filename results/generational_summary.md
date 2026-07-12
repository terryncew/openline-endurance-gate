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

