#!/usr/bin/env python3
"""Reseal unchanged v0.9.1 evidence under the v0.10.0 tooling source tree.

This command does not claim a new scientific experiment and does not fabricate
a full release report. It updates the source manifest, public witness, and
experiment receipt chain, then writes a candidate report under ``receipts/``.
The detached release attestation remains a separate release-gate step.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate.experiment import V91_SEMANTIC_ARTIFACTS, write_manifest
from openline_endurance_gate.integrity import build_public_witness
from openline_endurance_gate.receipts import (
    ReceiptSigner,
    artifact_hashes,
    create_chain,
    read_chain,
    verify_chain,
    write_anchor,
    write_chain,
)
from openline_endurance_gate.succession import COLE_ALGORITHM_ID, write_json
from openline_endurance_gate.tooling_lineage import verify_v0100_tooling_lineage
from openline_endurance_gate.verification import verify_evidence


def seal(root: Path) -> dict:
    root = root.resolve()
    lineage_errors = verify_v0100_tooling_lineage(root)
    if lineage_errors:
        raise RuntimeError(f"v0.10.0 tooling lineage failed: {lineage_errors}")
    env = dict(os.environ)
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + inherited if inherited else "")
    selftest_path = root / "results/succession_synthetic_selftest.json"
    completed = subprocess.run(
        [sys.executable, "scripts/succession_selftest.py", "--out", str(selftest_path)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"live succession self-test failed: {completed.stderr.strip()}")
    try:
        selftest = json.loads(completed.stdout)
        persisted_selftest = json.loads(selftest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("live succession self-test emitted invalid JSON") from exc
    if persisted_selftest != selftest:
        raise RuntimeError("persisted succession self-test does not match live output")
    if selftest.get("passed") is not True:
        raise RuntimeError("succession synthetic self-test artifact is not passing")

    experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))
    roots = json.loads((root / "results/cycle_roots.json").read_text(encoding="utf-8"))
    additional_roots = {
        key: value
        for key, value in roots.items()
        if key.endswith("_merkle_root")
        and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }

    manifest = write_manifest(root)
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        roots["primary_cycle_merkle_root"],
        roots["amplitude_cycle_merkle_root"],
        additional_roots,
        list(V91_SEMANTIC_ARTIFACTS),
    )
    write_json(root / "results/public_witness.json", public_witness)
    manifest = write_manifest(root)

    semantic_artifacts = list(V91_SEMANTIC_ARTIFACTS) + [
        "V0100_LINEAGE.json",
        "results/succession_synthetic_selftest.json",
        "results/public_witness.json",
        "MANIFEST.json",
    ]
    evidence = {
        "claim": (
            "v0.9.1 scientific artifacts remain unchanged; v0.10.0 adds a separately bounded "
            "COLE succession-calibration tool and synthetic mechanism check"
        ),
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": roots["amplitude_cycle_merkle_root"],
        **additional_roots,
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance recovery-semantic-shard/finalize",
        "claim_boundary": (
            "The succession result is a constructed mechanism check, not deployed-agent evidence. "
            "The preserved recovery result remains synthetic and does not establish a universal retirement threshold."
        ),
    }

    old_chain = read_chain(root / "receipts/experiment.jsonl")
    items = [
        (item["kind"], item["payload"])
        for item in old_chain
        if item["kind"] not in {"evidence_bundle", "succession_calibrator_tooling"}
    ]
    items.append(
        (
            "succession_calibrator_tooling",
            {
                "claim": "a receiver-owned advisory policy can be calibrated from recomputed labeled checkpoints",
                "action": {
                    "cole_algorithm_id": COLE_ALGORITHM_ID,
                    "submitted_samples": selftest["submitted_samples"],
                    "train_samples": selftest["train_samples"],
                    "holdout_samples": selftest["holdout_samples"],
                },
                "result": {
                    "synthetic_only": True,
                    "passed": selftest["passed"],
                    "passed_checks": selftest["passed_check_count"],
                    "total_checks": selftest["check_count"],
                    "automatic_retirement_authorized": False,
                },
                "next_use": "collect matched deployed-agent continue-versus-successor runs and test the held-out falsifier",
            },
        )
    )
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(root / "receipts/experiment.jsonl", chain)
    write_anchor(root / "receipts/experiment.anchor.json", chain, signer)
    chain_result = verify_chain(root / "receipts/experiment.jsonl", root / "receipts/experiment.anchor.json")
    if not chain_result["valid"]:
        raise RuntimeError(f"new experiment chain failed: {chain_result['errors']}")

    verification = verify_evidence(root, root, full_semantic=False, verify_release=False)
    report = {
        "schema": "openline.endurance.succession-tooling-candidate.v1",
        "tooling_version": "0.10.0",
        "scientific_release_preserved": "0.9.1",
        "experiment_chain": chain_result,
        "fast_verification_without_detached_release": verification,
        "succession_selftest": {
            "passed": selftest["passed"],
            "passed_check_count": selftest["passed_check_count"],
            "check_count": selftest["check_count"],
            "claim_boundary": selftest["claim_boundary"],
        },
        "detached_release_status": "PENDING_FULL_RELEASE_GATE",
        "candidate_passed": bool(chain_result["valid"] and verification["valid"] and selftest["passed"]),
    }
    write_json(root / "receipts/succession-candidate-report.json", report)
    if not report["candidate_passed"]:
        raise RuntimeError(f"candidate seal failed: {verification['errors']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    try:
        report = seal(Path(args.root))
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"candidate_passed": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
