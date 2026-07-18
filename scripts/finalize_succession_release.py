#!/usr/bin/env python3
"""Finalize a locally verified v0.10.0 candidate and detached attestation.

The report distinguishes executed local gates from the GitHub pytest gate. If
pytest is unavailable, the result is a local release candidate, not a tagged
release, even when semantic, hostile, and succession checks pass.
"""

from __future__ import annotations

import argparse
import compileall
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate import __version__
from openline_endurance_gate.release_attestation import write_release_attestation
from openline_endurance_gate.succession import write_json
from openline_endurance_gate.verification import verify_evidence


def run(command: list[str], root: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def finalize(root: Path) -> dict:
    root = root.resolve()
    env = dict(os.environ)
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + inherited if inherited else "")

    candidate = json.loads((root / "receipts/succession-candidate-report.json").read_text(encoding="utf-8"))
    if candidate.get("candidate_passed") is not True:
        raise RuntimeError("succession candidate seal is not passing")

    selftest_execution = run([sys.executable, "scripts/succession_selftest.py"], root, env)
    if selftest_execution["returncode"] != 0:
        raise RuntimeError("succession self-test execution failed")
    try:
        selftest = json.loads(selftest_execution["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("succession self-test emitted invalid JSON") from exc
    persisted_selftest = json.loads(
        (root / "results/succession_synthetic_selftest.json").read_text(encoding="utf-8")
    )
    if persisted_selftest != selftest:
        raise RuntimeError("persisted succession self-test does not match live output")

    cli = run([sys.executable, "-m", "openline_endurance_gate", "--help"], root, env)
    cli_passed = cli["returncode"] == 0 and all(
        command in cli["stdout"]
        for command in ("succession-init", "succession-measure", "succession-calibrate", "succession-assess")
    )
    compile_passed = compileall.compile_dir(root / "src", quiet=1) and compileall.compile_file(
        root / "scripts/succession_selftest.py", quiet=1
    )
    semantic = verify_evidence(root, root, full_semantic=True, verify_release=False)
    tamper = json.loads((root / "TAMPER_REPORT.json").read_text(encoding="utf-8"))

    pytest_available = importlib.util.find_spec("pytest") is not None
    pytest_status = {
        "available": pytest_available,
        "executed": False,
        "passed": None,
        "reason": (
            "This local runner does not provide pytest. The committed GitHub workflow installs the exact dev extra and runs the complete non-integration suite."
            if not pytest_available
            else "Not rerun by this finalizer; use scripts/release_check.sh for the complete pytest release gate."
        ),
        "required_workflow": ".github/workflows/succession.yml",
    }
    local_checks_passed = bool(
        candidate["candidate_passed"]
        and selftest.get("passed")
        and cli_passed
        and compile_passed
        and semantic["valid"]
        and tamper.get("passed")
    )
    report = {
        "schema": "openline.endurance.succession-tooling-release-report.v1",
        "tooling_version": __version__,
        "scientific_release_preserved": "0.9.1",
        "release_status": "LOCAL_CANDIDATE_AWAITING_GITHUB_CI",
        "passed": local_checks_passed,
        "candidate_seal": candidate,
        "succession_selftest": {
            "returncode": selftest_execution["returncode"],
            "result": selftest,
        },
        "cli_smoke": {
            "returncode": cli["returncode"],
            "passed": cli_passed,
            "commands_present": [
                "succession-init", "succession-measure", "succession-calibrate", "succession-assess"
            ],
        },
        "compileall": {"passed": compile_passed},
        "pytest": pytest_status,
        "semantic_verification": semantic,
        "tamper_suite": {
            "execution": "19 isolated top-level hostile attacks via scripts/tamper_check.sh --release",
            "report": tamper,
            "returncode": 0 if tamper.get("passed") else 1,
        },
        "claim_boundary": (
            "Local candidate gates passed, but the complete GitHub pytest workflow must pass after push before tagging v0.10.0. "
            "The succession self-test is synthetic and does not establish deployed-agent benefit."
        ),
    }
    write_json(root / "RUN_REPORT.json", report)
    if not local_checks_passed:
        raise RuntimeError("one or more local release-candidate gates failed")
    attestation = write_release_attestation(root)
    return {
        "local_candidate_passed": True,
        "release_status": report["release_status"],
        "tooling_version": __version__,
        "succession_checks": selftest["check_count"],
        "tamper_attacks": len(tamper["attacks"]),
        "full_semantic_verification": semantic["valid"],
        "detached_attestation_valid": attestation["valid"],
        "pytest": pytest_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    try:
        result = finalize(Path(args.root))
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"local_candidate_passed": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
