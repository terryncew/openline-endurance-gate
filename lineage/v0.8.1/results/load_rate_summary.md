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

