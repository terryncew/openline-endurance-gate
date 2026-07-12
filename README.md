# OpenLine Endurance Gate v0.7.0

A falsifiable synthetic reliability harness for one question: can an agent keep carrying the right state across repeated handoffs without slowly becoming a confident copy of an earlier mistake?

v0.7 adds a state-restoration experiment on top of the released v0.6 inheritance capsule. It separates four interventions that are easy to blur together: pruning active history, restarting an instance, reconstructing state from verified lineage, and correcting detected state errors.

## v0.7 result

Seven matched modes ran for 320 cycles across 80 untouched held-out seeds. Every mode received the same event packets and event-bound random draws. The controls included a sham restart that preserved defects and a pressure-disabled null world.

**State-restoration result: 5/9 exploratory gates passed.**

The combined restoration stack met the absolute 160- and 320-cycle survival gates and preserved checkpoint accuracy. It reached 82.5% survival at 320 cycles, compared with 43.75% for the verified-capsule baseline. Its paired median life gain was still zero because 44 of 80 pairs tied. The preregistered relative-effect rule therefore does not support the stronger claim that the stack materially extended median lifetime.

The individual interventions failed their material-life gates:

- scheduled pruning at cycle 80: median gain 0 cycles;
- fixed retirement every 85 cycles: median gain 0;
- telemetry-triggered retirement versus fixed retirement: median gain 0;
- ECC-style digest correction: median gain 0.

Several improved mean life or survival for a minority of seeds, but the preregistered statistic was the paired median. They stay failed.

The sham retirement passed its specificity gate: restarting while carrying the same defects produced essentially no benefit. The pressure-disabled null also passed its one-sided median rule, although 18 of 80 seeds still favored the stack. That residual is disclosed rather than called equivalence.

## What this does—and does not—say

The build supports a narrower engineering claim: verified reconstruction can participate in a stack that survives farther than the inherited capsule baseline in this seeded world. It does not identify an exact 160-cycle law, prove that rolling noise physically saturates, or establish that the synthetic `epsilon`, coherence-margin, and stability values are measured Coherence Dynamics variables. They are trigger-policy proxies.

The clean result is slightly rude to the original pitch: ordinary pruning and fresh-process retirement were weak. Repair only became useful when the runtime reconstructed load-bearing state from verified lineage. A clean reboot carrying dirty state is still dirty state, just well rested.

## Preserved prior results

`V060_LINEAGE.json` pins the released v0.6 scientific evidence byte-for-byte.

- v0.4 endurance and tip capture: **8/10**;
- v0.5 collision spacing: **5/7**—Ulam failed, conflict-aware spacing passed;
- v0.6 generational inheritance: **5/7**—capsules cleared 40 and 80, then failed 160;
- v0.7 state restoration: **5/9**.

These remain separate scores.

## Run and verify

```bash
python -m pip install -e . --no-deps --no-build-isolation
openline-endurance verify --root . --source-root . --fast
openline-endurance state-restoration --root .
```

The full v0.7 semantic witness is deliberately shardable. Each phase independently regenerates 12 seeds, then the finalizer combines the canonical Merkle leaves and recomputes all nine gates:

```bash
for shard in 0 1 2 3 4 5 6 7; do
  openline-endurance semantic-shard --root . --index "$shard"
done
openline-endurance semantic-finalize --root .
```

A normal machine may also use the one-command verifier:

```bash
openline-endurance verify --root . --source-root .
```

Run the documented release sequence:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
bash scripts/tamper_check.sh
bash scripts/release_check.sh
```

The standalone tamper command writes `TAMPER_REPORT.standalone.json`, which is intentionally outside the detached release attestation. `release_check.sh` rebuilds the attested `TAMPER_REPORT.json`, reruns the semantic shards, writes `RUN_REPORT.json`, and signs the final reports. Running the standalone hostile gate first therefore cannot deadlock or falsely strand a clean clone as tampered.

## Evidence boundary

The experiment chain is Ed25519-signed and hash-linked. A detached release receipt binds the final run and hostile-test reports. The v0.7 verifier independently regenerates 276,480 cycle observations and 864 run summaries while checking prior v0.6 evidence against pinned lineage.

The local public keys remain self-declared. A full-write attacker can replace the repository, source, evidence, keys, and anchors. Publish `results/public_witness.json` and `receipts/release.anchor.json`, or their digests, outside the repository to detect whole-repository replacement.

This remains a seeded toy world with canonical ground truth. The next serious test uses real agent traces and externally scored reconstruction checkpoints.
