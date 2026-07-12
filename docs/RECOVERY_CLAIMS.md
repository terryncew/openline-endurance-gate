# Recovery Claims and Boundaries

## Permitted claim

> In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.

Report the measured amount from `results/recovery_summary.json`; do not substitute a qualitative claim.

## What v0.9.1 can distinguish

- State-bearing handoff versus empty reset.
- Compact state versus full-history carriage.
- Plain checksum detection of accidental/transit corruption.
- Signed origin plus evidence and required-field coverage checks versus an unkeyed checksum.
- Acceptance, rejection, and undecidable outcomes as separate observations.
- Signed freshness binding from identical checksum-covered but attacker-rewritable fields.
- Stale replay, cross-run copy, isolated generation rollback, and immediate same-packet replay.

## Excluded

No claim is made about ε, m, Λ, “coherence recovery,” a universal cycle-count law, signing making a runtime smarter, operational key security, or transfer to deployed agents. Timing is descriptive and environment-sensitive. The secondary damage and fractography fields are diagnostics, not physical identification.

The freshness result is confined to this verifier state machine and synthetic alternate histories. It does not establish global uniqueness, secure clocks, durable rollback resistance, distributed consensus, or transfer to deployed agents.
