from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path

import pytest

from openline_endurance_gate.successor_benchmark import (
    BenchmarkError,
    canonical_hash,
    compare_reports,
    finalize_case,
    prepare_case,
    register_case,
    sign_checker_report,
    write_json,
)
from openline_endurance_gate.successor_verifier import verify_case_directory

from helpers import finalize_with_metrics, make_inputs, make_prepared, make_submission, sha


def read(path: Path):
    return json.loads(path.read_text())


def test_candidate_promoted_only_with_floor_and_material_gain(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 1, "task_score": 90})
    assert read(final / "decision.json")["decision"] == "PROMOTE_CANDIDATE"
    assert read(final / "decision.json")["execution_authorized"] is False
    assert verify_case_directory(final)["valid"] is True


def test_required_regression_keeps_incumbent(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 3, "task_score": 95})
    result = read(final / "decision.json")
    assert result["decision"] == "KEEP_INCUMBENT"
    assert result["reason_codes"] == ["required_metric_regression:defects"]


def test_no_material_improvement_keeps_incumbent(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 2, "task_score": 80})
    assert read(final / "decision.json")["reason_codes"] == ["no_declared_material_improvement"]


def test_undecidable_report_makes_case_inconclusive(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 1, "task_score": 90}, candidate_status="UNDECIDABLE")
    assert read(final / "decision.json")["decision"] == "INCONCLUSIVE"


def test_candidate_fail_keeps_incumbent(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 1, "task_score": 90}, candidate_status="FAIL", failures=["violated-constraint"])
    assert read(final / "decision.json")["decision"] == "KEEP_INCUMBENT"


def test_registration_must_precede_arm_data_by_interface(tmp_path):
    state = make_prepared(tmp_path)
    registration = read(state["registration"])
    assert "submission" not in registration
    assert "evidence" not in registration
    assert "checker_report" not in registration


def test_case_two_requires_previous_registration(tmp_path):
    inputs = make_inputs(tmp_path)
    with pytest.raises(BenchmarkError, match="requires previous_registration_path"):
        register_case(
            trial_id="trial-1", case_id="case-2", case_index=2, planned_case_count=2,
            previous_registration_path=None, task_path=inputs["task"], constraints_path=inputs["constraints"],
            budget_path=inputs["budget"], policy_path=inputs["policy"], repository_state_hash=sha("repo"),
            incumbent_version_hash=sha("inc"), candidate_version_hash=sha("cand"), checker_id="checker",
            checker_public_key="1" * 64, blinding_nonce="0123456789abcdef", output_path=tmp_path / "reg.json",
        )


def test_previous_registration_must_be_contiguous(tmp_path):
    first = make_prepared(tmp_path / "first", case_index=1, planned=3)["registration"]
    inputs = make_inputs(tmp_path / "third")
    with pytest.raises(BenchmarkError, match="not contiguous"):
        register_case(
            trial_id="trial-1", case_id="case-3", case_index=3, planned_case_count=3,
            previous_registration_path=first, task_path=inputs["task"], constraints_path=inputs["constraints"],
            budget_path=inputs["budget"], policy_path=inputs["policy"], repository_state_hash=sha("repo"),
            incumbent_version_hash=sha("inc"), candidate_version_hash=sha("cand"), checker_id="checker",
            checker_public_key="1" * 64, blinding_nonce="0123456789abcdef", output_path=tmp_path / "third" / "reg.json",
        )


def test_changed_task_after_registration_is_rejected(tmp_path):
    state = make_prepared(tmp_path / "base")
    changed = tmp_path / "changed-task.json"
    task = read(state["inputs"]["task"])
    task["statement"] = "different task"
    write_json(changed, task)
    with pytest.raises(BenchmarkError, match="task_hash"):
        prepare_case(
            registration_path=state["registration"], task_path=changed,
            constraints_path=state["inputs"]["constraints"], budget_path=state["inputs"]["budget"],
            policy_path=state["inputs"]["policy"], incumbent_submission_path=tmp_path / "missing",
            candidate_submission_path=tmp_path / "missing2", incumbent_evidence_dir=tmp_path,
            candidate_evidence_dir=tmp_path, blinding_nonce="0123456789abcdef-fixed", output_dir=tmp_path / "nope",
        )


def test_changed_blinding_nonce_after_registration_is_rejected(tmp_path):
    state = make_prepared(tmp_path / "base")
    with pytest.raises(BenchmarkError, match="blinding_nonce_hash"):
        prepare_case(
            registration_path=state["registration"], task_path=state["inputs"]["task"],
            constraints_path=state["inputs"]["constraints"], budget_path=state["inputs"]["budget"],
            policy_path=state["inputs"]["policy"], incumbent_submission_path=tmp_path / "missing",
            candidate_submission_path=tmp_path / "missing2", incumbent_evidence_dir=tmp_path,
            candidate_evidence_dir=tmp_path, blinding_nonce="another-nonce-value", output_dir=tmp_path / "nope",
        )


