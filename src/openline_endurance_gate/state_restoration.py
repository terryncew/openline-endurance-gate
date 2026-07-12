from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .integrity import merkle_root
from .sim import AMPLITUDE_BASE_DIFFICULTY, AMPLITUDE_SCALE, generate_perturbations
from .statistics import paired_effect
from .util import canonical_json, clamp, mean, median, sha256_bytes, stable_uniform
from .world import (
    DEPENDENCY_EDGES,
    INITIAL_REQUIREMENTS,
    REQUIREMENTS,
    Perturbation,
    apply_partial_solve,
    config_accuracy,
    invariant_results,
    requirement_accuracy,
    solve,
)

RESTORATION_CYCLE_FIELDS = [
    "world", "mode", "seed", "cycle", "generation", "event_id", "amplitude", "target",
    "truth_delta", "applied_delta", "application_outcome", "difficulty", "common_random_draw",
    "correction_required", "correction_success", "checkpoint", "capsule_boundary",
    "restoration_triggered", "restoration_kind", "restoration_reason", "restored_requirement_count",
    "pruned_tokens", "ecc_corrections", "active_context_tokens", "external_record_tokens",
    "context_pressure", "rolling_noise_epsilon", "structural_defect", "coherence_margin_proxy",
    "stability_lambda_proxy", "critical_omission_count", "unresolved_dependency_count",
    "config_accuracy", "requirement_accuracy", "invariant_failure_count", "critical_failure",
    "first_failure_this_cycle", "failed_by_cycle", "total_restorations", "total_pruned_tokens",
    "total_ecc_corrections", "total_external_retrievals", "total_quarantines",
]

RESTORATION_RUN_FIELDS = [
    "world", "mode", "seed", "declared_horizon", "n_f", "failed", "first_failure_cycle",
    "survival_160", "survival_320", "mean_active_context_tokens_160", "mean_active_context_tokens_320",
    "mean_checkpoint_accuracy_160", "mean_checkpoint_accuracy_320", "critical_omission_rate_160",
    "critical_omission_rate_320", "mean_epsilon_160", "mean_epsilon_320", "minimum_margin_160",
    "minimum_margin_320", "restorations", "pruned_tokens", "ecc_corrections", "external_retrievals",
    "quarantines", "final_config_accuracy", "final_requirement_accuracy",
]

MODES = (
    "capsule_baseline",
    "scheduled_prune_80",
    "fixed_retirement_85",
    "telemetry_breaker",
    "ecc_digest",
    "restoration_stack",
    "sham_retirement_85",
)


@dataclass
class RestorationState:
    truth: dict[str, int]
    believed: dict[str, int]
    config: dict[str, int]
    known_edges: set[str]
    ledger: list[dict[str, Any]] = field(default_factory=list)
    active_requirements: set[str] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)
    active_context_tokens: int = 0
    epsilon: float = 0.0
    total_restorations: int = 0
    total_pruned_tokens: int = 0
    total_ecc_corrections: int = 0
    total_external_retrievals: int = 0
    total_quarantines: int = 0
    last_restoration_cycle: int = -10_000
    first_failure: int | None = None

    @classmethod
    def initial(cls, base_tokens: int) -> "RestorationState":
        truth = dict(INITIAL_REQUIREMENTS)
        state = cls(truth, dict(truth), solve(truth), set(DEPENDENCY_EDGES))
        state.active_requirements = set(REQUIREMENTS)
        state.active_context_tokens = base_tokens
        previous = "GENESIS"
        for requirement in REQUIREMENTS:
            body = {
                "record_id": f"genesis:{requirement}",
                "cycle": 0,
                "requirement": requirement,
                "truth_value": truth[requirement],
                "previous": previous,
            }
            digest = sha256_bytes(canonical_json(body))
            state.ledger.append({**body, "record_hash": digest})
            previous = digest
        return state


def _events(seed: int, horizon: int, counts: dict[str, int]) -> list[Perturbation]:
    events: list[Perturbation] = []
    block_size = sum(int(value) for value in counts.values())
    blocks = math.ceil(horizon / block_size)
    for block in range(blocks):
        packet = generate_perturbations(seed * 101 + block * 7919 + 37, counts)
        for index, event in enumerate(packet):
            cycle = block * block_size + index + 1
            events.append(Perturbation(
                event_id=f"r{seed}-c{cycle:03d}",
                amplitude=event.amplitude,
                target=event.target,
                delta=event.delta,
                ambiguity=event.ambiguity,
                correction_required=event.correction_required,
                token_cost=event.token_cost,
            ))
    return events[:horizon]


