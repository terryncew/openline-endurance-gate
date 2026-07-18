import json
from pathlib import Path

from openline_endurance_gate.integrity import verify_preregistration, verify_v091_lineage
from openline_endurance_gate.tooling_lineage import verify_v0100_tooling_lineage
from openline_endurance_gate.util import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def test_preregistration_locks_experiment_and_mechanisms():
    assert verify_preregistration(ROOT) == []
    prereg = json.loads((ROOT / "PREREGISTRATION.json").read_text())
    assert prereg["schema"] == "openline.endurance.preregistration.v7"
    assert prereg["experiment_sha256"] == sha256_file(ROOT / "experiment.json")
    assert prereg["locked_design"]["release_version"] == "0.9.1"
    assert prereg["lineage_file"] == "V091_LINEAGE.json"
    assert prereg["pass"] == 2
    assert prereg["freshness_binding"]["verifier_state_updates"] == "caller_applies_proposed_update_only_on_acceptance"
    assert prereg["freshness_binding"]["hostile_controls"] == [
        "stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay",
    ]
    assert prereg["fresh_seed_status"] == "NO_V0.9.0_RECOVERY_SEED_REUSED"
    assert "src/openline_endurance_gate/recovery.py" in prereg["mechanism_hashes"]
    assert verify_v091_lineage(ROOT) == []


def test_public_witness_is_compact_and_self_scoped():
    witness = json.loads((ROOT / "results/public_witness.json").read_text())
    assert witness["external_anchor_status"] == "UNPUBLISHED_LOCAL_WITNESS"
    assert len(witness["witness_digest"]) == 64
    assert "whole-repository replacement" in witness["claim_boundary"]


def test_v0100_tooling_lineage_preserves_the_scientific_artifact_set():
    assert verify_v0100_tooling_lineage(ROOT) == []


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
