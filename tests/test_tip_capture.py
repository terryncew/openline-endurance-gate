import copy
import json
from pathlib import Path

from openline_endurance_gate.tip_capture import (
    analyze_tip_capture,
    generate_tip_packets,
    run_tip_capture_one,
    simulate_tip_capture,
    tip_design_witness,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = json.loads((ROOT / "experiment.json").read_text())


def _small_experiment():
    experiment = copy.deepcopy(EXPERIMENT)
    config = experiment["tip_capture"]
    config["training_seeds"] = [1, 2]
    config["validation_seeds"] = [3, 4]
    config["heldout_seeds"] = [5, 6, 7, 8]
    config["seeds"] = list(range(1, 9))
    config["cycles"] = 12
    config["analysis_plan"]["minimum_repair_pairs"] = 4
    config["analysis_plan"]["bootstrap_resamples"] = 100
    return experiment


def test_tip_capture_seed_count_and_null_are_frozen():
    config = EXPERIMENT["tip_capture"]
    assert len(config["seeds"]) == 96
    assert len(config["heldout_seeds"]) == 80
    assert config["analysis_plan"]["minimum_repair_pairs"] == 80
    assert "uniform_null" in config["attachment_conditions"]
    assert "least_capture_balancer" in config["attachment_conditions"]
    assert "diffusive_first_contact" in config["attachment_conditions"]
    assert "even_spread" not in config["attachment_conditions"]
    assert config["schema"] == "openline.tip-capture.experiment.v2"
    assert config["training_seeds"] == list(range(5101, 5109))
    assert config["parameter_status"].startswith("PRE_REGISTERED")


def test_logging_records_without_changing_graph_dynamics():
    witness = tip_design_witness(_small_experiment())
    assert witness["logging_only_dynamics_match_no_intervention"]
    assert witness["exposure_rank_is_not_attachment_function"]
    assert witness["first_contact_selector_reads_exposure_rank"] is False
    assert witness["first_contact_selector_reads_capture_history"] is False


def test_same_packets_feed_every_condition_and_policy():
    packets = generate_tip_packets(123, 48)
    assert len(packets) == 48
    assert {packet.severity for packet in packets} == {"low", "medium", "high"}
    config = _small_experiment()["tip_capture"]
    left = run_tip_capture_one("uniform_null", "no_intervention", 123, packets[:12], config)[0]
    right = run_tip_capture_one("diffusive_first_contact", "tip_targeted", 123, packets[:12], config)[0]
    assert [row["event_id"] for row in left] == [row["event_id"] for row in right]
    assert [row["event_type"] for row in left] == [row["event_type"] for row in right]
    assert [row["severity"] for row in left] == [row["severity"] for row in right]


def test_tip_targeted_repairs_only_observed_tips():
    config = _small_experiment()["tip_capture"]
    packets = generate_tip_packets(77, config["cycles"])
    cycles, _, _, _ = run_tip_capture_one("diffusive_first_contact", "tip_targeted", 77, packets, config)
    attempted = [row for row in cycles if row["repair_attempted"]]
    assert attempted
    assert all(row["repair_target_was_tip"] == 1 for row in attempted)


def test_diffusive_walk_sticks_at_first_lattice_contact():
    config = _small_experiment()["tip_capture"]
    packets = generate_tip_packets(91, config["cycles"])
    cycles, _, _, _ = run_tip_capture_one("diffusive_first_contact", "logging_only", 91, packets, config)
    positions = {}
    witnessed = 0
    for row in cycles:
        if row["walker_used"] and row["attached_to_existing"] and not row["walker_fallback"]:
            parent_x, parent_y = positions[row["selected_parent_id"]]
            assert max(abs(row["new_node_x"] - parent_x), abs(row["new_node_y"] - parent_y)) == 1
            witnessed += 1
        positions[row["new_node_id"]] = (row["new_node_x"], row["new_node_y"])
    assert witnessed


def test_small_tip_capture_analysis_can_fail_cleanly():
    experiment = _small_experiment()
    cycles, runs, candidates, probes = simulate_tip_capture(experiment)
    summary = analyze_tip_capture(cycles, runs, candidates, probes, experiment)
    assert summary["gate_count"] == 5
    assert summary["passed_gate_count"] == sum(int(gate["passed"]) for gate in summary["gates"].values())
    assert summary["status"] in {
        "SURVIVES_ALL_PRE_REGISTERED_TIP_CAPTURE_GATES",
        "MIXED_TIP_CAPTURE_RESULT",
        "FAILS_ALL_PRE_REGISTERED_TIP_CAPTURE_GATES",
    }
