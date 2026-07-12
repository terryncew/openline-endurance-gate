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
