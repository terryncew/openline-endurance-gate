from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import canonical_json, sha256_bytes, sha256_file


def _artifact_normalize(value: Any) -> Any:
    """Normalize equivalent CSV/JSON representations before hashing.

    CSV round-trips encode absent optional values as an empty field, while the
    verifier loads them as ``None``. Tuples also become JSON arrays. These are
    representation differences, not scientific differences, so Merkle binding
    uses one canonical form.
    """
    if value == "":
        return None
    if isinstance(value, dict):
        return {key: _artifact_normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_artifact_normalize(item) for item in value]
    return value


def merkle_root(rows: list[dict[str, Any]]) -> str:
    leaves = [sha256_bytes(canonical_json(_artifact_normalize(row))) for row in rows]
    if not leaves:
        return sha256_bytes(b"")
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [sha256_bytes(bytes.fromhex(level[index]) + bytes.fromhex(level[index + 1])) for index in range(0, len(level), 2)]
    return level[0]


def verify_preregistration(root: Path) -> list[str]:
    errors: list[str] = []
    path = root / "PREREGISTRATION.json"
    if not path.exists():
        return ["preregistration_missing"]
    prereg = json.loads(path.read_text(encoding="utf-8"))
    if prereg.get("schema") != "openline.endurance.preregistration.v1":
        errors.append("preregistration_schema_invalid")
    experiment_path = root / "experiment.json"
    if not experiment_path.exists() or sha256_file(experiment_path) != prereg.get("experiment_sha256"):
        errors.append("preregistration_experiment_hash_mismatch")
    for relative, expected in prereg.get("mechanism_hashes", {}).items():
        candidate = root / relative
        if not candidate.exists():
            errors.append(f"preregistration_mechanism_missing:{relative}")
        elif sha256_file(candidate) != expected:
            errors.append(f"preregistration_mechanism_hash_mismatch:{relative}")
    experiment = json.loads(experiment_path.read_text(encoding="utf-8")) if experiment_path.exists() else {}
    locked = prereg.get("locked_design", {})
    for key, expected in locked.items():
        if experiment.get(key) != expected:
            errors.append(f"preregistration_locked_design_mismatch:{key}")
    return errors


def build_public_witness(
    root: Path,
    experiment: dict[str, Any],
    summary: dict[str, Any],
    source_tree_digest: str,
    cycle_merkle_root: str,
    amplitude_cycle_merkle_root: str,
    additional_roots: dict[str, str] | None,
    semantic_artifacts: list[str],
) -> dict[str, Any]:
    body = {
        "schema": "openline.endurance.public-witness.v1",
        "release_version": experiment.get("release_version"),
        "experiment_sha256": sha256_file(root / "experiment.json"),
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "source_tree_digest": source_tree_digest,
        "primary_cycle_merkle_root": cycle_merkle_root,
        "amplitude_cycle_merkle_root": amplitude_cycle_merkle_root,
        "additional_roots": dict(sorted((additional_roots or {}).items())),
        "theory_status": summary["theory_status"],
        "passed_gate_count": summary["passed_gate_count"],
        "gate_count": summary["gate_count"],
        "semantic_artifact_hashes": {relative: sha256_file(root / relative) for relative in sorted(semantic_artifacts)},
        "external_anchor_status": "UNPUBLISHED_LOCAL_WITNESS",
        "claim_boundary": "Publishing this witness hash outside the repository can make later whole-repository replacement detectable. The local file alone is self-declared.",
    }
    return {**body, "witness_digest": sha256_bytes(canonical_json(body))}
