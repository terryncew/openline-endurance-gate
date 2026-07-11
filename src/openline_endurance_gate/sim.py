from __future__ import annotations

import copy
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any

from .util import clamp, mean, stable_uniform
from .world import (
    DEPENDENCY_EDGES,
    FIELDS,
    INITIAL_REQUIREMENTS,
    REQ_TO_FIELDS,
    REQUIREMENTS,
    Perturbation,
    apply_partial_solve,
    config_accuracy,
    invariant_results,
    requirement_accuracy,
    solve,
)

AMPLITUDE_RANK = {"low": 0, "medium": 1, "high": 2}
AMPLITUDE_SCALE = {"low": 1, "medium": 2, "high": 3}
AMPLITUDE_BASE_DIFFICULTY = {"low": 0.025, "medium": 0.055, "high": 0.095}


@dataclass
class AgentState:
    believed_requirements: dict[str, int]
    config: dict[str, int]
    known_edges: set[str]
    history: list[dict[str, Any]] = field(default_factory=list)
    receipt_nodes: list[dict[str, Any]] = field(default_factory=list)
    summary_explicit: set[str] = field(default_factory=set)
    unresolved_notes: set[str] = field(default_factory=set)
    contradictions: int = 0
    retries: int = 0
    total_tokens: int = 0
    last_changed: dict[str, int] = field(default_factory=lambda: {key: 0 for key in REQUIREMENTS})

    @classmethod
    def initial(cls) -> "AgentState":
        req = dict(INITIAL_REQUIREMENTS)
        return cls(req, solve(req), set(DEPENDENCY_EDGES))


@dataclass
class RunResult:
    cycles: list[dict[str, Any]]
    summary: dict[str, Any]


def _delta_for(target: str, amplitude: str, sign: int) -> int:
    mag = AMPLITUDE_SCALE[amplitude]
    if target == "latency_floor":
        return sign * mag * 35
    return sign * mag


def generate_perturbations(seed: int, counts: dict[str, int]) -> list[Perturbation]:
    rng = random.Random(seed * 7919 + 17)
    amplitudes: list[str] = []
    for level in ("low", "medium", "high"):
        amplitudes.extend([level] * int(counts[level]))
    rng.shuffle(amplitudes)
    events: list[Perturbation] = []
    for index, amplitude in enumerate(amplitudes):
        target = REQUIREMENTS[rng.randrange(len(REQUIREMENTS))]
        sign = -1 if rng.random() < 0.5 else 1
        delta = _delta_for(target, amplitude, sign)
        ambiguity = round(0.02 + 0.04 * AMPLITUDE_RANK[amplitude] + 0.08 * rng.random(), 5)
        correction_required = rng.random() < (0.18 + 0.08 * AMPLITUDE_RANK[amplitude])
        token_cost = 18 + 7 * AMPLITUDE_SCALE[amplitude] + (10 if correction_required else 0)
        events.append(
            Perturbation(
                event_id=f"s{seed}-e{index:02d}",
                amplitude=amplitude,
                target=target,
                delta=delta,
                ambiguity=ambiguity,
                correction_required=correction_required,
                token_cost=token_cost,
            )
        )
    return events


def schedule_events(events: list[Perturbation], schedule: str, seed: int) -> list[Perturbation]:
    if schedule == "low_to_high":
        return sorted(events, key=lambda e: (AMPLITUDE_RANK[e.amplitude], e.event_id))
    if schedule == "high_to_low":
        return sorted(events, key=lambda e: (-AMPLITUDE_RANK[e.amplitude], e.event_id))
    if schedule == "randomized":
        result = list(events)
        random.Random(seed * 104729 + 31).shuffle(result)
        return result
    if schedule == "alternating":
        buckets = {
            level: sorted((event for event in events if event.amplitude == level), key=lambda e: e.event_id)
            for level in ("low", "medium", "high")
        }
        order = ("high", "low", "medium", "low")
        result: list[Perturbation] = []
        cursor = 0
        while any(buckets.values()):
            level = order[cursor % len(order)]
            if buckets[level]:
                result.append(buckets[level].pop(0))
            else:
                for fallback in ("medium", "high", "low"):
                    if buckets[fallback]:
                        result.append(buckets[fallback].pop(0))
                        break
            cursor += 1
        return result
    raise ValueError(f"unknown schedule: {schedule}")


