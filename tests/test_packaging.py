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


def test_no_private_signing_key_is_persisted():
    forbidden = {"private.key", "signing.key", "ed25519.key", "private.pem"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*"))
