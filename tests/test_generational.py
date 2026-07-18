import json
from pathlib import Path

from openline_endurance_gate.generational import (
    analyze_generational_endurance,
    generational_design_witness,
    schedule_generational_events,
)
from openline_endurance_gate.util import read_csv
from openline_endurance_gate.verification import _close

ROOT = Path(__file__).resolve().parents[1]


def test_generational_design_is_powered_equal_budget_and_heldout():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    config = experiment["generational_endurance"]
    assert config["modes"] == [
        "continuous_full_history",
        "ordinary_summary_reset",
        "verified_inheritance_capsule",
        "capsule_conflict_aware",
    ]
    assert config["horizons"] == [40, 80, 160]
    assert config["generation_length_cycles"] == 20
    assert config["capsule_budget_tokens"] == config["summary_budget_tokens"]
    assert len(config["heldout_seeds"]) == 80
    assert set(config["training_seeds"]).isdisjoint(config["heldout_seeds"])
    assert set(config["validation_seeds"]).isdisjoint(config["heldout_seeds"])


def test_conflict_schedule_changes_order_not_event_multiset():
    seed = 7317
    base = schedule_generational_events(seed, 160, "verified_inheritance_capsule", 20)
    conflict = schedule_generational_events(seed, 160, "capsule_conflict_aware", 20)
    key = lambda event: (event.event_id, event.amplitude, event.target, event.delta, event.ambiguity, event.correction_required, event.token_cost)
    assert sorted(map(key, base)) == sorted(map(key, conflict))
    assert [event.event_id for event in base] != [event.event_id for event in conflict]


def test_saved_generational_result_preserves_losses_and_null():
    summary = json.loads((ROOT / "results/generational_summary.json").read_text())
    assert summary["status"] == "MIXED_EXPLORATORY_GENERATIONAL_RESULT"
    assert summary["passed_gate_count"] == 5
    assert summary["gate_count"] == 7
    assert summary["maximum_verified_horizon_cycles"] == 80
    assert summary["gates"]["verified_horizon_40"]["passed"] is True
    assert summary["gates"]["verified_horizon_80"]["passed"] is True
    assert summary["gates"]["verified_horizon_160"]["passed"] is False
    assert summary["gates"]["conflict_aware_capsule_advantage"]["passed"] is False
    assert summary["gates"]["pressure_disabled_null_specificity"]["passed"] is True
    null_gate = summary["gates"]["pressure_disabled_null_specificity"]
    assert null_gate["thresholds"] == {
        "positive_median_advantage_max_cycles": 1.0,
        "significant_positive_advantage_p_max": 0.1,
    }
    assert null_gate["observed"]["median_difference_cycles"] < 0.0
    assert "Negative values mean continuous history performs better" in null_gate["decision_rule"]


def test_generational_artifact_counts_and_design_witness():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    config = experiment["generational_endurance"]
    assert len(read_csv(ROOT / "results/generational_runs.csv")) == len(config["seeds"]) * 6
    assert len(read_csv(ROOT / "results/generational_cycles.csv")) == len(config["seeds"]) * 6 * config["max_horizon_cycles"]
    witness = json.loads((ROOT / "results/generational_design_witness.json").read_text())
    assert witness == generational_design_witness(experiment)
    assert witness["raw_record_policy"] == "OUTSIDE_ACTIVE_CONTEXT_RETRIEVABLE_BY_HASH_REFERENCE"
    assert witness["null_world"] == "PRESSURE_DISABLED_COMMON_EVENT_WORLD"


def test_saved_run_analysis_recomputes_summary():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    runs = read_csv(ROOT / "results/generational_runs.csv")
    int_fields = {
        "seed", "declared_horizon", "n_f", "failed", "first_failure_cycle",
        "survival_40", "survival_80", "survival_160", "critical_omissions_40",
        "critical_omissions_80", "critical_omissions_160", "external_retrievals",
        "successful_retrievals", "quarantines", "total_active_token_work",
    }
    float_fields = {
        "mean_active_context_tokens_40", "mean_active_context_tokens_80", "mean_active_context_tokens_160",
        "peak_active_context_tokens", "mean_checkpoint_accuracy_40", "mean_checkpoint_accuracy_80",
        "mean_checkpoint_accuracy_160", "critical_omission_rate_40", "critical_omission_rate_80",
        "critical_omission_rate_160", "final_config_accuracy", "final_requirement_accuracy",
    }
    for row in runs:
        for field in int_fields:
            if row.get(field) not in (None, ""):
                row[field] = int(float(row[field]))
        for field in float_fields:
            if row.get(field) not in (None, ""):
                row[field] = float(row[field])
    recomputed = analyze_generational_endurance(runs, experiment)
    saved = json.loads((ROOT / "results/generational_summary.json").read_text())
    # Python 3.12+ uses higher-accuracy float summation than Python 3.11.
    # Keep the test aligned with the semantic verifier: structure and exact
    # non-numeric values must match, while regenerated floats use its declared
    # cross-runtime relative tolerance.
    assert _close(recomputed, saved, 1e-7)