def _representation_tokens(state: AgentState, mode: str, budget: int) -> int:
    if mode == "fresh_ground_truth":
        return min(budget, 18 * len(FIELDS) + 4 * len(DEPENDENCY_EDGES))
    if mode == "persistent_history":
        return min(budget, sum(int(item["token_cost"]) for item in state.history) + 96)
    if mode == "prose_summary":
        return min(budget, 26 * len(state.summary_explicit) + 5 * len(state.known_edges) + 48)
    if mode == "receipt_ancestry":
        return min(budget, sum(int(item["token_cost"]) for item in state.receipt_nodes[-12:]) + 7 * len(state.known_edges) + 32)
    raise ValueError(mode)


def _history_pressure(state: AgentState, mode: str, budget: int) -> float:
    if mode == "persistent_history":
        raw = sum(int(item["token_cost"]) for item in state.history) + 96
        return clamp((raw - 0.65 * budget) / max(budget, 1), 0.0, 1.5)
    if mode == "prose_summary":
        missing = 1.0 - len(state.known_edges) / len(DEPENDENCY_EDGES)
        return clamp(0.25 + 0.75 * missing, 0.0, 1.0)
    if mode == "receipt_ancestry":
        unresolved = len(state.unresolved_notes) / max(1, len(REQUIREMENTS))
        return clamp(0.12 + 0.65 * unresolved, 0.0, 1.0)
    return 0.0


def _prepare_fresh(state: AgentState, canonical_before: dict[str, int]) -> None:
    state.believed_requirements = dict(canonical_before)
    state.config = solve(canonical_before)
    state.known_edges = set(DEPENDENCY_EDGES)
    state.summary_explicit = set(REQUIREMENTS)
    state.unresolved_notes.clear()
    state.contradictions = 0


def _visible_relevant_history(state: AgentState, target: str, budget: int) -> int:
    used = 96
    count = 0
    for item in reversed(state.history):
        cost = int(item["token_cost"])
        if used + cost > budget:
            continue
        used += cost
        if item["target"] == target:
            count += 1
    return count


def _application_outcome(
    state: AgentState,
    event: Perturbation,
    mode: str,
    schedule: str,
    seed: int,
    cycle: int,
    budget: int,
    config: dict[str, Any],
) -> tuple[str, int, float]:
    pressure = _history_pressure(state, mode, budget)
    missing_edges = 1.0 - len(state.known_edges) / len(DEPENDENCY_EDGES)
    repeat_target = sum(1 for item in state.history if item["target"] == event.target)
    visible_relevant = _visible_relevant_history(state, event.target, budget) if mode == "persistent_history" else repeat_target
    hidden_relevant = max(0, repeat_target - visible_relevant)
    confusion = min(0.35, hidden_relevant * float(config["persistent_confusion_scale"])) if mode == "persistent_history" else 0.0
    difficulty = (
        AMPLITUDE_BASE_DIFFICULTY[event.amplitude]
        + event.ambiguity
        + 0.15 * pressure
        + 0.12 * missing_edges
        + 0.035 * min(repeat_target, 5)
        + confusion
        + 0.02 * min(state.contradictions, 5)
    )
    if mode == "fresh_ground_truth":
        difficulty *= 0.15
    elif mode == "prose_summary":
        difficulty *= 0.76
        if event.target not in state.summary_explicit:
            difficulty += 0.055
    elif mode == "receipt_ancestry":
        difficulty *= 0.68
        if event.target in state.unresolved_notes:
            difficulty += 0.07
        difficulty += float(config["receipt_reference_error"])
    difficulty = clamp(difficulty, 0.002, 0.72)
    u = stable_uniform("apply", seed, event.event_id, mode)
    reverse_band = 0.26 * difficulty
    duplicate_band = 0.18 * difficulty
    if u < difficulty:
        sub = stable_uniform("failure-kind", seed, event.event_id, mode)
        if sub < 0.56:
            return "missed", 0, difficulty
        if sub < 0.56 + reverse_band / max(difficulty, 1e-9):
            return "reversed", -event.delta, difficulty
        return "duplicated", 2 * event.delta, difficulty
    return "correct", event.delta, difficulty


