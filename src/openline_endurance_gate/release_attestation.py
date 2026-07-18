from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .receipts import (
    ReceiptSigner,
    artifact_hashes,
    create_chain,
    read_chain,
    verify_chain,
    write_anchor,
    write_chain,
)
from .util import sha256_file


RELEASE_REPORTS = ("RUN_REPORT.json", "TAMPER_REPORT.json")


def verify_release_attestation(root: Path) -> dict[str, Any]:
    """Verify the detached outer receipt that binds post-run reports.

    The experiment chain cannot include ``RUN_REPORT.json`` because that report
    describes the already-sealed experiment chain. A one-receipt outer chain
    closes that ordering gap without pretending to solve whole-repository
    replacement; its digest still needs independent publication for that.
    """
    root = root.resolve()
    chain_path = root / "receipts/release.jsonl"
    anchor_path = root / "receipts/release.anchor.json"
    errors: list[str] = []
    if not chain_path.exists():
        errors.append("release_attestation_missing_chain")
    if not anchor_path.exists():
        errors.append("release_attestation_missing_anchor")
    if errors:
        return {"valid": False, "chain": None, "errors": errors}

    chain_result = verify_chain(chain_path, anchor_path)
    if not chain_result["valid"]:
        errors.extend(f"release_attestation_chain:{error}" for error in chain_result["errors"])
    chain = read_chain(chain_path)
    if len(chain) != 1 or chain[0].get("kind") != "release_attestation":
        errors.append("release_attestation_receipt_shape_mismatch")
        payload: dict[str, Any] = {}
    else:
        payload = chain[0].get("payload", {})
    if payload.get("schema") != "openline.endurance.release-attestation.v1":
        errors.append("release_attestation_schema_invalid")

    expected_hashes = payload.get("artifact_hashes", {})
    if set(expected_hashes) != set(RELEASE_REPORTS):
        errors.append("release_attestation_artifact_set_mismatch")
    reports: dict[str, dict[str, Any]] = {}
    for relative in RELEASE_REPORTS:
        path = root / relative
        if not path.exists():
            errors.append(f"release_attestation_missing_artifact:{relative}")
            continue
        if sha256_file(path) != expected_hashes.get(relative):
            errors.append(f"release_attestation_artifact_hash_mismatch:{relative}")
        try:
            reports[relative] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"release_attestation_invalid_json:{relative}")

    experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    if payload.get("release_version") != experiment.get("release_version"):
        errors.append("release_attestation_version_mismatch")
    experiment_chain = verify_chain(
        root / "receipts/experiment.jsonl", root / "receipts/experiment.anchor.json"
    )
    if not experiment_chain["valid"]:
        errors.append("release_attestation_experiment_chain_invalid")
    if payload.get("experiment_chain_digest") != experiment_chain.get("chain_digest"):
        errors.append("release_attestation_experiment_chain_digest_mismatch")
    if payload.get("experiment_tail_hash") != experiment_chain.get("tail_hash"):
        errors.append("release_attestation_experiment_tail_mismatch")

    witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
    if payload.get("public_witness_digest") != witness.get("witness_digest"):
        errors.append("release_attestation_public_witness_mismatch")
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if payload.get("source_tree_digest") != manifest.get("source_tree_digest"):
        errors.append("release_attestation_source_tree_mismatch")
    if payload.get("preregistration_sha256") != sha256_file(root / "PREREGISTRATION.json"):
        errors.append("release_attestation_preregistration_mismatch")

    run_report = reports.get("RUN_REPORT.json", {})
    tamper_report = reports.get("TAMPER_REPORT.json", {})
    if run_report.get("passed") is not True:
        errors.append("release_attestation_run_report_not_passed")
    if tamper_report.get("passed") is not True:
        errors.append("release_attestation_tamper_report_not_passed")
    if run_report.get("tamper_suite", {}).get("report") != tamper_report:
        errors.append("release_attestation_embedded_tamper_report_mismatch")
    if run_report.get("tamper_suite", {}).get("returncode") != 0:
        errors.append("release_attestation_tamper_returncode_mismatch")
    tooling_version = payload.get("tooling_version")
    if tooling_version is not None and tooling_version != run_report.get("tooling_version"):
        errors.append("release_attestation_tooling_version_mismatch")
    release_status = payload.get("release_status")
    if release_status is not None and release_status != run_report.get("release_status"):
        errors.append("release_attestation_status_mismatch")
    semantic = run_report.get("semantic_verification", {})
    if semantic.get("valid") is not True:
        errors.append("release_attestation_semantic_report_not_valid")
    if semantic.get("chain", {}).get("chain_digest") != experiment_chain.get("chain_digest"):
        errors.append("release_attestation_reported_chain_digest_mismatch")
    if semantic.get("chain", {}).get("tail_hash") != experiment_chain.get("tail_hash"):
        errors.append("release_attestation_reported_chain_tail_mismatch")
    if tamper_report.get("release_version") != experiment.get("release_version"):
        errors.append("release_attestation_tamper_version_mismatch")

    return {"valid": not errors, "chain": chain_result, "payload": payload, "errors": errors}


def write_release_attestation(root: Path) -> dict[str, Any]:
    """Create a detached signed receipt after release reports are final."""
    root = root.resolve()
    for relative in RELEASE_REPORTS:
        if not (root / relative).exists():
            raise RuntimeError(f"cannot attest missing release report: {relative}")
    experiment_chain = verify_chain(
        root / "receipts/experiment.jsonl", root / "receipts/experiment.anchor.json"
    )
    if not experiment_chain["valid"]:
        raise RuntimeError(f"cannot attest invalid experiment chain: {experiment_chain['errors']}")
    experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    run_report = json.loads((root / "RUN_REPORT.json").read_text(encoding="utf-8"))
    payload = {
        "schema": "openline.endurance.release-attestation.v1",
        "release_version": experiment.get("release_version"),
        "artifact_hashes": artifact_hashes(root, list(RELEASE_REPORTS)),
        "experiment_chain_digest": experiment_chain["chain_digest"],
        "experiment_tail_hash": experiment_chain["tail_hash"],
        "public_witness_digest": witness["witness_digest"],
        "source_tree_digest": manifest["source_tree_digest"],
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "tooling_version": run_report.get("tooling_version"),
        "release_status": run_report.get("release_status"),
        "claim_boundary": (
            "This outer receipt detects later release-report edits under the pinned release key. "
            "Independent publication of its anchor hash is still required to resist whole-repository replacement."
        ),
    }
    signer = ReceiptSigner.generate()
    chain = create_chain([("release_attestation", payload)], signer)
    write_chain(root / "receipts/release.jsonl", chain)
    write_anchor(root / "receipts/release.anchor.json", chain, signer)
    result = verify_release_attestation(root)
    if not result["valid"]:
        raise RuntimeError(f"release attestation failed after creation: {result['errors']}")
    return result
