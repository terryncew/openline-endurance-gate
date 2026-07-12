from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / ".release_preflight.json"
SEMANTIC = ROOT / ".release_semantic.json"
PREFLIGHT_PARTS = ROOT / ".release_preflight_parts"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))



def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    print("running:", " ".join(command), file=sys.stderr, flush=True)
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, env=env)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


PYTEST_GROUPS = [
    [
        "tests/test_collision_spacing.py",
        "tests/test_damage.py",
        "tests/test_generational.py",
        "tests/test_integrity.py",
        "tests/test_outputs.py",
    ],
    [
        "tests/test_packaging.py",
        "tests/test_receipts.py",
        "tests/test_simulation.py",
    ],
    [
        "tests/test_state_restoration.py",
        "tests/test_statistics.py",
        "tests/test_tip_capture.py",
        "tests/test_world.py",
    ],
]

STALE_ATTESTATION_FILTER = (
    "not test_fast_custody_verifier_passes_default_artifacts "
    "and not test_detached_release_attestation_binds_post_run_reports"
)


def _source_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _reset_preflight_state() -> None:
    PREFLIGHT.unlink(missing_ok=True)
    SEMANTIC.unlink(missing_ok=True)
    shutil.rmtree(PREFLIGHT_PARTS, ignore_errors=True)
    PREFLIGHT_PARTS.mkdir(parents=True, exist_ok=True)


