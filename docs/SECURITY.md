# Security boundary

The benchmark separates four authorities:

1. **Registration** fixes what will be compared before either arm is submitted.
2. **Arm submission** supplies candidate artifacts and evidence but cannot set its own score.
3. **Checker** evaluates one blinded lane and signs measured outcomes.
4. **Receiver** applies the pre-registered comparison policy to the two verified reports.

A valid checker signature proves possession of the pinned checker private key. It does not prove the checker is independent, truthful, or uncompromised. Key custody and organizational separation are deployment responsibilities.

The benchmark does not execute a promotion. A downstream system must separately confirm that the incumbent being replaced is still the receiver's current version and must authorize the exact replacement at execution time.

Case registration provides an artifact ordering boundary, not a public timestamp. If an operator can rewrite the registration, checker key, and retained evidence before anyone relies on them, the benchmark cannot prove earlier custody.

Evidence directories reject symlinks, path traversal, unlisted files, oversized files, duplicate identifiers, and hash mismatches. JSON parsing rejects duplicate object keys, non-finite numbers, excessive nesting, and floating-point values in signed or hashed protocol objects.
