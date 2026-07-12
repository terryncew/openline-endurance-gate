#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openline-tamper.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
ATTACKS=(
  resealed_raw_cycle_forgery
  resealed_first_contact_forgery
  resealed_collision_spacing_forgery
  resealed_summary_forgery
  tail_truncation
  unpatched_source_drift
)
status=0
for attack in "${ATTACKS[@]}"; do
  echo "running $attack" >&2
  if ! PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u "$ROOT/scripts/tamper_check.py" --attack "$attack" > "$TMP/$attack.json"; then
    status=1
  fi
done
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u "$ROOT/scripts/tamper_check.py" --aggregate-dir "$TMP" || status=1
exit "$status"
