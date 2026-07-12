import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openline_endurance_gate.receipts import ReceiptSigner, create_chain, read_chain, verify_chain, write_anchor, write_chain
from openline_endurance_gate.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def test_default_receipt_chain_is_signed_and_complete():
    chain = read_chain(ROOT / "receipts/experiment.jsonl")
    result = verify_chain(ROOT / "receipts/experiment.jsonl", ROOT / "receipts/experiment.anchor.json")
    runs = len((ROOT / "results/runs.csv").read_text().splitlines()) - 1
    amplitude_runs = len((ROOT / "results/amplitude_runs.csv").read_text().splitlines()) - 1
    assert result["valid"]
    assert result["completeness_verified"]
    assert len(chain) == 2 + runs + amplitude_runs + 5
    assert sum(receipt["kind"] == "collision_aware_spacing" for receipt in chain) == 1


def test_tail_deletion_fails_completeness(tmp_path):
    chain = read_chain(ROOT / "receipts/experiment.jsonl")
    path = tmp_path / "chain.jsonl"
    anchor = tmp_path / "anchor.json"
    path.write_text("\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in chain[:-1]) + "\n")
    shutil.copy2(ROOT / "receipts/experiment.anchor.json", anchor)
    result = verify_chain(path, anchor)
    assert not result["valid"]
    assert any(error.startswith("completeness") for error in result["errors"])


@pytest.mark.integration
def test_semantic_recompute_catches_resealed_gate_forgery(tmp_path):
    forged = tmp_path / "repo"
    shutil.copytree(ROOT, forged, ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.egg-info"))
    summary_path = forged / "results/summary.json"
    summary = json.loads(summary_path.read_text())
    target = summary["gates"]["tip_capture/geometry_adds_heldout_prediction"]
    target["passed"] = not target["passed"]
    summary["passed_gate_count"] = sum(int(gate["passed"]) for gate in summary["gates"].values())
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    manifest_path = forged / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["entries"]:
        if entry["path"] == "results/summary.json":
            entry["sha256"] = sha256_file(summary_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    old_chain = read_chain(forged / "receipts/experiment.jsonl")
    items = []
    for receipt in old_chain:
        payload = receipt["payload"]
        if receipt["kind"] == "evidence_bundle":
            payload = dict(payload)
            hashes = dict(payload["artifact_hashes"])
            hashes["results/summary.json"] = sha256_file(summary_path)
            hashes["MANIFEST.json"] = sha256_file(manifest_path)
            payload["artifact_hashes"] = hashes
        items.append((receipt["kind"], payload))
    attacker = ReceiptSigner.generate()
    new_chain = create_chain(items, attacker)
    write_chain(forged / "receipts/experiment.jsonl", new_chain)
    write_anchor(forged / "receipts/experiment.anchor.json", new_chain, attacker)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(forged / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "openline_endurance_gate",
            "verify",
            "--root",
            str(forged),
            "--source-root",
            str(forged),
        ],
        cwd=forged,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert not result["valid"]
    assert result["chain"]["valid"]
    assert result["artifact_binding_valid"]
    assert "summary_semantic_recompute_mismatch" in result["errors"]
