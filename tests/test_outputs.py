import csv
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

from openline_endurance_gate.util import read_csv

ROOT = Path(__file__).resolve().parents[1]


def test_default_run_has_expected_powered_artifacts_and_heldout_split():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    assert set(experiment["training_seeds"]).isdisjoint(experiment["validation_seeds"])
    assert set(experiment["training_seeds"]).isdisjoint(experiment["heldout_seeds"])
    assert set(experiment["validation_seeds"]).isdisjoint(experiment["heldout_seeds"])
    assert len(read_csv(ROOT / "results/cycles.csv")) == 8320
    assert len(read_csv(ROOT / "results/runs.csv")) == 416
    assert len(read_csv(ROOT / "results/amplitude_cycles.csv")) == 6240
    assert len(read_csv(ROOT / "results/amplitude_runs.csv")) == 312
    tip = experiment["tip_capture"]
    expected_tip_cycles = len(tip["seeds"]) * len(tip["attachment_conditions"]) * len(tip["repair_policies"]) * tip["cycles"]
    assert len(read_csv(ROOT / "results/tip_capture_cycles.csv")) == expected_tip_cycles
    assert len(read_csv(ROOT / "results/tip_capture_runs.csv")) == len(tip["seeds"]) * len(tip["attachment_conditions"]) * len(tip["repair_policies"])
    spacing = experiment["collision_spacing"]
    assert len(read_csv(ROOT / "results/collision_spacing_runs.csv")) == len(spacing["seeds"]) * len(spacing["schedules"])
    assert len(read_csv(ROOT / "results/collision_spacing_events.csv")) == len(spacing["seeds"]) * len(spacing["schedules"]) * spacing["events_per_run"]
    generational = experiment["generational_endurance"]
    assert len(read_csv(ROOT / "results/generational_runs.csv")) == len(generational["seeds"]) * 6
    assert len(read_csv(ROOT / "results/generational_cycles.csv")) == len(generational["seeds"]) * 6 * generational["max_horizon_cycles"]
    restoration = experiment["state_restoration"]
    assert len(read_csv(ROOT / "results/state_restoration_runs.csv")) == len(restoration["seeds"]) * 9
    cycle_count = 0
    shards = sorted((ROOT / "results").glob("state_restoration_cycles.part-*.csv.gz"))
    assert len(shards) == 8
    for shard in shards:
        with gzip.open(shard, "rt", newline="", encoding="utf-8") as handle:
            cycle_count += sum(1 for _ in csv.DictReader(handle))
    assert cycle_count == len(restoration["seeds"]) * 9 * restoration["max_horizon_cycles"]

    rate = experiment["load_rate"]
    assert len(read_csv(ROOT / "results/load_rate_runs.csv")) == len(rate["seeds"]) * len(rate["worlds"]) * len(rate["modes"]) * len(rate["schedules"])
    rate_cycle_count = 0
    rate_shards = sorted((ROOT / "results").glob("load_rate_cycles.part-*.csv.gz"))
    assert len(rate_shards) == 12
    for shard in rate_shards:
        with gzip.open(shard, "rt", newline="", encoding="utf-8") as handle:
            rate_cycle_count += sum(1 for _ in csv.DictReader(handle))
    assert rate_cycle_count == len(rate["seeds"]) * len(rate["worlds"]) * len(rate["modes"]) * len(rate["schedules"]) * rate["horizon_ticks"]


def test_summary_exposes_every_gate_and_power_boundary():
    summary = json.loads((ROOT / "results/summary.json").read_text())
    markdown = (ROOT / "results/summary.md").read_text()
    assert summary["gate_count"] == summary["endurance_gate_count"] + summary["tip_capture"]["gate_count"]
    assert summary["passed_gate_count"] == sum(int(gate["passed"]) for gate in summary["gates"].values())
    assert summary["order_effect"]["paired_difference_count"] == 80
    assert summary["order_effect"]["pair_count_requirement_met"]
    for name, gate in summary["gates"].items():
        assert name in markdown
        assert ("PASS" if gate["passed"] else "FAIL") in markdown


