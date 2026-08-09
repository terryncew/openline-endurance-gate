from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openline_endurance_gate.successor_benchmark import (
    finalize_case,
    generate_keypair,
    prepare_case,
    register_case,
    sign_checker_report,
    write_json,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_inputs(root: Path, *, minimum_score_improvement: int = 5) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {name: root / f"{name}.json" for name in ("task", "constraints", "budget", "policy")}
    write_json(paths["task"], {"schema": "agent.successor.task.v1", "task_id": "task-1", "statement": "Complete the same bounded coding task."})
    write_json(paths["constraints"], {"schema": "agent.successor.constraints.v1", "items": ["all tests pass", "protected files unchanged"]})
    write_json(paths["budget"], {"schema": "agent.successor.budget.v1", "max_tool_calls": 20, "max_wall_time_seconds": 600, "max_cost_micros": 1_000_000, "max_output_bytes": 1_000_000})
    write_json(paths["policy"], {
        "schema": "agent.successor.policy.v1",
        "policy_id": "policy-1",
        "metrics": [
            {"name": "defects", "description": "Checker-confirmed defect count.", "direction": "minimize", "required": True, "max_regression": 0, "minimum_improvement": 1},
            {"name": "task_score", "description": "Checker task score.", "direction": "maximize", "required": True, "max_regression": 0, "minimum_improvement": minimum_score_improvement},
        ],
    })
    return paths


def make_submission(root: Path, role: str, version_hash: str, *, case_id: str = "case-1") -> tuple[Path, Path]:
    evidence = root / f"{role}-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "result.txt").write_text(f"{role} result\n", encoding="utf-8")
    submission = root / f"{role}.json"
    write_json(submission, {
        "schema": "agent.successor.submission.v1", "case_id": case_id, "role": role,
        "submission_id": f"sub-{role}", "version_hash": version_hash,
        "artifact_hash": sha(f"artifact-{role}"),
        "evidence": [{"evidence_id": "result", "kind": "test", "path": "result.txt"}],
    })
    return submission, evidence


def make_prepared(root: Path, *, case_index: int = 1, planned: int = 1, previous: Path | None = None) -> dict:
    inputs = make_inputs(root)
    private = root / "checker.private.hex"
    public = root / "checker.public.hex"
    generate_keypair(private, public)
    inc_hash, cand_hash = sha("inc"), sha("cand")
    registration = root / "registration.json"
    register_case(
        trial_id="trial-1", case_id=f"case-{case_index}", case_index=case_index, planned_case_count=planned,
        previous_registration_path=previous, task_path=inputs["task"], constraints_path=inputs["constraints"],
        budget_path=inputs["budget"], policy_path=inputs["policy"], repository_state_hash=sha("repo"),
        incumbent_version_hash=inc_hash, candidate_version_hash=cand_hash, checker_id="checker-1",
        checker_public_key=public.read_text().strip(), blinding_nonce="0123456789abcdef-fixed", output_path=registration,
    )
    inc_sub, inc_ev = make_submission(root, "incumbent", inc_hash, case_id=f"case-{case_index}")
    cand_sub, cand_ev = make_submission(root, "candidate", cand_hash, case_id=f"case-{case_index}")
    prepared = root / "prepared"
    preparation = prepare_case(
        registration_path=registration, task_path=inputs["task"], constraints_path=inputs["constraints"],
        budget_path=inputs["budget"], policy_path=inputs["policy"], incumbent_submission_path=inc_sub,
        candidate_submission_path=cand_sub, incumbent_evidence_dir=inc_ev, candidate_evidence_dir=cand_ev,
        blinding_nonce="0123456789abcdef-fixed", output_dir=prepared,
    )
    return {"inputs": inputs, "private": private, "public": public, "registration": registration, "prepared": prepared, "preparation": preparation}


def finalize_with_metrics(root: Path, incumbent: dict[str, int], candidate: dict[str, int], *, candidate_status: str = "PASS", failures: list[str] | None = None) -> Path:
    state = make_prepared(root)
    reports = []
    for role, metrics, status in (("incumbent", incumbent, "PASS"), ("candidate", candidate, candidate_status)):
        lane = state["preparation"]["lane_mapping"][role]
        report = root / f"{role}-report.json"
        sign_checker_report(
            package_dir=state["prepared"] / "checker_packages" / lane,
            status=status, metrics=metrics, citations=["result"],
            critical_failures=(failures or []) if role == "candidate" else [],
            reason_codes=["checked"], checker_private_key_path=state["private"], output_path=report,
        )
        reports.append(report)
    final = root / "final"
    finalize_case(prepared_dir=state["prepared"], checker_report_paths=reports, output_dir=final)
    return final
