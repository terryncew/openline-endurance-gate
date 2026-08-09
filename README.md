# Agent Successor Benchmark

Compare a current agent with a candidate under the same task, constraints, budget, evidence rules, and checker.

The repository name and Python package name are retained for compatibility. The maintained product is the successor benchmark described here.

## What it does

A candidate does not win because it is newer, larger, or self-reports a better score. The receiver fixes the comparison before either arm runs, each arm submits evidence separately, and a pinned checker signs direct outcome measurements for one blinded lane at a time.

The final result is one of:

```text
PROMOTE_CANDIDATE
KEEP_INCUMBENT
INCONCLUSIVE
```

`PROMOTE_CANDIDATE` requires all of the following:

- both reports are determinate;
- the candidate passes the checker;
- the candidate has no critical failure;
- every required metric stays within its declared regression allowance;
- at least one metric meets its declared minimum improvement.

The benchmark emits a recommendation only. It never executes a replacement.

## Why registration comes first

The registration step fixes the exact task, constraints, budget, evaluation policy, repository state, incumbent version, candidate version, checker identity and key, case order, and a hash of the lane-blinding nonce before either arm is submitted.

Later arm packages must match those commitments. Changing the task, policy, budget, version binding, or checker key after registration fails closed.

Registration is an artifact-ordering boundary, not a public timestamp. External custody is still required if you need to prove when the registration existed.

## Checker boundary

The checker receives one lane package at a time. The package contains the fixed task, constraints, budget, measurement contract, one submission hash, and that lane's evidence. It contains no incumbent/candidate role field and no peer-arm package.

The checker cannot add its own metric. Its report must contain exactly the metrics registered by receiver policy, cite packaged evidence, and carry a valid Ed25519 signature under the checker key pinned at registration.

A valid signature proves possession of that private key. It does not prove checker truth or organizational independence.

## Quick verification

Python 3.11 or newer is required.

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/successor_benchmark_selftest.py
python scripts/release_check.py
```

The self-test covers promotion, required regression, no-material-gain, and undecidable cases plus re-sealed tampering of registration, policy, budget, submissions, packages, evidence, reports, and the final decision.

## CLI workflow

Generate a checker key pair:

```bash
agent-successor-benchmark keygen \
  --private-out checker.private.hex \
  --public-out checker.public.hex
```

Register the comparison before either arm is submitted:

```bash
agent-successor-benchmark register \
  --trial-id trial-001 \
  --case-id case-001 \
  --case-index 1 \
  --planned-case-count 10 \
  --task task.json \
  --constraints constraints.json \
  --budget budget.json \
  --policy policy.json \
  --repository-state-hash <sha256> \
  --incumbent-version-hash <sha256> \
  --candidate-version-hash <sha256> \
  --checker-id checker-001 \
  --checker-public-key <hex> \
  --blinding-nonce <receiver-held-value> \
  --out registration.json
```

After both arms finish, create separate checker packages:

```bash
agent-successor-benchmark prepare \
  --registration registration.json \
  --task task.json \
  --constraints constraints.json \
  --budget budget.json \
  --policy policy.json \
  --incumbent-submission incumbent.json \
  --candidate-submission candidate.json \
  --incumbent-evidence incumbent-evidence \
  --candidate-evidence candidate-evidence \
  --blinding-nonce <receiver-held-value> \
  --out prepared-case
```

The checker signs each lane independently:

```bash
agent-successor-benchmark checker-sign \
  --package prepared-case/checker_packages/<lane-id> \
  --status PASS \
  --metric defects=0 \
  --metric task_score=91 \
  --citation test-output \
  --reason-code checked \
  --checker-private-key checker.private.hex \
  --out lane-report.json
```

Finalize after both signed reports exist:

```bash
agent-successor-benchmark finalize \
  --prepared prepared-case \
  --checker-report lane-a-report.json \
  --checker-report lane-b-report.json \
  --out completed-case

agent-successor-benchmark verify --case-dir completed-case
```

The independent verifier does not import the candidate comparison implementation. It recomputes registered bindings, package closure, evidence hashes, checker signatures, metric comparison, final decision, and the case manifest.

## Policy shape

Metrics use integer values so comparison is deterministic across runtimes.

```json
{
  "schema": "agent.successor.policy.v1",
  "policy_id": "coding-agent-v1",
  "metrics": [
    {
      "name": "defects",
      "description": "Checker-confirmed defect count.",
      "direction": "minimize",
      "required": true,
      "max_regression": 0,
      "minimum_improvement": 1
    },
    {
      "name": "task_score",
      "description": "Integer score on the fixed task.",
      "direction": "maximize",
      "required": true,
      "max_regression": 0,
      "minimum_improvement": 5
    }
  ]
}
```

The benchmark does not define universal metrics or thresholds. The receiver does.

## Security limits

This repository does not prove that the checker is independent, that supplied evidence is complete, that a registration was externally timestamped, or that the receiver's current deployed version still matches the registered incumbent when a later replacement is attempted.

That last check belongs at execution time. Comparison evidence alone is never permission to replace an agent.

See [docs/SECURITY.md](docs/SECURITY.md) and [docs/DESIGN.md](docs/DESIGN.md).

## Historical material

Versions through `0.12.0rc2` included synthetic endurance experiments and an experimental metric-based succession calibrator. They remain in Git history for reproducibility but are not used by this benchmark. See [docs/HISTORICAL_RESEARCH.md](docs/HISTORICAL_RESEARCH.md).

MIT licensed.