def test_candidate_version_must_match_registration(tmp_path):
    state = make_prepared(tmp_path / "base")
    submission = read(tmp_path / "base" / "candidate.json")
    submission["version_hash"] = sha("other")
    changed = tmp_path / "changed-submission.json"
    write_json(changed, submission)
    with pytest.raises(BenchmarkError, match="candidate version hash"):
        prepare_case(
            registration_path=state["registration"], task_path=state["inputs"]["task"], constraints_path=state["inputs"]["constraints"],
            budget_path=state["inputs"]["budget"], policy_path=state["inputs"]["policy"],
            incumbent_submission_path=tmp_path / "base" / "incumbent.json", candidate_submission_path=changed,
            incumbent_evidence_dir=tmp_path / "base" / "incumbent-evidence", candidate_evidence_dir=tmp_path / "base" / "candidate-evidence",
            blinding_nonce="0123456789abcdef-fixed", output_dir=tmp_path / "nope",
        )


def test_unlisted_evidence_file_is_rejected(tmp_path):
    inputs = make_inputs(tmp_path)
    state = make_prepared(tmp_path / "state")
    # Reuse a fresh evidence directory and make it contain an unlisted file.
    inc_sub, inc_ev = make_submission(tmp_path, "incumbent", sha("inc"))
    cand_sub, cand_ev = make_submission(tmp_path, "candidate", sha("cand"))
    (cand_ev / "extra.txt").write_text("extra")
    with pytest.raises(BenchmarkError, match="extra"):
        prepare_case(
            registration_path=state["registration"], task_path=state["inputs"]["task"], constraints_path=state["inputs"]["constraints"],
            budget_path=state["inputs"]["budget"], policy_path=state["inputs"]["policy"], incumbent_submission_path=inc_sub,
            candidate_submission_path=cand_sub, incumbent_evidence_dir=inc_ev, candidate_evidence_dir=cand_ev,
            blinding_nonce="0123456789abcdef-fixed", output_dir=tmp_path / "bad-prepared",
        )


def test_checker_private_key_must_match_registered_key(tmp_path):
    state = make_prepared(tmp_path / "base")
    from openline_endurance_gate.successor_benchmark import generate_keypair
    other_private, other_public = tmp_path / "other.private", tmp_path / "other.public"
    generate_keypair(other_private, other_public)
    lane = state["preparation"]["lane_mapping"]["candidate"]
    with pytest.raises(BenchmarkError, match="does not match"):
        sign_checker_report(
            package_dir=state["prepared"] / "checker_packages" / lane,
            status="PASS", metrics={"defects": 1, "task_score": 90}, citations=["result"],
            critical_failures=[], reason_codes=["checked"], checker_private_key_path=other_private,
            output_path=tmp_path / "bad-report.json",
        )


def test_checker_cannot_add_unregistered_metric(tmp_path):
    state = make_prepared(tmp_path / "base")
    lane = state["preparation"]["lane_mapping"]["candidate"]
    with pytest.raises(BenchmarkError, match="exactly match"):
        sign_checker_report(
            package_dir=state["prepared"] / "checker_packages" / lane,
            status="PASS", metrics={"defects": 1, "task_score": 90, "surprise": 999}, citations=["result"],
            critical_failures=[], reason_codes=["checked"], checker_private_key_path=state["private"],
            output_path=tmp_path / "bad-report.json",
        )


def test_checker_citation_must_reference_packaged_evidence(tmp_path):
    state = make_prepared(tmp_path / "base")
    lane = state["preparation"]["lane_mapping"]["candidate"]
    with pytest.raises(BenchmarkError, match="packaged evidence"):
        sign_checker_report(
            package_dir=state["prepared"] / "checker_packages" / lane,
            status="PASS", metrics={"defects": 1, "task_score": 90}, citations=["outside"],
            critical_failures=[], reason_codes=["checked"], checker_private_key_path=state["private"],
            output_path=tmp_path / "bad-report.json",
        )


def test_pass_report_cannot_contain_critical_failure(tmp_path):
    state = make_prepared(tmp_path / "base")
    lane = state["preparation"]["lane_mapping"]["candidate"]
    with pytest.raises(BenchmarkError, match="PASS report"):
        sign_checker_report(
            package_dir=state["prepared"] / "checker_packages" / lane,
            status="PASS", metrics={"defects": 1, "task_score": 90}, citations=["result"],
            critical_failures=["bad"], reason_codes=["checked"], checker_private_key_path=state["private"],
            output_path=tmp_path / "bad-report.json",
        )


def test_wrong_checker_report_signature_is_rejected_after_manifest_reseal(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 1, "task_score": 90})
    report = read(final / "checker_reports" / "candidate.json")
    report["signature"] = "0" * 128
    write_json(final / "checker_reports" / "candidate.json", report)
    _reseal(final)
    assert verify_case_directory(final, require_stored_verification=False)["valid"] is False


