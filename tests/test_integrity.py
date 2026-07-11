import json
from pathlib import Path

from openline_endurance_gate.integrity import verify_preregistration
from openline_endurance_gate.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def test_preregistration_locks_experiment_and_mechanisms():
    assert verify_preregistration(ROOT) == []
    prereg = json.loads((ROOT / "PREREGISTRATION.json").read_text())
    assert prereg["experiment_sha256"] == sha256_file(ROOT / "experiment.json")
    assert prereg["locked_design"]["randomness_coupling"] == "EVENT_BOUND_COMMON_RANDOM_NUMBERS"
    assert prereg["locked_design"]["tip_capture"]["analysis_plan"]["heldout_seed_count"] == 80


def test_public_witness_is_compact_and_self_scoped():
    witness = json.loads((ROOT / "results/public_witness.json").read_text())
    assert witness["external_anchor_status"] == "UNPUBLISHED_LOCAL_WITNESS"
    assert len(witness["witness_digest"]) == 64
    assert "whole-repository replacement" in witness["claim_boundary"]


def test_streaming_csv_merkle_matches_in_memory(tmp_path):
    from openline_endurance_gate.integrity import merkle_root
    from openline_endurance_gate.util import read_csv, write_csv
    from openline_endurance_gate.verification import _coerce, _csv_merkle_root

    path = tmp_path / "rows.csv"
    rows = [
        {"seed": 1, "damage_D": 0.25, "first_failure_cycle": None, "mode": "null"},
        {"seed": 2, "damage_D": 0.5, "first_failure_cycle": 7, "mode": "tip"},
    ]
    write_csv(path, rows, ["seed", "damage_D", "first_failure_cycle", "mode"])
    streamed_root, count = _csv_merkle_root(path)
    assert count == len(rows)
    assert streamed_root == merkle_root(_coerce(read_csv(path)))
