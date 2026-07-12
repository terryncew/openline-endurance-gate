import json
import pytest
from pathlib import Path

from openline_endurance_gate.state_restoration import (
    MODES,
    _simulate_one,
    analyze_state_restoration,
    state_restoration_design_witness,
)
from openline_endurance_gate.util import read_csv

ROOT = Path(__file__).resolve().parents[1]


def test_state_restoration_design_is_powered_and_falsifiable():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    config = experiment["state_restoration"]
    assert config["modes"] == list(MODES)
    assert config["horizons"] == [160, 320]
    assert config["fixed_retirement_interval_cycles"] == 85
    assert len(config["heldout_seeds"]) == 80
    assert set(config["training_seeds"]).isdisjoint(config["heldout_seeds"])
    assert set(config["validation_seeds"]).isdisjoint(config["heldout_seeds"])
    assert "FROZEN" in config["parameter_status"]


def test_event_randomness_is_common_across_modes():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    seed = experiment["state_restoration"]["training_seeds"][0]
    baseline, _ = _simulate_one("capsule_baseline", "main", seed, experiment)
    stack, _ = _simulate_one("restoration_stack", "main", seed, experiment)
    for left, right in zip(baseline[:40], stack[:40]):
        assert (left["event_id"], left["amplitude"], left["target"], left["truth_delta"]) == (
            right["event_id"], right["amplitude"], right["target"], right["truth_delta"]
        )
        assert left["common_random_draw"] == right["common_random_draw"]


def test_sham_control_preserves_restart_without_claimed_repair():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    seed = experiment["state_restoration"]["training_seeds"][0]
    rows, run = _simulate_one("sham_retirement_85", "main", seed, experiment)
    trigger = next(row for row in rows if row["cycle"] == 85)
    assert trigger["restoration_triggered"] == 1
    assert trigger["restoration_kind"] == "instance_retirement"
    assert trigger["restored_requirement_count"] == 0
    assert run["restorations"] >= 1


@pytest.mark.integration
def test_saved_state_restoration_analysis_recomputes_summary():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    runs = read_csv(ROOT / "results/state_restoration_runs.csv")
    int_fields = {
        "seed", "declared_horizon", "n_f", "failed", "first_failure_cycle",
        "survival_160", "survival_320", "restorations", "pruned_tokens",
        "ecc_corrections", "external_retrievals", "quarantines",
    }
    float_fields = {
        "mean_active_context_tokens_160", "mean_active_context_tokens_320",
        "mean_checkpoint_accuracy_160", "mean_checkpoint_accuracy_320",
        "critical_omission_rate_160", "critical_omission_rate_320",
        "mean_epsilon_160", "mean_epsilon_320", "minimum_margin_160", "minimum_margin_320",
        "final_config_accuracy", "final_requirement_accuracy",
    }
    for row in runs:
        for field in int_fields:
            if row.get(field) not in (None, ""):
                row[field] = int(float(row[field]))
        for field in float_fields:
            if row.get(field) not in (None, ""):
                row[field] = float(row[field])
    recomputed = analyze_state_restoration(runs, experiment)
    saved = json.loads((ROOT / "results/state_restoration_summary.json").read_text())
    assert recomputed == saved


def test_state_restoration_design_witness_disclaims_physical_identification():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    witness = state_restoration_design_witness(experiment)
    assert witness["telemetry_status"] == "SYNTHETIC_PROXY_NOT_PHYSICAL_IDENTIFICATION"
    assert witness["sham_control"] == "SAME_RESTART_SCHEDULE_WITH_DEFECT_AND_NOISE_STATE_PRESERVED"


@pytest.mark.integration
def test_streaming_evidence_matches_in_memory_simulator(tmp_path):
    import copy
    from openline_endurance_gate.integrity import merkle_root
    from openline_endurance_gate.restoration_stream import stream_state_restoration
    from openline_endurance_gate.state_restoration import simulate_state_restoration
    from openline_endurance_gate.verification import _csv_merkle_root

    experiment = json.loads((ROOT / "experiment.json").read_text())
    small = copy.deepcopy(experiment)
    seed = int(small["state_restoration"]["training_seeds"][0])
    small["state_restoration"]["seeds"] = [seed]
    small["state_restoration"]["training_seeds"] = [seed]
    small["state_restoration"]["validation_seeds"] = []
    small["state_restoration"]["heldout_seeds"] = []

    cycles, runs = simulate_state_restoration(small)
    cycle_path = tmp_path / "cycles.csv"
    streamed = stream_state_restoration(small, cycle_path)

    assert streamed["cycle_count"] == len(cycles)
    assert streamed["run_count"] == len(runs)
    assert streamed["cycle_merkle_root"] == merkle_root(cycles)
    assert streamed["run_merkle_root"] == merkle_root(runs)
    assert len(streamed["cycle_artifacts"]) == 1
    shard_path = Path(streamed["cycle_artifacts"][0])
    assert _csv_merkle_root(shard_path) == (
        streamed["cycle_merkle_root"], streamed["cycle_count"]
    )
