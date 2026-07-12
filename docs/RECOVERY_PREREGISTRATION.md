# Recovery Intervention Preregistration — v0.9.1 Pass 2

## Frozen question

Can a fresh runtime continue a 320-cycle synthetic task from a compact handoff issued at cycle 80 while preserving required state and avoiding continuous-context degradation? Does verification do measurable work beyond compression?

The permitted claim is: “In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.”

## Conditions

1. `continuous_control`: no handoff and no integrity mechanism.
2. `empty_reset`: fresh runtime with no carried state.
3. `full_history_handoff`: unverified complete history.
4. `unsigned_minimal_handoff`: compact payload plus plain unkeyed SHA-256, without origin, policy-completeness, run, or freshness binding.
5. `olp_handoff`: the same compact semantic payload plus Ed25519, evidence hashes, eight chained receipts, required-field coverage, and signed run/parent/generation binding.

The checksum comparator is intentionally able to detect a packet bit flip. In clean runs, conditions 4 and 5 must be behaviorally equivalent; signing is not allowed to improve the simulator.

## Frozen design

- Horizon: 320 cycles.
- Single intervention: cycle 80.
- Training seeds: 9201–9208.
- Validation seeds: 9217–9224.
- Held-out seeds: 9225–9304.
- No v0.9.0 recovery seed is reused.
- Common random draws are bound to event identity, seed, and cycle, excluding condition.
- Hidden truth is evaluator-only and never enters a handoff.
- Six persistent fields are measured separately: retry demand, latency floor, risk tolerance, memory horizon, handoff depth, and token capacity.

## Measurements

Measurements remain separate: correct post-handoff decisions; per-field retention; policy violations; cycles until first failure; cycles until the same failure returns; packet bytes and lexical tokens; handoff and verification CPU/wall time; evidence reads; and rejected/undecidable handoffs. Timing is environment-sensitive and excluded from deterministic reproduction claims. There is no Recovery Score.

## Frozen freshness mechanism

Both compact envelopes carry `run_id`, packet-level `parent_hash`, and `generation_index`; the unsigned payload checksum covers the same fields that OLP signs. The verifier session holds `expected_run_id`, `last_accepted_parent_hash = GENESIS`, and `last_accepted_generation_index = 0`.

Verification functions are pure. They return a proposed next parent/generation, and the caller advances the session only after acceptance. Run mismatch, parent mismatch, and non-advancing generation are definite `rejected` outcomes. Valid integrity with insufficient required-state coverage is `undecidable`.

The core design retains one intervention at cycle 80. Synthetic alternate histories exercise replay without changing simulation exposure.

## Pass-2 hostile controls

The release must fail closed on the five Pass-1 attacks plus stale earlier-packet replay, cross-run packet copy, isolated generation rollback with a correct current parent, and immediate same-packet replay. A separate supporting control requires a correctly signed omission of one required state field to be `undecidable`. The unsigned comparator must reject a bit flip, but an attacker who rewrites freshness fields and recomputes the unkeyed checksum must be able to pass it; that failure is the comparator result.

## Gates and falsifiers

- Empty reset must underperform state-bearing handoffs.
- Compact handoffs must not materially underperform full history.
- OLP must refuse corrupted or structurally unsupported handoffs.
- Direction must replicate on untouched held-out seeds.
- The result must not be reducible to a constant postponement of the same failure.
- Clean unsigned and OLP behavior must be equivalent.
- The checksum must catch bit-flip corruption.
- OLP must reject all four replay/freshness attacks while rebound unsigned packets are accepted after attacker checksum recomputation.

Failed gates remain visible. No combined score may replace them.

The mechanism, eight gates, nine counted hostile controls, omission supporting control, and fresh seed partition were frozen after v0.9.0 adversarial review and before v0.9.1 held-out execution.
