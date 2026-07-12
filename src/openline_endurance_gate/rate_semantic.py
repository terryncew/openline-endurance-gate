from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .experiment import load_experiment
from .integrity import _artifact_normalize
from .rate_streaming import (
    DEFAULT_RATE_SEEDS_PER_SHARD,
    _paths,
    load_rate_shard_names,
)
from .rate_worker import run_worker
from .receipts import read_chain
from .restoration_stream import _finish_merkle, _finish_merkle_file
from .util import canonical_json, read_csv, sha256_bytes, sha256_file
from .verification import _close, _coerce, _verify_v8_semantics_from_streamed, verify_evidence

SEMANTIC_WORK = ".load_rate_semantic"


def _semantic_paths(work: Path, index: int) -> dict[str, Path]:
    return {
        "cycles": work / f"cycles-{index:03d}.csv.gz",
        "leaves": work / f"leaves-{index:03d}.bin",
        "runs": work / f"runs-{index:03d}.json",
        "report": work / f"report-{index:03d}.json",
    }


def verify_load_rate_shard(
    root: Path,
    shard_index: int,
    *,
    work_dir: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    names = load_rate_shard_names(experiment)
    if shard_index < 0 or shard_index >= len(names):
        raise IndexError(f"load-rate shard index out of range: {shard_index}")
    owned = None
    if work_dir is None:
        if persist:
            work_dir = root / SEMANTIC_WORK
        else:
            owned = tempfile.TemporaryDirectory(prefix="openline-v8-rate-shard-")
            work_dir = Path(owned.name)
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = _semantic_paths(work_dir, shard_index)
    seeds = list(map(int, experiment["load_rate"]["seeds"]))
    start = shard_index * DEFAULT_RATE_SEEDS_PER_SHARD
    shard_seeds = seeds[start : start + DEFAULT_RATE_SEEDS_PER_SHARD]
    metadata = run_worker(experiment, shard_seeds, paths["cycles"], paths["leaves"], paths["runs"])
    fresh_runs = json.loads(paths["runs"].read_text(encoding="utf-8"))
    stored_runs = _coerce(read_csv(root / "results/load_rate_runs.csv"))
    seed_set = set(shard_seeds)
    stored_subset = [row for row in stored_runs if int(row["seed"]) in seed_set]
    stored_cycle = root / "results" / names[shard_index]
    report = {
        "schema": "openline.load-rate.semantic-shard.v1",
        "shard_index": shard_index,
        "seeds": shard_seeds,
        "cycle_count": metadata["cycle_count"],
        "run_count": metadata["run_count"],
        "cycle_artifact": names[shard_index],
        "stored_cycle_sha256": sha256_file(stored_cycle) if stored_cycle.exists() else None,
        "fresh_cycle_sha256": sha256_file(paths["cycles"]),
        "cycle_bytes_match": stored_cycle.exists() and sha256_file(stored_cycle) == sha256_file(paths["cycles"]),
        "run_metrics_match": _close(_artifact_normalize(fresh_runs), stored_subset, 1e-7),
        "leaf_count": paths["leaves"].stat().st_size // 32,
    }
    report["passed"] = bool(
        report["cycle_bytes_match"]
        and report["run_metrics_match"]
        and report["leaf_count"] == report["cycle_count"]
    )
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if owned is not None:
        result = dict(report)
        owned.cleanup()
        return result
    return report


def finalize_load_rate_semantics(root: Path, *, cleanup: bool = True) -> dict[str, Any]:
    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    work = root / SEMANTIC_WORK
    reports: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    total_cycles = 0
    combined = work / "all-leaves.bin"
    with combined.open("wb") as target:
        for index in range(len(load_rate_shard_names(experiment))):
            paths = _semantic_paths(work, index)
            if not all(path.exists() for path in paths.values()):
                raise RuntimeError(f"load-rate semantic shard {index} is incomplete")
            report = json.loads(paths["report"].read_text(encoding="utf-8"))
            reports.append(report)
            total_cycles += int(report["cycle_count"])
            runs.extend(json.loads(paths["runs"].read_text(encoding="utf-8")))
            with paths["leaves"].open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    cycle_root = _finish_merkle_file(combined, total_cycles)
    run_leaves = [sha256_bytes(canonical_json(_artifact_normalize(run))) for run in runs]
    streamed = {
        "cycle_merkle_root": cycle_root,
        "cycle_count": total_cycles,
        "runs": runs,
        "run_merkle_root": _finish_merkle(run_leaves),
        "run_count": len(runs),
    }
    fast = verify_evidence(root, root, full_semantic=False, verify_release=False)
    chain = read_chain(root / "receipts/experiment.jsonl")
    evidence_items = [item for item in chain if item.get("kind") == "evidence_bundle"]
    evidence = evidence_items[0]["payload"] if len(evidence_items) == 1 else {}
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    shard_errors = [
        f"load_rate_cycle_shard_recompute_mismatch:{report['cycle_artifact']}"
        for report in reports if not report.get("passed")
    ]
    semantic_errors = _verify_v8_semantics_from_streamed(
        root, experiment, manifest, evidence, streamed, shard_errors
    )
    result = {
        "valid": bool(fast["valid"] and not semantic_errors),
        "artifact_binding_valid": fast["artifact_binding_valid"],
        "chain": fast["chain"],
        "lineage_binding_valid": fast.get("lineage_binding_valid", False),
        "release_attestation_valid": True,
        "release_attestation": {"valid": True, "skipped": True, "errors": []},
        "semantic_recomputation_valid": not semantic_errors,
        "semantic_shards": reports,
        "errors": list(fast["errors"]) + semantic_errors,
    }
    if cleanup:
        shutil.rmtree(work, ignore_errors=True)
    return result
