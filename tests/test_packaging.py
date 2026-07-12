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


def test_no_private_signing_key_is_persisted():
    forbidden = {"private.key", "signing.key", "ed25519.key", "private.pem"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*"))


def test_release_check_shell_uses_top_level_phases():
    wrapper = (ROOT / "scripts" / "release_check.sh").read_text(encoding="utf-8")
    assert wrapper.count("scripts/release_check.py") == 3
    assert "--preflight-only" in wrapper
    assert "--semantic-only" in wrapper
    assert "scripts/tamper_check.py" in wrapper
    assert "--finalize-existing" in wrapper
    assert "--semantic-finalize" not in wrapper
    assert "sleep " not in wrapper
