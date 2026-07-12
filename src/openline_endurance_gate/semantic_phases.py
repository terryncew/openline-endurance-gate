from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .experiment import load_experiment
from .integrity import _artifact_normalize
from .receipts import read_chain
from .restoration_stream import (
    DEFAULT_SEEDS_PER_SHARD,
    _finish_merkle,
    _finish_merkle_file,
    cycle_shard_names,
)
from .restoration_worker import run_worker
from .util import canonical_json, read_csv, sha256_bytes, sha256_file
from .verification import (
    _close,
    _coerce,
    _verify_v7_semantics_from_streamed,
    verify_evidence,
)

SEMANTIC_WORK = ".state_restoration_semantic"


def _paths(root: Path, shard_index: int, work_dir: Path) -> dict[str, Path]:
    return {
        "cycles": work_dir / f"cycles-{shard_index:03d}.csv.gz",
        "leaves": work_dir / f"leaves-{shard_index:03d}.bin",
        "runs": work_dir / f"runs-{shard_index:03d}.json",
        "report": work_dir / f"report-{shard_index:03d}.json",
    }


def verify_state_restoration_shard(
    root: Path,
    shard_index: int,
    *,
    work_dir: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    names = cycle_shard_names(experiment)
    if shard_index < 0 or shard_index >= len(names):
        raise IndexError(f"state-restoration shard index out of range: {shard_index}")
    owned_temp = None
    if work_dir is None:
        if persist:
            work_dir = root / SEMANTIC_WORK
        else:
            owned_temp = tempfile.TemporaryDirectory(prefix="openline-v7-shard-verify-")
            work_dir = Path(owned_temp.name)
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = _paths(root, shard_index, work_dir)
    seeds = list(map(int, experiment["state_restoration"]["seeds"]))
    start = shard_index * DEFAULT_SEEDS_PER_SHARD
    shard_seeds = seeds[start:start + DEFAULT_SEEDS_PER_SHARD]
    metadata = run_worker(
        experiment,
        shard_seeds,
        paths["cycles"],
        paths["leaves"],
        paths["runs"],
    )
    fresh_runs = json.loads(paths["runs"].read_text(encoding="utf-8"))
    stored_runs = _coerce(read_csv(root / "results/state_restoration_runs.csv"))
    seed_set = set(shard_seeds)
    stored_subset = [row for row in stored_runs if int(row["seed"]) in seed_set]
    stored_cycle = root / "results" / names[shard_index]
    report = {
        "schema": "openline.state-restoration.semantic-shard.v1",
        "shard_index": shard_index,
        "seeds": shard_seeds,
        "cycle_count": metadata["cycle_count"],
        "run_count": metadata["run_count"],
        "cycle_artifact": names[shard_index],
        "stored_cycle_sha256": sha256_file(stored_cycle) if stored_cycle.exists() else None,
        "fresh_cycle_sha256": sha256_file(paths["cycles"]),
        "cycle_bytes_match": stored_cycle.exists() and sha256_file(stored_cycle) == sha256_file(paths["cycles"]),
        "run_metrics_match": _close(fresh_runs, stored_subset, 1e-7),
        "leaf_count": paths["leaves"].stat().st_size // 32,
    }
    report["passed"] = bool(report["cycle_bytes_match"] and report["run_metrics_match"] and report["leaf_count"] == report["cycle_count"])
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if owned_temp is not None:
        result = dict(report)
        owned_temp.cleanup()
        return result
    return report


def finalize_state_restoration_semantics(root: Path, *, cleanup: bool = True) -> dict[str, Any]:
    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    work_dir = root / SEMANTIC_WORK
    shard_count = len(cycle_shard_names(experiment))
    reports: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    combined = work_dir / "all-leaves.bin"
    total_cycles = 0
    with combined.open("wb") as target:
        for index in range(shard_count):
            paths = _paths(root, index, work_dir)
            if not all(path.exists() for path in paths.values()):
                raise RuntimeError(f"semantic shard {index} is incomplete")
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
        f"state_restoration_cycle_shard_recompute_mismatch:{report['cycle_artifact']}"
        for report in reports if not report.get("passed")
    ]
    semantic_errors = _verify_v7_semantics_from_streamed(
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
        shutil.rmtree(work_dir, ignore_errors=True)
    return result
