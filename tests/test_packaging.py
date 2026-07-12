import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_import_and_cli_help():
    completed = subprocess.run(
        [sys.executable, "-m", "openline_endurance_gate", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "verify" in completed.stdout
    assert "witness" in completed.stdout
    assert "fracture" in completed.stdout
    assert "tip-capture" in completed.stdout
    assert "collision-spacing" in completed.stdout
    assert "generational" in completed.stdout
    assert "state-restoration" in completed.stdout
    assert "semantic-shard" in completed.stdout
    assert "semantic-finalize" in completed.stdout


def test_no_private_signing_key_is_persisted():
    forbidden = {"private.key", "signing.key", "ed25519.key", "private.pem"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*"))


def test_release_check_shell_uses_top_level_phases():
    wrapper = (ROOT / "scripts" / "release_check.sh").read_text(encoding="utf-8")
    assert "capture_step pytest-0" in wrapper
    assert "capture_step pytest-1" in wrapper
    assert "capture_step pytest-2" in wrapper
    assert "--preflight-finalize-raw" in wrapper
    assert "--preflight-only" in wrapper
    assert "--semantic-shard" in wrapper
    assert "--semantic-finalize" in wrapper
    assert "scripts/tamper_check.sh --release" in wrapper
    assert "--finalize-existing" in wrapper
    assert "sleep " not in wrapper


def test_standalone_tamper_check_does_not_overwrite_attested_report():
    wrapper = (ROOT / "scripts" / "tamper_check.sh").read_text(encoding="utf-8")
    assert 'OUTPUT="$ROOT/TAMPER_REPORT.standalone.json"' in wrapper
    assert 'OUTPUT="$ROOT/TAMPER_REPORT.json"' in wrapper
    assert 'if [[ "${1:-}" == "--release" ]]' in wrapper


def test_release_preflight_can_rebuild_stale_outer_attestation():
    source = (ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8")
    assert "--skip-release-attestation" in source
    assert "not test_fast_custody_verifier_passes_default_artifacts" in source
    assert "not test_detached_release_attestation_binds_post_run_reports" in source
    assert "PREFLIGHT_PARTS" in source
    assert "preflight_group" in source
    assert "preflight_finalize" in source
