from __future__ import annotations

from collections import defaultdict
from typing import Any

from .statistics import (
    approximate_paired_mde,
    effect_classification,
    holm_adjust,
    paired_effect,
    survival_summary,
)
from .util import mean, median


def aggregate_runs(runs: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        groups[tuple(row[key] for key in keys)].append(row)
    output = []
    for group_key, rows in sorted(groups.items(), key=lambda item: tuple(map(str, item[0]))):
        record = {key: value for key, value in zip(keys, group_key)}
        checkpoint_values = [float(row["mean_checkpoint_accuracy"]) for row in rows if row["mean_checkpoint_accuracy"] is not None]
        record.update(
            {
                "run_count": len(rows),
                "median_n_f": median(float(row["n_f"]) for row in rows),
                "mean_n_f": mean(float(row["n_f"]) for row in rows),
                "failure_rate": mean(float(row["failed"]) for row in rows),
                "mean_checkpoint_accuracy": mean(checkpoint_values) if checkpoint_values else None,
                "mean_total_tokens": mean(float(row["total_tokens"]) for row in rows),
                "subcritical_first_failure_rate": mean(float(row["subcritical_first_failure"]) for row in rows),
            }
        )
        output.append(record)
    return output


def _paired_mode_differences(
    runs: list[dict[str, Any]], left_mode: str, right_mode: str, seeds: set[int]
) -> list[float]:
    lookup = {
        (int(row["seed"]), str(row["schedule"]), str(row["mode"])): float(row["n_f"])
        for row in runs
        if int(row["seed"]) in seeds
    }
    differences = []
    for seed in sorted(seeds):
        schedules = sorted({key[1] for key in lookup if key[0] == seed})
        for schedule in schedules:
            left = lookup.get((seed, schedule, left_mode))
            right = lookup.get((seed, schedule, right_mode))
            if left is not None and right is not None:
                differences.append(left - right)
    return differences


def _schedule_differences(
    runs: list[dict[str, Any]], left_schedule: str, right_schedule: str, seeds: set[int], mode: str | None = None
) -> list[float]:
    lookup = {
        (int(row["seed"]), str(row["mode"]), str(row["schedule"])): float(row["n_f"])
        for row in runs
        if int(row["seed"]) in seeds and (mode is None or str(row["mode"]) == mode)
    }
    modes = [mode] if mode is not None else sorted({key[1] for key in lookup})
    differences = []
    for seed in sorted(seeds):
        for current_mode in modes:
            left = lookup.get((seed, current_mode, left_schedule))
            right = lookup.get((seed, current_mode, right_schedule))
            if left is not None and right is not None:
                differences.append(left - right)
    return differences


def _amplitude_differences(
    runs: list[dict[str, Any]], left: str, right: str, seeds: set[int]
) -> list[float]:
    lookup = {
        (int(row["seed"]), str(row["mode"]), str(row["schedule"])): float(row["n_f"])
        for row in runs
        if int(row["seed"]) in seeds
    }
    differences = []
    for seed in sorted(seeds):
        for mode in sorted({key[1] for key in lookup if key[0] == seed}):
            left_value = lookup.get((seed, mode, f"constant_{left}"))
            right_value = lookup.get((seed, mode, f"constant_{right}"))
            if left_value is not None and right_value is not None:
                differences.append(left_value - right_value)
    return differences


def _effect_with_power(
    differences: list[float], experiment: dict[str, Any], tag: str
) -> dict[str, Any]:
    analysis = experiment["analysis_plan"]
    result = paired_effect(
        differences,
        confidence=float(analysis["confidence_level"]),
        resamples=int(analysis["bootstrap_resamples"]),
        seed_tag=tag,
    )
    result["approximate_mde_cycles_at_declared_alpha_power"] = approximate_paired_mde(
        differences,
        alpha=float(experiment["theory_thresholds"]["sequence_p_max"]),
        power=float(analysis["target_power"]),
    )
    result["effect_classification"] = effect_classification(
        result, float(experiment["theory_thresholds"]["material_nf_cycles"])
    )
    return result


def build_summary(
    primary_cycles: list[dict[str, Any]],
    primary_runs: list[dict[str, Any]],
    amplitude_runs: list[dict[str, Any]],
    calibration: dict[str, Any],
    damage_fit: dict[str, Any],
    damage_diagnostics: dict[str, Any],
    model_comparison: dict[str, Any],
    fractography_summary: dict[str, Any],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    heldout = set(map(int, experiment["heldout_seeds"]))
    thresholds = experiment["theory_thresholds"]
    analysis = experiment["analysis_plan"]
    horizon = int(experiment["primary_cycles"])

    order_diffs = _schedule_differences(primary_runs, "low_to_high", "high_to_low", heldout)
    order_effect = _effect_with_power(order_diffs, experiment, "primary-order")
    order_effect.update(
        {
            "comparison": "low_to_high minus high_to_low on held-out seeds, paired within mode and seed",
            "absolute_median_difference_cycles": abs(float(order_effect["median_difference_cycles"])),
            "minimum_declared_pairs": int(analysis["minimum_primary_order_pairs"]),
            "pair_count_requirement_met": len(order_diffs) >= int(analysis["minimum_primary_order_pairs"]),
        }
    )
    order_effect["by_mode"] = {
        mode: _effect_with_power(
            _schedule_differences(primary_runs, "low_to_high", "high_to_low", heldout, mode),
            experiment,
            f"order-{mode}",
        )
        for mode in experiment["modes"]
    }

    schedule_pairs = []
    schedules = list(experiment["schedules"])
    for i, left in enumerate(schedules):
        for right in schedules[i + 1:]:
            effect = _effect_with_power(
                _schedule_differences(primary_runs, left, right, heldout),
                experiment,
                f"exploratory-{left}-{right}",
            )
            schedule_pairs.append({"left": left, "right": right, **effect})
    adjusted = holm_adjust([float(item["exact_sign_flip_p"]) for item in schedule_pairs])
    for item, adjusted_p in zip(schedule_pairs, adjusted):
        item["holm_adjusted_p"] = adjusted_p
    order_effect["exploratory_all_schedule_pairs"] = schedule_pairs

    heldout_runs = [row for row in primary_runs if int(row["seed"]) in heldout]
    order_effect["survival"] = {
        schedule: survival_summary(
            [float(row["n_f"]) for row in heldout_runs if row["schedule"] == schedule], horizon
        )
        for schedule in ("low_to_high", "high_to_low")
    }

    receipt_diffs = _paired_mode_differences(primary_runs, "receipt_ancestry", "prose_summary", heldout)
    receipt_effect = _effect_with_power(receipt_diffs, experiment, "receipt-vs-prose")
    receipt_effect["comparison"] = "receipt_ancestry minus prose_summary on held-out seeds, paired by schedule and seed"
    receipt_effect["median_n_f_gain_cycles"] = receipt_effect.pop("median_difference_cycles")
    receipt_effect["mean_n_f_gain_cycles"] = receipt_effect.pop("mean_difference_cycles")
    receipt_effect["median_gain_confidence_interval"] = receipt_effect.pop("median_confidence_interval")
    receipt_effect["mean_gain_confidence_interval"] = receipt_effect.pop("mean_confidence_interval")
    receipt_effect["by_schedule"] = {}
    for schedule in experiment["schedules"]:
        schedule_rows = [row for row in primary_runs if int(row["seed"]) in heldout and row["schedule"] == schedule]
        diffs = _paired_mode_differences(schedule_rows, "receipt_ancestry", "prose_summary", heldout)
        receipt_effect["by_schedule"][schedule] = _effect_with_power(diffs, experiment, f"receipt-{schedule}")
    receipt_rows = [row for row in heldout_runs if row["mode"] == "receipt_ancestry"]
    prose_rows = [row for row in heldout_runs if row["mode"] == "prose_summary"]
    receipt_acc_values = [float(row["mean_checkpoint_accuracy"]) for row in receipt_rows if row["mean_checkpoint_accuracy"] is not None]
    prose_acc_values = [float(row["mean_checkpoint_accuracy"]) for row in prose_rows if row["mean_checkpoint_accuracy"] is not None]
    receipt_acc = mean(receipt_acc_values) if receipt_acc_values else None
    prose_acc = mean(prose_acc_values) if prose_acc_values else None
    receipt_effect.update(
        {
            "receipt_checkpoint_accuracy": receipt_acc,
            "prose_checkpoint_accuracy": prose_acc,
            "checkpoint_accuracy_delta": receipt_acc - prose_acc if receipt_acc is not None and prose_acc is not None else None,
            "survival": {
                "receipt_ancestry": survival_summary([float(row["n_f"]) for row in receipt_rows], horizon),
                "prose_summary": survival_summary([float(row["n_f"]) for row in prose_rows], horizon),
            },
        }
    )

    amp_medians: dict[str, float] = {}
    for amplitude in ("low", "medium", "high"):
        amp_medians[amplitude] = median(
            float(row["n_f"])
            for row in amplitude_runs
            if int(row["seed"]) in heldout and row["schedule"] == f"constant_{amplitude}"
        )
    amplitude_monotonic = (
        amp_medians["low"] >= amp_medians["medium"] >= amp_medians["high"]
        and amp_medians["low"] > amp_medians["high"]
    )
    amplitude_effect = _effect_with_power(
        _amplitude_differences(amplitude_runs, "low", "high", heldout), experiment, "amplitude-low-high"
    )
    amplitude_effect.update(
        {
            "comparison": "constant_low minus constant_high under matched event packets",
            "observed_median_n_f": amp_medians,
            "monotonic_group_medians": amplitude_monotonic,
        }
    )

    load_order_pass = (
        order_effect["pair_count_requirement_met"]
        and order_effect["absolute_median_difference_cycles"] >= float(thresholds["material_nf_cycles"])
        and float(order_effect["exact_sign_flip_p"]) <= float(thresholds["sequence_p_max"])
    )
    amplitude_pass = (
        amplitude_monotonic
        and float(amplitude_effect["median_difference_cycles"]) >= float(thresholds["material_nf_cycles"])
        and float(amplitude_effect["exact_sign_flip_p"]) <= float(thresholds["sequence_p_max"])
    )
    checkpoint_delta = receipt_effect["checkpoint_accuracy_delta"]
    receipt_pass = (
        float(receipt_effect["median_n_f_gain_cycles"]) >= float(thresholds["material_nf_cycles"])
        and checkpoint_delta is not None
        and float(checkpoint_delta) >= -float(thresholds["max_checkpoint_accuracy_loss"])
    )

    gates = {
        "fresh_subcritical_calibration": {
            "passed": bool(calibration["passed"]),
            "observed": calibration["one_shot_pass_rates"],
            "threshold": calibration["floor"],
        },
        "amplitude_endurance_gradient": {
            "passed": bool(amplitude_pass),
            "observed": amplitude_effect,
            "rule": "matched low-high median gain is material and sign-flip p passes; group medians are low >= medium >= high",
        },
        "load_order_noncommutativity": {
            "passed": bool(load_order_pass),
            "observed": order_effect,
            "thresholds": {
                "absolute_median_cycles": thresholds["material_nf_cycles"],
                "p_max": thresholds["sequence_p_max"],
                "minimum_pairs": analysis["minimum_primary_order_pairs"],
            },
        },
        "damage_adds_heldout_prediction": {
            "passed": model_comparison["damage_vs_cd_logloss_gain"] > float(thresholds["heldout_logloss_improvement"]),
            "observed_cd_logloss_gain": model_comparison["damage_vs_cd_logloss_gain"],
            "observed_operational_logloss_gain": model_comparison["damage_vs_operational_logloss_gain"],
            "observed_strong_baseline_logloss_gain": model_comparison["damage_vs_strong_baseline_logloss_gain"],
            "threshold": thresholds["heldout_logloss_improvement"],
        },
        "receipt_handoff_advantage": {
            "passed": bool(receipt_pass),
            "observed": receipt_effect,
            "thresholds": {
                "median_n_f_gain_cycles": thresholds["material_nf_cycles"],
                "max_checkpoint_accuracy_loss": thresholds["max_checkpoint_accuracy_loss"],
            },
        },
    }
    passed_count = sum(int(gate["passed"]) for gate in gates.values())
    if passed_count == len(gates):
        theory_status = "SURVIVES_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    elif passed_count == 0:
        theory_status = "FAILS_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    else:
        theory_status = "MIXED_SYNTHETIC_RESULT"

    subcritical_failures = sum(int(row["subcritical_failure"]) for row in primary_cycles)
    first_failures = sum(int(row["first_failure_this_cycle"]) for row in primary_cycles)
    return {
        "schema": "openline.endurance.summary.v2",
        "claim_label": "POWERED_SYNTHETIC_SIM_CALIBRATED",
        "theory_status": theory_status,
        "passed_gate_count": passed_count,
        "gate_count": len(gates),
        "primary_observation_count": len(primary_cycles),
        "primary_run_count": len(primary_runs),
        "amplitude_sweep_run_count": len(amplitude_runs),
        "heldout_seed_count": len(heldout),
        "calibration": calibration,
        "damage_fit": damage_fit,
        "damage_diagnostics": damage_diagnostics,
        "model_comparison": model_comparison,
        "order_effect": order_effect,
        "receipt_effect": receipt_effect,
        "amplitude_effect": amplitude_effect,
        "amplitude_median_n_f": amp_medians,
        "fractography": fractography_summary,
        "subcritical_first_failures": subcritical_failures,
        "all_first_failures": first_failures,
        "subcritical_share_of_first_failures": subcritical_failures / first_failures if first_failures else None,
        "gates": gates,
        "robustness_witnesses": {
            "damage_beats_cycle_operational_baseline": model_comparison["damage_vs_strong_baseline_logloss_gain"] > 0.0,
            "damage_fit_identifiability_warning": damage_diagnostics["identifiability_warning"],
            "primary_order_pair_count_requirement_met": order_effect["pair_count_requirement_met"],
            "common_random_numbers_across_schedules": experiment.get("randomness_coupling") == "EVENT_BOUND_COMMON_RANDOM_NUMBERS",
            "matched_amplitude_packets": experiment.get("amplitude_sweep_design") == "COMMON_PACKET_AMPLITUDE_TRANSFORM",
        },
        "claim_boundary": "This seeded toy world tests whether the proposed measurements recover known synthetic mechanisms under a powered, common-random-number design. It does not validate cumulative damage in deployed AI systems or prove receipts are a repair mechanism.",
    }
