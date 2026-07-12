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

