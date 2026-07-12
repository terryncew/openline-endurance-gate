from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .integrity import _artifact_normalize
from .load_rate import LOAD_RATE_CYCLE_FIELDS, simulate_load_rate, write_deterministic_gzip_csv
from .util import canonical_json


def run_worker(
    experiment: dict[str, Any],
    seeds: list[int],
    cycles_path: Path,
    leaves_path: Path,
    runs_path: Path,
) -> dict[str, Any]:
    cycles, runs = simulate_load_rate(experiment, seeds)
    write_deterministic_gzip_csv(cycles_path, cycles, LOAD_RATE_CYCLE_FIELDS)
    leaves_path.parent.mkdir(parents=True, exist_ok=True)
    with leaves_path.open("wb") as handle:
        for row in cycles:
            handle.write(hashlib.sha256(canonical_json(_artifact_normalize(row))).digest())
    runs_path.write_text(json.dumps(runs, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "seeds": seeds,
        "cycle_count": len(cycles),
        "run_count": len(runs),
        "leaf_count": leaves_path.stat().st_size // 32,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--cycles", type=Path, required=True)
    parser.add_argument("--leaves", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
    seeds = [int(value) for value in args.seeds.split(",") if value]
    metadata = run_worker(experiment, seeds, args.cycles, args.leaves, args.runs)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