def _latest_record(state: RestorationState, requirement: str) -> dict[str, Any]:
    for record in reversed(state.ledger):
        if record["requirement"] == requirement:
            return record
    raise KeyError(requirement)


def _record_valid(record: dict[str, Any]) -> bool:
    body = {key: record[key] for key in ("record_id", "cycle", "requirement", "truth_value", "previous")}
    return sha256_bytes(canonical_json(body)) == record["record_hash"]


def _append_record(state: RestorationState, event: Perturbation, cycle: int) -> None:
    previous = str(state.ledger[-1]["record_hash"])
    body = {
        "record_id": event.event_id,
        "cycle": cycle,
        "requirement": event.target,
        "truth_value": int(state.truth[event.target]),
        "previous": previous,
    }
    state.ledger.append({**body, "record_hash": sha256_bytes(canonical_json(body))})


def _normalized_requirement_error(state: RestorationState) -> float:
    errors: list[float] = []
    for requirement in REQUIREMENTS:
        scale = 35.0 if requirement == "latency_floor" else 3.0
        errors.append(min(1.0, abs(float(state.believed[requirement] - state.truth[requirement])) / scale))
    return mean(errors)


def _telemetry(state: RestorationState, config: dict[str, Any], world: str) -> tuple[float, float, float, float]:
    context_pressure = 0.0
    if world != "pressure_disabled_null":
        start = float(config["context_pressure_start_tokens"])
        width = float(config["context_pressure_width_tokens"])
        context_pressure = clamp((state.active_context_tokens - start) / max(width, 1.0), 0.0, 1.5)
    structural_defect = clamp(
        _normalized_requirement_error(state)
        + float(config["unresolved_defect_weight"]) * len(state.unresolved) / len(REQUIREMENTS)
        + float(config["inactive_requirement_weight"]) * (len(REQUIREMENTS) - len(state.active_requirements)) / len(REQUIREMENTS),
        0.0,
        1.5,
    )
    margin = 1.0 - (
        float(config["margin_epsilon_weight"]) * state.epsilon
        + float(config["margin_defect_weight"]) * structural_defect
        + float(config["margin_context_weight"]) * context_pressure
    )
    stability = clamp(margin * (1.0 - min(structural_defect, 1.0)), -1.0, 1.0)
    return context_pressure, structural_defect, margin, stability


def _lazy_retrieve(state: RestorationState, requirement: str, seed: int, cycle: int, config: dict[str, Any]) -> tuple[int, int]:
    if requirement in state.active_requirements:
        return 0, 0
    state.total_external_retrievals += 1
    record = _latest_record(state, requirement)
    missed = stable_uniform("restore-lazy-miss", seed, cycle, requirement) < float(config["lazy_retrieval_miss_rate"])
    if missed or not _record_valid(record):
        state.unresolved.add(requirement)
        state.total_quarantines += int(not _record_valid(record))
        return 1, 0
    state.believed[requirement] = int(record["truth_value"])
    state.active_requirements.add(requirement)
    state.known_edges.update(edge for edge in DEPENDENCY_EDGES if edge.startswith(requirement + "->"))
    state.unresolved.discard(requirement)
    state.config = solve(state.believed)
    return 1, 1


def _capsule_boundary(state: RestorationState, seed: int, cycle: int, config: dict[str, Any]) -> None:
    capacity = int(config["capsule_full_requirement_capacity"])
    ordered = sorted(
        REQUIREMENTS,
        key=lambda requirement: (
            int(requirement in state.unresolved),
            int(_latest_record(state, requirement)["cycle"]),
            stable_uniform("restore-capsule-rank", seed, cycle, requirement),
        ),
        reverse=True,
    )
    full = set(ordered[:capacity])
    state.active_requirements = set(full)
    for requirement in full:
        record = _latest_record(state, requirement)
        corrupt = stable_uniform("restore-capsule-corrupt", seed, cycle, requirement) < float(config["capsule_pointer_corruption_rate"])
        if corrupt or not _record_valid(record):
            state.unresolved.add(requirement)
            state.total_quarantines += 1
            continue
        state.believed[requirement] = int(record["truth_value"])
        state.unresolved.discard(requirement)
    state.config = solve(state.believed)
    state.active_context_tokens = int(config["capsule_budget_tokens"])
    state.epsilon *= float(config["capsule_noise_retention"])


