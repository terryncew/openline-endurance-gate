#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate.successor_benchmark import (
    CASE_MANIFEST_SCHEMA,
    canonical_hash,
    file_hash,
    finalize_case,
    generate_keypair,
    prepare_case,
    register_case,
    sign_checker_report,
    write_json,
)
from openline_endurance_gate.successor_verifier import verify_case_directory


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_inputs(root: Path) -> dict[str, Path]:
    paths = {name: root / f"{name}.json" for name in ("task", "constraints", "budget", "policy")}
    write_json(paths["task"], {"schema": "agent.successor.task.v1", "task_id": "fixture-task", "statement": "Repair the fixture without changing its required behavior."})
    write_json(paths["constraints"], {"schema": "agent.successor.constraints.v1", "items": ["all tests must pass", "no protected file may change"]})
    write_json(paths["budget"], {"schema": "agent.successor.budget.v1", "max_tool_calls": 20, "max_wall_time_seconds": 600, "max_cost_micros": 1_000_000, "max_output_bytes": 1_000_000})
    write_json(paths["policy"], {
        "schema": "agent.successor.policy.v1",
        "policy_id": "fixture-policy",
        "metrics": [
            {"name": "defects", "description": "Count of checker-confirmed defects.", "direction": "minimize", "required": True, "max_regression": 0, "minimum_improvement": 1},
            {"name": "task_score", "description": "Integer task score assigned by the checker.", "direction": "maximize", "required": True, "max_regression": 0, "minimum_improvement": 5},
            {"name": "tool_calls", "description": "Count of tool calls used for the task.", "direction": "minimize", "required": False, "max_regression": 0, "minimum_improvement": 2},
        ],
    })
    return paths


def _write_submission(root: Path, role: str, version_hash: str) -> tuple[Path, Path]:
    evidence = root / f"{role}-evidence"
    (evidence / "artifacts").mkdir(parents=True)
    (evidence / "logs").mkdir(parents=True)
    (evidence / "artifacts" / "result.json").write_text('{"ok":true}\n', encoding="utf-8")
    (evidence / "logs" / "tests.txt").write_text("all tests passed\n", encoding="utf-8")
    submission = root / f"{role}-submission.json"
    write_json(submission, {
        "schema": "agent.successor.submission.v1",
        "case_id": "fixture-case",
        "role": role,
        "submission_id": f"submission-{role}",
        "version_hash": version_hash,
        "artifact_hash": _sha(f"artifact-{role}"),
        "evidence": [
            {"evidence_id": "result", "kind": "artifact", "path": "artifacts/result.json"},
            {"evidence_id": "tests", "kind": "test", "path": "logs/tests.txt"},
        ],
    })
    return submission, evidence


def _build_case(root: Path, *, candidate_status: str = "PASS", candidate_metrics: dict[str, int] | None = None, name: str = "case") -> Path:
    inputs = _write_inputs(root)
    private = root / "checker.private.hex"
    public = root / "checker.public.hex"
    generate_keypair(private, public)
    public_hex = public.read_text(encoding="ascii").strip()
    inc_hash = _sha("incumbent-v1")
    cand_hash = _sha("candidate-v2")
    registration = root / "registration.json"
    nonce = "fixture-blinding-nonce-0001"
    register_case(
        trial_id="fixture-trial", case_id="fixture-case", case_index=1, planned_case_count=1,
        previous_registration_path=None, task_path=inputs["task"], constraints_path=inputs["constraints"],
        budget_path=inputs["budget"], policy_path=inputs["policy"], repository_state_hash=_sha("repo-state"),
        incumbent_version_hash=inc_hash, candidate_version_hash=cand_hash, checker_id="fixture-checker",
        checker_public_key=public_hex, blinding_nonce=nonce, output_path=registration,
    )
    inc_sub, inc_evidence = _write_submission(root, "incumbent", inc_hash)
    cand_sub, cand_evidence = _write_submission(root, "candidate", cand_hash)
    prepared = root / f"{name}-prepared"
    preparation = prepare_case(
        registration_path=registration, task_path=inputs["task"], constraints_path=inputs["constraints"],
        budget_path=inputs["budget"], policy_path=inputs["policy"], incumbent_submission_path=inc_sub,
        candidate_submission_path=cand_sub, incumbent_evidence_dir=inc_evidence,
        candidate_evidence_dir=cand_evidence, blinding_nonce=nonce, output_dir=prepared,
    )
    reports: list[Path] = []
    metrics_by_role = {
        "incumbent": {"defects": 2, "task_score": 80, "tool_calls": 10},
        "candidate": candidate_metrics or {"defects": 1, "task_score": 90, "tool_calls": 8},
    }
    for role in ("incumbent", "candidate"):
        lane = preparation["lane_mapping"][role]
        report = root / f"{name}-{role}-report.json"
        status = "PASS" if role == "incumbent" else candidate_status
        sign_checker_report(
            package_dir=prepared / "checker_packages" / lane,
            status=status,
            metrics=metrics_by_role[role],
            citations=["result", "tests"],
            critical_failures=[] if status != "FAIL" else ["checker-confirmed-failure"],
            reason_codes=["fixture-evaluation"], checker_private_key_path=private, output_path=report,
        )
        reports.append(report)
    final = root / f"{name}-final"
    finalize_case(prepared_dir=prepared, checker_report_paths=reports, output_dir=final)
    return final


