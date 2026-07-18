"""Verify that a tooling-only release preserves the v0.9.1 scientific set."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .experiment import V91_SEMANTIC_ARTIFACTS
from .util import canonical_json, sha256_bytes, sha256_file


HASH256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def verify_v0100_tooling_lineage(root: Path) -> list[str]:
    path = root / "V0100_LINEAGE.json"
    if not path.exists():
        return ["v0100_lineage_missing"]
    try:
        lineage: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["v0100_lineage_invalid_json"]

    errors: list[str] = []
    if lineage.get("schema") != "openline.endurance.tooling-lineage.v1":
        errors.append("v0100_lineage_schema_invalid")
    if lineage.get("tooling_release") != "0.10.0" or lineage.get("base_release") != "0.9.1":
        errors.append("v0100_lineage_release_invalid")
    if not isinstance(lineage.get("base_commit"), str) or not COMMIT.fullmatch(lineage["base_commit"]):
        errors.append("v0100_lineage_base_commit_invalid")
    if lineage.get("scientific_result_changed") is not False:
        errors.append("v0100_lineage_change_boundary_invalid")

    wrapper_hashes = lineage.get("base_wrapper_hashes")
    if not isinstance(wrapper_hashes, dict) or any(
        not isinstance(value, str) or not HASH256.fullmatch(value)
        for value in wrapper_hashes.values()
    ):
        errors.append("v0100_lineage_wrapper_hashes_invalid")

    hashes: dict[str, str] = {}
    for relative in sorted(V91_SEMANTIC_ARTIFACTS):
        artifact = root / relative
        if not artifact.exists():
            errors.append(f"v0100_scientific_artifact_missing:{relative}")
        else:
            hashes[relative] = sha256_file(artifact)
    if lineage.get("scientific_artifact_count") != len(V91_SEMANTIC_ARTIFACTS):
        errors.append("v0100_scientific_artifact_count_mismatch")
    if lineage.get("scientific_artifact_hash_map_digest_algorithm") != "sha256-canonical-path-hash-map-v1":
        errors.append("v0100_scientific_digest_algorithm_invalid")
    if len(hashes) == len(V91_SEMANTIC_ARTIFACTS):
        digest = sha256_bytes(canonical_json(hashes))
        if digest != lineage.get("scientific_artifact_hash_map_digest"):
            errors.append("v0100_scientific_artifact_digest_mismatch")
    return errors

