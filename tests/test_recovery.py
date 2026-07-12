import copy
import json
from pathlib import Path

from openline_endurance_gate.recovery import (
    GENESIS_PARENT_HASH, MODES, REQUIREMENTS, RecoveryState, RecoveryVerifierSession,
    _simulate_one, create_olp_handoff, create_unsigned_handoff, derive_run_id,
    advance_recovery_session, run_hostile_controls, verify_olp_handoff, verify_unsigned_handoff,
)

ROOT = Path(__file__).resolve().parents[1]


def _experiment():
    return json.loads((ROOT / "experiment.json").read_text(encoding="utf-8"))


def test_recovery_design_has_five_fair_conditions_and_frozen_depth():
    config = _experiment()["recovery"]
    assert config["modes"] == list(MODES)
    assert config["horizon_cycles"] == 320
    assert config["intervention_cycle"] == 80
    assert config["freshness_mechanism_status"] == "ACTIVE_STATEFUL_V0.9.1"
    assert config["pass"] == 2
    assert set(config["training_seeds"]).isdisjoint(config["heldout_seeds"])
    assert set(config["validation_seeds"]).isdisjoint(config["heldout_seeds"])
    assert not set(config["seeds"]).intersection(range(9101, 9157))
    assert len(config["heldout_seeds"]) == 80


def test_common_random_stream_is_condition_bound_not_mode_bound():
    experiment = _experiment()
    seed = experiment["recovery"]["training_seeds"][0]
    left, _, _ = _simulate_one("continuous_control", seed, experiment)
    right, _, _ = _simulate_one("olp_handoff", seed, experiment)
    assert [
        (row["event_id"], row["amplitude"], row["target"], row["truth_delta"], row["common_random_draw"])
        for row in left
    ] == [
        (row["event_id"], row["amplitude"], row["target"], row["truth_delta"], row["common_random_draw"])
        for row in right
    ]


def test_unsigned_checksum_has_identical_fields_but_attacker_can_rebind_and_recompute():
    run_id = derive_run_id("test", "unsigned")
    session = RecoveryVerifierSession(run_id)
    packet = create_unsigned_handoff(
        RecoveryState.initial(), 80, run_id=run_id, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    clean = verify_unsigned_handoff(packet, session)
    assert clean["status"] == "accepted"
    assert not clean["origin_verified"]
    assert not clean["coverage_verified"]
    assert clean["freshness_verified"]
    changed = copy.deepcopy(packet)
    changed["payload"]["persistent_state"][REQUIREMENTS[0]] += 1
    assert verify_unsigned_handoff(changed, session)["reason_codes"] == ["checksum_mismatch"]
    session = advance_recovery_session(session, clean)
    rebound = copy.deepcopy(packet)
    fields = {
        "run_id": run_id,
        "generation_index": 2,
        "parent_hash": session.last_accepted_parent_hash,
    }
    rebound.update(fields)
    rebound["payload"].update(fields)
    from openline_endurance_gate.util import canonical_json, sha256_bytes
    rebound["checksum"] = sha256_bytes(canonical_json(rebound["payload"]))
    assert verify_unsigned_handoff(rebound, session)["status"] == "accepted"


def test_olp_has_exact_eight_receipts_and_rejects_unknown_coverage():
    run_id = derive_run_id("test", "coverage")
    packet = create_olp_handoff(
        RecoveryState.initial(), 80, 1234, run_id=run_id,
        generation_index=1, parent_hash=GENESIS_PARENT_HASH,
    )
    assert len(packet["receipts"]) == 8
    assert all(receipt["run_id"] == run_id for receipt in packet["receipts"])
    assert verify_olp_handoff(packet, RecoveryVerifierSession(run_id))["status"] == "accepted"
    omitted = copy.deepcopy(packet)
    omitted["payload"]["persistent_state"].pop(REQUIREMENTS[0])
    result = verify_olp_handoff(omitted, RecoveryVerifierSession(run_id))
    assert result["status"] == "rejected"  # signed body no longer matches
    assert "required_state_incomplete" in result["reason_codes"]


def test_correctly_signed_omission_is_undecidable_not_accepted():
    run_id = derive_run_id("test", "signed-omission")
    packet = create_olp_handoff(
        RecoveryState.initial(), 80, 1235, run_id=run_id,
        generation_index=1, parent_hash=GENESIS_PARENT_HASH,
        omit_required_field=REQUIREMENTS[0],
    )
    result = verify_olp_handoff(packet, RecoveryVerifierSession(run_id))
    assert result["signature_valid"]
    assert result["status"] == "undecidable"
    assert "required_state_incomplete" in result["reason_codes"]


def test_pass_two_hostile_controls_all_fail_closed():
    result = run_hostile_controls()
    assert result["attack_count"] == 9
    assert result["passed_count"] == 9
    assert result["all_passed"]
    assert result["freshness_controls"] == [
        "stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay",
    ]
    by_id = {item["attack_id"]: item for item in result["attacks"]}
    assert all(by_id[name]["signature_valid"] for name in result["freshness_controls"])
    assert all(by_id[name]["unsigned_rebound_observed"] == "accepted" for name in result["freshness_controls"])
    omission = result["supporting_controls"]["signed_required_state_omission"]
    assert omission["signature_valid"] and omission["observed"] == "undecidable"


def test_verification_is_pure_and_caller_advances_only_after_acceptance():
    run_id = derive_run_id("test", "state-machine")
    session = RecoveryVerifierSession(run_id)
    wrong = create_olp_handoff(
        RecoveryState.initial(), 80, 1236,
        run_id=derive_run_id("test", "wrong"), generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    rejected = verify_olp_handoff(wrong, session)
    assert rejected["status"] == "rejected"
    assert session.last_accepted_parent_hash == GENESIS_PARENT_HASH
    assert session.last_accepted_generation_index == 0
    assert advance_recovery_session(session, rejected) == session
    current = create_olp_handoff(
        RecoveryState.initial(), 80, 1236, run_id=run_id,
        generation_index=1, parent_hash=GENESIS_PARENT_HASH,
    )
    accepted = verify_olp_handoff(current, session)
    assert accepted["status"] == "accepted"
    assert session.last_accepted_parent_hash == GENESIS_PARENT_HASH
    advanced = advance_recovery_session(session, accepted)
    assert advanced.last_accepted_parent_hash != GENESIS_PARENT_HASH
    assert advanced.last_accepted_generation_index == 1


def test_clean_checksum_and_olp_critical_pair_restore_identical_runtime_state():
    experiment = _experiment()
    seed = experiment["recovery"]["training_seeds"][0]
    unsigned_rows, unsigned_run, _ = _simulate_one("unsigned_minimal_handoff", seed, experiment)
    olp_rows, olp_run, _ = _simulate_one("olp_handoff", seed, experiment)
    dynamic_fields = {
        "mode", "handoff_reason", "packet_bytes", "packet_tokens", "evidence_reads",
    }
    assert [
        {key: value for key, value in row.items() if key not in dynamic_fields}
        for row in unsigned_rows
    ] == [
        {key: value for key, value in row.items() if key not in dynamic_fields}
        for row in olp_rows
    ]
    assert unsigned_run["post_handoff_decision_accuracy"] == olp_run["post_handoff_decision_accuracy"]
    assert unsigned_run["n_f"] == olp_run["n_f"]
