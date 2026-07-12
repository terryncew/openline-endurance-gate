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
