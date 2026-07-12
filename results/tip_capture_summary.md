# OpenLine Execution Tip-Capture — Powered Synthetic Run

**Claim label:** `POWERED_SYNTHETIC_FIRST_CONTACT_TIP_CAPTURE`
**Status:** `MIXED_TIP_CAPTURE_RESULT`
**Pre-registered gates:** 4/5 passed
**Cycle observations:** 69120
**Held-out seeds:** 80

## Main witnesses

- First-contact frontier capture lift over candidate-count null: 0.253671
- Random-walk fallback rate: 0.000956
- Geometry held-out log-loss gain: 0.04087282
- Geometry held-out AUC gain: 0.05399487
- Tip-minus-random repair yield median: 0.000000 violations prevented per successful repair
- Repair-yield majority direction: `random_repair_higher_yield_than_tip_targeted`
- Positive-direction consistency among non-ties: 0.428571
- Pair counts — tip favored: 15; random favored: 20; tied: 45
- Receipt ancestry root-recovery median gain: 0.500000 recovery-rate points
- Burial depth / successful recovery-cost Spearman: 1.0
- v0.3.1 lineage: `even_spread` is retired and retained only as the accurately named descriptive `least_capture_balancer` condition.

## Gate results

- `first_contact_frontier_concentration`: **PASS**
- `geometry_adds_heldout_prediction`: **PASS**
- `null_geometry_specificity`: **PASS**
- `tip_targeted_repair_yield`: **FAIL**
- `receipt_ancestry_root_recovery`: **PASS**

## Boundary

This is a seeded mechanism-recovery test. The first-contact condition uses an explicit lattice random walk whose contact rule is independent of the reported spatial exposure heuristic; uniform attachment is the null. Success shows recovery of that declared synthetic mechanism, not that deployed agents follow DLA or any physical fracture law.

