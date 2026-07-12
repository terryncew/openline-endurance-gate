import json
from pathlib import Path

from openline_endurance_gate.collision_spacing import (
    analyze_collision_spacing,
    collision_design_witness,
    schedule_positions,
    simulate_collision_spacing,
    ulam_sequence,
)
from openline_endurance_gate.sim import generate_perturbations
from openline_endurance_gate.util import read_csv

ROOT = Path(__file__).resolve().parents[1]


def test_first_twenty_ulam_numbers_are_exact():
    assert ulam_sequence(20) == [1, 2, 3, 4, 6, 8, 11, 13, 16, 18, 26, 28, 36, 38, 47, 48, 53, 57, 62, 69]


def test_sparse_conditions_match_gap_multiset_span_and_event_order():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    config = experiment["collision_spacing"]
    seed = config["heldout_seeds"][0]
    events = generate_perturbations(seed, experiment["amplitude_multiset"])
    positions = {name: schedule_positions(events, name, seed) for name in config["schedules"]}
    ulam_gaps = sorted(b - a for a, b in zip(positions["ulam_spaced"], positions["ulam_spaced"][1:]))
    for name in ("random_sparse_a", "random_sparse_b", "conflict_aware"):
        assert sorted(b - a for a, b in zip(positions[name], positions[name][1:])) == ulam_gaps
        assert positions[name][-1] == positions["ulam_spaced"][-1] == config["horizon_ticks"]


def test_common_outcome_draw_excludes_schedule():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    events, _ = simulate_collision_spacing(experiment)
    draws = {}
    for row in events:
        key = (row["seed"], row["event_id"])
        draws.setdefault(key, set()).add(row["common_random_draw"])
    assert all(len(values) == 1 for values in draws.values())


def test_saved_collision_summary_recomputes_and_preserves_legacy_score():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    _, runs = simulate_collision_spacing(experiment)
    recomputed = analyze_collision_spacing(runs, experiment)
    saved = json.loads((ROOT / "results/collision_spacing_summary.json").read_text())
    assert recomputed == saved
    combined = json.loads((ROOT / "results/summary.json").read_text())
    assert combined["legacy_scientific_result_preserved"] == {
        "status": "MIXED_SYNTHETIC_RESULT",
        "passed_gate_count": 8,
        "gate_count": 10,
    }
    assert combined["collision_spacing"]["status"] == "EXPLORATORY_NULL_OR_MIXED"


def test_collision_outputs_have_frozen_power_and_honest_units():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    config = experiment["collision_spacing"]
    assert len(config["heldout_seeds"]) == 80
    assert len(read_csv(ROOT / "results/collision_spacing_runs.csv")) == len(config["seeds"]) * len(config["schedules"])
    assert len(read_csv(ROOT / "results/collision_spacing_events.csv")) == len(config["seeds"]) * len(config["schedules"]) * config["events_per_run"]
    summary = json.loads((ROOT / "results/collision_spacing_summary.json").read_text())
    for effect in summary["effects"].values():
        assert "median_difference" in effect
        assert "median_difference_cycles" not in effect
        assert "effect_unit" in effect
    witness = collision_design_witness(experiment)
    assert witness["common_random_draw_key_excludes_schedule"]