def test_changed_decision_is_rejected_after_manifest_reseal(tmp_path):
    final = finalize_with_metrics(tmp_path, {"defects": 2, "task_score": 80}, {"defects": 1, "task_score": 90})
    decision = read(final / "decision.json")
    decision["decision"] = "KEEP_INCUMBENT"
    write_json(final / "decision.json", decision)
    _reseal(final)
    assert verify_case_directory(final, require_stored_verification=False)["valid"] is False


def test_checker_package_has_no_role_or_peer_arm_fields(tmp_path):
    state = make_prepared(tmp_path)
    for lane in state["preparation"]["lane_mapping"].values():
        package = read(state["prepared"] / "checker_packages" / lane / "package.json")
        assert "role" not in package
        assert "incumbent" not in package
        assert "candidate" not in package


def test_independent_verifier_does_not_import_candidate_module():
    source = (Path(__file__).parents[1] / "src/openline_endurance_gate/successor_verifier.py").read_text()
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any("successor_benchmark" in name for name in imported)


def test_duplicate_json_keys_are_rejected(tmp_path):
    from openline_endurance_gate.successor_benchmark import load_json
    path = tmp_path / "dup.json"
    path.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(BenchmarkError, match="duplicate JSON key"):
        load_json(path)


def test_float_protocol_values_are_rejected(tmp_path):
    from openline_endurance_gate.successor_benchmark import load_json
    path = tmp_path / "float.json"
    path.write_text('{"a":1.5}', encoding="utf-8")
    with pytest.raises(BenchmarkError, match="floating-point"):
        load_json(path)


def test_symlink_evidence_is_rejected_when_supported(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    state = make_prepared(tmp_path / "base")
    candidate_evidence = tmp_path / "base" / "candidate-evidence"
    target = candidate_evidence / "result.txt"
    target.rename(candidate_evidence / "real.txt")
    os.symlink("real.txt", target)
    with pytest.raises(BenchmarkError, match="symlink evidence"):
        prepare_case(
            registration_path=state["registration"], task_path=state["inputs"]["task"], constraints_path=state["inputs"]["constraints"],
            budget_path=state["inputs"]["budget"], policy_path=state["inputs"]["policy"],
            incumbent_submission_path=tmp_path / "base" / "incumbent.json", candidate_submission_path=tmp_path / "base" / "candidate.json",
            incumbent_evidence_dir=tmp_path / "base" / "incumbent-evidence", candidate_evidence_dir=candidate_evidence,
            blinding_nonce="0123456789abcdef-fixed", output_dir=tmp_path / "nope",
        )


def _reseal(root: Path):
    from openline_endurance_gate.successor_benchmark import CASE_MANIFEST_SCHEMA, file_hash
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() not in {"case_manifest.json", "verification.json"}:
            entries.append({"path": path.relative_to(root).as_posix(), "sha256": file_hash(path), "bytes": path.stat().st_size})
    write_json(root / "case_manifest.json", {"schema": CASE_MANIFEST_SCHEMA, "entries": entries})


def test_release_checkout_normalizer_removes_unmanifested_files(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    work = tmp_path / "checkout"
    work.mkdir()
    (work / "scripts").mkdir()
    (work / "tests").mkdir()
    script_source = root / "scripts" / "prepare_release_checkout.py"
    script_target = work / "scripts" / "prepare_release_checkout.py"
    script_target.write_bytes(script_source.read_bytes())
    kept = work / "tests" / "test_successor_benchmark.py"
    kept.write_text("# kept\n", encoding="utf-8")
    stale = work / "tests" / "test_succession.py"
    stale.write_text("raise RuntimeError('retired test executed')\n", encoding="utf-8")
    (work / "RELEASE_VERIFICATION.json").write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema": "agent.successor.release-manifest.v1",
        "version": "test",
        "entries": [
            {"path": "scripts/prepare_release_checkout.py", "sha256": "unused", "bytes": script_target.stat().st_size},
            {"path": "tests/test_successor_benchmark.py", "sha256": "unused", "bytes": kept.stat().st_size},
        ],
    }
    (work / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script_target), "--apply", str(work)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert kept.exists()
    assert not stale.exists()
    parsed = json.loads(result.stdout)
    assert parsed["removed"] == 1
    assert parsed["remaining"] == []


def test_release_check_falls_back_to_isolated_build_without_setuptools(monkeypatch):
    import importlib.metadata
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("release_check_under_test", root / "scripts" / "release_check.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(module.importlib.metadata, "version", missing)
    assert module.build_backend_flags() == []


def test_release_check_rejects_too_old_ambient_setuptools(monkeypatch):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("release_check_under_test_old", root / "scripts" / "release_check.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setattr(module.importlib.metadata, "version", lambda _name: "67.9.0")
    assert module.build_backend_flags() == []
