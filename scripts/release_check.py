#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VERSION = "0.13.0rc1"
EXCLUDED_NAMES = {"RELEASE_MANIFEST.json", "RELEASE_VERIFICATION.json"}
EXCLUDED_PARTS = {".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist"}
def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    return {"command": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_env(extra: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(SRC)]
    if extra:
        paths.insert(0, extra)
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def release_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if rel.name in EXCLUDED_NAMES or rel.suffix in {".zip", ".sha256"}:
            continue
        files.append(path)
    return files


def write_manifest(root: Path) -> dict[str, object]:
    entries = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
        for path in release_files(root)
    ]
    manifest = {"schema": "agent.successor.release-manifest.v1", "version": VERSION, "entries": entries}
    (root / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def manifest_hash(manifest: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def check_public_language() -> list[str]:
    findings: list[str] = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = (
        "# Agent Successor Benchmark",
        "current agent",
        "candidate",
        "PROMOTE_CANDIDATE",
        "KEEP_INCUMBENT",
        "INCONCLUSIVE",
        "never executes a replacement",
    )
    for phrase in required:
        if phrase not in readme:
            findings.append(f"README missing plain-language contract: {phrase}")
    return findings


def check_verifier_import_boundary() -> bool:
    path = SRC / "openline_endurance_gate" / "successor_verifier.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    return not any("successor_benchmark" in name for name in imported)


def check_versions() -> bool:
    init = (SRC / "openline_endurance_gate" / "__init__.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return f'__version__ = "{VERSION}"' in init and f'version = "{VERSION}"' in pyproject


def main() -> int:
    report: dict[str, object] = {"schema": "agent.successor.release-verification.v1", "version": VERSION}
    compile_result = run([sys.executable, "-m", "compileall", "-q", "src", "scripts"], ROOT, source_env())
    report["compile"] = {"passed": compile_result["returncode"] == 0, "returncode": compile_result["returncode"]}

    tests = run([sys.executable, "-m", "pytest", "-q"], ROOT, source_env())
    report["tests"] = {"passed": tests["returncode"] == 0, "returncode": tests["returncode"], "summary": tests["stdout"].strip().splitlines()[-1] if tests["stdout"].strip() else ""}

    selftest_run = run([sys.executable, "scripts/successor_benchmark_selftest.py"], ROOT, source_env())
    try:
        selftest = json.loads(selftest_run["stdout"]) if selftest_run["stdout"] else {}
    except json.JSONDecodeError:
        selftest = {}
    report["hostile_selftest"] = {
        "passed": selftest_run["returncode"] == 0 and selftest.get("passed") is True,
        "check_count": selftest.get("check_count"),
        "passed_check_count": selftest.get("passed_check_count"),
    }

    crosscheck_run = run([sys.executable, "scripts/comparison_crosscheck.py"], ROOT, source_env())
    try:
        crosscheck = json.loads(crosscheck_run["stdout"]) if crosscheck_run["stdout"] else {}
    except json.JSONDecodeError:
        crosscheck = {}
    report["comparison_crosscheck"] = {
        "passed": crosscheck_run["returncode"] == 0 and crosscheck.get("passed") is True,
        "iterations": crosscheck.get("iterations"),
        "mismatches": crosscheck.get("mismatches"),
    }

    report["independent_verifier_import_boundary"] = {"passed": check_verifier_import_boundary()}
    language_findings = check_public_language()
    report["plain_language_check"] = {"passed": not language_findings, "findings": language_findings}
    report["version_consistency"] = {"passed": check_versions()}

    with tempfile.TemporaryDirectory(prefix="agent-successor-release-") as temp:
        temp_root = Path(temp)
        site = temp_root / "site"
        install = run([sys.executable, "-m", "pip", "install", ".", "--target", str(site), "--no-deps", "--no-build-isolation"], ROOT, source_env())
        clean_env = dict(os.environ)
        clean_env["PYTHONPATH"] = str(site)
        clean_env["PYTHONNOUSERSITE"] = "1"
        version = run([sys.executable, "-m", "openline_endurance_gate", "--version"], temp_root, clean_env)
        help_run = run([sys.executable, "-m", "openline_endurance_gate", "--help"], temp_root, clean_env)
        expected_commands = ("keygen", "register", "prepare", "checker-sign", "finalize", "verify")
        report["clean_install"] = {
            "passed": install["returncode"] == 0 and version["returncode"] == 0 and help_run["returncode"] == 0 and all(command in help_run["stdout"] for command in expected_commands),
            "install_returncode": install["returncode"],
            "reported_version": version["stdout"].strip(),
            "commands_present": [command for command in expected_commands if command in help_run["stdout"]],
        }

        wheel_dir = temp_root / "wheels"
        wheel_dir.mkdir()
        wheel = run([sys.executable, "-m", "pip", "wheel", ".", "--wheel-dir", str(wheel_dir), "--no-deps", "--no-build-isolation"], ROOT, source_env())
        wheels = sorted(wheel_dir.glob("*.whl"))
        wheel_site = temp_root / "wheel-site"
        wheel_install = {"returncode": 1, "stdout": "", "stderr": "wheel not built"}
        wheel_import = {"returncode": 1, "stdout": "", "stderr": "wheel not installed"}
        if wheel["returncode"] == 0 and len(wheels) == 1:
            wheel_install = run([sys.executable, "-m", "pip", "install", str(wheels[0]), "--target", str(wheel_site), "--no-deps"], temp_root, clean_env)
            wheel_env = dict(clean_env)
            wheel_env["PYTHONPATH"] = str(wheel_site)
            wheel_import = run([sys.executable, "-c", "import openline_endurance_gate as m; print(m.__version__)"], temp_root, wheel_env)
        report["wheel"] = {
            "passed": wheel["returncode"] == 0 and len(wheels) == 1 and wheel_install["returncode"] == 0 and wheel_import["returncode"] == 0 and wheel_import["stdout"].strip() == VERSION,
            "build_returncode": wheel["returncode"],
            "wheel_count": len(wheels),
            "imported_version": wheel_import["stdout"].strip(),
        }

    baseline = json.loads((ROOT / "BASELINE.json").read_text(encoding="utf-8"))
    report["baseline"] = {
        "version": baseline["incumbent"]["version"],
        "archive_sha256": baseline["incumbent"]["archive_sha256"],
        "preserved_capabilities": baseline["incumbent"]["verified_capabilities"],
    }

    passed = all(
        bool(report[name]["passed"])
        for name in (
            "compile", "tests", "hostile_selftest", "independent_verifier_import_boundary",
            "plain_language_check", "version_consistency", "comparison_crosscheck", "clean_install", "wheel",
        )
    )
    report["passed"] = passed

    comparison = {
        "schema": "agent.successor.release-comparison.v1",
        "incumbent": baseline["incumbent"],
        "candidate": {
            "version": VERSION,
            "preserved_capabilities": baseline["incumbent"]["verified_capabilities"],
            "improvements": [
                "candidate selection now uses direct checker outcomes instead of experimental metric-derived thresholds",
                "the maintained install has no dependency on the retired metric package",
                "checker packages remain lane-separated and omit incumbent/candidate role fields",
                "the final recommendation explicitly grants no execution authority",
                "the current source tree is a small benchmark package instead of a 48 MB research archive",
            ],
            "unit_test_summary": report["tests"]["summary"],
            "hostile_selftest_checks": report["hostile_selftest"]["check_count"],
            "randomized_comparison_checks": report["comparison_crosscheck"]["iterations"],
        },
        "promotion": "ADVANCE" if passed else "HOLD",
    }
    (ROOT / "RELEASE_COMPARISON.json").write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = write_manifest(ROOT)
    report["release_manifest"] = {"entry_count": len(manifest["entries"]), "sha256": manifest_hash(manifest)}
    (ROOT / "RELEASE_VERIFICATION.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
