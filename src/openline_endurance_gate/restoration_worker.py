from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
from pathlib import Path
from typing import Any

from .integrity import _artifact_normalize
from .state_restoration import MODES, RESTORATION_CYCLE_FIELDS, _simulate_one
from .util import canonical_json, sha256_bytes


def _leaf_bytes(row: dict[str, Any]) -> bytes:
    return bytes.fromhex(sha256_bytes(canonical_json(_artifact_normalize(row))))


def run_worker(
    experiment: dict[str, Any],
    seeds: list[int],
    cycle_path: Path,
    leaf_path: Path,
    runs_path: Path,
) -> dict[str, Any]:
    cycle_path.parent.mkdir(parents=True, exist_ok=True)
    leaf_path.parent.mkdir(parents=True, exist_ok=True)
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    cycle_temp = Path(str(cycle_path) + ".tmp")
    leaf_temp = Path(str(leaf_path) + ".tmp")
    runs_temp = Path(str(runs_path) + ".tmp")
    runs: list[dict[str, Any]] = []
    cycle_count = 0
    try:
        with cycle_temp.open("wb") as raw, gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0
        ) as gz, io.TextIOWrapper(gz, encoding="utf-8", newline="") as text, leaf_temp.open("wb") as leaves:
            writer = csv.DictWriter(text, fieldnames=RESTORATION_CYCLE_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for seed in seeds:
                for mode in MODES:
                    rows, run = _simulate_one(mode, "main", seed, experiment)
                    for row in rows:
                        writer.writerow(row)
                        leaves.write(_leaf_bytes(row))
                        cycle_count += 1
                    runs.append(run)
                for mode in ("capsule_baseline", "restoration_stack"):
                    rows, run = _simulate_one(mode, "pressure_disabled_null", seed, experiment)
                    for row in rows:
                        writer.writerow(row)
                        leaves.write(_leaf_bytes(row))
                        cycle_count += 1
                    runs.append(run)
        runs_temp.write_text(json.dumps(runs, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        for path in (cycle_temp, leaf_temp, runs_temp):
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        cycle_temp.replace(cycle_path)
        leaf_temp.replace(leaf_path)
        runs_temp.replace(runs_path)
    except BaseException:
        for path in (cycle_temp, leaf_temp, runs_temp):
            path.unlink(missing_ok=True)
        raise
    return {"cycle_count": cycle_count, "run_count": len(runs), "seeds": seeds}


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal bounded v0.7 state-restoration shard worker")
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--seeds", required=True, help="comma-separated integer seeds")
    parser.add_argument("--cycles", type=Path, required=True)
    parser.add_argument("--leaves", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
    seeds = [int(value) for value in args.seeds.split(",") if value]
    metadata = run_worker(experiment, seeds, args.cycles, args.leaves, args.runs)
    args.metadata.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