def _prune(state: RestorationState, config: dict[str, Any]) -> int:
    before = state.active_context_tokens
    state.active_context_tokens = int(config["pruned_context_tokens"])
    pruned = max(0, before - state.active_context_tokens)
    state.total_pruned_tokens += pruned
    state.epsilon *= float(config["prune_noise_retention"])
    return pruned


def _full_restore(
    state: RestorationState,
    seed: int,
    cycle: int,
    config: dict[str, Any],
    *,
    preserve_defects: bool = False,
) -> tuple[int, int]:
    state.total_restorations += 1
    state.last_restoration_cycle = cycle
    if preserve_defects:
        state.active_context_tokens = int(config["restored_context_tokens"])
        return 0, 0
    restored = 0
    quarantines = 0
    rebuilt = dict(state.believed)
    active: set[str] = set()
    unresolved: set[str] = set()
    for requirement in REQUIREMENTS:
        state.total_external_retrievals += 1
        record = _latest_record(state, requirement)
        transport_error = stable_uniform("restore-full-transport", seed, cycle, requirement) < float(config["restore_transport_error_rate"])
        if transport_error or not _record_valid(record):
            unresolved.add(requirement)
            quarantines += 1
            continue
        rebuilt[requirement] = int(record["truth_value"])
        active.add(requirement)
        restored += 1
    state.believed = rebuilt
    state.active_requirements = active
    state.unresolved = unresolved
    state.known_edges = set(DEPENDENCY_EDGES) if len(active) == len(REQUIREMENTS) else {
        edge for edge in DEPENDENCY_EDGES if edge.split("->", 1)[0] in active
    }
    state.config = solve(rebuilt)
    state.active_context_tokens = int(config["restored_context_tokens"])
    state.epsilon *= float(config["retirement_noise_retention"])
    state.total_quarantines += quarantines
    return restored, quarantines


def _ecc_correct(state: RestorationState, seed: int, cycle: int, config: dict[str, Any]) -> int:
    if cycle % int(config["ecc_interval_cycles"]) != 0:
        return 0
    mismatches = [requirement for requirement in REQUIREMENTS if state.believed[requirement] != state.truth[requirement]]
    if not mismatches:
        return 0
    if stable_uniform("restore-ecc-detect", seed, cycle) < float(config["ecc_false_negative_rate"]):
        return 0
    target = max(
        mismatches,
        key=lambda requirement: (
            len([edge for edge in DEPENDENCY_EDGES if edge.startswith(requirement + "->")]),
            abs(state.believed[requirement] - state.truth[requirement]),
            requirement,
        ),
    )
    record = _latest_record(state, target)
    if not _record_valid(record) or stable_uniform("restore-ecc-correct", seed, cycle, target) >= float(config["ecc_correction_success_rate"]):
        state.unresolved.add(target)
        return 0
    state.believed[target] = int(record["truth_value"])
    state.active_requirements.add(target)
    state.unresolved.discard(target)
    state.known_edges.update(edge for edge in DEPENDENCY_EDGES if edge.startswith(target + "->"))
    state.config = solve(state.believed)
    state.epsilon *= float(config["ecc_noise_retention"])
    state.total_ecc_corrections += 1
    return 1


def _application(
    state: RestorationState,
    event: Perturbation,
    seed: int,
    cycle: int,
    context_pressure: float,
    structural_defect: float,
    config: dict[str, Any],
) -> tuple[str, int, float, float]:
    repeat_target = sum(1 for record in state.ledger if record["requirement"] == event.target) - 1
    difficulty = clamp(
        float(config["base_difficulty_multiplier"]) * AMPLITUDE_BASE_DIFFICULTY[event.amplitude]
        + float(config["ambiguity_difficulty_multiplier"]) * event.ambiguity
        + float(config["epsilon_difficulty_scale"]) * state.epsilon
        + float(config["defect_difficulty_scale"]) * structural_defect
        + float(config["context_difficulty_scale"]) * context_pressure
        + float(config["repeat_target_difficulty_scale"]) * min(repeat_target, 8),
        0.002,
        float(config["difficulty_ceiling"]),
    )
    u = stable_uniform("restore-apply", seed, cycle)
    if u >= difficulty:
        return "correct", event.delta, difficulty, u
    kind = stable_uniform("restore-failure-kind", seed, cycle)
    if kind < 0.55:
        return "missed", 0, difficulty, u
    if kind < 0.78:
        return "reversed", -event.delta, difficulty, u
    return "duplicated", 2 * event.delta, difficulty, u