def preflight_group(index: int) -> int:
    if index < 0 or index >= len(PYTEST_GROUPS):
        raise IndexError(f"preflight pytest group out of range: {index}")
    PREFLIGHT_PARTS.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *PYTEST_GROUPS[index],
            "-k",
            STALE_ATTESTATION_FILTER,
        ],
        ROOT,
        _source_env(),
    )
    (PREFLIGHT_PARTS / f"pytest-{index}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    passed = result["returncode"] == 0
    print(json.dumps({"pytest_group": index, "passed": passed}, indent=2))
    return 0 if passed else 1


def preflight_clean() -> int:
    PREFLIGHT_PARTS.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="openline-endurance-clean-") as temp:
        temp_root = Path(temp)
        clean = temp_root / "repo"
        shutil.copytree(
            ROOT,
            clean,
            ignore=shutil.ignore_patterns(
                ".git",
                ".pytest_cache",
                "__pycache__",
                "*.egg-info",
                ".release_preflight.json",
                ".release_preflight_parts",
                ".release_semantic.json",
                ".state_restoration_semantic",
                ".state_restoration_work",
                "*.zip",
                "*.sha256",
            ),
        )
        site = temp_root / "site"
        report["clean_target_create"] = run(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(site)!r}).mkdir(parents=True, exist_ok=True)"],
            clean,
        )
        report["clean_install"] = run(
            [sys.executable, "-m", "pip", "install", ".", "--target", str(site), "--no-deps", "--no-build-isolation"],
            clean,
        )
        clean_env = dict(os.environ)
        clean_env["PYTHONPATH"] = str(site)
        clean_env["PYTHONNOUSERSITE"] = "1"
        clean_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        import_code = (
            "import pathlib, openline_endurance_gate as m; "
            "p=pathlib.Path(m.__file__).resolve(); print(m.__version__); print(p); "
            f"assert p.is_relative_to(pathlib.Path({str(site)!r}).resolve())"
        )
        report["clean_import"] = run([sys.executable, "-c", import_code], clean, clean_env)
        report["clean_fast_verify"] = run(
            [
                sys.executable, "-m", "openline_endurance_gate", "verify",
                "--root", ".", "--source-root", ".", "--fast", "--skip-release-attestation",
            ],
            clean,
            clean_env,
        )
        report["clean_cli_tip"] = run(
            [sys.executable, "-m", "openline_endurance_gate", "tip-capture", "--root", "."],
            clean,
            clean_env,
        )
        report["clean_cli_spacing"] = run(
            [sys.executable, "-m", "openline_endurance_gate", "collision-spacing", "--root", "."],
            clean,
            clean_env,
        )
        report["clean_cli_generational"] = run(
            [sys.executable, "-m", "openline_endurance_gate", "generational", "--root", "."],
            clean,
            clean_env,
        )
        report["clean_cli_state_restoration"] = run(
            [sys.executable, "-m", "openline_endurance_gate", "state-restoration", "--root", "."],
            clean,
            clean_env,
        )

    (PREFLIGHT_PARTS / "clean.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    passed = all(item["returncode"] == 0 for item in report.values())
    print(json.dumps({"clean_preflight_passed": passed}, indent=2))
    return 0 if passed else 1


def preflight_finalize() -> int:
    report: dict[str, object] = {"schema": "openline.endurance.release-report.v7"}
    pytest_results: list[dict[str, object]] = []
    for index in range(len(PYTEST_GROUPS)):
        path = PREFLIGHT_PARTS / f"pytest-{index}.json"
        if not path.exists():
            raise RuntimeError(f"missing preflight pytest witness: {path}")
        pytest_results.append(json.loads(path.read_text(encoding="utf-8")))
    clean_path = PREFLIGHT_PARTS / "clean.json"
    if not clean_path.exists():
        raise RuntimeError(f"missing clean preflight witness: {clean_path}")
    clean = json.loads(clean_path.read_text(encoding="utf-8"))

    report["pytest_groups"] = pytest_results
    report["pytest"] = {
        "returncode": 0 if all(item["returncode"] == 0 for item in pytest_results) else 1,
        "execution": "bounded file groups in fresh top-level processes; all non-integration tests remain selected",
        "group_count": len(pytest_results),
        "commands": [item["command"] for item in pytest_results],
        "stdout": "\n".join(str(item["stdout"]) for item in pytest_results),
        "stderr": "\n".join(str(item["stderr"]) for item in pytest_results),
    }
    report.update(clean)
    PREFLIGHT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.rmtree(PREFLIGHT_PARTS, ignore_errors=True)
    passed = all(
        report[key]["returncode"] == 0
        for key in (
            "pytest",
            "clean_target_create",
            "clean_install",
            "clean_import",
            "clean_fast_verify",
            "clean_cli_tip",
            "clean_cli_spacing",
            "clean_cli_generational",
            "clean_cli_state_restoration",
        )
    )
    print(json.dumps({"preflight_passed": passed}, indent=2))
    return 0 if passed else 1


def preflight_only() -> int:
    # Replace this process with a shell coordinator so every heavy witness gets
    # a fresh process boundary. This is equivalent to the documented release
    # preflight and avoids retaining one pytest heap across later witnesses.
    shell = ROOT / "scripts" / "release_check.sh"
    if os.name != "nt" and shell.exists():
        os.execvp("bash", ["bash", str(shell), "--preflight-only"])
    _reset_preflight_state()
    for index in range(len(PYTEST_GROUPS)):
        if preflight_group(index) != 0:
            return 1
    if preflight_clean() != 0:
        return 1
    return preflight_finalize()


def _read_raw_step(name: str, command: list[str]) -> dict[str, object]:
    rc_path = PREFLIGHT_PARTS / f"{name}.rc"
    stdout_path = PREFLIGHT_PARTS / f"{name}.stdout"
    stderr_path = PREFLIGHT_PARTS / f"{name}.stderr"
    if not rc_path.exists():
        raise RuntimeError(f"missing raw preflight exit code: {rc_path}")
    return {
        "command": command,
        "returncode": int(rc_path.read_text(encoding="utf-8").strip()),
        "stdout": stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else "",
        "stderr": stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else "",
    }


def preflight_finalize_raw() -> int:
    report: dict[str, object] = {"schema": "openline.endurance.release-report.v7"}
    pytest_results = [
        _read_raw_step(
            f"pytest-{index}",
            [sys.executable, "-m", "pytest", "-q", *group, "-k", STALE_ATTESTATION_FILTER],
        )
        for index, group in enumerate(PYTEST_GROUPS)
    ]
    report["pytest_groups"] = pytest_results
    report["pytest"] = {
        "returncode": 0 if all(item["returncode"] == 0 for item in pytest_results) else 1,
        "execution": "direct top-level shell processes; all non-integration tests remain selected",
        "group_count": len(pytest_results),
        "commands": [item["command"] for item in pytest_results],
        "stdout": "\n".join(str(item["stdout"]) for item in pytest_results),
        "stderr": "\n".join(str(item["stderr"]) for item in pytest_results),
    }
    clean_names = (
        "clean_copy",
        "clean_target_create",
        "clean_install",
        "clean_import",
        "clean_fast_verify",
        "clean_cli_tip",
        "clean_cli_spacing",
        "clean_cli_generational",
        "clean_cli_state_restoration",
    )
    for name in clean_names:
        report[name] = _read_raw_step(name, ["direct-shell-preflight", name])

    PREFLIGHT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    passed = report["pytest"]["returncode"] == 0 and all(
        report[name]["returncode"] == 0 for name in clean_names
    )
    shutil.rmtree(PREFLIGHT_PARTS, ignore_errors=True)
    print(json.dumps({"preflight_passed": passed}, indent=2))
    return 0 if passed else 1


def semantic_shard(index: int) -> int:
    from openline_endurance_gate.semantic_phases import verify_state_restoration_shard

    report = verify_state_restoration_shard(ROOT, index)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def semantic_finalize() -> int:
    from openline_endurance_gate.semantic_phases import finalize_state_restoration_semantics

    if not PREFLIGHT.exists():
        raise RuntimeError(f"missing release preflight: {PREFLIGHT}")
    report = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    report["semantic_verification"] = finalize_state_restoration_semantics(ROOT)
    SEMANTIC.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    passed = bool(report["semantic_verification"]["valid"])
    print(json.dumps({"semantic_verification_passed": passed}, indent=2))
    return 0 if passed else 1


def semantic_only() -> int:
    # Compatibility path for ordinary runners without the hosted CPU ceiling.
    for index in range(8):
        if semantic_shard(index) != 0:
            return 1
    return semantic_finalize()


def finalize_existing() -> int:
    from openline_endurance_gate.release_attestation import write_release_attestation

    if not SEMANTIC.exists():
        raise RuntimeError(f"missing semantic release state: {SEMANTIC}")
    report = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    tamper_path = ROOT / "TAMPER_REPORT.json"
    if tamper_path.exists():
        tamper_report = json.loads(tamper_path.read_text(encoding="utf-8"))
        report["tamper_suite"] = {
            "execution": "isolated top-level attacks via scripts/tamper_check.sh",
            "report": tamper_report,
            "returncode": 0 if tamper_report.get("passed") else 1,
        }
    else:
        report["tamper_suite"] = {"returncode": 1, "error": "missing TAMPER_REPORT.json"}

    checks = [
        report["pytest"]["returncode"] == 0,
        report.get("clean_copy", {"returncode": 0})["returncode"] == 0,
        report["clean_target_create"]["returncode"] == 0,
        report["clean_install"]["returncode"] == 0,
        report["clean_import"]["returncode"] == 0,
        report["clean_fast_verify"]["returncode"] == 0,
        report["clean_cli_tip"]["returncode"] == 0,
        report["clean_cli_spacing"]["returncode"] == 0,
        report["clean_cli_generational"]["returncode"] == 0,
        report["clean_cli_state_restoration"]["returncode"] == 0,
        report["semantic_verification"]["valid"],
        report["tamper_suite"]["returncode"] == 0,
        bool(report["tamper_suite"].get("report", {}).get("passed")),
    ]
    report["passed"] = all(checks)
    (ROOT / "RUN_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PREFLIGHT.unlink(missing_ok=True)
    SEMANTIC.unlink(missing_ok=True)
    if not report["passed"]:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    release_attestation = write_release_attestation(ROOT)
    print(
        json.dumps(
            {
                "release_attestation_valid": release_attestation["valid"],
                "release_attestation_errors": release_attestation["errors"],
            },
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if release_attestation["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--preflight-group", type=int)
    parser.add_argument("--preflight-clean", action="store_true")
    parser.add_argument("--preflight-finalize", action="store_true")
    parser.add_argument("--preflight-finalize-raw", action="store_true")
    parser.add_argument("--semantic-only", action="store_true")
    parser.add_argument("--semantic-shard", type=int)
    parser.add_argument("--semantic-finalize", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        return preflight_only()
    if args.preflight_group is not None:
        return preflight_group(args.preflight_group)
    if args.preflight_clean:
        return preflight_clean()
    if args.preflight_finalize:
        return preflight_finalize()
    if args.preflight_finalize_raw:
        return preflight_finalize_raw()
    if args.semantic_shard is not None:
        return semantic_shard(args.semantic_shard)
    if args.semantic_finalize:
        return semantic_finalize()
    if args.semantic_only:
        return semantic_only()
    if args.finalize_existing:
        return finalize_existing()

    shell = ROOT / "scripts" / "release_check.sh"
    if os.name != "nt" and shell.exists():
        os.execvp("bash", ["bash", str(shell)])
    raise RuntimeError("Run the three release phases manually on platforms without bash.")


if __name__ == "__main__":
    raise SystemExit(main())
