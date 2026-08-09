#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate.successor_benchmark import compare_reports
from openline_endurance_gate.successor_verifier import _compare as verify_compare


def run(iterations: int = 10_000, seed: int = 13_001) -> dict:
    rng = random.Random(seed)
    for index in range(iterations):
        metrics = []
        incumbent_metrics = {}
        candidate_metrics = {}
        for name in ("accuracy", "defects", "latency"):
            metrics.append({
                "name": name,
                "description": f"Synthetic integer {name} measurement.",
                "direction": rng.choice(("maximize", "minimize")),
                "required": rng.choice((True, False)),
                "max_regression": rng.randrange(0, 4),
                "minimum_improvement": rng.randrange(1, 6),
            })
            incumbent_metrics[name] = rng.randrange(-20, 101)
            candidate_metrics[name] = rng.randrange(-20, 101)
        policy = {"schema": "agent.successor.policy.v1", "policy_id": "crosscheck", "metrics": metrics}
        incumbent = {"status": rng.choice(("PASS", "FAIL", "UNDECIDABLE")), "metrics": incumbent_metrics, "critical_failures": []}
        candidate = {"status": rng.choice(("PASS", "FAIL", "UNDECIDABLE")), "metrics": candidate_metrics, "critical_failures": []}
        implementation = compare_reports(policy=policy, incumbent_report=incumbent, candidate_report=candidate)
        verifier = verify_compare(policy, incumbent, candidate)
        if implementation != verifier:
            return {"schema": "agent.successor.comparison-crosscheck.v1", "passed": False, "seed": seed, "iterations": iterations, "failed_index": index}
    return {"schema": "agent.successor.comparison-crosscheck.v1", "passed": True, "seed": seed, "iterations": iterations, "mismatches": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=13_001)
    args = parser.parse_args()
    if args.iterations <= 0:
        parser.error("iterations must be positive")
    result = run(args.iterations, args.seed)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
