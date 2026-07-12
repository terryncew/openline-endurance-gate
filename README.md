# OpenLine Endurance Gate

Version 0.9.1 completes Recovery Intervention Pass 2. It preserves v0.9.0 byte-for-byte, reruns the five matched conditions on 80 fresh held-out seeds, and adds stateful `run_id`, packet-parent, and generation binding. A valid signature is not sufficient for acceptance: stale, cross-run, and incomplete packets fail through independent checks.

`openline-endurance-gate` is a falsifiable synthetic reliability harness for cumulative state loss, dependency-frontier geometry, verified inheritance, restoration, and disturbance-rate effects.

## v0.9.1 — Replay and freshness binding, Pass 2

Both compact tracks carry the same `run_id`, `parent_hash`, and `generation_index` fields and check them against the same verifier-session shape. The unsigned track covers its fields only with an unkeyed checksum; an attacker can rewrite them and recompute it. The OLP track signs the fields in the envelope body and in all eight receipts.

Verification is pure: it returns a proposed session update, and the caller advances expected parent/generation state only after acceptance. The nine module hostile controls add stale replay, cross-run copy, isolated generation rollback, and immediate same-packet replay to the five Pass-1 controls. Correctly signed state omission remains a separate supporting control and must be `undecidable`, never accepted.

All **8 of 8** preregistered Pass-2 gates passed on 80 fresh held-out seeds. Empty reset failed at cycle 80; state-bearing arms averaged 136.7625 cycles to failure. Clean unsigned and OLP compact arms were exactly equal at 153.0125 cycles and 0.350207 post-intervention decision accuracy. OLP retained every required field at 97.5% or better at intervention.

The OLP packet averaged 8,486 bytes versus 2,203 for unsigned compact state and 19,874 for full history. Under all four replay/freshness attacks, OLP rejected while signature validity remained intact; after attacker rebinding and checksum recomputation, the unsigned packet accepted. The prior Pass-1 result remains pinned in `lineage/v0.9.0`.

## v0.9.0 — Recovery Intervention, Pass 1 (preserved)

All **7 of 7** preregistered recovery gates passed on 32 held-out seeds. Empty reset failed at cycle 80; the state-bearing arms averaged 135.854 cycles to failure. The clean unsigned and OLP compact arms were exactly equal at 153.031 cycles and 0.345176 post-intervention decision accuracy, while full history averaged 101.5 cycles and 0.077412 accuracy. Every OLP field retained at least 96.875% at intervention; three retained 100%.

The OLP packet averaged 7,280 bytes versus 19,880 for full history. Its overhead over the 1,952-byte unsigned packet is the signed eight-receipt evidence and coverage layer. The v0.9.0 top-level tamper runner detected all 15 attacks: the inherited ten plus five recovery-specific controls.

The clean equality is intentional. This experiment does not let signing make the runtime smarter; verification’s distinct role is fail-closed refusal when integrity, evidence, chain, report, or trusted-summary binding is challenged.

## v0.8.1 — Same Disturbance, Different Speed: phase-controlled replication

v0.8.0 found a real spacing association but failed its null because ordinary-work tokens accumulated permanently in active context. Slow schedules therefore reached the same disturbance index with more retained context than burst schedules. That hidden schedule-to-context pathway was concentrated in continuous history.

v0.8.1 preserves the original 3/4 result byte-for-byte in `lineage/v0.8.0` and reruns the same four gates on fresh seeds after one mechanism correction:

> Ordinary work still executes, consumes the same tokens, and can perform bounded repair, but its scratch context is released after the task. Only receipt-worthy disturbances persist in active context.

Everything else remains matched: disturbance identities, order, amplitudes, total load, ordinary work, horizon, event-bound random draws, active-context ceiling, schedules, gates, and thresholds.

## Held-out result

v0.8.1 passed **4 of 4** exploratory gates on 80 fresh held-out seeds.

- Slow delivery survived **4.5792 more disturbances** than sudden burst on average; 95% interval **3.8458 to 5.3417**.
- The direction replicated in all three modes: continuous history **+4.30**, ordinary summary **+3.8875**, verified capsule **+5.55**.
- Ordinary-work recovery windows survived **4.0583 more disturbances** than a continuous burst; 95% interval **3.3458 to 4.7833**.
- The rate-disabled null was **+0.0417** overall; 95% interval **0.0 to 0.125**. Mode-specific nulls were continuous history **+0.1125**, ordinary summary **+0.0125**, and verified capsule **0.0**.

This closes the discovered phase confound inside the declared synthetic world. It does not establish a universal load-rate law for deployed agents.

## Claim boundary

The hard result is narrow:

**With retained context matched by disturbance index, concentrated disturbances shortened synthetic survival relative to slow delivery.**

This release does not claim that AI agents obey fluid mechanics, identify a universal breaking rate, validate a physical Coherence Dynamics variable, or establish an activation-envelope retirement policy.

## Run

```bash
python -m openline_endurance_gate run --root .
python -m openline_endurance_gate recovery --root .
python -m openline_endurance_gate load-rate --root .
python -m openline_endurance_gate verify --root . --source-root . --fast
python -m openline_endurance_gate verify --root . --source-root .
```

## Release gate

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
bash scripts/tamper_check.sh
bash scripts/release_check.sh
```

The standalone hostile check writes `TAMPER_REPORT.standalone.json`; it does not overwrite the report bound by the detached release attestation.

## Evidence boundary

The experiment chain is Ed25519-signed and hash-linked. The verifier checks the byte-pinned v0.9.0 snapshot, every earlier inherited lineage boundary, recovery preregistration, deterministic cycle shards, timing-stripped handoff semantics, module gates, the integrated summary, and the detached outer release attestation.

A local key and witness cannot detect total repository replacement by an attacker with full write access. Publish `results/public_witness.json`, `receipts/release.anchor.json`, or their digests outside the repository to close that boundary.
