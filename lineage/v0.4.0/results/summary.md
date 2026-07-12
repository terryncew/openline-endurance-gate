# OpenLine Endurance Gate — Powered Sequence Run

**Claim label:** `POWERED_SYNTHETIC_ENDURANCE_AND_TIP_CAPTURE`
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

- `endurance/fresh_subcritical_calibration`: **PASS**
- `endurance/amplitude_endurance_gradient`: **PASS**
- `endurance/load_order_noncommutativity`: **FAIL**
- `endurance/damage_adds_heldout_prediction`: **PASS**
- `endurance/receipt_handoff_advantage`: **PASS**
- `tip_capture/first_contact_frontier_concentration`: **PASS**
- `tip_capture/geometry_adds_heldout_prediction`: **PASS**
- `tip_capture/null_geometry_specificity`: **PASS**
- `tip_capture/tip_targeted_repair_yield`: **FAIL**
- `tip_capture/receipt_ancestry_root_recovery`: **PASS**

## Boundary

The endurance world and the execution-graph world are seeded mechanism tests. The first-contact treatment uses a lattice random walk independent of the reported exposure heuristic, while uniform attachment is the null. Passing shows the instruments recover declared mechanisms and reject nulls where preregistered; it does not show deployed agents obey material fatigue or DLA.

A passing simulation earns a real-agent experiment. It does not validate the physical analogy.
