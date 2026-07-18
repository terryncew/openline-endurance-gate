#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
cd "$ROOT"

capture_step() {
  local name="$1"
  shift
  set +e
  "$@" > "$ROOT/.release_preflight_parts/$name.stdout" 2> "$ROOT/.release_preflight_parts/$name.stderr"
  local rc=$?
  set -e
  printf '%s\n' "$rc" > "$ROOT/.release_preflight_parts/$name.rc"
  cat "$ROOT/.release_preflight_parts/$name.stdout"
  cat "$ROOT/.release_preflight_parts/$name.stderr" >&2
}

run_preflight() {
  rm -rf "$ROOT/.release_preflight_parts"
  mkdir -p "$ROOT/.release_preflight_parts"
  rm -f "$ROOT/.release_preflight.json" "$ROOT/.release_semantic.json"

  local filter="not test_fast_custody_verifier_passes_default_artifacts and not test_detached_release_attestation_binds_post_run_reports"
  capture_step pytest-0 env PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    "$PYTHON_BIN" -m pytest -q \
    tests/test_collision_spacing.py tests/test_damage.py tests/test_generational.py tests/test_load_rate.py tests/test_recovery.py tests/test_integrity.py tests/test_outputs.py \
    -k "$filter"
  capture_step pytest-1 env PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    "$PYTHON_BIN" -m pytest -q \
    tests/test_packaging.py tests/test_receipts.py tests/test_simulation.py tests/test_succession.py \
    -k "$filter"
  capture_step pytest-2 env PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    "$PYTHON_BIN" -m pytest -q \
    tests/test_state_restoration.py tests/test_statistics.py tests/test_tip_capture.py tests/test_world.py \
    -k "$filter"

  local tmp clean site
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/openline-endurance-clean.XXXXXX")"
  clean="$tmp/repo"
  site="$tmp/site"
  capture_step clean_copy "$PYTHON_BIN" -c \
    'import shutil,sys; from pathlib import Path; root=Path(sys.argv[1]); clean=Path(sys.argv[2]); shutil.copytree(root,clean,ignore=shutil.ignore_patterns(".git",".pytest_cache","__pycache__","*.egg-info",".release_preflight.json",".release_preflight_parts",".release_semantic.json",".state_restoration_semantic",".state_restoration_work",".load_rate_semantic",".load_rate_work",".recovery_semantic",".recovery_work","*.zip","*.sha256"))' \
    "$ROOT" "$clean"
  capture_step clean_target_create "$PYTHON_BIN" -c 'from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)' "$site"
  capture_step clean_install "$PYTHON_BIN" -m pip install "$clean" --target "$site" --no-deps --no-build-isolation
  capture_step clean_import env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -c 'import pathlib,sys,openline_endurance_gate as m; p=pathlib.Path(m.__file__).resolve(); site=pathlib.Path(sys.argv[1]).resolve(); print(m.__version__); print(p); assert p.is_relative_to(site)' "$site"
  capture_step clean_fast_verify env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate verify --root "$clean" --source-root "$clean" --fast --skip-release-attestation
  capture_step clean_cli_tip env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate tip-capture --root "$clean"
  capture_step clean_cli_spacing env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate collision-spacing --root "$clean"
  capture_step clean_cli_generational env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate generational --root "$clean"
  capture_step clean_cli_state_restoration env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate state-restoration --root "$clean"
  capture_step clean_cli_load_rate env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate load-rate --root "$clean"
  capture_step clean_cli_recovery env PYTHONPATH="$site" PYTHONNOUSERSITE=1 \
    "$PYTHON_BIN" -m openline_endurance_gate recovery --root "$clean"
  rm -rf "$tmp"

  PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --preflight-finalize-raw
}

if [[ "${1:-}" == "--preflight-only" ]]; then
  if [[ $# -ne 1 ]]; then
    echo "usage: bash scripts/release_check.sh [--preflight-only]" >&2
    exit 2
  fi
  run_preflight
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "usage: bash scripts/release_check.sh [--preflight-only]" >&2
  exit 2
fi

run_preflight
rm -rf "${TMPDIR:-/tmp}"/openline-v9-recovery-semantic-*
for index in $(seq 0 11); do
  PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --semantic-v91-shard "$index"
done
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --semantic-v91-finalize
bash scripts/tamper_check.sh --release
PYTHONPATH="$ROOT/src" "$PYTHON_BIN" -u scripts/release_check.py --finalize-existing
