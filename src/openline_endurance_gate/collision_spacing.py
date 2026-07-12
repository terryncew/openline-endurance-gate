from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .statistics import paired_effect
from .util import clamp, mean, median, stable_uniform
from .world import REQ_TO_FIELDS, REQUIREMENTS, Perturbation
from .sim import AMPLITUDE_SCALE, generate_perturbations

COLLISION_EVENT_FIELDS = [
    "schedule", "seed", "event_index", "event_id", "event_time", "gap",
    "amplitude", "target", "conflict_degree", "collision_burden",
    "active_conflict_count", "damage_before", "damage_after",
    "failure_probability", "common_random_draw", "failed",
    "first_failure_this_event",
]

COLLISION_RUN_FIELDS = [
    "schedule", "seed", "event_count", "declared_horizon", "last_event_time",
    "failures", "first_failure_event", "n_f", "mean_collision_burden",
    "peak_collision_burden", "damage_auc", "peak_damage", "final_event_damage",
    "adjacent_conflict_count", "conflicting_pair_count",
]

SCHEDULES = (
    "clustered",
    "random_sparse_a",
    "random_sparse_b",
    "ulam_spaced",
    "conflict_aware",
)


def ulam_sequence(count: int) -> list[int]:
    """Return the first ``count`` Ulam numbers, starting with 1, 2.

    A new term is the smallest integer expressible as a sum of two distinct
    earlier terms in exactly one way. The implementation is intentionally
    direct because the default experiment needs only twenty terms.
    """
    if count <= 0:
        return []
    if count == 1:
        return [1]
    values = [1, 2]
    candidate = 3
    while len(values) < count:
        representations = 0
        seen: set[tuple[int, int]] = set()
        for i, left in enumerate(values):
            for right in values[i + 1 :]:
                if left + right == candidate:
                    pair = (left, right)
                    if pair not in seen:
                        seen.add(pair)
                        representations += 1
                        if representations > 1:
                            break
            if representations > 1:
                break
        if representations == 1:
            values.append(candidate)
        candidate += 1
    return values


def _conflict_score(left: str, right: str) -> float:
    """Graph-derived semantic interference score, independent of outcomes.

    Requirements conflict when they update overlapping load-bearing fields.
    Same-target events receive the maximum score. Disconnected requirements
    receive zero. No schedule label or observed result enters this function.
    """
    if left == right:
        return 1.0
    left_fields = REQ_TO_FIELDS[left]
    right_fields = REQ_TO_FIELDS[right]
    overlap = left_fields & right_fields
    if not overlap:
        return 0.0
    return len(overlap) / min(len(left_fields), len(right_fields))


def conflict_graph() -> dict[str, list[str]]:
    return {
        requirement: sorted(
            other for other in REQUIREMENTS
            if other != requirement and _conflict_score(requirement, other) > 0.0
        )
        for requirement in REQUIREMENTS
    }


def _shuffle_gaps(gaps: list[int], seed: int, label: str) -> list[int]:
    shuffled = list(gaps)
    for index in range(len(shuffled) - 1, 0, -1):
        draw = stable_uniform("collision-gap-shuffle", label, seed, index)
        swap = min(index, int(draw * (index + 1)))
        shuffled[index], shuffled[swap] = shuffled[swap], shuffled[index]
    return shuffled


def _interface_pressure(events: list[Perturbation], interface_index: int) -> float:
    """Predict conflict at the interface before event ``interface_index + 1``.

    The score uses only the declared conflict graph, amplitudes, and event
    order. It does not inspect simulated failures or schedule outcomes.
    """
    incoming = events[interface_index + 1]
    pressure = 0.0
    for prior_index in range(interface_index + 1):
        prior = events[prior_index]
        index_distance = interface_index - prior_index
        recency = math.exp(-index_distance / 3.0)
        pressure += (
            _conflict_score(incoming.target, prior.target)
            * float(AMPLITUDE_SCALE[prior.amplitude])
            * recency
        )
    return pressure


def _conflict_aware_gaps(events: list[Perturbation], base_gaps: list[int], seed: int) -> list[int]:
    interfaces = list(range(len(base_gaps)))
    interfaces.sort(
        key=lambda index: (
            _interface_pressure(events, index),
            stable_uniform("collision-interface-tie", seed, index),
        ),
        reverse=True,
    )
    available = sorted(base_gaps, reverse=True)
    assigned = [0] * len(base_gaps)
    for index, gap in zip(interfaces, available):
        assigned[index] = gap
    return assigned


