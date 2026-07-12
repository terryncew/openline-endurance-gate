from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate.receipts import (
    ReceiptSigner,
    create_chain,
    read_chain,
    verify_chain,
    write_anchor,
    write_chain,
)
from openline_endurance_gate.util import sha256_file


def _verify_subprocess(repo: Path, full_semantic: bool = True) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    command = [
        sys.executable,
        "-m",
        "openline_endurance_gate",
        "verify",
        "--root",
        str(repo),
        "--source-root",
        str(repo),
    ]
    if not full_semantic:
        command.append("--fast")
    completed = subprocess.run(
        command,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if not completed.stdout.strip():
        raise RuntimeError(f"verifier produced no JSON: {completed.stderr}")
    return json.loads(completed.stdout)


def _clone(destination: Path) -> Path:
    repo = destination / "repo"
    shutil.copytree(
        ROOT,
        repo,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_cache",
            "__pycache__",
            "*.egg-info",
            "ZIP_VERIFICATION.json",
            "*.zip",
            "*.sha256",
        ),
    )
    return repo


def _patch_manifest(repo: Path, relative: str) -> None:
    manifest_path = repo / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = repo / relative
    found = False
    for entry in manifest["entries"]:
        if entry["path"] == relative:
            entry["sha256"] = sha256_file(target)
            found = True
            break
    if not found:
        raise RuntimeError(f"manifest entry missing: {relative}")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resign_with_patched_hashes(repo: Path, changed_artifacts: list[str]) -> None:
    chain_path = repo / "receipts/experiment.jsonl"
    anchor_path = repo / "receipts/experiment.anchor.json"
    old_chain = read_chain(chain_path)
    items: list[tuple[str, dict[str, Any]]] = []
    for receipt in old_chain:
        payload = receipt["payload"]
        if receipt["kind"] == "evidence_bundle":
            payload = dict(payload)
            hashes = dict(payload["artifact_hashes"])
            for relative in changed_artifacts:
                hashes[relative] = sha256_file(repo / relative)
            hashes["MANIFEST.json"] = sha256_file(repo / "MANIFEST.json")
            payload["artifact_hashes"] = hashes
        items.append((receipt["kind"], payload))
    attacker = ReceiptSigner.generate()
    new_chain = create_chain(items, attacker)
    write_chain(chain_path, new_chain)
    write_anchor(anchor_path, new_chain, attacker)


def _tail_truncation(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    chain = read_chain(repo / "receipts/experiment.jsonl")
    write_chain(repo / "receipts/experiment.jsonl", chain[:-1])
    result = verify_chain(repo / "receipts/experiment.jsonl", repo / "receipts/experiment.anchor.json")
    detected = (not result["valid"]) and any(error.startswith("completeness") for error in result["errors"])
    return {"detected": detected, "verifier": result}


def _summary_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "results/summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    target_name = "tip_capture/geometry_adds_heldout_prediction"
    summary["gates"][target_name]["passed"] = not summary["gates"][target_name]["passed"]
    summary["passed_gate_count"] = sum(int(gate["passed"]) for gate in summary["gates"].values())
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _patch_manifest(repo, "results/summary.json")
    _resign_with_patched_hashes(repo, ["results/summary.json"])
    result = _verify_subprocess(repo, full_semantic=True)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and result["artifact_binding_valid"]
        and not result["semantic_recomputation_valid"]
        and "summary_semantic_recompute_mismatch" in result["errors"]
    )
    return {"detected": detected, "verifier": result, "attack": "flip one gate, patch hashes, replace keypair, resign chain"}


def _raw_cycle_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "results/cycles.csv"
    rewritten = path.with_suffix(".tampered.csv")
    changed = False
    with path.open("r", newline="", encoding="utf-8") as source, rewritten.open("w", newline="", encoding="utf-8") as destination:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        if "damage_D" not in fields:
            raise RuntimeError("cycles.csv is missing damage_D")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            if not changed and row.get("damage_D") not in {None, ""}:
                row["damage_D"] = f"{float(row['damage_D']) + 0.001:.10f}"
                changed = True
            writer.writerow(row)
    if not changed:
        raise RuntimeError("no damage_D value available to tamper")
    rewritten.replace(path)
    _patch_manifest(repo, "results/cycles.csv")
    _resign_with_patched_hashes(repo, ["results/cycles.csv"])
    result = _verify_subprocess(repo, full_semantic=True)
    expected = "v040_lineage_hash_mismatch:results/cycles.csv"
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("lineage_binding_valid", True)
        and expected in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate fitted damage_D in a raw primary-cycle row, patch hashes, replace keypair, resign chain",
    }



