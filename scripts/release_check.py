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


def preflight_only() -> int:
    PREFLIGHT.unlink(missing_ok=True)
    SEMANTIC.unlink(missing_ok=True)
    source_env = dict(os.environ)
    source_env["PYTHONPATH"] = str(ROOT / "src")
    source_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    report: dict[str, object] = {"schema": "openline.endurance.release-report.v5"}
    report["pytest"] = run([sys.executable, "-m", "pytest", "-q"], ROOT, source_env)

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
                ".release_semantic.json",
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
            [sys.executable, "-m", "openline_endurance_gate", "verify", "--root", ".", "--source-root", ".", "--fast"],
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

    PREFLIGHT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
        )
    )
    print(json.dumps({"preflight_passed": passed}, indent=2))
    return 0 if passed else 1


def semantic_only() -> int:
    if not PREFLIGHT.exists():
        raise RuntimeError(f"missing release preflight: {PREFLIGHT}")
    report = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    print("running: top-level full semantic verification", file=sys.stderr, flush=True)
    from openline_endurance_gate.verification import verify_evidence

    report["semantic_verification"] = verify_evidence(ROOT, ROOT, full_semantic=True)
    SEMANTIC.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    passed = bool(report["semantic_verification"]["valid"])
    print(json.dumps({"semantic_verification_passed": passed}, indent=2))
    return 0 if passed else 1


def finalize_existing() -> int:
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
        report["clean_target_create"]["returncode"] == 0,
        report["clean_install"]["returncode"] == 0,
        report["clean_import"]["returncode"] == 0,
        report["clean_fast_verify"]["returncode"] == 0,
        report["clean_cli_tip"]["returncode"] == 0,
        report["clean_cli_spacing"]["returncode"] == 0,
        report["semantic_verification"]["valid"],
        report["tamper_suite"]["returncode"] == 0,
        bool(report["tamper_suite"].get("report", {}).get("passed")),
    ]
    report["passed"] = all(checks)
    (ROOT / "RUN_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PREFLIGHT.unlink(missing_ok=True)
    SEMANTIC.unlink(missing_ok=True)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--semantic-only", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        return preflight_only()
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
