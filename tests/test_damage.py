import json
from pathlib import Path

from openline_endurance_gate.damage import compute_damage
from openline_endurance_gate.util import read_csv
from openline_endurance_gate.verification import _coerce

ROOT = Path(__file__).resolve().parents[1]


def test_damage_parameters_are_declared_unfit_before_run():
    experiment = json.loads((ROOT / "experiment.json").read_text())
    assert experiment["damage_parameter_status"].startswith("UNFIT")
    assert set(experiment["damage_parameter_grid"]) == {"m", "beta", "lambda", "mu", "tau_r"}


def test_damage_is_history_dependent_bounded_and_diagnosed():
    rows = _coerce(read_csv(ROOT / "results/cycles.csv"))
    fit = json.loads((ROOT / "results/damage_fit.json").read_text())
    damage = compute_damage(rows, fit["parameters"])
    values = list(damage.values())
    diagnostics = json.loads((ROOT / "results/damage_diagnostics.json").read_text())
    assert values
    assert all(0.0 <= value <= 1.0 for value in values)
    assert len(set(round(value, 6) for value in values)) > 2
    assert diagnostics["near_best_candidate_count"] >= 1
    assert "identifiability_warning" in diagnostics


def test_strong_cycle_operational_baseline_is_reported():
    comparison = json.loads((ROOT / "results/model_comparison.json").read_text())
    assert "operational_plus_cycle" in comparison
    assert "strong_plus_damage" in comparison
    assert "damage_vs_strong_baseline_logloss_gain" in comparison
