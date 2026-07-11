#!/usr/bin/env bash
set -euo pipefail
python scripts/release_check.py --preflight
sleep 2
python scripts/release_check.py --semantic-finalize