def _collision_cycle_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "results/collision_spacing_events.csv"
    rewritten = path.with_suffix(".tampered.csv")
    changed = False
    with path.open("r", newline="", encoding="utf-8") as source, rewritten.open("w", newline="", encoding="utf-8") as destination:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        if "damage_after" not in fields:
            raise RuntimeError("collision_spacing_events.csv is missing damage_after")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            if not changed and row.get("damage_after") not in {None, ""}:
                row["damage_after"] = f"{float(row['damage_after']) + 0.001:.10f}"
                changed = True
            writer.writerow(row)
    if not changed:
        raise RuntimeError("no collision damage value available to tamper")
    rewritten.replace(path)
    _patch_manifest(repo, "results/collision_spacing_events.csv")
    _resign_with_patched_hashes(repo, ["results/collision_spacing_events.csv"])
    result = _verify_subprocess(repo, full_semantic=True)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and result["artifact_binding_valid"]
        and not result["semantic_recomputation_valid"]
        and "collision_spacing_events_recompute_mismatch" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate one collision-spacing damage row, patch hashes, replace keypair, resign chain",
    }

def _walker_cycle_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "results/tip_capture_cycles.csv"
    rewritten = path.with_suffix(".tampered.csv")
    changed = False
    with path.open("r", newline="", encoding="utf-8") as source, rewritten.open("w", newline="", encoding="utf-8") as destination:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        required = {"walker_used", "walker_fallback", "walker_steps", "new_node_x"}
        if required - set(fields):
            raise RuntimeError("tip_capture_cycles.csv is missing first-contact evidence fields")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            if not changed and row.get("walker_used") == "1" and row.get("walker_fallback") == "0":
                row["new_node_x"] = str(int(row["new_node_x"]) + 1)
                changed = True
            writer.writerow(row)
    if not changed:
        raise RuntimeError("no successful first-contact row available to tamper")
    rewritten.replace(path)
    _patch_manifest(repo, "results/tip_capture_cycles.csv")
    _resign_with_patched_hashes(repo, ["results/tip_capture_cycles.csv"])
    result = _verify_subprocess(repo, full_semantic=True)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("lineage_binding_valid", True)
        and "v040_lineage_hash_mismatch:results/tip_capture_cycles.csv" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate one first-contact lattice coordinate, patch hashes, replace keypair, resign chain",
    }


def _source_drift(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "src/openline_endurance_gate/tip_capture.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# attacker source drift\n", encoding="utf-8")
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and any(error.startswith("manifest_hash_mismatch:src/openline_endurance_gate/tip_capture.py") for error in result["errors"])
        and any(error.startswith("preregistration_mechanism_hash_mismatch:src/openline_endurance_gate/tip_capture.py") for error in result["errors"])
    )
    return {"detected": detected, "verifier": result}


def _attack_map():
    return {
        "resealed_raw_cycle_forgery": _raw_cycle_reseal,
        "resealed_first_contact_forgery": _walker_cycle_reseal,
        "resealed_collision_spacing_forgery": _collision_cycle_reseal,
        "resealed_summary_forgery": _summary_reseal,
        "tail_truncation": _tail_truncation,
        "unpatched_source_drift": _source_drift,
    }


def _run_single_attack(name: str) -> int:
    attack = _attack_map()[name]
    with tempfile.TemporaryDirectory(prefix=f"openline-{name}-") as directory:
        result = attack(Path(directory))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["detected"] else 1


def _aggregate_reports(directory: Path) -> int:
    report: dict[str, Any] = {
        "schema": "openline.endurance.tamper-report.v3",
        "release_version": "0.5.0",
        "attacks": {},
        "execution_boundary": "Each complete hostile attack, including its semantic verifier, ran as a separate top-level Python process under a low-memory shell orchestrator.",
        "trust_boundary": {
            "whole_repository_replacement": "OUT_OF_SCOPE_WITHOUT_EXTERNAL_WITNESS",
            "reason": "A full-write attacker can replace source, artifacts, keypair, anchor, and local witness. Publish results/public_witness.json or its digest outside the repository.",
        },
    }
    for name in _attack_map():
        path = directory / f"{name}.json"
        if not path.exists():
            report["attacks"][name] = {"detected": False, "runner_error": f"missing isolated report: {path.name}"}
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            item = {"detected": False, "runner_error": f"invalid isolated report: {exc}"}
        report["attacks"][name] = item
    report["passed"] = all(item.get("detected") for item in report["attacks"].values())
    (ROOT / "TAMPER_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attack", choices=list(_attack_map()))
    parser.add_argument("--aggregate-dir", type=Path)
    args = parser.parse_args()
    if args.attack:
        return _run_single_attack(args.attack)
    if args.aggregate_dir:
        return _aggregate_reports(args.aggregate_dir)

    shell = ROOT / "scripts" / "tamper_check.sh"
    if os.name != "nt" and shell.exists():
        os.execvp("bash", ["bash", str(shell)])
    raise RuntimeError("Run each attack with --attack and aggregate with --aggregate-dir on platforms without bash.")



if __name__ == "__main__":
    raise SystemExit(main())
