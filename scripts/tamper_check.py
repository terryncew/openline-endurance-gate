from __future__ import annotations

import argparse
import csv
import gzip
import io
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
from openline_endurance_gate.release_attestation import write_release_attestation
from openline_endurance_gate.util import sha256_file
from openline_endurance_gate.experiment import load_experiment
from openline_endurance_gate.semantic_phases import verify_state_restoration_shard
from openline_endurance_gate.state_restoration import analyze_state_restoration
from openline_endurance_gate.verification import _close, _coerce, _v7_expected_summary
from openline_endurance_gate.util import read_csv


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


def _light_summary_verification(repo: Path) -> dict[str, Any]:
    result = _verify_subprocess(repo, full_semantic=False)
    experiment = load_experiment(repo / "experiment.json")
    runs = _coerce(read_csv(repo / "results/state_restoration_runs.csv"))
    restoration = analyze_state_restoration(runs, experiment)
    expected = _v7_expected_summary(repo, restoration)
    stored = json.loads((repo / "results/summary.json").read_text(encoding="utf-8"))
    summary_match = _close(expected, stored, 1e-7)
    errors = list(result.get("errors", []))
    if not summary_match:
        errors.append("summary_semantic_recompute_mismatch")
    result["errors"] = errors
    result["semantic_recomputation_valid"] = summary_match
    result["valid"] = bool(result.get("valid") and summary_match)
    return result


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
    result = _light_summary_verification(repo)
    detected = (
        not result["semantic_recomputation_valid"]
        and result["chain"]["valid"]
        and result["artifact_binding_valid"]
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
    result = _verify_subprocess(repo, full_semantic=False)
    expected = "v060_lineage_hash_mismatch:results/cycles.csv"
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
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("lineage_binding_valid", True)
        and "v060_lineage_hash_mismatch:results/collision_spacing_events.csv" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate one collision-spacing damage row, patch hashes, replace keypair, resign chain",
    }

def _generational_cycle_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "results/generational_cycles.csv"
    rewritten = path.with_suffix(".tampered.csv")
    changed = False
    with path.open("r", newline="", encoding="utf-8") as source, rewritten.open("w", newline="", encoding="utf-8") as destination:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        if "active_context_tokens" not in fields:
            raise RuntimeError("generational_cycles.csv is missing active_context_tokens")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            if not changed and row.get("active_context_tokens") not in {None, ""}:
                row["active_context_tokens"] = str(int(float(row["active_context_tokens"])) + 1)
                changed = True
            writer.writerow(row)
    if not changed:
        raise RuntimeError("no generational context value available to tamper")
    rewritten.replace(path)
    _patch_manifest(repo, "results/generational_cycles.csv")
    _resign_with_patched_hashes(repo, ["results/generational_cycles.csv"])
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("lineage_binding_valid", True)
        and "v060_lineage_hash_mismatch:results/generational_cycles.csv" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate one generational active-context value, patch hashes, replace keypair, resign chain",
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
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("lineage_binding_valid", True)
        and "v060_lineage_hash_mismatch:results/tip_capture_cycles.csv" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": "mutate one first-contact lattice coordinate, patch hashes, replace keypair, resign chain",
    }



def _state_restoration_cycle_reseal(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    relative = "results/state_restoration_cycles.part-000.csv.gz"
    path = repo / relative
    rewritten = path.with_name(path.name + ".tampered")
    changed = False
    with gzip.open(path, "rt", newline="", encoding="utf-8") as source, rewritten.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, io.TextIOWrapper(
            gz, encoding="utf-8", newline=""
        ) as destination:
            reader = csv.DictReader(source)
            fields = list(reader.fieldnames or [])
            if "rolling_noise_epsilon" not in fields:
                raise RuntimeError("state-restoration shard is missing rolling_noise_epsilon")
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            for row in reader:
                if not changed and row.get("rolling_noise_epsilon") not in {None, ""}:
                    row["rolling_noise_epsilon"] = f"{float(row['rolling_noise_epsilon']) + 0.001:.10f}"
                    changed = True
                writer.writerow(row)
    if not changed:
        raise RuntimeError("no state-restoration telemetry value available to tamper")
    rewritten.replace(path)
    _patch_manifest(repo, relative)
    _resign_with_patched_hashes(repo, [relative])
    fast = _verify_subprocess(repo, full_semantic=False)
    shard = verify_state_restoration_shard(repo, 0, persist=False)
    detected = (
        fast["chain"]["valid"]
        and fast["artifact_binding_valid"]
        and not shard["passed"]
        and not shard["cycle_bytes_match"]
    )
    return {
        "detected": detected,
        "verifier": fast,
        "semantic_shard": shard,
        "attack": "mutate one compressed state-restoration telemetry row, patch hashes, replace keypair, resign chain",
    }

def _source_drift(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)
    path = repo / "src/openline_endurance_gate/generational.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# attacker source drift\n", encoding="utf-8")
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and any(error.startswith("manifest_hash_mismatch:src/openline_endurance_gate/generational.py") for error in result["errors"])
        and any(error.startswith("preregistration_mechanism_hash_mismatch:src/openline_endurance_gate/generational.py") for error in result["errors"])
    )
    return {"detected": detected, "verifier": result}


