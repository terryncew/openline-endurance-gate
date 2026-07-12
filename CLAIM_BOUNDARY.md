# Claim Boundary

## Permitted v0.9.1 claim

> In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.

The measured amount is reported by condition and field in `results/recovery_summary.json`. There is no Recovery Score.

## What v0.9.1 tests

The experiment compares uninterrupted execution, empty reset, unverified full history, unsigned compact state with a plain SHA-256 checksum, and the same compact state protected by Ed25519, evidence hashes, eight chained receipts, and explicit coverage. All conditions receive event-bound common random draws over 320 cycles with one intervention at cycle 80.

The checksum is a fair corruption comparator. Both compact tracks carry and check identical freshness fields, and clean behavior must remain equal. An attacker can rewrite those fields and recompute the unsigned checksum; the OLP signature prevents the same rebinding. The permitted Pass-2 mechanism claim is that this stateful binding rejects stale replay, cross-run copy, and counter rollback in the controlled verifier session while checksum-only binding does not.

## Excluded

This release does not claim ε, m, Λ, “coherence recovery,” a universal cycle-count law, that signing makes a runtime smarter, operational key security, or transfer to deployed agents. Damage and fractography values are secondary synthetic diagnostics. CPU and wall timing are environment-sensitive observations.

Signatures alone do not establish completeness. A correctly signed packet missing required state remains `undecidable`; a definite freshness mismatch is `rejected`. The experiment uses synthetic alternate histories for replay tests and retains one real intervention at cycle 80.

## Inherited result

The v0.9.0 Pass-1 recovery result remains byte-pinned in `lineage/v0.9.0`. v0.9.1 does not rewrite it.

## Trust boundary

Signatures establish integrity and origin relative to a declared key; they do not prove scientific truth. An attacker with full repository write access can replace source, artifacts, keys, and local anchors. External publication of the public witness or release anchor digest is required to detect whole-repository replacement.
