# OpenLine Recovery Intervention — Pass 1

**Status:** `PASSES_ALL_PREREGISTERED_V091_RECOVERY_GATES`
**Preregistered 0.9.1 gates:** 8/8 passed

## Held-out condition measurements

- `continuous_control`: mean n_f=104.263; post-handoff accuracy=0.085633; policy violations=0; mean packet bytes=0.0
- `empty_reset`: mean n_f=80.000; post-handoff accuracy=0.000000; policy violations=880; mean packet bytes=45.0
- `full_history_handoff`: mean n_f=104.263; post-handoff accuracy=0.085633; policy violations=0; mean packet bytes=19874.3
- `unsigned_minimal_handoff`: mean n_f=153.012; post-handoff accuracy=0.350207; policy violations=0; mean packet bytes=2202.8
- `olp_handoff`: mean n_f=153.012; post-handoff accuracy=0.350207; policy violations=0; mean packet bytes=8485.8

## Gates

- `empty_reset_underperforms_state_bearing_handoffs`: **PASS**
- `compact_not_materially_worse_than_full_history`: **PASS**
- `olp_refuses_corrupted_or_incomplete_state`: **PASS**
- `effect_replicates_on_heldout_seeds`: **PASS**
- `not_a_fixed_failure_postponement`: **PASS**
- `clean_unsigned_olp_equivalence`: **PASS**
- `checksum_detects_bit_flip`: **PASS**
- `unsigned_checksum_cannot_prevent_replay_even_with_identical_fields`: **PASS**

## Boundary

In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.

Stateful run, parent, and generation freshness binding is active. Stale replay, cross-run copy, and correctly signed omission were tested on fresh seeds.