def _correction_attempt(
    state: AgentState,
    event: Perturbation,
    applied_delta: int,
    mode: str,
    schedule: str,
    seed: int,
    budget: int,
) -> tuple[int, bool]:
    if not event.correction_required or applied_delta == event.delta:
        return applied_delta, False
    pressure = _history_pressure(state, mode, budget)
    if mode == "fresh_ground_truth":
        success_p = 0.97
    elif mode == "persistent_history":
        success_p = clamp(0.82 - 0.32 * pressure, 0.28, 0.82)
    elif mode == "prose_summary":
        success_p = 0.78 if event.target in state.summary_explicit else 0.50
    else:
        has_reference = any(node["target"] == event.target for node in state.receipt_nodes[-8:])
        success_p = 0.88 if has_reference else 0.58
    success = stable_uniform("correction", seed, event.event_id, mode) < success_p
    return (event.delta if success else applied_delta), success


def _summary_handoff(state: AgentState, event: Perturbation, seed: int, schedule: str, cycle: int, budget: int, config: dict[str, Any]) -> None:
    req_capacity = max(2, min(len(REQUIREMENTS), (budget - 60) // 28))
    scores: list[tuple[float, str]] = []
    for req in REQUIREMENTS:
        recency = 1.0 / (1.0 + max(0, cycle - state.last_changed.get(req, 0)))
        salience = abs(state.believed_requirements[req] - INITIAL_REQUIREMENTS[req])
        if req == "latency_floor":
            salience /= 35.0
        score = 1.4 * recency + 0.18 * salience + (1.2 if req == event.target else 0.0)
        score += 0.04 * stable_uniform("summary-rank", seed, event.event_id, req)
        scores.append((score, req))
    state.summary_explicit = {req for _, req in sorted(scores, reverse=True)[:req_capacity]}
    edge_capacity = max(5, (budget - 28 * len(state.summary_explicit) - 40) // 7)
    preferred = [edge for edge in DEPENDENCY_EDGES if edge.split("->", 1)[0] in state.summary_explicit]
    other = [edge for edge in DEPENDENCY_EDGES if edge not in preferred]
    preferred.sort(key=lambda edge: stable_uniform("summary-edge", seed, event.event_id, edge), reverse=True)
    other.sort(key=lambda edge: stable_uniform("summary-edge-other", seed, event.event_id, edge), reverse=True)
    state.known_edges = set((preferred + other)[:edge_capacity])
    for req in state.summary_explicit:
        if stable_uniform("summary-compress", seed, event.event_id, req) < float(config["summary_compression_error"]):
            unit = 35 if req == "latency_floor" else 1
            direction = -1 if stable_uniform("summary-sign", seed, event.event_id, req) < 0.5 else 1
            state.believed_requirements[req] += direction * unit
            state.contradictions += 1
            state.unresolved_notes.add(req)


def _receipt_handoff(state: AgentState, event: Perturbation, seed: int, schedule: str, cycle: int, budget: int, config: dict[str, Any]) -> None:
    node = {
        "event_id": event.event_id,
        "target": event.target,
        "applied_delta": state.history[-1]["applied_delta"],
        "token_cost": 20 + 5 * AMPLITUDE_SCALE[event.amplitude],
        "parent": state.receipt_nodes[-1]["event_id"] if state.receipt_nodes else None,
        "next_use": sorted(state.unresolved_notes | {event.target}),
    }
    state.receipt_nodes.append(node)
    active = [event.target] + sorted(state.unresolved_notes)
    edge_priority: list[str] = []
    for req in active:
        edge_priority.extend(sorted(edge for edge in DEPENDENCY_EDGES if edge.startswith(req + "->")))
    edge_priority.extend(sorted(DEPENDENCY_EDGES - set(edge_priority)))
    edge_capacity = max(5, (budget - 32 - min(12, len(state.receipt_nodes)) * 12) // 7)
    selected: list[str] = []
    for edge in edge_priority:
        if len(selected) >= edge_capacity:
            break
        ref_error = stable_uniform("receipt-ref", seed, event.event_id, edge)
        if ref_error < float(config["receipt_reference_error"]):
            state.unresolved_notes.add(edge.split("->", 1)[0])
            continue
        selected.append(edge)
    state.known_edges = set(selected)
    state.summary_explicit = set(active[: max(2, min(len(REQUIREMENTS), budget // 40))])


def _persistent_handoff(state: AgentState, budget: int) -> None:
    raw = sum(int(item["token_cost"]) for item in state.history) + 96
    if raw > budget:
        state.unresolved_notes.add("history_overflow")


def _repair_at_checkpoint(
    state: AgentState,
    canonical_requirements: dict[str, int],
    truth_config: dict[str, int],
    mode: str,
    seed: int,
    schedule: str,
    cycle: int,
    budget: int,
) -> tuple[int, int]:
    failures = [result.name for result in invariant_results(state.config) if not result.passed]
    mismatched = [key for key in FIELDS if state.config[key] != truth_config[key]]
    if not failures and not mismatched:
        return 0, 0
    if mode == "fresh_ground_truth":
        success_p = 0.98
    elif mode == "persistent_history":
        success_p = clamp(0.80 - 0.35 * _history_pressure(state, mode, budget), 0.20, 0.80)
    elif mode == "prose_summary":
        success_p = 0.52 + 0.22 * (len(state.known_edges) / len(DEPENDENCY_EDGES))
    else:
        relevant_refs = sum(1 for node in state.receipt_nodes[-12:] if node["target"] in state.unresolved_notes or node["target"] in REQUIREMENTS)
        success_p = clamp(0.55 + 0.03 * relevant_refs, 0.55, 0.91)
    repaired = stable_uniform("checkpoint-repair", seed, cycle, mode) < success_p
    state.retries += 1
    if repaired:
        if mode in {"fresh_ground_truth", "receipt_ancestry"}:
            state.believed_requirements = dict(canonical_requirements)
            state.config = dict(truth_config)
            state.known_edges = set(DEPENDENCY_EDGES)
            state.unresolved_notes.clear()
        elif mode == "persistent_history":
            # Raw history can reconstruct only events still inside the fixed input budget.
            visible: list[dict[str, Any]] = []
            used = 96
            for item in reversed(state.history):
                if used + int(item["token_cost"]) > budget:
                    continue
                used += int(item["token_cost"])
                visible.append(item)
            rebuilt = dict(INITIAL_REQUIREMENTS)
            for item in reversed(visible):
                rebuilt[item["target"]] += int(item["truth_delta"])
            state.believed_requirements = rebuilt
            state.config = solve(rebuilt)
        else:
            for req in state.summary_explicit:
                state.believed_requirements[req] = canonical_requirements[req]
            state.config = solve(state.believed_requirements)
            state.unresolved_notes -= state.summary_explicit
        return len(failures), len(mismatched)
    state.contradictions += max(1, len(failures))
    state.unresolved_notes.update(req for req in REQUIREMENTS if state.believed_requirements[req] != canonical_requirements[req])
    return 0, 0


def _error_dispersion(config: dict[str, int], truth: dict[str, int]) -> float:
    residuals: list[float] = []
    for key in FIELDS:
        denom = max(1.0, abs(float(truth[key])))
        residuals.append((float(config[key]) - float(truth[key])) / denom)
    return statistics.pstdev(residuals) if len(residuals) > 1 else 0.0


def _dhol(config: dict[str, int], truth: dict[str, int]) -> float:
    values = []
    for key in FIELDS:
        denom = max(1.0, abs(float(truth[key])))
        values.append(abs(float(config[key]) - float(truth[key])) / denom)
    return mean(values)


def _unsafe_attempt(config: dict[str, int], truth: dict[str, int]) -> bool:
    critical = ("approval_threshold", "risk_limit", "timeout_ms", "receipt_ttl", "evidence_budget")
    for key in critical:
        denom = max(1.0, abs(float(truth[key])))
        if abs(float(config[key]) - float(truth[key])) / denom > 0.18:
            return True
    return any(not result.passed for result in invariant_results(config))


def run_one(
    mode: str,
    schedule: str,
    seed: int,
    events: list[Perturbation],
    experiment: dict[str, Any],
    run_family: str = "primary",
    kappa_star_0: float = 1.0,
    phi_base: float = 1.0,
) -> RunResult:
    budget = int(experiment["input_budget_tokens"])
    checkpoint_every = int(experiment["checkpoint_every"])
    failure_floor = float(experiment["failure_accuracy_floor"])
    canonical = dict(INITIAL_REQUIREMENTS)
    state = AgentState.initial()
    cycle_rows: list[dict[str, Any]] = []
    first_failure: int | None = None
    checkpoint_accuracies: list[float] = []
    total_repair_count = 0
    for cycle, event in enumerate(events, start=1):
        canonical_before = dict(canonical)
        if mode == "fresh_ground_truth":
            _prepare_fresh(state, canonical_before)
        canonical[event.target] += event.delta
        truth_config = solve(canonical)
        outcome, applied_delta, difficulty = _application_outcome(
            state, event, mode, schedule, seed, cycle, budget, experiment
        )
        applied_delta, correction_success = _correction_attempt(
            state, event, applied_delta, mode, schedule, seed, budget
        )
        if applied_delta != event.delta:
            state.contradictions += 1
            state.unresolved_notes.add(event.target)
        else:
            state.unresolved_notes.discard(event.target)
        state.believed_requirements[event.target] += applied_delta
        state.last_changed[event.target] = cycle
        state.config = apply_partial_solve(
            state.config, state.believed_requirements, event.target, state.known_edges
        )
        state.total_tokens += event.token_cost + _representation_tokens(state, mode, budget)
        state.history.append(
            {
                "event_id": event.event_id,
                "target": event.target,
                "truth_delta": event.delta,
                "applied_delta": applied_delta,
                "amplitude": event.amplitude,
                "token_cost": event.token_cost,
                "outcome": outcome,
            }
        )
        if mode == "persistent_history":
            _persistent_handoff(state, budget)
        elif mode == "prose_summary":
            _summary_handoff(state, event, seed, schedule, cycle, budget, experiment)
        elif mode == "receipt_ancestry":
            _receipt_handoff(state, event, seed, schedule, cycle, budget, experiment)
        pre_repair_config_accuracy = config_accuracy(state.config, truth_config)
        pre_repair_req_accuracy = requirement_accuracy(state.believed_requirements, canonical)
        invariant_failures = [result.name for result in invariant_results(state.config) if not result.passed]
        unsafe = _unsafe_attempt(state.config, truth_config)
        checkpoint = cycle % checkpoint_every == 0
        checkpoint_failed = checkpoint and pre_repair_config_accuracy < failure_floor
        failed_now = bool(unsafe or checkpoint_failed)
        if failed_now and first_failure is None:
            first_failure = cycle
        representation_tokens = _representation_tokens(state, mode, budget)
        context_pressure = _history_pressure(state, mode, budget)
        handoff_loss = 1.0 - len(state.known_edges) / len(DEPENDENCY_EDGES)
        phi = clamp(
            0.55 * (len(state.known_edges) / len(DEPENDENCY_EDGES))
            + 0.25 * pre_repair_req_accuracy
            + 0.20 * pre_repair_config_accuracy,
            0.0,
            1.0,
        )
        epsilon = _error_dispersion(state.config, truth_config)
        dhol = _dhol(state.config, truth_config)
        amp_load = {"low": 0.14, "medium": 0.24, "high": 0.35}[event.amplitude]
        kappa = clamp(
            0.12
            + amp_load
            + 0.18 * context_pressure
            + 0.17 * handoff_loss
            + 0.025 * min(state.contradictions, 6)
            + 0.02 * (1 if outcome != "correct" else 0),
            0.0,
            1.35,
        )
        vkd = min(kappa_star_0 - kappa, phi - float(experiment["phi_min"]))
        repaired_invariants = 0
        repaired_fields = 0
        if checkpoint:
            checkpoint_accuracies.append(pre_repair_config_accuracy)
            repaired_invariants, repaired_fields = _repair_at_checkpoint(
                state, canonical, truth_config, mode, seed, schedule, cycle, budget
            )
            total_repair_count += 1 if repaired_fields else 0
        cycle_rows.append(
            {
                "run_family": run_family,
                "mode": mode,
                "schedule": schedule,
                "seed": seed,
                "cycle": cycle,
                "event_id": event.event_id,
                "amplitude": event.amplitude,
                "target": event.target,
                "truth_delta": event.delta,
                "applied_delta": applied_delta,
                "application_outcome": outcome,
                "difficulty": round(difficulty, 8),
                "correction_required": int(event.correction_required),
                "correction_success": int(correction_success),
                "checkpoint": int(checkpoint),
                "checkpoint_failed": int(checkpoint_failed),
                "unsafe_attempt": int(unsafe),
                "first_failure_this_cycle": int(first_failure == cycle),
                "failed_by_cycle": int(first_failure is not None),
                "config_accuracy": round(pre_repair_config_accuracy, 8),
                "requirement_accuracy": round(pre_repair_req_accuracy, 8),
                "invariant_failure_count": len(invariant_failures),
                "invariant_failures": "|".join(invariant_failures),
                "known_dependency_count": len(state.known_edges),
                "unresolved_dependency_count": len(state.unresolved_notes),
                "unresolved_dependencies": "|".join(sorted(state.unresolved_notes)),
                "contradiction_count": state.contradictions,
                "retry_count": state.retries,
                "repair_succeeded": int(bool(repaired_fields)),
                "repaired_invariant_count": repaired_invariants,
                "repaired_field_count": repaired_fields,
                "representation_tokens": representation_tokens,
                "total_tokens": state.total_tokens,
                "context_pressure": round(context_pressure, 8),
                "handoff_loss": round(handoff_loss, 8),
                "kappa": round(kappa, 8),
                "kappa_star_0": round(kappa_star_0, 8),
                "phi_star": round(phi, 8),
                "phi_base": round(phi_base, 8),
                "epsilon": round(epsilon, 8),
                "delta_hol": round(dhol, 8),
                "vkd": round(vkd, 8),
                "subcritical_failure": int(first_failure == cycle and kappa < kappa_star_0),
            }
        )
    nf = first_failure if first_failure is not None else len(events) + 1
    summary = {
        "run_family": run_family,
        "mode": mode,
        "schedule": schedule,
        "seed": seed,
        "cycles": len(events),
        "n_f": nf,
        "failed": int(first_failure is not None),
        "first_failure_cycle": first_failure,
        "mean_checkpoint_accuracy": round(mean(checkpoint_accuracies), 8) if checkpoint_accuracies else None,
        "final_config_accuracy": cycle_rows[-1]["config_accuracy"],
        "final_requirement_accuracy": cycle_rows[-1]["requirement_accuracy"],
        "unsafe_attempts": sum(int(row["unsafe_attempt"]) for row in cycle_rows),
        "retry_count": state.retries,
        "repair_successes": total_repair_count,
        "total_tokens": state.total_tokens,
        "subcritical_first_failure": int(any(int(row["subcritical_failure"]) for row in cycle_rows)),
    }
    return RunResult(cycle_rows, summary)


def calibrate_fresh(experiment: dict[str, Any]) -> dict[str, Any]:
    trials = int(experiment["calibration_trials_per_amplitude"])
    rates: dict[str, float] = {}
    kappa_values: list[float] = []
    phi_values: list[float] = []
    for amplitude in ("low", "medium", "high"):
        passed = 0
        for trial in range(trials):
            target = REQUIREMENTS[trial % len(REQUIREMENTS)]
            sign = -1 if trial % 2 else 1
            event = Perturbation(
                event_id=f"cal-{amplitude}-{trial}",
                amplitude=amplitude,
                target=target,
                delta=_delta_for(target, amplitude, sign),
                ambiguity=0.02 + 0.04 * AMPLITUDE_RANK[amplitude] + 0.08 * stable_uniform("cal-amb", amplitude, trial),
                correction_required=stable_uniform("cal-corr", amplitude, trial) < (0.18 + 0.08 * AMPLITUDE_RANK[amplitude]),
                token_cost=18 + 7 * AMPLITUDE_SCALE[amplitude],
            )
            result = run_one(
                "fresh_ground_truth",
                "calibration",
                900000 + trial,
                [event],
                experiment,
                run_family="calibration",
                kappa_star_0=1.0,
                phi_base=1.0,
            )
            row = result.cycles[0]
            ok = float(row["config_accuracy"]) >= float(experiment["failure_accuracy_floor"]) and not int(row["unsafe_attempt"])
            passed += int(ok)
            kappa_values.append(float(row["kappa"]))
            phi_values.append(float(row["phi_star"]))
        rates[amplitude] = passed / trials
    sorted_kappa = sorted(kappa_values)
    q99 = sorted_kappa[min(len(sorted_kappa) - 1, int(0.99 * len(sorted_kappa)))]
    kappa_star_0 = min(1.25, max(0.75, q99 * 1.12))
    phi_base = mean(phi_values)
    return {
        "one_shot_pass_rates": rates,
        "floor": float(experiment["fresh_one_shot_floor"]),
        "passed": all(rate >= float(experiment["fresh_one_shot_floor"]) for rate in rates.values()),
        "kappa_star_0": round(kappa_star_0, 8),
        "phi_base": round(phi_base, 8),
        "trials_per_amplitude": trials,
    }