def schedule_positions(events: list[Perturbation], schedule: str, seed: int) -> list[int]:
    count = len(events)
    if count == 0:
        return []
    ulam = ulam_sequence(count)
    gaps = [right - left for left, right in zip(ulam, ulam[1:])]
    if schedule == "clustered":
        return list(range(1, count + 1))
    if schedule == "ulam_spaced":
        return ulam
    if schedule == "random_sparse_a":
        selected = _shuffle_gaps(gaps, seed, "a")
    elif schedule == "random_sparse_b":
        selected = _shuffle_gaps(gaps, seed, "b")
    elif schedule == "conflict_aware":
        selected = _conflict_aware_gaps(events, gaps, seed)
    else:
        raise ValueError(f"unknown collision-spacing schedule: {schedule}")
    positions = [1]
    for gap in selected:
        positions.append(positions[-1] + gap)
    return positions


def _run_one(seed: int, events: list[Perturbation], schedule: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    positions = schedule_positions(events, schedule, seed)
    tau_collision = float(config["collision_half_life_ticks"]) / math.log(2.0)
    tau_repair = float(config["damage_half_life_ticks"]) / math.log(2.0)
    collision_scale = float(config["collision_failure_scale"])
    damage_scale = float(config["damage_failure_scale"])
    collision_damage_scale = float(config["collision_damage_scale"])
    base_failure = {key: float(value) for key, value in config["base_failure_probability"].items()}
    own_damage = {key: float(value) for key, value in config["event_damage"].items()}

    rows: list[dict[str, Any]] = []
    damage = 0.0
    failures = 0
    first_failure: int | None = None
    prior: list[tuple[Perturbation, int]] = []
    adjacent_conflicts = 0
    pair_conflicts = 0

    for event_index, (event, event_time) in enumerate(zip(events, positions), start=1):
        gap = event_time - positions[event_index - 2] if event_index > 1 else event_time
        damage_before = damage * math.exp(-gap / tau_repair)
        collision_burden = 0.0
        active_conflicts = 0
        for prior_event, prior_time in prior:
            score = _conflict_score(event.target, prior_event.target)
            if score <= 0.0:
                continue
            pair_conflicts += 1
            distance = event_time - prior_time
            contribution = (
                score
                * float(AMPLITUDE_SCALE[prior_event.amplitude])
                * math.exp(-distance / tau_collision)
            )
            collision_burden += contribution
            if distance <= int(config["active_collision_window_ticks"]):
                active_conflicts += 1
        if prior and _conflict_score(event.target, prior[-1][0].target) > 0.0:
            adjacent_conflicts += 1

        damage = (
            damage_before
            + own_damage[event.amplitude]
            + collision_damage_scale * collision_burden
        )
        failure_probability = clamp(
            base_failure[event.amplitude]
            + collision_scale * collision_burden
            + damage_scale * damage,
            0.0,
            float(config["failure_probability_ceiling"]),
        )
        draw = stable_uniform("collision-outcome", seed, event.event_id)
        failed = draw < failure_probability
        failures += int(failed)
        if failed and first_failure is None:
            first_failure = event_index
        rows.append(
            {
                "schedule": schedule,
                "seed": seed,
                "event_index": event_index,
                "event_id": event.event_id,
                "event_time": event_time,
                "gap": gap,
                "amplitude": event.amplitude,
                "target": event.target,
                "conflict_degree": len(conflict_graph()[event.target]),
                "collision_burden": round(collision_burden, 10),
                "active_conflict_count": active_conflicts,
                "damage_before": round(damage_before, 10),
                "damage_after": round(damage, 10),
                "failure_probability": round(failure_probability, 10),
                "common_random_draw": round(draw, 10),
                "failed": int(failed),
                "first_failure_this_event": int(first_failure == event_index),
            }
        )
        prior.append((event, event_time))

    summary = {
        "schedule": schedule,
        "seed": seed,
        "event_count": len(events),
        "declared_horizon": int(config["horizon_ticks"]),
        "last_event_time": positions[-1],
        "failures": failures,
        "first_failure_event": first_failure,
        "n_f": first_failure if first_failure is not None else len(events) + 1,
        "mean_collision_burden": round(mean(float(row["collision_burden"]) for row in rows), 10),
        "peak_collision_burden": round(max(float(row["collision_burden"]) for row in rows), 10),
        "damage_auc": round(sum(float(row["damage_after"]) for row in rows), 10),
        "peak_damage": round(max(float(row["damage_after"]) for row in rows), 10),
        "final_event_damage": round(float(rows[-1]["damage_after"]), 10),
        "adjacent_conflict_count": adjacent_conflicts,
        "conflicting_pair_count": pair_conflicts,
    }
    return rows, summary


def simulate_collision_spacing(experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = experiment["collision_spacing"]
    rows: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for seed in map(int, config["seeds"]):
        events = generate_perturbations(seed, experiment["amplitude_multiset"])
        for schedule in config["schedules"]:
            event_rows, run = _run_one(seed, events, schedule, config)
            rows.extend(event_rows)
            runs.append(run)
    return rows, runs


def _paired_differences(
    runs: list[dict[str, Any]],
    heldout: set[int],
    left: str,
    right: str,
    field: str,
) -> list[float]:
    index = {(str(row["schedule"]), int(row["seed"])): row for row in runs}
    return [
        float(index[(left, seed)][field]) - float(index[(right, seed)][field])
        for seed in sorted(heldout)
    ]


def _named_effect(
    differences: list[float],
    config: dict[str, Any],
    comparison: str,
    positive_direction: str,
    negative_direction: str,
    unit: str,
    seed_tag: str,
) -> dict[str, Any]:
    effect = paired_effect(
        differences,
        confidence=float(config["analysis_plan"]["confidence_level"]),
        resamples=int(config["analysis_plan"]["bootstrap_resamples"]),
        seed_tag=seed_tag,
    )
    positive = int(effect["positive_count"])
    negative = int(effect["negative_count"])
    nonzero = positive + negative
    effect = dict(effect)
    effect["median_difference"] = effect.pop("median_difference_cycles")
    effect["mean_difference"] = effect.pop("mean_difference_cycles")
    return {
        **effect,
        "comparison": comparison,
        "effect_unit": unit,
        "positive_direction": positive_direction,
        "negative_direction": negative_direction,
        "majority_direction": (
            positive_direction if positive > negative
            else negative_direction if negative > positive
            else "tie"
        ),
        "positive_direction_consistency": positive / nonzero if nonzero else 0.0,
    }


def collision_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["collision_spacing"]
    seed = int(config["heldout_seeds"][0])
    events = generate_perturbations(seed, experiment["amplitude_multiset"])
    positions = {schedule: schedule_positions(events, schedule, seed) for schedule in config["schedules"]}
    ulam_gaps = [right - left for left, right in zip(positions["ulam_spaced"], positions["ulam_spaced"][1:])]
    return {
        "schema": "openline.collision-spacing.design-witness.v1",
        "event_order_identical_across_schedules": True,
        "event_count": len(events),
        "declared_horizon": int(config["horizon_ticks"]),
        "ulam_positions": positions["ulam_spaced"],
        "ulam_random_a_same_gap_multiset": sorted(ulam_gaps) == sorted(
            right - left for left, right in zip(positions["random_sparse_a"], positions["random_sparse_a"][1:])
        ),
        "ulam_random_b_same_gap_multiset": sorted(ulam_gaps) == sorted(
            right - left for left, right in zip(positions["random_sparse_b"], positions["random_sparse_b"][1:])
        ),
        "ulam_conflict_aware_same_gap_multiset": sorted(ulam_gaps) == sorted(
            right - left for left, right in zip(positions["conflict_aware"], positions["conflict_aware"][1:])
        ),
        "same_sparse_span": len({positions[name][-1] for name in ("ulam_spaced", "random_sparse_a", "random_sparse_b", "conflict_aware")}) == 1,
        "common_random_draw_key_excludes_schedule": True,
        "conflict_graph": conflict_graph(),
        "clustered_is_positive_control_not_primary_contrast": True,
    }


def analyze_collision_spacing(runs: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["collision_spacing"]
    heldout = set(map(int, config["heldout_seeds"]))
    thresholds = config["theory_thresholds"]
    design = collision_design_witness(experiment)

    clustered_collision = _named_effect(
        _paired_differences(runs, heldout, "clustered", "random_sparse_a", "mean_collision_burden"),
        config,
        "clustered minus random_sparse_a mean collision burden",
        "clustered_higher_collision",
        "random_sparse_higher_collision",
        "mean_collision_burden",
        "collision-clustered-control",
    )
    random_null = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "random_sparse_b", "mean_collision_burden"),
        config,
        "random_sparse_a minus random_sparse_b mean collision burden",
        "random_a_higher_collision",
        "random_b_higher_collision",
        "mean_collision_burden",
        "collision-random-null",
    )
    ulam_collision = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "ulam_spaced", "mean_collision_burden"),
        config,
        "random_sparse_a minus Ulam mean collision burden",
        "ulam_lower_collision",
        "ulam_higher_collision",
        "mean_collision_burden",
        "collision-ulam",
    )
    ulam_damage = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "ulam_spaced", "damage_auc"),
        config,
        "random_sparse_a minus Ulam damage AUC",
        "ulam_lower_damage",
        "ulam_higher_damage",
        "damage_auc_event_exposures",
        "damage-ulam",
    )
    ulam_failures = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "ulam_spaced", "failures"),
        config,
        "random_sparse_a minus Ulam failure count",
        "ulam_fewer_failures",
        "ulam_more_failures",
        "failures_per_20_events",
        "failures-ulam",
    )
    conflict_collision = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "conflict_aware", "mean_collision_burden"),
        config,
        "random_sparse_a minus conflict-aware mean collision burden",
        "conflict_aware_lower_collision",
        "conflict_aware_higher_collision",
        "mean_collision_burden",
        "collision-conflict-aware",
    )
    conflict_damage = _named_effect(
        _paired_differences(runs, heldout, "random_sparse_a", "conflict_aware", "damage_auc"),
        config,
        "random_sparse_a minus conflict-aware damage AUC",
        "conflict_aware_lower_damage",
        "conflict_aware_higher_damage",
        "damage_auc_event_exposures",
        "damage-conflict-aware",
    )

    design_pass = all(
        bool(design[key])
        for key in (
            "event_order_identical_across_schedules",
            "ulam_random_a_same_gap_multiset",
            "ulam_random_b_same_gap_multiset",
            "ulam_conflict_aware_same_gap_multiset",
            "same_sparse_span",
            "common_random_draw_key_excludes_schedule",
        )
    )
    gates = {
        "matched_spacing_design": {
            "passed": design_pass,
            "observed": design,
        },
        "clustered_positive_control": {
            "passed": (
                float(clustered_collision["median_difference"]) >= float(thresholds["clustered_collision_gain_min"])
                and float(clustered_collision["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": clustered_collision,
            "thresholds": {
                "collision_gain_min": thresholds["clustered_collision_gain_min"],
                "p_max": thresholds["p_max"],
            },
        },
        "random_sparse_null_specificity": {
            "passed": (
                abs(float(random_null["median_difference"])) <= float(thresholds["random_null_abs_median_max"])
                and float(random_null["exact_sign_flip_p"]) > float(thresholds["p_max"])
            ),
            "observed": random_null,
            "thresholds": {
                "abs_median_max": thresholds["random_null_abs_median_max"],
                "p_must_exceed": thresholds["p_max"],
            },
        },
        "ulam_collision_reduction": {
            "passed": (
                float(ulam_collision["median_difference"]) >= float(thresholds["ulam_collision_gain_min"])
                and float(ulam_collision["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": ulam_collision,
            "thresholds": {
                "collision_gain_min": thresholds["ulam_collision_gain_min"],
                "p_max": thresholds["p_max"],
            },
        },
        "ulam_damage_reduction": {
            "passed": (
                float(ulam_damage["median_difference"]) >= float(thresholds["ulam_damage_gain_min"])
                and float(ulam_damage["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": ulam_damage,
            "thresholds": {
                "damage_auc_gain_min": thresholds["ulam_damage_gain_min"],
                "p_max": thresholds["p_max"],
            },
        },
        "conflict_graph_collision_reduction": {
            "passed": (
                float(conflict_collision["median_difference"]) >= float(thresholds["conflict_collision_gain_min"])
                and float(conflict_collision["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": conflict_collision,
            "thresholds": {
                "collision_gain_min": thresholds["conflict_collision_gain_min"],
                "p_max": thresholds["p_max"],
            },
        },
        "conflict_graph_damage_reduction": {
            "passed": (
                float(conflict_damage["median_difference"]) >= float(thresholds["conflict_damage_gain_min"])
                and float(conflict_damage["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": conflict_damage,
            "thresholds": {
                "damage_auc_gain_min": thresholds["conflict_damage_gain_min"],
                "p_max": thresholds["p_max"],
            },
        },
    }
    passed = sum(int(gate["passed"]) for gate in gates.values())
    status = (
        "EXPLORATORY_SIGNAL" if gates["ulam_collision_reduction"]["passed"] and gates["ulam_damage_reduction"]["passed"]
        else "EXPLORATORY_NULL_OR_MIXED"
    )
    return {
        "schema": "openline.collision-spacing.summary.v1",
        "claim_label": "COLLISION_AWARE_SPACING_EXPLORATORY",
        "status": status,
        "passed_gate_count": passed,
        "gate_count": len(gates),
        "heldout_seed_count": len(heldout),
        "run_count": len(runs),
        "event_observation_count": len(runs) * int(config["events_per_run"]),
        "design_witness": design,
        "effects": {
            "clustered_positive_control": clustered_collision,
            "random_sparse_null": random_null,
            "ulam_collision": ulam_collision,
            "ulam_damage": ulam_damage,
            "ulam_failures": ulam_failures,
            "conflict_aware_collision": conflict_collision,
            "conflict_aware_damage": conflict_damage,
        },
        "gates": gates,
        "claim_boundary": (
            "This is a synthetic timing experiment. Ulam positions supply an irregular clock; the conflict graph is declared from overlapping requirement dependencies. "
            "A signal would justify testing real agent traces. It would not establish that Ulam numbers have semantic intelligence or that deployed agents repair during idle time according to this simulator."
        ),
    }
