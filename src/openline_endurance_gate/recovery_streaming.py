from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .integrity import _artifact_normalize
from .restoration_stream import _finish_merkle, _finish_merkle_file
from .util import canonical_json, sha256_bytes

DEFAULT_RECOVERY_SEEDS_PER_SHARD = 8


def _work_dir(root: Path) -> Path:
    suffix = sha256_bytes(str(root.resolve()).encode("utf-8"))[:12]
    return Path(tempfile.gettempdir()) / f"openline-v9-recovery-work-{suffix}"


@dataclass(frozen=True)
class CountedRows:
    count: int

    def __len__(self) -> int:
        return self.count


def recovery_shard_names(experiment: dict[str, Any]) -> list[str]:
    count = len(experiment["recovery"]["seeds"])
    shards = (count + DEFAULT_RECOVERY_SEEDS_PER_SHARD - 1) // DEFAULT_RECOVERY_SEEDS_PER_SHARD
    return [f"recovery_cycles.part-{index:03d}.csv.gz" for index in range(shards)]


def _paths(root: Path, experiment: dict[str, Any], index: int) -> dict[str, Path]:
    work = _work_dir(root)
    result = {
        "cycles": root / "results" / recovery_shard_names(experiment)[index],
        "leaves": work / f"leaves-{index:03d}.bin",
        "runs": work / f"runs-{index:03d}.json",
        "handoffs": work / f"handoffs-{index:03d}.json",
        "metadata": work / f"metadata-{index:03d}.json",
    }
    return result


def generate_recovery_shard(root: Path, experiment: dict[str, Any], index: int) -> dict[str, Any]:
    from .recovery_worker import run_worker

    seeds = list(map(int, experiment["recovery"]["seeds"]))
    start = index * DEFAULT_RECOVERY_SEEDS_PER_SHARD
    shard = seeds[start:start + DEFAULT_RECOVERY_SEEDS_PER_SHARD]
    if not shard:
        raise IndexError(f"recovery shard index out of range: {index}")
    paths = _paths(root, experiment, index)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    metadata = run_worker(
        experiment, shard, paths["cycles"], paths["leaves"], paths["runs"], paths["handoffs"],
    )
    paths["metadata"].write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return {**metadata, "shard_index": index, "cycle_artifact": paths["cycles"].name}


def recovery_shards_ready(root: Path, experiment: dict[str, Any]) -> bool:
    return all(
        all(path.exists() for path in _paths(root, experiment, index).values())
        for index in range(len(recovery_shard_names(experiment)))
    )


def finalize_recovery_shards(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    from .recovery_worker import semantic_handoff

    if not recovery_shards_ready(root, experiment):
        raise RuntimeError("recovery shards are incomplete")
    work = _work_dir(root)
    combined = work / "all-cycle-leaves.bin"
    runs: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    total_cycles = 0
    artifacts: list[str] = []
    with combined.open("wb") as target:
        for index, name in enumerate(recovery_shard_names(experiment)):
            paths = _paths(root, experiment, index)
            metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            total_cycles += int(metadata["cycle_count"])
            runs.extend(json.loads(paths["runs"].read_text(encoding="utf-8")))
            handoffs.extend(json.loads(paths["handoffs"].read_text(encoding="utf-8")))
            artifacts.append(str(paths["cycles"]))
            with paths["leaves"].open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    run_leaves = [sha256_bytes(canonical_json(_artifact_normalize(row))) for row in runs]
    handoff_leaves = [sha256_bytes(canonical_json(_artifact_normalize(semantic_handoff(row)))) for row in handoffs]
    result = {
        "cycle_merkle_root": _finish_merkle_file(combined, total_cycles), "cycle_count": total_cycles,
        "cycle_artifacts": artifacts, "runs": runs, "run_merkle_root": _finish_merkle(run_leaves),
        "run_count": len(runs), "handoffs": handoffs,
        "handoff_semantic_merkle_root": _finish_merkle(handoff_leaves), "handoff_count": len(handoffs),
        "seed_chunk_size": DEFAULT_RECOVERY_SEEDS_PER_SHARD,
        "execution_boundary": "Deterministic rows are generated in eight-seed shards; environment-sensitive timing fields are separately observed.",
    }
    shutil.rmtree(work, ignore_errors=True)
    return result


def stream_recovery(experiment: dict[str, Any], root: Path) -> dict[str, Any]:
    for index in range(len(recovery_shard_names(experiment))):
        generate_recovery_shard(root, experiment, index)
    return finalize_recovery_shards(root, experiment)
