# Recovery Threat Model — v0.9.1

## Protected in Pass 2

The OLP condition detects mutation of the signed packet, mismatch between external evidence and signed evidence hashes, reordering/truncation of the eight-receipt envelope, stale replay, cross-run copy, counter rollback, and required-state omission. Required persistent fields and evidence categories are explicitly enumerated. The detached repository release witness detects replacement of the recovery report or summary even if an attacker constructs a new self-consistent inner chain under a different key.

The unsigned condition detects payload byte changes with an unkeyed SHA-256 checksum. This is deliberate comparator fairness, not authentication.

## Failure semantics

- `rejected`: integrity, freshness, or trusted-witness failure; the runtime does not restore the packet.
- `undecidable`: integrity may be valid, but evidence or policy coverage is insufficient; the runtime does not restore the packet.
- `accepted`: all checks succeeded; the caller may then advance the verifier session and restore the packet.

Unknown or missing evidence never falls through to `accepted`.

## Freshness trust boundary

Freshness depends on verifier-held state surviving between calls. A verifier whose session is erased, rolled back, or attacker-controlled cannot recognize an otherwise valid replay. `run_id` is deterministic in this synthetic harness and is not a secret nonce. The mechanism does not provide distributed consensus, secure time, multi-writer fork resolution, or rollback-resistant hardware.

Compromised signing keys, side channels, denial of service, malicious cryptographic libraries, verifier-session rollback, and claims about real-agent safety remain out of scope.
