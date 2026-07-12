#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
cd "$ROOT"
PYTHONPATH="$ROOT/src" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON_BIN" -u scripts/release_check.py --preflight-only
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --semantic-only
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/tamper_check.py
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --finalize-existing
