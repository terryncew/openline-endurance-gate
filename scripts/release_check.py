from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / ".release_preflight.json"
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


def finalize_semantic() -> int:
    if not PREFLIGHT.exists():
        raise RuntimeError(f"missing release preflight: {PREFLIGHT}")
    report = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    PREFLIGHT.unlink(missing_ok=True)
    print("running: fresh-process full semantic verification", file=sys.stderr, flush=True)
    from openline_endurance_gate.verification import verify_evidence

    report["semantic_verification"] = verify_evidence(ROOT, ROOT, full_semantic=True)
    tamper = run([sys.executable, str(ROOT / "scripts" / "tamper_check.py")], ROOT)
    report["tamper_suite"] = {
        "command": tamper["command"],
        "returncode": tamper["returncode"],
        "stderr": tamper["stderr"],
    }
    tamper_path = ROOT / "TAMPER_REPORT.json"
    if tamper_path.exists():
        report["tamper_suite"]["report"] = json.loads(tamper_path.read_text(encoding="utf-8"))
    checks = [
        report["pytest"]["returncode"] == 0,
        report["clean_target_create"]["returncode"] == 0,
        report["clean_install"]["returncode"] == 0,
        report["clean_import"]["returncode"] == 0,
        report["clean_fast_verify"]["returncode"] == 0,
        report["clean_cli_tip"]["returncode"] == 0,
        report["semantic_verification"]["valid"],
        report["tamper_suite"]["returncode"] == 0,
        bool(report["tamper_suite"].get("report", {}).get("passed")),
    ]
    report["passed"] = all(checks)
    (ROOT / "RUN_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def preflight() -> int:
    root = ROOT
    PREFLIGHT.unlink(missing_ok=True)
    source_env = dict(os.environ)
    source_env["PYTHONPATH"] = str(root / "src")
    source_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    report: dict[str, object] = {"schema": "openline.endurance.release-report.v4"}
    report["pytest"] = run([sys.executable, "-m", "pytest", "-q"], root, source_env)

    with tempfile.TemporaryDirectory(prefix="openline-endurance-clean-") as temp:
        temp_root = Path(temp)
        clean = temp_root / "repo"
        shutil.copytree(
            root,
            clean,
            ignore=shutil.ignore_patterns(
                ".git",
                ".pytest_cache",
                "__pycache__",
                "*.egg-info",
                "RUN_REPORT.json",
                "TAMPER_REPORT.json",
                "RAW_TAMPER_REPORT.json",
                ".release_preflight.json",
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

    PREFLIGHT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preflight_passed = all(
        report[key]["returncode"] == 0
        for key in ("pytest", "clean_target_create", "clean_install", "clean_import", "clean_fast_verify", "clean_cli_tip")
    )
    print(json.dumps({"preflight_passed": preflight_passed}, indent=2), flush=True)
    if not preflight_passed:
        return 1
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--semantic-finalize"],
        cwd=root,
        env=source_env,
        check=False,
    )
    return completed.returncode


def main() -> int:
    if "--semantic-finalize" in sys.argv[1:]:
        return finalize_semantic()
    return preflight()


if __name__ == "__main__":
    raise SystemExit(main())
