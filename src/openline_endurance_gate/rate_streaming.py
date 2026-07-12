from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integrity import _artifact_normalize
from .restoration_stream import _finish_merkle, _finish_merkle_file
from .util import canonical_json, sha256_bytes

DEFAULT_RATE_SEEDS_PER_SHARD = 8


@dataclass(frozen=True)
class CountedRows:
    count: int

    def __len__(self) -> int:
        return self.count


def load_rate_shard_names(
    experiment: dict[str, Any], seeds_per_shard: int = DEFAULT_RATE_SEEDS_PER_SHARD
) -> list[str]:
    count = len(experiment["load_rate"]["seeds"])
    shard_count = (count + seeds_per_shard - 1) // seeds_per_shard
    return [f"load_rate_cycles.part-{index:03d}.csv.gz" for index in range(shard_count)]


def _paths(root: Path, experiment: dict[str, Any], shard_index: int) -> dict[str, Path]:
    work = root / "results" / ".load_rate_work"
    names = load_rate_shard_names(experiment)
    return {
        "cycles": root / "results" / names[shard_index],
        "leaves": work / f"leaves-{shard_index:03d}.bin",
        "runs": work / f"runs-{shard_index:03d}.json",
        "metadata": work / f"metadata-{shard_index:03d}.json",
    }


def generate_load_rate_shard(root: Path, experiment: dict[str, Any], shard_index: int) -> dict[str, Any]:
    from .rate_worker import run_worker

    seeds = list(map(int, experiment["load_rate"]["seeds"]))
    start = shard_index * DEFAULT_RATE_SEEDS_PER_SHARD
    shard_seeds = seeds[start : start + DEFAULT_RATE_SEEDS_PER_SHARD]
    if not shard_seeds:
        raise IndexError(f"load-rate shard index out of range: {shard_index}")
    paths = _paths(root, experiment, shard_index)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    metadata = run_worker(experiment, shard_seeds, paths["cycles"], paths["leaves"], paths["runs"])
    paths["metadata"].write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return {**metadata, "shard_index": shard_index, "cycle_artifact": paths["cycles"].name}


def load_rate_shards_ready(root: Path, experiment: dict[str, Any]) -> bool:
    return all(
        all(path.exists() for path in _paths(root, experiment, index).values())
        for index in range(len(load_rate_shard_names(experiment)))
    )


def finalize_load_rate_shards(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    if not load_rate_shards_ready(root, experiment):
        raise RuntimeError("load-rate shards are incomplete")
    work = root / "results" / ".load_rate_work"
    combined = work / "all-cycle-leaves.bin"
    runs: list[dict[str, Any]] = []
    total_cycles = 0
    artifacts: list[str] = []
    with combined.open("wb") as target:
        for index, name in enumerate(load_rate_shard_names(experiment)):
            paths = _paths(root, experiment, index)
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            total_cycles += int(metadata["cycle_count"])
            runs.extend(json.loads(paths["runs"].read_text(encoding="utf-8")))
            artifacts.append(str(paths["cycles"]))
            with paths["leaves"].open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    cycle_root = _finish_merkle_file(combined, total_cycles)
    run_leaves = [sha256_bytes(canonical_json(_artifact_normalize(run))) for run in runs]
    return {
        "cycle_merkle_root": cycle_root,
        "cycle_count": total_cycles,
        "cycle_artifacts": artifacts,
        "runs": runs,
        "run_merkle_root": _finish_merkle(run_leaves),
        "run_count": len(runs),
        "seed_chunk_size": DEFAULT_RATE_SEEDS_PER_SHARD,
        "execution_boundary": "Identical rows are generated in deterministic eight-seed worker shards; mechanisms and row order are unchanged.",
    }


def stream_load_rate(experiment: dict[str, Any], root: Path) -> dict[str, Any]:
    """Normal-environment coordinator; release CI may run each shard directly."""
    names = load_rate_shard_names(experiment)
    with tempfile.TemporaryDirectory(prefix="openline-v8-rate-stream-") as temp_name:
        temp = Path(temp_name)
        exp_path = temp / "experiment.json"
        exp_path.write_text(json.dumps(experiment, sort_keys=True) + "\n", encoding="utf-8")
        for index, name in enumerate(names):
            seeds = list(map(int, experiment["load_rate"]["seeds"]))
            start = index * DEFAULT_RATE_SEEDS_PER_SHARD
            shard = seeds[start : start + DEFAULT_RATE_SEEDS_PER_SHARD]
            paths = _paths(root, experiment, index)
            for path in paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable, "-m", "openline_endurance_gate.rate_worker",
                "--experiment", str(exp_path),
                "--seeds", ",".join(map(str, shard)),
                "--cycles", str(paths["cycles"]),
                "--leaves", str(paths["leaves"]),
                "--runs", str(paths["runs"]),
                "--metadata", str(paths["metadata"]),
            ]
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"load-rate shard {index} failed: {completed.stderr or completed.stdout}")
    return finalize_load_rate_shards(root, experiment)
