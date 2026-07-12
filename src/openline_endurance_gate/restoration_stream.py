from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .integrity import _artifact_normalize
from .util import canonical_json, sha256_bytes

DEFAULT_SEEDS_PER_SHARD = 12


def _finish_merkle(leaves: list[str]) -> str:
    if not leaves:
        return sha256_bytes(b"")
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [
            sha256_bytes(bytes.fromhex(level[index]) + bytes.fromhex(level[index + 1]))
            for index in range(0, len(level), 2)
        ]
    return level[0]


def _finish_merkle_file(leaf_path: Path, count: int) -> str:
    if count == 0:
        return sha256_bytes(b"")
    current_path = leaf_path
    current_count = count
    level = 0
    while current_count > 1:
        next_path = leaf_path.with_name(f"{leaf_path.name}.level{level + 1}")
        with current_path.open("rb") as source, next_path.open("wb") as target:
            produced = 0
            while produced < current_count:
                left = source.read(32)
                if len(left) != 32:
                    raise RuntimeError("truncated Merkle leaf file")
                right = source.read(32)
                if len(right) != 32:
                    right = left
                target.write(bytes.fromhex(sha256_bytes(left + right)))
                produced += 2
        if current_path != leaf_path:
            current_path.unlink(missing_ok=True)
        current_path = next_path
        current_count = (current_count + 1) // 2
        level += 1
    with current_path.open("rb") as source:
        root = source.read(32)
        if len(root) != 32 or source.read(1):
            raise RuntimeError("invalid final Merkle level")
    if current_path != leaf_path:
        current_path.unlink(missing_ok=True)
    return root.hex()


def cycle_shard_names(experiment: dict[str, Any], seeds_per_shard: int = DEFAULT_SEEDS_PER_SHARD) -> list[str]:
    seed_count = len(experiment["state_restoration"]["seeds"])
    shard_count = (seed_count + seeds_per_shard - 1) // seeds_per_shard
    return [f"state_restoration_cycles.part-{index:03d}.csv.gz" for index in range(shard_count)]


def stream_state_restoration(
    experiment: dict[str, Any],
    cycle_base_path: Path | None = None,
    *,
    seeds_per_shard: int = DEFAULT_SEEDS_PER_SHARD,
) -> dict[str, Any]:
    """Run the frozen simulator in bounded deterministic worker processes."""
    config = experiment["state_restoration"]
    seeds = list(map(int, config["seeds"]))
    runs: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    run_leaves: list[str] = []
    total_cycles = 0

    with tempfile.TemporaryDirectory(prefix="openline-v7-stream-") as temp_name:
        temp_dir = Path(temp_name)
        experiment_path = temp_dir / "experiment.json"
        experiment_path.write_text(json.dumps(experiment, sort_keys=True) + "\n", encoding="utf-8")
        leaf_paths: list[Path] = []

        for shard_index, start in enumerate(range(0, len(seeds), seeds_per_shard)):
            shard_seeds = seeds[start:start + seeds_per_shard]
            name = cycle_shard_names(experiment, seeds_per_shard)[shard_index]
            cycle_path = (
                cycle_base_path.parent / name
                if cycle_base_path is not None
                else temp_dir / name
            )
            leaf_path = temp_dir / f"leaves-{shard_index:03d}.bin"
            runs_path = temp_dir / f"runs-{shard_index:03d}.json"
            metadata_path = temp_dir / f"metadata-{shard_index:03d}.json"
            command = [
                sys.executable, "-m", "openline_endurance_gate.restoration_worker",
                "--experiment", str(experiment_path),
                "--seeds", ",".join(map(str, shard_seeds)),
                "--cycles", str(cycle_path),
                "--leaves", str(leaf_path),
                "--runs", str(runs_path),
                "--metadata", str(metadata_path),
            ]
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"state-restoration shard {shard_index} failed: {completed.stderr or completed.stdout}"
                )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            shard_runs = json.loads(runs_path.read_text(encoding="utf-8"))
            total_cycles += int(metadata["cycle_count"])
            runs.extend(shard_runs)
            leaf_paths.append(leaf_path)
            artifact_paths.append(cycle_path)

        combined_leaves = temp_dir / "all-cycle-leaves.bin"
        with combined_leaves.open("wb") as target:
            for path in leaf_paths:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        cycle_root = _finish_merkle_file(combined_leaves, total_cycles)

    for run in runs:
        run_leaves.append(sha256_bytes(canonical_json(_artifact_normalize(run))))
    return {
        "cycle_merkle_root": cycle_root,
        "cycle_count": total_cycles,
        "cycle_artifacts": [str(path) for path in artifact_paths],
        "runs": runs,
        "run_merkle_root": _finish_merkle(run_leaves),
        "run_count": len(runs),
    }


def _shard_paths(root: Path, experiment: dict[str, Any], shard_index: int) -> dict[str, Path]:
    work = root / "results" / ".state_restoration_work"
    return {
        "cycles": root / "results" / cycle_shard_names(experiment)[shard_index],
        "leaves": work / f"leaves-{shard_index:03d}.bin",
        "runs": work / f"runs-{shard_index:03d}.json",
        "metadata": work / f"metadata-{shard_index:03d}.json",
    }


def generate_state_restoration_shard(root: Path, experiment: dict[str, Any], shard_index: int) -> dict[str, Any]:
    """Generate one bounded 12-seed evidence shard in the current process."""
    from .restoration_worker import run_worker

    seeds = list(map(int, experiment["state_restoration"]["seeds"]))
    start = shard_index * DEFAULT_SEEDS_PER_SHARD
    shard_seeds = seeds[start:start + DEFAULT_SEEDS_PER_SHARD]
    if not shard_seeds:
        raise IndexError(f"state-restoration shard index out of range: {shard_index}")
    paths = _shard_paths(root, experiment, shard_index)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    metadata = run_worker(
        experiment,
        shard_seeds,
        paths["cycles"],
        paths["leaves"],
        paths["runs"],
    )
    paths["metadata"].write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return {**metadata, "shard_index": shard_index, "cycle_artifact": str(paths["cycles"])}


def state_restoration_shards_ready(root: Path, experiment: dict[str, Any]) -> bool:
    return all(
        all(path.exists() for path in _shard_paths(root, experiment, index).values())
        for index in range(len(cycle_shard_names(experiment)))
    )


def finalize_state_restoration_shards(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    """Combine already generated shard witnesses without rerunning science."""
    if not state_restoration_shards_ready(root, experiment):
        raise RuntimeError("state-restoration shards are incomplete")
    work = root / "results" / ".state_restoration_work"
    combined = work / "all-cycle-leaves.bin"
    runs: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    total_cycles = 0
    with combined.open("wb") as target:
        for index in range(len(cycle_shard_names(experiment))):
            paths = _shard_paths(root, experiment, index)
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            shard_runs = json.loads(paths["runs"].read_text(encoding="utf-8"))
            total_cycles += int(metadata["cycle_count"])
            runs.extend(shard_runs)
            artifact_paths.append(paths["cycles"])
            with paths["leaves"].open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    cycle_root = _finish_merkle_file(combined, total_cycles)
    run_leaves = [sha256_bytes(canonical_json(_artifact_normalize(run))) for run in runs]
    return {
        "cycle_merkle_root": cycle_root,
        "cycle_count": total_cycles,
        "cycle_artifacts": [str(path) for path in artifact_paths],
        "runs": runs,
        "run_merkle_root": _finish_merkle(run_leaves),
        "run_count": len(runs),
    }
