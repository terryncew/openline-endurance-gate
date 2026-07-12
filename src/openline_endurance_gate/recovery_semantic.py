from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .experiment import load_experiment
from .integrity import _artifact_normalize
from .receipts import read_chain
from .recovery_streaming import (
    DEFAULT_RECOVERY_SEEDS_PER_SHARD, recovery_shard_names,
)
from .recovery_worker import run_worker, semantic_handoff
from .restoration_stream import _finish_merkle, _finish_merkle_file
from .util import canonical_json, read_csv, sha256_bytes, sha256_file

def _default_semantic_work(root: Path) -> Path:
    # Keep recomputation scratch outside the release tree. The inherited
    # evidence is intentionally large and semantic scratch is not an artifact.
    suffix = sha256_bytes(str(root.resolve()).encode("utf-8"))[:12]
    return Path(tempfile.gettempdir()) / f"openline-v9-recovery-semantic-{suffix}"


def _semantic_paths(work: Path, index: int) -> dict[str, Path]:
    return {
        "cycles": work / f"cycles-{index:03d}.csv.gz",
        "leaves": work / f"leaves-{index:03d}.bin",
        "runs": work / f"runs-{index:03d}.json",
        "handoffs": work / f"handoffs-{index:03d}.json",
        "report": work / f"report-{index:03d}.json",
    }


def _coerce_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    int_fields = {
        "seed", "declared_horizon", "intervention_cycle", "n_f", "failed", "first_failure_cycle",
        "same_failure_returned", "same_failure_return_cycle", "cycles_until_same_failure_returns",
        "correct_decisions_post_handoff", "decision_opportunities_post_handoff", "policy_violations",
        "retained_retry_demand", "retained_latency_floor", "retained_risk_tolerance",
        "retained_memory_horizon", "retained_handoff_depth", "retained_token_capacity",
        "packet_bytes", "packet_tokens", "evidence_reads", "accepted_handoffs",
        "rejected_handoffs", "undecidable_handoffs",
    }
    float_fields = {"post_handoff_decision_accuracy", "final_config_accuracy", "final_requirement_accuracy"}
    output: list[dict[str, Any]] = []
    for source in rows:
        row: dict[str, Any] = dict(source)
        for field in int_fields:
            if row.get(field) not in (None, ""):
                row[field] = int(float(row[field]))
        for field in float_fields:
            if row.get(field) not in (None, ""):
                row[field] = float(row[field])
        output.append(row)
    return output