def _release_report_mutation(temp: Path) -> dict[str, Any]:
    repo = _clone(temp)

    # This attack must be runnable before the real release attestation exists;
    # otherwise the tamper suite and final attestation depend on each other.
    # Build a minimal internally consistent provisional pair in the isolated
    # clone, attest it, then mutate only the release verdict.
    experiment = json.loads((repo / "experiment.json").read_text(encoding="utf-8"))
    chain = verify_chain(repo / "receipts/experiment.jsonl", repo / "receipts/experiment.anchor.json")
    provisional_tamper = {
        "schema": "openline.endurance.tamper-report.provisional.v1",
        "release_version": experiment["release_version"],
        "passed": True,
        "attacks": {},
        "report_role": "ISOLATED_ATTACK_FIXTURE",
    }
    provisional_run = {
        "schema": "openline.endurance.release-report.provisional.v1",
        "passed": True,
        "semantic_verification": {
            "valid": True,
            "chain": {
                "chain_digest": chain["chain_digest"],
                "tail_hash": chain["tail_hash"],
            },
        },
        "tamper_suite": {
            "returncode": 0,
            "report": provisional_tamper,
        },
    }
    (repo / "TAMPER_REPORT.json").write_text(
        json.dumps(provisional_tamper, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path = repo / "RUN_REPORT.json"
    path.write_text(json.dumps(provisional_run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_release_attestation(repo)

    report = json.loads(path.read_text(encoding="utf-8"))
    report["passed"] = False
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = _verify_subprocess(repo, full_semantic=False)
    detected = (
        not result["valid"]
        and result["chain"]["valid"]
        and not result.get("release_attestation_valid", True)
        and "release_attestation_artifact_hash_mismatch:RUN_REPORT.json" in result["errors"]
    )
    return {
        "detected": detected,
        "verifier": result,
        "attack": (
            "establish a valid provisional detached release receipt in an isolated clone, "
            "then edit the final release verdict without touching scientific artifacts"
        ),
    }


def _attack_map():
    return {
        "resealed_raw_cycle_forgery": _raw_cycle_reseal,
        "resealed_first_contact_forgery": _walker_cycle_reseal,
        "resealed_collision_spacing_forgery": _collision_cycle_reseal,
        "resealed_generational_forgery": _generational_cycle_reseal,
        "resealed_state_restoration_forgery": _state_restoration_cycle_reseal,
        "resealed_summary_forgery": _summary_reseal,
        "tail_truncation": _tail_truncation,
        "unpatched_source_drift": _source_drift,
        "release_report_mutation": _release_report_mutation,
    }


def _run_single_attack(name: str) -> int:
    attack = _attack_map()[name]
    with tempfile.TemporaryDirectory(prefix=f"openline-{name}-") as directory:
        result = attack(Path(directory))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["detected"] else 1


def _aggregate_reports(directory: Path, output_path: Path) -> int:
    report: dict[str, Any] = {
        "schema": "openline.endurance.tamper-report.v6",
        "release_version": json.loads((ROOT / "experiment.json").read_text(encoding="utf-8"))["release_version"],
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
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_role"] = (
        "RELEASE_ATTESTATION_INPUT" if output_path == (ROOT / "TAMPER_REPORT.json").resolve()
        else "STANDALONE_UNATTESTED_WITNESS"
    )
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attack", choices=list(_attack_map()))
    parser.add_argument("--aggregate-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "TAMPER_REPORT.standalone.json")
    args = parser.parse_args()
    if args.attack:
        return _run_single_attack(args.attack)
    if args.aggregate_dir:
        return _aggregate_reports(args.aggregate_dir, args.output)

    shell = ROOT / "scripts" / "tamper_check.sh"
    if os.name != "nt" and shell.exists():
        os.execvp("bash", ["bash", str(shell)])
    raise RuntimeError("Run each attack with --attack and aggregate with --aggregate-dir on platforms without bash.")



if __name__ == "__main__":
    raise SystemExit(main())