def test_design_and_fractography_witnesses_are_present():
    design = json.loads((ROOT / "results/design_witness.json").read_text())
    fracture = json.loads((ROOT / "results/fractography_summary.json").read_text())
    assert design["schedule_label_invariance_for_identical_one_cycle_state"]
    assert design["matched_amplitude_packet"]["common_event_ids_targets_and_signs"]
    assert fracture["run_count"] == 416
    assert "dominant_crack_cluster" in fracture
    tip_design = json.loads((ROOT / "results/tip_capture_design_witness.json").read_text())
    tip_summary = json.loads((ROOT / "results/tip_capture_summary.json").read_text())
    assert tip_design["logging_only_dynamics_match_no_intervention"]
    assert tip_design["heldout_seed_count"] == 80
    assert "geometry_lift" in tip_summary
    assert "uniform_null" in tip_summary["capture_by_condition"]
    spacing_design = json.loads((ROOT / "results/collision_spacing_design_witness.json").read_text())
    spacing_summary = json.loads((ROOT / "results/collision_spacing_summary.json").read_text())
    assert spacing_design["ulam_random_a_same_gap_multiset"]
    assert spacing_design["common_random_draw_key_excludes_schedule"]
    assert spacing_summary["heldout_seed_count"] == 80
    generational_design = json.loads((ROOT / "results/generational_design_witness.json").read_text())
    generational_summary = json.loads((ROOT / "results/generational_summary.json").read_text())
    assert generational_design["heldout_seed_count"] == 80
    assert generational_design["capsule_budget_tokens"] == generational_design["summary_budget_tokens"]
    assert generational_summary["maximum_verified_horizon_cycles"] == 80
    restoration_design = json.loads((ROOT / "results/state_restoration_design_witness.json").read_text())
    restoration_summary = json.loads((ROOT / "results/state_restoration_summary.json").read_text())
    assert restoration_design["heldout_seed_count"] == 80
    assert restoration_design["fixed_retirement_interval_cycles"] == 85
    assert restoration_design["telemetry_status"] == "SYNTHETIC_PROXY_NOT_PHYSICAL_IDENTIFICATION"
    assert restoration_summary["gate_count"] == 9

    rate_design = json.loads((ROOT / "results/load_rate_design_witness.json").read_text())
    rate_summary = json.loads((ROOT / "results/load_rate_summary.json").read_text())
    assert rate_design["all_matching_checks_pass"]
    assert rate_design["matching_checks"]["recovery_windows_contain_ordinary_work"]
    assert rate_design["matching_checks"]["same_persistent_context_growth_by_disturbance_index"]
    assert rate_summary["heldout_seed_count"] == 80
    assert rate_summary["gate_count"] == 4
    assert rate_summary["passed_gate_count"] == 4
    assert "per_mode_null_effects" in rate_summary
    assert rate_summary["primary_effect"]["unit"] == "disturbances_survived_before_critical_failure"

    recovery = json.loads((ROOT / "experiment.json").read_text())["recovery"]
    recovery_runs = read_csv(ROOT / "results/recovery_runs.csv")
    assert len(recovery_runs) == len(recovery["seeds"]) * len(recovery["modes"])
    recovery_cycle_count = 0
    recovery_shards = sorted((ROOT / "results").glob("recovery_cycles.part-*.csv.gz"))
    assert len(recovery_shards) == (len(recovery["seeds"]) + 7) // 8
    for shard in recovery_shards:
        with gzip.open(shard, "rt", newline="", encoding="utf-8") as handle:
            recovery_cycle_count += sum(1 for _ in csv.DictReader(handle))
    assert recovery_cycle_count == len(recovery["seeds"]) * len(recovery["modes"]) * recovery["horizon_cycles"]
    recovery_summary = json.loads((ROOT / "results/recovery_summary.json").read_text())
    assert recovery_summary["gate_count"] == 8
    assert recovery_summary["freshness_binding"]["verifier_state_updates"] == "caller_applies_proposed_update_only_on_acceptance"
    assert recovery_summary["freshness_binding"]["seed_status"].startswith("fresh v0.9.1")
    assert recovery_summary["gates"]["unsigned_checksum_cannot_prevent_replay_even_with_identical_fields"]["passed"]


def test_fast_custody_verifier_passes_default_artifacts():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "openline_endurance_gate",
            "verify",
            "--root",
            str(ROOT),
            "--source-root",
            str(ROOT),
            "--fast",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert result["valid"], result["errors"]
    assert result["release_attestation_valid"] is True


def test_v040_tip_reporting_names_units_and_first_contact_boundary():
    tip = json.loads((ROOT / "results/tip_capture_summary.json").read_text())
    repair = tip["repair_effect"]
    assert repair["effect_unit"] == "violations_prevented_per_successful_repair"
    assert repair["positive_direction"] == "tip_targeted_higher_yield_than_random_repair"
    assert repair["positive_count"] + repair["negative_count"] + repair["zero_count"] == 80
    assert "median_difference_cycles" not in repair
    disclosure = tip["reporting_disclosures"]["v031_even_spread_retired"]
    assert disclosure["present"] is True
    assert disclosure["replacement"] == "least_capture_balancer"
    independence = tip["reporting_disclosures"]["first_contact_independence"]
    assert independence["selector_reads_exposure_observable"] is False
    assert independence["selector_reads_capture_history"] is False
