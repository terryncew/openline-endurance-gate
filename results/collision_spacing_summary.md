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