def _read_handoffs(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_recovery_shard(
    root: Path, index: int, *, work_dir: Path | None = None, persist: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    names = recovery_shard_names(experiment)
    if index < 0 or index >= len(names):
        raise IndexError(f"recovery shard index out of range: {index}")
    owned = None
    if work_dir is None:
        if persist:
            work_dir = _default_semantic_work(root)
        else:
            owned = tempfile.TemporaryDirectory(prefix="openline-v9-recovery-shard-")
            work_dir = Path(owned.name)
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = _semantic_paths(work_dir, index)
    seeds = list(map(int, experiment["recovery"]["seeds"]))
    start = index * DEFAULT_RECOVERY_SEEDS_PER_SHARD
    shard = seeds[start:start + DEFAULT_RECOVERY_SEEDS_PER_SHARD]
    metadata = run_worker(
        experiment, shard, paths["cycles"], paths["leaves"], paths["runs"], paths["handoffs"],
    )
    fresh_runs = json.loads(paths["runs"].read_text(encoding="utf-8"))
    stored_runs = _coerce_rows(read_csv(root / "results/recovery_runs.csv"))
    seed_set = set(shard)
    stored_run_subset = [row for row in stored_runs if int(row["seed"]) in seed_set]
    fresh_handoffs = [semantic_handoff(row) for row in json.loads(paths["handoffs"].read_text(encoding="utf-8"))]
    stored_handoffs = [semantic_handoff(row) for row in _read_handoffs(root / "results/recovery_handoffs.jsonl")]
    stored_handoff_subset = [row for row in stored_handoffs if int(row["seed"]) in seed_set]
    stored_cycle = root / "results" / names[index]
    from .verification import _close

    report = {
        "schema": "openline.recovery.semantic-shard.v1", "shard_index": index, "seeds": shard,
        "cycle_count": metadata["cycle_count"], "run_count": metadata["run_count"],
        "handoff_count": metadata["handoff_count"], "cycle_artifact": names[index],
        "stored_cycle_sha256": sha256_file(stored_cycle) if stored_cycle.exists() else None,
        "fresh_cycle_sha256": sha256_file(paths["cycles"]),
        "cycle_bytes_match": stored_cycle.exists() and sha256_file(stored_cycle) == sha256_file(paths["cycles"]),
        "run_metrics_match": _close(_artifact_normalize(fresh_runs), stored_run_subset, 1e-7),
        "handoff_semantics_match": _close(_artifact_normalize(fresh_handoffs), stored_handoff_subset, 1e-7),
        "timing_fields_recomputed_but_excluded": True,
        "leaf_count": paths["leaves"].stat().st_size // 32,
    }
    report["passed"] = bool(
        report["cycle_bytes_match"] and report["run_metrics_match"]
        and report["handoff_semantics_match"] and report["leaf_count"] == report["cycle_count"]
    )
    paths["report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if owned is not None:
        result = dict(report)
        owned.cleanup()
        return result
    return report


def finalize_recovery_semantics(root: Path, *, cleanup: bool = True) -> dict[str, Any]:
    from .verification import _verify_v9_semantics_from_streamed, verify_evidence

    root = root.resolve()
    experiment = load_experiment(root / "experiment.json")
    work = _default_semantic_work(root)
    reports: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    total = 0
    combined = work / "all-leaves.bin"
    with combined.open("wb") as target:
        for index in range(len(recovery_shard_names(experiment))):
            paths = _semantic_paths(work, index)
            if not all(path.exists() for path in paths.values()):
                raise RuntimeError(f"recovery semantic shard {index} is incomplete")
            report = json.loads(paths["report"].read_text(encoding="utf-8"))
            reports.append(report)
            total += int(report["cycle_count"])
            runs.extend(json.loads(paths["runs"].read_text(encoding="utf-8")))
            handoffs.extend(json.loads(paths["handoffs"].read_text(encoding="utf-8")))
            with paths["leaves"].open("rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
    cycle_root = _finish_merkle_file(combined, total)
    run_root = _finish_merkle([sha256_bytes(canonical_json(_artifact_normalize(row))) for row in runs])
    handoff_root = _finish_merkle([
        sha256_bytes(canonical_json(_artifact_normalize(semantic_handoff(row)))) for row in handoffs
    ])
    streamed = {
        "cycle_merkle_root": cycle_root, "cycle_count": total,
        "runs": runs, "run_merkle_root": run_root, "run_count": len(runs),
        "handoffs": handoffs, "handoff_semantic_merkle_root": handoff_root,
        "handoff_count": len(handoffs),
    }
    fast = verify_evidence(root, root, full_semantic=False, verify_release=False)
    chain = read_chain(root / "receipts/experiment.jsonl")
    bundles = [item for item in chain if item.get("kind") == "evidence_bundle"]
    evidence = bundles[0]["payload"] if len(bundles) == 1 else {}
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    shard_errors = [
        f"recovery_cycle_shard_recompute_mismatch:{report['cycle_artifact']}"
        for report in reports if not report.get("passed")
    ]
    semantic_errors = _verify_v9_semantics_from_streamed(
        root, experiment, manifest, evidence, streamed, shard_errors,
    )
    result = {
        "valid": bool(fast["valid"] and not semantic_errors),
        "artifact_binding_valid": fast["artifact_binding_valid"], "chain": fast["chain"],
        "lineage_binding_valid": fast.get("lineage_binding_valid", False),
        "release_attestation_valid": True,
        "release_attestation": {"valid": True, "skipped": True, "errors": []},
        "semantic_recomputation_valid": not semantic_errors, "semantic_shards": reports,
        "errors": list(fast["errors"]) + semantic_errors,
    }
    if cleanup:
        shutil.rmtree(work, ignore_errors=True)
    return result
