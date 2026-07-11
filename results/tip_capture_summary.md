# OpenLine Execution Tip-Capture — Powered Synthetic Run

**Claim label:** `POWERED_SYNTHETIC_EXECUTION_TIP_CAPTURE`
**Status:** `MIXED_TIP_CAPTURE_RESULT`
**Pre-registered gates:** 3/5 passed
**Cycle observations:** 69120
**Held-out seeds:** 80

## Main witnesses

- Diffusive frontier capture lift over candidate-count null: 0.019904
- Geometry held-out log-loss gain: 0.01442930
- Geometry held-out AUC gain: 0.11012878
- Tip-minus-random repair yield median: 0.000000 violations prevented per successful repair
- Repair-yield majority direction: `random_repair_higher_yield_than_tip_targeted`
- Positive-direction consistency among non-ties: 0.318182
- Pair counts — tip favored: 14; random favored: 30; tied: 36
- Receipt ancestry root-recovery median gain: 0.333333 recovery-rate points
- Burial depth / successful recovery-cost Spearman: 1.0
- Even-spread disclosure: selecting the least-captured node in the smallest branch creates an unintended leaf/tip bias; this condition is descriptive and no gate was retuned.

## Gate results

- `frontier_capture_concentration`: **FAIL**
- `geometry_adds_heldout_prediction`: **PASS**
- `null_geometry_specificity`: **PASS**
- `tip_targeted_repair_yield`: **FAIL**
- `receipt_ancestry_root_recovery`: **PASS**

## Boundary

This is a seeded mechanism-recovery test. The diffusive condition deliberately contains a stochastic tip-capture process; success shows the instrumentation can detect and exploit that process while the null condition checks specificity. It does not establish that deployed agents follow DLA or any physical fracture law.