def _reseal_manifest(root: Path) -> None:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() not in {"case_manifest.json", "verification.json"}:
            entries.append({"path": path.relative_to(root).as_posix(), "sha256": file_hash(path), "bytes": path.stat().st_size})
    write_json(root / "case_manifest.json", {"schema": CASE_MANIFEST_SCHEMA, "entries": entries})


def _mutate_json(path: Path, change) -> None:
    value = _read(path)
    change(value)
    write_json(path, value)


def run() -> dict:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="agent-successor-selftest-") as temp:
        work = Path(temp)
        promote = _build_case(work / "promote", name="promote")
        promote_verify = verify_case_directory(promote)
        checks["promote_candidate"] = promote_verify["valid"] and promote_verify["recomputed_decision"] == "PROMOTE_CANDIDATE"

        regression = _build_case(work / "regression", candidate_metrics={"defects": 3, "task_score": 95, "tool_calls": 8}, name="regression")
        regression_verify = verify_case_directory(regression)
        checks["required_regression_keeps_incumbent"] = regression_verify["valid"] and regression_verify["recomputed_decision"] == "KEEP_INCUMBENT"

        no_gain = _build_case(work / "no-gain", candidate_metrics={"defects": 2, "task_score": 80, "tool_calls": 10}, name="no-gain")
        no_gain_verify = verify_case_directory(no_gain)
        checks["no_material_gain_keeps_incumbent"] = no_gain_verify["valid"] and no_gain_verify["recomputed_decision"] == "KEEP_INCUMBENT"

        undecidable = _build_case(work / "undecidable", candidate_status="UNDECIDABLE", name="undecidable")
        undecidable_verify = verify_case_directory(undecidable)
        checks["undecidable_is_inconclusive"] = undecidable_verify["valid"] and undecidable_verify["recomputed_decision"] == "INCONCLUSIVE"

        prep = _read(work / "promote" / "promote-prepared" / "preparation.json")
        for role, lane in prep["lane_mapping"].items():
            package = _read(work / "promote" / "promote-prepared" / "checker_packages" / lane / "package.json")
            text = json.dumps(package, sort_keys=True)
            checks[f"{role}_checker_package_has_no_role_field"] = "\"role\"" not in text and "\"incumbent\"" not in text and "\"candidate\"" not in text

        hostile = {
            "registration_version": ("registration.json", lambda v: v.__setitem__("candidate_version_hash", "0" * 64)),
            "task": ("task.json", lambda v: v.__setitem__("statement", "changed after registration")),
            "policy": ("policy.json", lambda v: v["metrics"][0].__setitem__("max_regression", 99)),
            "budget": ("budget.json", lambda v: v.__setitem__("max_tool_calls", 999)),
            "submission": ("sealed_submissions/candidate.json", lambda v: v.__setitem__("artifact_hash", "0" * 64)),
            "package": (f"checker_packages/{prep['lane_mapping']['candidate']}/package.json", lambda v: v.__setitem__("artifact_hash", "0" * 64)),
            "precheck": ("precheck.json", lambda v: v.__setitem__("checker_reports_present", True)),
            "report_status": ("checker_reports/candidate.json", lambda v: v.__setitem__("status", "FAIL")),
            "report_metric": ("checker_reports/candidate.json", lambda v: v["metrics"].__setitem__("task_score", 999)),
            "report_signature": ("checker_reports/candidate.json", lambda v: v.__setitem__("signature", "0" * 128)),
            "report_citation": ("checker_reports/candidate.json", lambda v: v.__setitem__("citations", ["not-packaged"])),
            "decision": ("decision.json", lambda v: v.__setitem__("decision", "KEEP_INCUMBENT")),
        }
        for index, (label, (relative, change)) in enumerate(hostile.items()):
            copy = work / f"hostile-{index}"
            shutil.copytree(promote, copy)
            _mutate_json(copy / relative, change)
            _reseal_manifest(copy)
            checks[f"resealed_{label}_rejected"] = not verify_case_directory(copy, require_stored_verification=False)["valid"]

        evidence_attack = work / "hostile-evidence"
        shutil.copytree(promote, evidence_attack)
        lane = prep["lane_mapping"]["candidate"]
        (evidence_attack / "checker_packages" / lane / "evidence" / "artifacts" / "result.json").write_text('{"ok":false}\n', encoding="utf-8")
        _reseal_manifest(evidence_attack)
        checks["resealed_evidence_bytes_rejected"] = not verify_case_directory(evidence_attack, require_stored_verification=False)["valid"]

        extra = work / "hostile-extra"
        shutil.copytree(promote, extra)
        (extra / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        checks["unlisted_extra_file_rejected"] = not verify_case_directory(extra)["valid"]

        if hasattr(os, "symlink"):
            symlink = work / "hostile-symlink"
            shutil.copytree(promote, symlink)
            try:
                os.symlink("decision.json", symlink / "link.json")
                checks["symlink_rejected"] = not verify_case_directory(symlink)["valid"]
            except OSError:
                checks["symlink_rejected"] = True

    return {
        "schema": "agent.successor.selftest.v1",
        "passed": all(checks.values()),
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "checks": checks,
        "claim_boundary": "Synthetic mechanism and hostile-input checks only; no deployed-agent performance claim is made.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run()
    if args.out:
        write_json(Path(args.out), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
