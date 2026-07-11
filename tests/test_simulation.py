import json
from pathlib import Path

from openline_endurance_gate.amplitude import matched_amplitude_events
from openline_endurance_gate.sim import calibrate_fresh, generate_perturbations, run_one, schedule_events

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = json.loads((ROOT / "experiment.json").read_text())


def test_fresh_calibration_is_subcritical():
    calibration = calibrate_fresh(EXPERIMENT)
    assert calibration["passed"]
    assert min(calibration["one_shot_pass_rates"].values()) >= 0.95


def test_powered_primary_design_has_eighty_heldout_order_pairs():
    assert len(EXPERIMENT["heldout_seeds"]) * len(EXPERIMENT["modes"]) == 80
    assert len(EXPERIMENT["seeds"]) * len(EXPERIMENT["modes"]) * len(EXPERIMENT["schedules"]) * EXPERIMENT["primary_cycles"] == 8320


def test_damage_parameters_do_not_enter_failure_generator():
    events = schedule_events(generate_perturbations(101, EXPERIMENT["amplitude_multiset"]), "alternating", 101)
    result = run_one("prose_summary", "alternating", 101, events, EXPERIMENT, kappa_star_0=0.75, phi_base=0.99)
    assert all("damage_D" not in row for row in result.cycles)


def test_representation_budget_is_enforced():
    events = schedule_events(generate_perturbations(202, EXPERIMENT["amplitude_multiset"]), "randomized", 202)
    for mode in EXPERIMENT["modes"]:
        result = run_one(mode, "randomized", 202, events, EXPERIMENT, kappa_star_0=0.75, phi_base=0.99)
        assert max(row["representation_tokens"] for row in result.cycles) <= EXPERIMENT["input_budget_tokens"]


def test_common_random_numbers_ignore_schedule_label_for_identical_state():
    event = generate_perturbations(707, {"low": 1, "medium": 0, "high": 0})[0]
    left = run_one("fresh_ground_truth", "label-a", 707, [event], EXPERIMENT, "test", 1.0, 1.0).cycles[0]
    right = run_one("fresh_ground_truth", "label-b", 707, [event], EXPERIMENT, "test", 1.0, 1.0).cycles[0]
    left.pop("schedule")
    right.pop("schedule")
    assert left == right


def test_matched_amplitude_packets_share_event_target_and_sign():
    packets = {level: matched_amplitude_events(808, level, 20) for level in ("low", "medium", "high")}
    for index in range(20):
        events = [packets[level][index] for level in ("low", "medium", "high")]
        assert len({event.event_id for event in events}) == 1
        assert len({event.target for event in events}) == 1
        assert len({event.delta > 0 for event in events}) == 1


def test_receipt_advantage_is_reachable_but_not_guaranteed():
    hostile = dict(EXPERIMENT)
    hostile["receipt_reference_error"] = 0.80
    events = schedule_events(generate_perturbations(404, hostile["amplitude_multiset"]), "alternating", 404)
    receipt = run_one("receipt_ancestry", "alternating", 404, events, hostile, kappa_star_0=0.75, phi_base=0.99)
    prose = run_one("prose_summary", "alternating", 404, events, hostile, kappa_star_0=0.75, phi_base=0.99)
    assert receipt.summary["n_f"] <= prose.summary["n_f"]
