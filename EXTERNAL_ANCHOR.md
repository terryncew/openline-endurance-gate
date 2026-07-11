# External Anchor

The repository can prove internal consistency. It cannot, by itself, prove that an attacker did not replace the entire repository and issue a new signing key.

After a verified run, publish the `witness_digest` from `results/public_witness.json` somewhere independently durable. The smallest useful publication is:

```text
OpenLine Endurance Gate v0.3.1
witness_digest: <64 hex characters>
release archive sha256: <64 hex characters>
```

A GitHub release, mirrored commit, public timestamp, transparency log, or another party's signed receipt can serve as the external witness. Keep the raw data local if needed; the digest is enough to detect later replacement.