def _critical_failure(
    state: RestorationState,
    seed: int,
    cycle: int,
    margin: float,
    config: dict[str, Any],
) -> tuple[bool, int, float, int]:
    truth_config = solve(state.truth)
    accuracy = config_accuracy(state.config, truth_config)
    invariants = invariant_results(state.config)
    invariant_failures = sum(not result.passed for result in invariants)
    omissions = sum(
        requirement not in state.active_requirements or state.believed[requirement] != state.truth[requirement]
        for requirement in REQUIREMENTS
    )
    deterministic = (
        invariant_failures >= int(config["critical_invariant_failure_count"])
        or accuracy < float(config["critical_config_accuracy_floor"])
        or omissions >= int(config["critical_omission_count"])
    )
    margin_hazard = clamp(
        float(config["negative_margin_failure_scale"]) * max(0.0, -margin),
        0.0,
        float(config["margin_failure_ceiling"]),
    )
    stochastic = stable_uniform("restore-margin-failure", seed, cycle) < margin_hazard
    return bool(deterministic or stochastic), omissions, accuracy, invariant_failures


def _simulate_one(mode: str, world: str, seed: int, experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = experiment["state_restoration"]
    horizon = int(config["max_horizon_cycles"])
    state = RestorationState.initial(int(config["base_context_tokens"]))
    rows: list[dict[str, Any]] = []
    events = _events(seed, horizon, experiment["amplitude_multiset"])
    successful_retrievals = 0

    for cycle, event in enumerate(events, start=1):
        generation = (cycle - 1) // int(config["generation_length_cycles"]) + 1
        retrieval_required, retrieval_success = _lazy_retrieve(state, event.target, seed, cycle, config)
        successful_retrievals += retrieval_success
        context_pressure_before, defect_before, _, _ = _telemetry(state, config, world)

        state.truth[event.target] += event.delta
        outcome, applied_delta, difficulty, common_draw = _application(
            state, event, seed, cycle, context_pressure_before, defect_before, config
        )
        state.believed[event.target] += applied_delta
        correction_success = False
        if event.correction_required and applied_delta != event.delta:
            correction_p = clamp(
                float(config["correction_base_success"])
                - float(config["correction_epsilon_penalty"]) * state.epsilon
                - float(config["correction_defect_penalty"]) * defect_before,
                float(config["correction_success_floor"]),
                float(config["correction_success_ceiling"]),
            )
            correction_success = stable_uniform("restore-correction", seed, cycle) < correction_p
            if correction_success:
                state.believed[event.target] += event.delta - applied_delta
                applied_delta = event.delta
                outcome = "corrected"
        if state.believed[event.target] == state.truth[event.target]:
            state.unresolved.discard(event.target)
        else:
            state.unresolved.add(event.target)
        state.config = apply_partial_solve(state.config, state.believed, event.target, state.known_edges)
        _append_record(state, event, cycle)
        state.active_context_tokens += int(event.token_cost) + int(config["per_event_context_overhead"])

        exogenous_noise = (
            float(config["base_noise_by_amplitude"][event.amplitude])
            + float(config["ambiguity_noise_scale"]) * event.ambiguity
            + float(config["incorrect_noise_increment"]) * int(applied_delta != event.delta)
            + float(config["unresolved_noise_scale"]) * len(state.unresolved) / len(REQUIREMENTS)
        )
        if world == "pressure_disabled_null":
            exogenous_noise *= float(config["null_noise_multiplier"])
        state.epsilon = clamp(
            float(config["noise_retention"]) * state.epsilon + exogenous_noise,
            0.0,
            float(config["epsilon_ceiling"]),
        )

        capsule_boundary = cycle % int(config["generation_length_cycles"]) == 0
        if capsule_boundary:
            _capsule_boundary(state, seed, cycle, config)

        context_pressure, structural_defect, margin, stability = _telemetry(state, config, world)
        restoration_triggered = False
        restoration_kind = "none"
        restoration_reason = "none"
        restored_count = 0
        pruned_tokens = 0
        ecc_corrections = 0

        if mode == "scheduled_prune_80" and cycle % int(config["prune_interval_cycles"]) == 0:
            restoration_triggered = True
            restoration_kind = "state_prune"
            restoration_reason = "fixed_cycle"
            pruned_tokens = _prune(state, config)
        elif mode in {"fixed_retirement_85", "sham_retirement_85"} and cycle % int(config["fixed_retirement_interval_cycles"]) == 0:
            restoration_triggered = True
            restoration_kind = "instance_retirement"
            restoration_reason = "fixed_cycle"
            restored_count, _ = _full_restore(
                state, seed, cycle, config, preserve_defects=(mode == "sham_retirement_85")
            )
        elif mode in {"telemetry_breaker", "restoration_stack"}:
            trigger = (
                cycle - state.last_restoration_cycle >= int(config["breaker_cooldown_cycles"])
                and cycle >= int(config["breaker_min_cycle"])
                and (
                    state.epsilon >= float(config["breaker_epsilon_threshold"])
                    or margin <= float(config["breaker_margin_threshold"])
                )
            )
            if trigger:
                restoration_triggered = True
                restoration_kind = "instance_retirement"
                restoration_reason = "telemetry_threshold"
                restored_count, _ = _full_restore(state, seed, cycle, config)
        if mode in {"ecc_digest", "restoration_stack"}:
            corrected = _ecc_correct(state, seed, cycle, config)
            if corrected:
                ecc_corrections += corrected
                if not restoration_triggered:
                    restoration_triggered = True
                    restoration_kind = "ecc_digest"
                    restoration_reason = "digest_mismatch"
        if mode == "restoration_stack" and cycle % int(config["prune_interval_cycles"]) == 0:
            extra_pruned = _prune(state, config)
            pruned_tokens += extra_pruned
            if not restoration_triggered:
                restoration_triggered = True
                restoration_kind = "state_prune"
                restoration_reason = "fixed_cycle"

        context_pressure, structural_defect, margin, stability = _telemetry(state, config, world)
        checkpoint = cycle % int(config["checkpoint_every_cycles"]) == 0
        critical_failure = False
        critical_omissions = sum(
            requirement not in state.active_requirements or state.believed[requirement] != state.truth[requirement]
            for requirement in REQUIREMENTS
        )
        truth_config = solve(state.truth)
        current_config_accuracy = config_accuracy(state.config, truth_config)
        invariant_failure_count = sum(not result.passed for result in invariant_results(state.config))
        if checkpoint:
            critical_failure, critical_omissions, current_config_accuracy, invariant_failure_count = _critical_failure(
                state, seed, cycle, margin, config
            )
        first_failure_this_cycle = critical_failure and state.first_failure is None
        if first_failure_this_cycle:
            state.first_failure = cycle
        row = {
            "world": world,
            "mode": mode,
            "seed": seed,
            "cycle": cycle,
            "generation": generation,
            "event_id": event.event_id,
            "amplitude": event.amplitude,
            "target": event.target,
            "truth_delta": event.delta,
            "applied_delta": applied_delta,
            "application_outcome": outcome,
            "difficulty": difficulty,
            "common_random_draw": common_draw,
            "correction_required": int(event.correction_required),
            "correction_success": int(correction_success),
            "checkpoint": int(checkpoint),
            "capsule_boundary": int(capsule_boundary),
            "restoration_triggered": int(restoration_triggered),
            "restoration_kind": restoration_kind,
            "restoration_reason": restoration_reason,
            "restored_requirement_count": restored_count,
            "pruned_tokens": pruned_tokens,
            "ecc_corrections": ecc_corrections,
            "active_context_tokens": state.active_context_tokens,
            "external_record_tokens": len(state.ledger) * int(config["external_record_tokens_per_entry"]),
            "context_pressure": context_pressure,
            "rolling_noise_epsilon": state.epsilon,
            "structural_defect": structural_defect,
            "coherence_margin_proxy": margin,
            "stability_lambda_proxy": stability,
            "critical_omission_count": critical_omissions,
            "unresolved_dependency_count": len(state.unresolved),
            "config_accuracy": current_config_accuracy,
            "requirement_accuracy": requirement_accuracy(state.believed, state.truth),
            "invariant_failure_count": invariant_failure_count,
            "critical_failure": int(critical_failure),
            "first_failure_this_cycle": int(first_failure_this_cycle),
            "failed_by_cycle": int(state.first_failure is not None),
            "total_restorations": state.total_restorations,
            "total_pruned_tokens": state.total_pruned_tokens,
            "total_ecc_corrections": state.total_ecc_corrections,
            "total_external_retrievals": state.total_external_retrievals,
            "total_quarantines": state.total_quarantines,
        }
        rows.append(row)

    first_failure = state.first_failure
    n_f = first_failure if first_failure is not None else horizon + 1

    def subset(end: int) -> list[dict[str, Any]]:
        return [row for row in rows if int(row["cycle"]) <= end]

    run: dict[str, Any] = {
        "world": world,
        "mode": mode,
        "seed": seed,
        "declared_horizon": horizon,
        "n_f": n_f,
        "failed": int(first_failure is not None),
        "first_failure_cycle": first_failure,
        "restorations": state.total_restorations,
        "pruned_tokens": state.total_pruned_tokens,
        "ecc_corrections": state.total_ecc_corrections,
        "external_retrievals": state.total_external_retrievals,
        "quarantines": state.total_quarantines,
        "final_config_accuracy": rows[-1]["config_accuracy"],
        "final_requirement_accuracy": rows[-1]["requirement_accuracy"],
    }
    for horizon_mark in (160, 320):
        part = subset(horizon_mark)
        checkpoints = [row for row in part if row["checkpoint"]]
        run[f"survival_{horizon_mark}"] = int(first_failure is None or first_failure > horizon_mark)
        run[f"mean_active_context_tokens_{horizon_mark}"] = mean(float(row["active_context_tokens"]) for row in part)
        run[f"mean_checkpoint_accuracy_{horizon_mark}"] = mean(float(row["config_accuracy"]) for row in checkpoints)
        run[f"critical_omission_rate_{horizon_mark}"] = mean(float(row["critical_omission_count"] > 0) for row in checkpoints)
        run[f"mean_epsilon_{horizon_mark}"] = mean(float(row["rolling_noise_epsilon"]) for row in part)
        run[f"minimum_margin_{horizon_mark}"] = min(float(row["coherence_margin_proxy"]) for row in part)
    return rows, run


def simulate_state_restoration(experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = experiment["state_restoration"]
    cycles: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for seed in map(int, config["seeds"]):
        for mode in MODES:
            rows, run = _simulate_one(mode, "main", seed, experiment)
            cycles.extend(rows)
            runs.append(run)
        for mode in ("capsule_baseline", "restoration_stack"):
            rows, run = _simulate_one(mode, "pressure_disabled_null", seed, experiment)
            cycles.extend(rows)
            runs.append(run)
    return cycles, runs


def _mode_summary(runs: list[dict[str, Any]], mode: str, world: str, seeds: set[int]) -> dict[str, Any]:
    selected = [row for row in runs if row["mode"] == mode and row["world"] == world and int(row["seed"]) in seeds]
    out: dict[str, Any] = {"mode": mode, "world": world, "run_count": len(selected)}
    for horizon in (160, 320):
        out[f"survival_{horizon}"] = mean(float(row[f"survival_{horizon}"]) for row in selected)
        out[f"median_n_f_{horizon}"] = median(min(int(row["n_f"]), horizon + 1) for row in selected)
        out[f"mean_active_context_tokens_{horizon}"] = mean(float(row[f"mean_active_context_tokens_{horizon}"]) for row in selected)
        out[f"mean_checkpoint_accuracy_{horizon}"] = mean(float(row[f"mean_checkpoint_accuracy_{horizon}"]) for row in selected)
        out[f"critical_omission_rate_{horizon}"] = mean(float(row[f"critical_omission_rate_{horizon}"]) for row in selected)
        out[f"mean_epsilon_{horizon}"] = mean(float(row[f"mean_epsilon_{horizon}"]) for row in selected)
        out[f"minimum_margin_{horizon}"] = mean(float(row[f"minimum_margin_{horizon}"]) for row in selected)
    out["mean_restorations"] = mean(float(row["restorations"]) for row in selected)
    out["mean_pruned_tokens"] = mean(float(row["pruned_tokens"]) for row in selected)
    out["mean_ecc_corrections"] = mean(float(row["ecc_corrections"]) for row in selected)
    return out


def _paired_nf(
    runs: list[dict[str, Any]], treatment: str, control: str, world: str, horizon: int, seeds: set[int]
) -> list[float]:
    lookup = {(row["world"], row["mode"], int(row["seed"])): row for row in runs}
    return [
        float(min(int(lookup[(world, treatment, seed)]["n_f"]), horizon + 1) - min(int(lookup[(world, control, seed)]["n_f"]), horizon + 1))
        for seed in sorted(seeds)
    ]


def analyze_state_restoration(runs: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["state_restoration"]
    heldout = set(map(int, config["heldout_seeds"]))
    thresholds = config["thresholds"]
    confidence = float(config["analysis_plan"]["confidence_level"])
    resamples = int(config["analysis_plan"]["bootstrap_resamples"])
    modes = {mode: _mode_summary(runs, mode, "main", heldout) for mode in MODES}

    def effect(treatment: str, control: str, label: str, world: str = "main") -> dict[str, Any]:
        return paired_effect(
            _paired_nf(runs, treatment, control, world, 320, heldout), confidence, resamples, label
        )

    effects = {
        "prune_vs_baseline": effect("scheduled_prune_80", "capsule_baseline", "v7-prune-baseline"),
        "fixed_retirement_vs_baseline": effect("fixed_retirement_85", "capsule_baseline", "v7-fixed-baseline"),
        "breaker_vs_fixed": effect("telemetry_breaker", "fixed_retirement_85", "v7-breaker-fixed"),
        "ecc_vs_baseline": effect("ecc_digest", "capsule_baseline", "v7-ecc-baseline"),
        "stack_vs_baseline": effect("restoration_stack", "capsule_baseline", "v7-stack-baseline"),
        "sham_vs_baseline": effect("sham_retirement_85", "capsule_baseline", "v7-sham-baseline"),
        "null_stack_vs_baseline": effect("restoration_stack", "capsule_baseline", "v7-null-stack", "pressure_disabled_null"),
    }
    baseline = modes["capsule_baseline"]
    stack = modes["restoration_stack"]

    def material(effect_name: str, minimum: float) -> bool:
        item = effects[effect_name]
        return (
            float(item["median_difference_cycles"]) >= minimum
            and float(item["exact_sign_flip_p"]) <= float(thresholds["p_max"])
        )

    gates = {
        "scheduled_pruning_adds_endurance": {
            "passed": material("prune_vs_baseline", float(thresholds["material_life_gain_cycles"])),
            "observed": effects["prune_vs_baseline"],
        },
        "fixed_retirement_adds_endurance": {
            "passed": material("fixed_retirement_vs_baseline", float(thresholds["material_life_gain_cycles"])),
            "observed": effects["fixed_retirement_vs_baseline"],
        },
        "telemetry_breaker_beats_fixed_schedule": {
            "passed": material("breaker_vs_fixed", float(thresholds["adaptive_gain_cycles"])),
            "observed": effects["breaker_vs_fixed"],
        },
        "ecc_digest_adds_endurance": {
            "passed": material("ecc_vs_baseline", float(thresholds["adaptive_gain_cycles"])),
            "observed": effects["ecc_vs_baseline"],
        },
        "restoration_stack_reaches_160": {
            "passed": (
                stack["median_n_f_160"] >= 161
                and stack["survival_160"] >= float(thresholds["survival_rate_min"])
                and stack["critical_omission_rate_160"] <= baseline["critical_omission_rate_160"] + float(thresholds["critical_omission_margin"])
            ),
            "observed": {
                "median_n_f_censored": stack["median_n_f_160"],
                "survival_rate": stack["survival_160"],
                "critical_omission_rate_delta": stack["critical_omission_rate_160"] - baseline["critical_omission_rate_160"],
            },
        },
        "restoration_stack_reaches_320": {
            "passed": (
                stack["median_n_f_320"] >= 321
                and stack["survival_320"] >= float(thresholds["survival_rate_min"])
                and stack["critical_omission_rate_320"] <= baseline["critical_omission_rate_320"] + float(thresholds["critical_omission_margin"])
            ),
            "observed": {
                "median_n_f_censored": stack["median_n_f_320"],
                "survival_rate": stack["survival_320"],
                "critical_omission_rate_delta": stack["critical_omission_rate_320"] - baseline["critical_omission_rate_320"],
            },
        },
        "restoration_preserves_checkpoint_accuracy": {
            "passed": (
                stack["mean_checkpoint_accuracy_160"] - baseline["mean_checkpoint_accuracy_160"]
                >= -float(thresholds["checkpoint_accuracy_loss_max"])
            ),
            "observed_delta": stack["mean_checkpoint_accuracy_160"] - baseline["mean_checkpoint_accuracy_160"],
        },
        "sham_retirement_specificity": {
            "passed": (
                float(effects["sham_vs_baseline"]["median_difference_cycles"])
                <= float(thresholds["null_materiality_max_cycles"])
            ),
            "observed": effects["sham_vs_baseline"],
        },
        "pressure_disabled_null_specificity": {
            "passed": (
                float(effects["null_stack_vs_baseline"]["median_difference_cycles"])
                <= float(thresholds["null_materiality_max_cycles"])
                and not (
                    float(effects["null_stack_vs_baseline"]["median_difference_cycles"]) > 0
                    and float(effects["null_stack_vs_baseline"]["exact_sign_flip_p"]) <= float(thresholds["p_max"])
                )
            ),
            "observed": effects["null_stack_vs_baseline"],
        },
    }
    passed = sum(int(gate["passed"]) for gate in gates.values())
    status = (
        "SURVIVES_ALL_EXPLORATORY_STATE_RESTORATION_GATES" if passed == len(gates)
        else "FAILS_ALL_EXPLORATORY_STATE_RESTORATION_GATES" if passed == 0
        else "MIXED_EXPLORATORY_STATE_RESTORATION_RESULT"
    )
    return {
        "schema": "openline.state-restoration.summary.v1",
        "status": status,
        "passed_gate_count": passed,
        "gate_count": len(gates),
        "heldout_seed_count": len(heldout),
        "modes": modes,
        "effects": effects,
        "gates": gates,
        "telemetry_boundary": (
            "rolling_noise_epsilon, coherence_margin_proxy, and stability_lambda_proxy are declared synthetic observables. "
            "They test trigger policies; they are not asserted measurements of physical Coherence Dynamics variables."
        ),
        "claim_boundary": (
            "This seeded toy world tests whether pruning, verified reconstruction, telemetry-triggered retirement, and digest repair "
            "extend continuity beyond an inherited capsule baseline. It does not establish an exact 160-cycle law in deployed models."
        ),
    }


def state_restoration_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["state_restoration"]
    return {
        "schema": "openline.state-restoration.design-witness.v1",
        "modes": list(MODES),
        "horizons": list(config["horizons"]),
        "heldout_seed_count": len(config["heldout_seeds"]),
        "common_randomness": config["randomness_coupling"],
        "fixed_retirement_interval_cycles": config["fixed_retirement_interval_cycles"],
        "breaker_thresholds": {
            "epsilon": config["breaker_epsilon_threshold"],
            "margin": config["breaker_margin_threshold"],
            "cooldown": config["breaker_cooldown_cycles"],
        },
        "sham_control": "SAME_RESTART_SCHEDULE_WITH_DEFECT_AND_NOISE_STATE_PRESERVED",
        "pressure_disabled_null": "CONTEXT_PRESSURE_DISABLED_AND_EXOGENOUS_NOISE_REDUCED",
        "telemetry_status": "SYNTHETIC_PROXY_NOT_PHYSICAL_IDENTIFICATION",
        "falsifiers": list(config["falsifiers"]),
        "mechanism_digest": sha256_bytes(canonical_json({
            key: value for key, value in config.items()
            if key not in {"pilot_seeds", "training_seeds", "validation_seeds", "heldout_seeds", "seeds"}
        })),
        "empty_result_root": merkle_root([]),
    }
