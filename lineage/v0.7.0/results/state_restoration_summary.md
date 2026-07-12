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

