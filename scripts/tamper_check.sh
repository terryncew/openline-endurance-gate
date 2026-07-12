#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
MODE="standalone"
if [[ "${1:-}" == "--release" ]]; then
  MODE="release"
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "usage: bash scripts/tamper_check.sh [--release]" >&2
  exit 2
fi
if [[ "$MODE" == "release" ]]; then
  OUTPUT="$ROOT/TAMPER_REPORT.json"
else
  OUTPUT="$ROOT/TAMPER_REPORT.standalone.json"
fi
TMP="$(mktemp -d "${TMPDIR:-/tmp}/openline-tamper.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
ATTACKS=(
  resealed_raw_cycle_forgery
  resealed_first_contact_forgery
  resealed_collision_spacing_forgery
  resealed_generational_forgery
  resealed_state_restoration_forgery
  resealed_load_rate_cycle_forgery
  resealed_summary_forgery
  tail_truncation
  unpatched_source_drift
  release_report_mutation
  recovery_signed_packet_mutation
  recovery_evidence_hash_mutation
  recovery_receipt_chain_mutation
  recovery_report_forgery
  recovery_summary_reseal
  recovery_stale_packet_replay
  recovery_cross_run_packet_copy
  recovery_generation_rollback
  recovery_same_packet_replay
)
status=0
for attack in "${ATTACKS[@]}"; do
  echo "running $attack" >&2
  if ! PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u "$ROOT/scripts/tamper_check.py" --attack "$attack" > "$TMP/$attack.json"; then
    status=1
  fi
done
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u "$ROOT/scripts/tamper_check.py" --aggregate-dir "$TMP" --output "$OUTPUT" || status=1
if [[ "$MODE" == "standalone" ]]; then
  echo "standalone tamper witness: $OUTPUT" >&2
  echo "This file is intentionally outside the detached release attestation." >&2
fi
exit "$status"
