import gzip
import json
from pathlib import Path

from openline_endurance_gate.load_rate import (
    LOAD_RATE_CYCLE_FIELDS,
    analyze_load_rate,
    load_rate_design_witness,
    schedule_positions,
    simulate_load_rate,
    write_deterministic_gzip_csv,
)

ROOT = Path(__file__).resolve().parents[1]


def _experiment():
    return json.loads((ROOT / "experiment.json").read_text())


def test_schedule_design_matches_everything_except_spacing():
    experiment = _experiment()
    config = experiment["load_rate"]
    witness = load_rate_design_witness(experiment)
    assert witness["all_matching_checks_pass"]
    assert all(witness["matching_checks"].values())
    counts = {item["disturbance_count"] for item in witness["schedule_map"].values()}
    work = {item["ordinary_work_count"] for item in witness["schedule_map"].values()}
    assert counts == {20}
    assert work == {140}
    assert schedule_positions("slow_drip", config["horizon_ticks"], config["block_ticks"]) != schedule_positions(
        "sudden_burst", config["horizon_ticks"], config["block_ticks"]
    )


def test_event_identity_order_and_draws_are_schedule_invariant():
    experiment = _experiment()
    cycles, _ = simulate_load_rate(experiment, [experiment["load_rate"]["training_seeds"][0]])
    selected = [row for row in cycles if row["world"] == "rate_sensitive" and row["mode"] == "verified_capsule"]
    streams = {}
    for schedule in experiment["load_rate"]["schedules"]:
        disturbances = [row for row in selected if row["schedule"] == schedule and row["event_kind"] == "disturbance"]
        streams[schedule] = [
            (row["event_id"], row["amplitude"], row["target"], row["truth_delta"], row["common_random_draw"])
            for row in disturbances
        ]
    assert len({tuple(stream) for stream in streams.values()}) == 1


def test_recovery_schedule_contains_real_work_and_equal_token_work():
    experiment = _experiment()
    cycles, runs = simulate_load_rate(experiment, [experiment["load_rate"]["training_seeds"][0]])
    selected = [row for row in cycles if row["world"] == "rate_sensitive" and row["mode"] == "ordinary_summary"]
    token_work = {}
    ordinary_counts = {}
    for schedule in experiment["load_rate"]["schedules"]:
        rows = [row for row in selected if row["schedule"] == schedule]
        ordinary_counts[schedule] = sum(row["event_kind"] == "ordinary_work" for row in rows)
        token_work[schedule] = rows[-1]["total_token_work"]
    assert set(ordinary_counts.values()) == {140}
    assert len(set(token_work.values())) == 1
    assert any(
        row["event_kind"] == "ordinary_work" and row["ordinary_repair_attempt"] in {0, 1}
        for row in selected if row["schedule"] == "burst_recovery"
    )
    assert len(runs) == 2 * 3 * 4


def test_rate_disabled_null_has_no_programmed_rate_pathway():
    experiment = _experiment()
    cycles, runs = simulate_load_rate(experiment, experiment["load_rate"]["training_seeds"])
    null_rows = [row for row in cycles if row["world"] == "rate_disabled_null"]
    # Burden remains observable, but it is excluded from difficulty and ordinary
    # repair is disabled so schedule timing cannot earn a recovery advantage.
    assert all(int(row["ordinary_repair_attempt"]) == 0 for row in null_rows)
    assert all(int(row["ordinary_repair_success"]) == 0 for row in null_rows)
    local = json.loads(json.dumps(experiment))
    local["load_rate"]["heldout_seeds"] = list(experiment["load_rate"]["training_seeds"])
    summary = analyze_load_rate(cycles, runs, local)
    assert summary["null_effect"]["unit"] == "disturbances_survived_before_critical_failure"
    assert float(summary["null_effect"]["mean_difference_disturbances"]) == 0.0
    assert all(
        float(effect["mean_difference_disturbances"]) == 0.0
        for effect in summary["per_mode_null_effects"].values()
    )




def test_persistent_context_is_matched_by_disturbance_index():
    experiment = _experiment()
    cycles, _ = simulate_load_rate(experiment, [experiment["load_rate"]["training_seeds"][0]])
    selected = [
        row for row in cycles
        if row["world"] == "rate_disabled_null"
        and row["mode"] == "continuous_history"
        and row["event_kind"] == "disturbance"
    ]
    by_schedule = {}
    for schedule in experiment["load_rate"]["schedules"]:
        by_schedule[schedule] = [
            (int(row["disturbance_index"]), int(row["active_context_tokens"]))
            for row in selected if row["schedule"] == schedule
        ]
    assert len({tuple(values) for values in by_schedule.values()}) == 1

def test_deterministic_gzip_evidence(tmp_path):
    experiment = _experiment()
    cycles, _ = simulate_load_rate(experiment, [experiment["load_rate"]["training_seeds"][0]])
    first = tmp_path / "first.csv.gz"
    second = tmp_path / "second.csv.gz"
    write_deterministic_gzip_csv(first, cycles, LOAD_RATE_CYCLE_FIELDS)
    write_deterministic_gzip_csv(second, cycles, LOAD_RATE_CYCLE_FIELDS)
    assert first.read_bytes() == second.read_bytes()
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        assert sum(1 for _ in handle) == len(cycles) + 1
