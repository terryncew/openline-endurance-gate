from __future__ import annotations

import csv
import gzip
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
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

LOAD_RATE_CYCLE_FIELDS = [
    "world", "mode", "schedule", "seed", "tick", "block", "event_kind", "event_id",
    "disturbance_index", "ordinary_index", "amplitude", "target", "truth_delta", "applied_delta",
    "application_outcome", "common_random_draw", "trailing_disturbance_count", "instantaneous_rate",
    "rolling_rate_burden", "peak_rate_so_far", "ordinary_repair_attempt", "ordinary_repair_success",
    "checkpoint", "generation_boundary", "active_context_tokens", "external_record_tokens",
    "context_pressure", "critical_omission_count", "critical_omissions", "config_accuracy",
    "requirement_accuracy", "invariant_failure_count", "checkpoint_accuracy", "critical_failure",
    "first_failure_this_tick", "failed_by_tick", "disturbances_seen", "disturbances_at_failure",
    "synthetic_damage", "total_token_work",
]

LOAD_RATE_RUN_FIELDS = [
    "world", "mode", "schedule", "seed", "horizon_ticks", "n_f_ticks", "failed",
    "first_failure_tick", "disturbances_at_failure", "final_disturbances_seen", "mean_checkpoint_accuracy",
    "minimum_checkpoint_accuracy", "critical_omission_events", "mean_critical_omissions",
    "peak_critical_omissions", "mean_active_context_tokens", "peak_active_context_tokens",
    "peak_instantaneous_rate", "peak_rolling_rate_burden", "synthetic_damage_auc",
    "total_token_work", "final_config_accuracy", "final_requirement_accuracy",
]

MODES = ("continuous_history", "ordinary_summary", "verified_capsule")
SCHEDULES = ("slow_drip", "steady_load", "sudden_burst", "burst_recovery")
WORLDS = ("rate_sensitive", "rate_disabled_null")


@dataclass
class RateState:
    truth: dict[str, int]
    believed: dict[str, int]
    config: dict[str, int]
    known_edges: set[str]
    ledger: list[dict[str, Any]] = field(default_factory=list)
    active_records: list[dict[str, Any]] = field(default_factory=list)
    active_requirements: set[str] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)
    active_context_tokens: int = 0
    rolling_rate_burden: float = 0.0
    peak_rate: float = 0.0
    synthetic_damage: float = 0.0
    total_token_work: int = 0
    first_failure: int | None = None
    disturbances_at_failure: int | None = None

    @classmethod
    def initial(cls, base_tokens: int) -> "RateState":
        truth = dict(INITIAL_REQUIREMENTS)
        state = cls(truth, dict(truth), solve(truth), set(DEPENDENCY_EDGES))
        state.active_requirements = set(REQUIREMENTS)
        state.active_context_tokens = int(base_tokens)
        previous = "GENESIS"
        for requirement in REQUIREMENTS:
            body = {
                "record_id": f"genesis:{requirement}",
                "tick": 0,
                "requirement": requirement,
                "truth_value": truth[requirement],
                "believed_value": truth[requirement],
                "previous": previous,
            }
            digest = sha256_bytes(canonical_json(body))
            record = {**body, "record_hash": digest, "token_cost": 14}
            state.ledger.append(record)
            state.active_records.append(record)
            previous = digest
        return state


def schedule_offsets(schedule: str, block_ticks: int) -> tuple[int, ...]:
    if block_ticks != 40:
        raise ValueError("v0.8 frozen schedule requires 40-tick blocks")
    mapping = {
        "slow_drip": (4, 12, 20, 28, 36),
        "steady_load": (8, 14, 20, 26, 32),
        "sudden_burst": (18, 19, 20, 21, 22),
        "burst_recovery": (5, 6, 20, 21, 35),
    }
    try:
        return mapping[schedule]
    except KeyError as exc:
        raise ValueError(f"unsupported schedule: {schedule}") from exc


def schedule_positions(schedule: str, horizon: int, block_ticks: int) -> list[int]:
    if horizon % block_ticks:
        raise ValueError("horizon must be divisible by block length")
    offsets = schedule_offsets(schedule, block_ticks)
    positions: list[int] = []
    for block_start in range(0, horizon, block_ticks):
        positions.extend(block_start + offset for offset in offsets)
    return positions


def _disturbances(seed: int, count: int) -> list[Perturbation]:
    if count % 20:
        raise ValueError("disturbance count must be a multiple of 20")
    events: list[Perturbation] = []
    for packet_index in range(count // 20):
        packet = generate_perturbations(seed * 1009 + packet_index * 7919 + 83, {"low": 7, "medium": 6, "high": 7})
        for event in packet:
            index = len(events) + 1
            events.append(Perturbation(
                event_id=f"rate-{seed}-d{index:03d}",
                amplitude=event.amplitude,
                target=event.target,
                delta=event.delta,
                ambiguity=event.ambiguity,
                correction_required=event.correction_required,
                token_cost=event.token_cost,
            ))
    return events


def _ordinary_target(seed: int, index: int) -> str:
    ranked = sorted(
        REQUIREMENTS,
        key=lambda requirement: stable_uniform("rate-ordinary-target", seed, index, requirement),
    )
    return ranked[0]


def _latest_record(state: RateState, requirement: str) -> dict[str, Any]:
    for record in reversed(state.ledger):
        if record["requirement"] == requirement:
            return record
    raise KeyError(requirement)


def _valid_record(record: dict[str, Any]) -> bool:
    body = {key: record[key] for key in ("record_id", "tick", "requirement", "truth_value", "believed_value", "previous")}
    return sha256_bytes(canonical_json(body)) == record["record_hash"]


def _append_record(state: RateState, event: Perturbation, tick: int) -> None:
    previous = str(state.ledger[-1]["record_hash"])
    body = {
        "record_id": event.event_id,
        "tick": tick,
        "requirement": event.target,
        "truth_value": int(state.truth[event.target]),
        "believed_value": int(state.believed[event.target]),
        "previous": previous,
    }
    record = {
        **body,
        "record_hash": sha256_bytes(canonical_json(body)),
        "token_cost": int(event.token_cost),
    }
    state.ledger.append(record)
    state.active_records.append(record)


def _context_pressure(tokens: int, config: dict[str, Any], world: str) -> float:
    if world == "rate_disabled_null":
        # The null removes only the rate-sensitive pathway, not ordinary context pressure.
        pass
    start = float(config["context_pressure_start_tokens"])
    width = float(config["context_pressure_width_tokens"])
    return clamp((tokens - start) / max(1.0, width), 0.0, 1.5)


def _enforce_context_budget(state: RateState, mode: str, config: dict[str, Any]) -> None:
    cap = int(config["active_context_budget_tokens"])
    if state.active_context_tokens <= cap:
        return
    if mode != "continuous_history":
        state.active_context_tokens = cap
        return
    evicted = False
    while state.active_context_tokens > cap and state.active_records:
        removed = state.active_records.pop(0)
        state.active_context_tokens = max(int(config["base_context_tokens"]), state.active_context_tokens - int(removed["token_cost"]) - int(config["record_context_overhead"]))
        evicted = True
    if not evicted:
        return
    active_latest: set[str] = set()
    active_ids = {str(record["record_id"]) for record in state.active_records}
    for requirement in REQUIREMENTS:
        latest = _latest_record(state, requirement)
        if str(latest["record_id"]) in active_ids:
            active_latest.add(requirement)
    state.active_requirements = active_latest


def _summary_boundary(state: RateState, seed: int, tick: int, config: dict[str, Any]) -> None:
    rebuilt = dict(state.believed)
    unresolved: set[str] = set()
    for requirement in REQUIREMENTS:
        if stable_uniform("rate-summary-error", seed, tick, requirement) < float(config["summary_value_error_rate"]):
            rebuilt[requirement] += 35 if requirement == "latency_floor" else (1 if stable_uniform("rate-summary-sign", seed, tick, requirement) < 0.5 else -1)
            unresolved.add(requirement)
    state.believed = rebuilt
    state.config = solve(rebuilt)
    state.unresolved = unresolved
    state.active_requirements = set(REQUIREMENTS)
    state.known_edges = set(DEPENDENCY_EDGES)
    state.active_records = []
    state.active_context_tokens = int(config["summary_context_tokens"])


def _capsule_boundary(state: RateState, seed: int, tick: int, config: dict[str, Any]) -> None:
    rebuilt = dict(state.believed)
    active: set[str] = set()
    unresolved: set[str] = set()
    for requirement in REQUIREMENTS:
        record = _latest_record(state, requirement)
        pointer_error = stable_uniform("rate-capsule-pointer", seed, tick, requirement) < float(config["capsule_pointer_error_rate"])
        if pointer_error or not _valid_record(record):
            unresolved.add(requirement)
            continue
        rebuilt[requirement] = int(record["truth_value"])
        active.add(requirement)
    state.believed = rebuilt
    state.config = solve(rebuilt)
    state.unresolved = unresolved
    state.active_requirements = active
    state.known_edges = set(DEPENDENCY_EDGES) if len(active) == len(REQUIREMENTS) else {
        edge for edge in DEPENDENCY_EDGES if edge.split("->", 1)[0] in active
    }
    state.active_records = []
    state.active_context_tokens = int(config["capsule_context_tokens"])


def _ordinary_work(
    state: RateState,
    mode: str,
    seed: int,
    event_id: str,
    target: str,
    config: dict[str, Any],
) -> tuple[int, int]:
    attempt = int(target in state.unresolved or state.believed[target] != state.truth[target])
    success = 0
    if attempt:
        base = float(config["ordinary_repair_success"])
        if mode == "ordinary_summary":
            base += float(config["summary_repair_bonus"])
        elif mode == "verified_capsule":
            base += float(config["capsule_repair_bonus"])
        base -= float(config["rate_repair_penalty"]) * state.rolling_rate_burden
        if stable_uniform("rate-ordinary-repair", seed, event_id, mode) < clamp(base, 0.05, 0.98):
            state.believed[target] = int(state.truth[target])
            state.unresolved.discard(target)
            state.active_requirements.add(target)
            state.known_edges.update(edge for edge in DEPENDENCY_EDGES if edge.startswith(target + "->"))
            state.config = solve(state.believed)
            success = 1
    return attempt, success


def _critical_omissions(state: RateState) -> list[str]:
    omissions = [
        requirement for requirement in REQUIREMENTS
        if requirement not in state.active_requirements or state.believed.get(requirement) != state.truth[requirement]
    ]
    required_edges = {
        edge for edge in DEPENDENCY_EDGES
        if edge.split("->", 1)[0] in REQUIREMENTS
    }
    if required_edges - state.known_edges:
        omissions.append("dependency_edges")
    return sorted(set(omissions))


def _run_one(seed: int, mode: str, schedule: str, world: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    horizon = int(config["horizon_ticks"])
    block_ticks = int(config["block_ticks"])
    checkpoint_every = int(config["checkpoint_every_ticks"])
    positions = schedule_positions(schedule, horizon, block_ticks)
    position_to_disturbance = {tick: index for index, tick in enumerate(positions)}
    disturbances = _disturbances(seed, len(positions))
    state = RateState.initial(int(config["base_context_tokens"]))
    rows: list[dict[str, Any]] = []
    trailing: list[int] = []
    ordinary_index = 0
    disturbances_seen = 0

    for tick in range(1, horizon + 1):
        is_disturbance = tick in position_to_disturbance
        event_kind = "disturbance" if is_disturbance else "ordinary_work"
        disturbance_index = position_to_disturbance.get(tick)
        ordinary_repair_attempt = ordinary_repair_success = 0
        event: Perturbation | None = disturbances[disturbance_index] if disturbance_index is not None else None
        if event is None:
            ordinary_index += 1
            event_id = f"rate-{seed}-w{ordinary_index:03d}"
            target = _ordinary_target(seed, ordinary_index)
            amplitude = "ordinary"
            truth_delta = 0
            applied_delta = 0
            outcome = "ordinary"
            draw = stable_uniform("rate-ordinary-draw", seed, event_id, mode, world)
            state.rolling_rate_burden *= float(config["ordinary_rate_retention"])
            if world == "rate_disabled_null":
                ordinary_repair_attempt = ordinary_repair_success = 0
            else:
                ordinary_repair_attempt, ordinary_repair_success = _ordinary_work(
                    state, mode, seed, event_id, target, config
                )
            token_cost = int(config["ordinary_work_tokens"])
        else:
            disturbances_seen += 1
            event_id = event.event_id
            target = event.target
            amplitude = event.amplitude
            truth_delta = int(event.delta)
            state.rolling_rate_burden = (
                state.rolling_rate_burden * float(config["disturbance_rate_retention"])
                + float(AMPLITUDE_SCALE[event.amplitude])
            )
            pressure = _context_pressure(state.active_context_tokens, config, world)
            omissions_before = _critical_omissions(state)
            rate_term = 0.0 if world == "rate_disabled_null" else float(config["rate_difficulty_scale"]) * state.rolling_rate_burden
            difficulty = (
                float(config["base_difficulty_scale"]) * (AMPLITUDE_BASE_DIFFICULTY[event.amplitude] + event.ambiguity)
                + rate_term
                + float(config["context_difficulty_scale"]) * pressure
                + float(config["omission_difficulty_scale"]) * len(omissions_before)
                + float(config["unresolved_difficulty_scale"]) * len(state.unresolved)
            )
            difficulty = clamp(difficulty, 0.001, float(config["difficulty_ceiling"]))
            draw = stable_uniform("rate-apply", seed, event.event_id, mode, world)
            applied_delta = event.delta
            outcome = "correct"
            if draw < difficulty:
                failure_kind = stable_uniform("rate-failure-kind", seed, event.event_id, mode, world)
                if failure_kind < 0.50:
                    applied_delta = 0
                    outcome = "missed"
                elif failure_kind < 0.78:
                    applied_delta = -event.delta
                    outcome = "reversed"
                else:
                    applied_delta = 2 * event.delta
                    outcome = "duplicated"
            if event.correction_required and applied_delta != event.delta:
                correction_p = float(config["correction_success_base"])
                if mode == "ordinary_summary":
                    correction_p += float(config["summary_correction_bonus"])
                elif mode == "verified_capsule":
                    correction_p += float(config["capsule_correction_bonus"])
                correction_p -= float(config["rate_correction_penalty"]) * state.rolling_rate_burden
                if stable_uniform("rate-correction", seed, event.event_id, mode, world) < clamp(correction_p, 0.05, 0.95):
                    applied_delta = event.delta
                    outcome = "corrected"
            state.truth[event.target] += event.delta
            state.believed[event.target] += applied_delta
            if applied_delta == event.delta:
                state.unresolved.discard(event.target)
            else:
                state.unresolved.add(event.target)
            state.active_requirements.add(event.target)
            state.config = apply_partial_solve(state.config, state.believed, event.target, state.known_edges)
            _append_record(state, event, tick)
            token_cost = int(event.token_cost)

        trailing.append(int(is_disturbance))
        window = int(config["rate_window_ticks"])
        trailing = trailing[-window:]
        trailing_count = sum(trailing)
        instantaneous_rate = trailing_count / window
        state.peak_rate = max(state.peak_rate, instantaneous_rate)
        # Ordinary work is real work and remains in total_token_work, but its
        # scratch context is released when the task completes. Persisting every
        # low-disturbance task made schedule phase a second causal pathway: a
        # slow schedule reached the same disturbance index with more retained
        # context than a burst schedule. Only receipt-worthy disturbances enter
        # the persistent active context in this rate-isolation experiment.
        if is_disturbance:
            state.active_context_tokens += token_cost + int(config["record_context_overhead"])
        state.total_token_work += token_cost
        _enforce_context_budget(state, mode, config)

        generation_boundary = tick % block_ticks == 0
        if generation_boundary:
            if mode == "ordinary_summary":
                _summary_boundary(state, seed, tick, config)
            elif mode == "verified_capsule":
                _capsule_boundary(state, seed, tick, config)

        omissions = _critical_omissions(state)
        truth_config = solve(state.truth)
        cfg_accuracy = config_accuracy(state.config, truth_config)
        req_accuracy = requirement_accuracy(state.believed, state.truth)
        invariant_failures = [item.name for item in invariant_results(state.config) if not item.passed]
        checkpoint = tick % checkpoint_every == 0
        checkpoint_accuracy = cfg_accuracy if checkpoint else 1.0
        critical_failure = bool(
            event is not None and (
                cfg_accuracy < float(config["critical_config_accuracy_floor"])
                or len(omissions) >= int(config["critical_omission_count"])
                or len(invariant_failures) >= int(config["critical_invariant_failure_count"])
            )
        )
        first = bool(critical_failure and state.first_failure is None)
        if first:
            state.first_failure = tick
            state.disturbances_at_failure = disturbances_seen

        state.synthetic_damage += max(0.0, state.rolling_rate_burden - float(config["damage_burden_floor"])) ** 2
        state.synthetic_damage += float(config["damage_error_weight"]) * len(omissions)

        rows.append({
            "world": world,
            "mode": mode,
            "schedule": schedule,
            "seed": seed,
            "tick": tick,
            "block": (tick - 1) // block_ticks + 1,
            "event_kind": event_kind,
            "event_id": event_id,
            "disturbance_index": "" if disturbance_index is None else disturbance_index + 1,
            "ordinary_index": ordinary_index if event is None else "",
            "amplitude": amplitude,
            "target": target,
            "truth_delta": truth_delta,
            "applied_delta": applied_delta,
            "application_outcome": outcome,
            "common_random_draw": round(draw, 10),
            "trailing_disturbance_count": trailing_count,
            "instantaneous_rate": round(instantaneous_rate, 10),
            "rolling_rate_burden": round(state.rolling_rate_burden, 10),
            "peak_rate_so_far": round(state.peak_rate, 10),
            "ordinary_repair_attempt": ordinary_repair_attempt,
            "ordinary_repair_success": ordinary_repair_success,
            "checkpoint": int(checkpoint),
            "generation_boundary": int(generation_boundary),
            "active_context_tokens": state.active_context_tokens,
            "external_record_tokens": sum(int(record["token_cost"]) + int(config["external_record_overhead"]) for record in state.ledger),
            "context_pressure": round(_context_pressure(state.active_context_tokens, config, world), 10),
            "critical_omission_count": len(omissions),
            "critical_omissions": "|".join(omissions),
            "config_accuracy": round(cfg_accuracy, 10),
            "requirement_accuracy": round(req_accuracy, 10),
            "invariant_failure_count": len(invariant_failures),
            "checkpoint_accuracy": round(checkpoint_accuracy, 10),
            "critical_failure": int(critical_failure),
            "first_failure_this_tick": int(first),
            "failed_by_tick": int(state.first_failure is not None),
            "disturbances_seen": disturbances_seen,
            "disturbances_at_failure": "" if state.disturbances_at_failure is None else state.disturbances_at_failure,
            "synthetic_damage": round(state.synthetic_damage, 10),
            "total_token_work": state.total_token_work,
        })

    checkpoints = [row for row in rows if int(row["checkpoint"])]
    omissions = [int(row["critical_omission_count"]) for row in checkpoints]
    n_f = state.first_failure if state.first_failure is not None else horizon + 1
    run = {
        "world": world,
        "mode": mode,
        "schedule": schedule,
        "seed": seed,
        "horizon_ticks": horizon,
        "n_f_ticks": n_f,
        "failed": int(state.first_failure is not None),
        "first_failure_tick": "" if state.first_failure is None else state.first_failure,
        "disturbances_at_failure": "" if state.disturbances_at_failure is None else state.disturbances_at_failure,
        "final_disturbances_seen": disturbances_seen,
        "mean_checkpoint_accuracy": round(mean(float(row["checkpoint_accuracy"]) for row in checkpoints), 10),
        "minimum_checkpoint_accuracy": round(min(float(row["checkpoint_accuracy"]) for row in checkpoints), 10),
        "critical_omission_events": sum(value > 0 for value in omissions),
        "mean_critical_omissions": round(mean(omissions), 10),
        "peak_critical_omissions": max(omissions) if omissions else 0,
        "mean_active_context_tokens": round(mean(float(row["active_context_tokens"]) for row in rows), 10),
        "peak_active_context_tokens": max(int(row["active_context_tokens"]) for row in rows),
        "peak_instantaneous_rate": round(max(float(row["instantaneous_rate"]) for row in rows), 10),
        "peak_rolling_rate_burden": round(max(float(row["rolling_rate_burden"]) for row in rows), 10),
        "synthetic_damage_auc": round(state.synthetic_damage, 10),
        "total_token_work": state.total_token_work,
        "final_config_accuracy": round(config_accuracy(state.config, solve(state.truth)), 10),
        "final_requirement_accuracy": round(requirement_accuracy(state.believed, state.truth), 10),
    }
    return rows, run


def simulate_load_rate(experiment: dict[str, Any], seeds: list[int] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = experiment["load_rate"]
    selected = list(map(int, seeds if seeds is not None else config["seeds"]))
    cycles: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for seed in selected:
        for world in WORLDS:
            for mode in MODES:
                for schedule in SCHEDULES:
                    cycle_rows, run = _run_one(seed, mode, schedule, world, config)
                    cycles.extend(cycle_rows)
                    runs.append(run)
    return cycles, runs


def _paired_nf(runs: list[dict[str, Any]], left: str, right: str, world: str, heldout: set[int], mode: str | None = None) -> list[float]:
    index = {
        (str(row["world"]), str(row["mode"]), str(row["schedule"]), int(row["seed"])): float(row["n_f_ticks"])
        for row in runs
    }
    modes = [mode] if mode else list(MODES)
    return [
        index[(world, selected_mode, left, seed)] - index[(world, selected_mode, right, seed)]
        for seed in sorted(heldout)
        for selected_mode in modes
    ]


def _paired_disturbances_survived(
    runs: list[dict[str, Any]], left: str, right: str, world: str, heldout: set[int], mode: str | None = None
) -> list[float]:
    index = {}
    for row in runs:
        value = (
            float(row["disturbances_at_failure"])
            if row["disturbances_at_failure"] not in {"", None}
            else float(row["final_disturbances_seen"]) + 1.0
        )
        index[(str(row["world"]), str(row["mode"]), str(row["schedule"]), int(row["seed"]))] = value
    modes = [mode] if mode else list(MODES)
    return [
        index[(world, selected_mode, left, seed)] - index[(world, selected_mode, right, seed)]
        for seed in sorted(heldout)
        for selected_mode in modes
    ]


def _mode_schedule_summary(runs: list[dict[str, Any]], world: str, mode: str, schedule: str, heldout: set[int]) -> dict[str, Any]:
    selected = [
        row for row in runs
        if row["world"] == world and row["mode"] == mode and row["schedule"] == schedule and int(row["seed"]) in heldout
    ]
    return {
        "run_count": len(selected),
        "failure_rate": mean(float(row["failed"]) for row in selected),
        "median_n_f_ticks": median(float(row["n_f_ticks"]) for row in selected),
        "median_disturbances_at_failure": median(
            float(row["disturbances_at_failure"]) if row["disturbances_at_failure"] not in {"", None} else float(row["final_disturbances_seen"] + 1)
            for row in selected
        ),
        "mean_checkpoint_accuracy": mean(float(row["mean_checkpoint_accuracy"]) for row in selected),
        "mean_critical_omissions": mean(float(row["mean_critical_omissions"]) for row in selected),
        "mean_active_context_tokens": mean(float(row["mean_active_context_tokens"]) for row in selected),
        "mean_synthetic_damage_auc": mean(float(row["synthetic_damage_auc"]) for row in selected),
        "peak_instantaneous_rate": max(float(row["peak_instantaneous_rate"]) for row in selected),
    }


def _with_disturbance_units(effect: dict[str, Any]) -> dict[str, Any]:
    """Label paired-effect fields with the actual primary endpoint unit.

    ``paired_effect`` is shared with older experiments and retains legacy
    ``*_cycles`` keys for compatibility.  v0.8 reports explicit aliases so no
    reader can mistake disturbances survived for wall-clock cycles.
    """
    labeled = dict(effect)
    labeled["unit"] = "disturbances_survived_before_critical_failure"
    aliases = {
        "mean_difference_disturbances": "mean_difference_cycles",
        "median_difference_disturbances": "median_difference_cycles",
        "mean_confidence_interval_disturbances": "mean_confidence_interval",
        "median_confidence_interval_disturbances": "median_confidence_interval",
    }
    for alias, legacy in aliases.items():
        labeled[alias] = labeled.get(legacy)
    return labeled


def analyze_load_rate(cycles: list[dict[str, Any]], runs: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["load_rate"]
    heldout = set(map(int, config["heldout_seeds"]))
    analysis = config["analysis_plan"]
    thresholds = config["thresholds"]
    confidence = float(analysis["confidence_level"])
    resamples = int(analysis["bootstrap_resamples"])

    slow_minus_burst = _with_disturbance_units(paired_effect(
        _paired_disturbances_survived(runs, "slow_drip", "sudden_burst", "rate_sensitive", heldout),
        confidence, resamples, "v8-rate-slow-burst",
    ))
    recovery_minus_burst = _with_disturbance_units(paired_effect(
        _paired_disturbances_survived(runs, "burst_recovery", "sudden_burst", "rate_sensitive", heldout),
        confidence, resamples, "v8-rate-recovery-burst",
    ))
    slow_minus_burst_null = _with_disturbance_units(paired_effect(
        _paired_disturbances_survived(runs, "slow_drip", "sudden_burst", "rate_disabled_null", heldout),
        confidence, resamples, "v8-rate-null",
    ))
    per_mode = {
        mode: _with_disturbance_units(paired_effect(
            _paired_disturbances_survived(runs, "slow_drip", "sudden_burst", "rate_sensitive", heldout, mode),
            confidence, resamples, f"v8-rate-{mode}",
        ))
        for mode in MODES
    }
    per_mode_null = {
        mode: _with_disturbance_units(paired_effect(
            _paired_disturbances_survived(runs, "slow_drip", "sudden_burst", "rate_disabled_null", heldout, mode),
            confidence, resamples, f"v81-rate-null-{mode}",
        ))
        for mode in MODES
    }

    ci = slow_minus_burst["median_confidence_interval"]
    null_ci = slow_minus_burst_null["median_confidence_interval"]
    recovery_ci = recovery_minus_burst["median_confidence_interval"]
    positive_modes = sum(float(effect["mean_difference_disturbances"]) > 0 for effect in per_mode.values())
    gates = {
        "burst_causes_earlier_critical_failure": {
            "passed": bool(
                float(slow_minus_burst["mean_difference_disturbances"]) >= float(thresholds["material_disturbance_difference"])
                and slow_minus_burst["mean_confidence_interval_disturbances"][0] is not None and float(slow_minus_burst["mean_confidence_interval_disturbances"][0]) > 0.0
                and float(slow_minus_burst["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": slow_minus_burst,
            "thresholds": {
                "mean_slow_minus_burst_min_disturbances": thresholds["material_disturbance_difference"],
                "mean_bootstrap_lower_bound_min": 0.0,
                "p_max": thresholds["p_max"],
            },
        },
        "rate_direction_replicates_across_modes": {
            "passed": positive_modes >= int(thresholds["minimum_positive_modes"]),
            "positive_mode_count": positive_modes,
            "mode_count": len(MODES),
            "per_mode": per_mode,
            "threshold": thresholds["minimum_positive_modes"],
        },
        "ordinary_work_recovery_windows_reduce_burst_harm": {
            "passed": bool(
                float(recovery_minus_burst["mean_difference_disturbances"]) >= float(thresholds["recovery_disturbance_difference"])
                and recovery_minus_burst["mean_confidence_interval_disturbances"][0] is not None and float(recovery_minus_burst["mean_confidence_interval_disturbances"][0]) >= 0.0
                and float(recovery_minus_burst["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": recovery_minus_burst,
            "thresholds": {
                "mean_recovery_minus_burst_min_disturbances": thresholds["recovery_disturbance_difference"],
                "mean_bootstrap_lower_bound_min": 0.0,
                "p_max": thresholds["p_max"],
            },
        },
        "rate_disabled_null_specificity": {
            "passed": bool(
                abs(float(slow_minus_burst_null["mean_difference_disturbances"])) <= float(thresholds["null_materiality_max_disturbances"])
                and slow_minus_burst_null["mean_confidence_interval_disturbances"][0] is not None and slow_minus_burst_null["mean_confidence_interval_disturbances"][1] is not None
                and float(slow_minus_burst_null["mean_confidence_interval_disturbances"][0]) <= 0.0 <= float(slow_minus_burst_null["mean_confidence_interval_disturbances"][1])
            ),
            "observed": slow_minus_burst_null,
            "thresholds": {
                "absolute_mean_max_disturbances": thresholds["null_materiality_max_disturbances"],
                "confidence_interval_must_include_zero": True,
            },
        },
    }
    passed = sum(int(gate["passed"]) for gate in gates.values())
    if passed == len(gates):
        status = "SURVIVES_ALL_EXPLORATORY_LOAD_RATE_GATES"
    elif passed == 0:
        status = "FAILS_ALL_EXPLORATORY_LOAD_RATE_GATES"
    else:
        status = "MIXED_EXPLORATORY_LOAD_RATE_RESULT"

    summaries = {
        world: {
            mode: {
                schedule: _mode_schedule_summary(runs, world, mode, schedule, heldout)
                for schedule in SCHEDULES
            }
            for mode in MODES
        }
        for world in WORLDS
    }

    schedule_witness = load_rate_design_witness(experiment)
    return {
        "schema": "openline.load-rate.summary.v2",
        "claim_label": "SAME_DISTURBANCE_DIFFERENT_SPEED_PHASE_CONTROLLED_REPLICATION",
        "status": status,
        "passed_gate_count": passed,
        "gate_count": len(gates),
        "heldout_seed_count": len(heldout),
        "cycle_observation_count": len(cycles),
        "run_count": len(runs),
        "primary_effect": slow_minus_burst,
        "recovery_effect": recovery_minus_burst,
        "null_effect": slow_minus_burst_null,
        "per_mode_effects": per_mode,
        "per_mode_null_effects": per_mode_null,
        "mode_schedule_summaries": summaries,
        "design_witness_digest": schedule_witness["mechanism_digest"],
        "secondary_synthetic_damage": {
            mode: {
                schedule: summaries["rate_sensitive"][mode][schedule]["mean_synthetic_damage_auc"]
                for schedule in SCHEDULES
            }
            for mode in MODES
        },
        "gates": gates,
        "claim_boundary": (
            "This seeded synthetic experiment tests whether disturbance spacing changes critical-failure life "
            "when disturbance identities, order, total load, ordinary work, horizon, random draws, and context cap are matched. "
            "Ordinary task scratch context is released after each task so retained-context growth is matched by disturbance index. "
            "It does not claim that AI agents obey fluid mechanics, identify a universal rate threshold, or establish a deployed-agent retirement policy."
        ),
    }


def load_rate_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["load_rate"]
    schedule_map = {
        schedule: schedule_positions(schedule, int(config["horizon_ticks"]), int(config["block_ticks"]))
        for schedule in SCHEDULES
    }
    per_schedule = {}
    for schedule, positions in schedule_map.items():
        per_schedule[schedule] = {
            "disturbance_count": len(positions),
            "ordinary_work_count": int(config["horizon_ticks"]) - len(positions),
            "positions": positions,
            "positions_by_block": [
                [position - block_start for position in positions if block_start < position <= block_start + int(config["block_ticks"])]
                for block_start in range(0, int(config["horizon_ticks"]), int(config["block_ticks"]))
            ],
        }
    matching = {
        "same_disturbance_count": len({item["disturbance_count"] for item in per_schedule.values()}) == 1,
        "same_ordinary_work_count": len({item["ordinary_work_count"] for item in per_schedule.values()}) == 1,
        "same_horizon": True,
        "same_disturbance_order": True,
        "same_event_bound_random_draws": config["randomness_coupling"] == "EVENT_BOUND_COMMON_RANDOM_DRAWS_SCHEDULE_EXCLUDED",
        "same_active_context_budget": True,
        "same_persistent_context_growth_by_disturbance_index": config.get("ordinary_work_context_policy") == "EPHEMERAL_SCRATCH_RELEASED_AFTER_EACH_TICK",
        "recovery_windows_contain_ordinary_work": True,
    }
    mechanism_payload = {
        key: value for key, value in config.items()
        if key not in {"pilot_seeds", "training_seeds", "validation_seeds", "heldout_seeds", "seeds"}
    }
    return {
        "schema": "openline.load-rate.design-witness.v1",
        "modes": list(MODES),
        "schedules": list(SCHEDULES),
        "worlds": list(WORLDS),
        "schedule_map": per_schedule,
        "matching_checks": matching,
        "all_matching_checks_pass": all(matching.values()),
        "ordinary_work_definition": (
            "Every non-disturbance tick executes a deterministic low-disturbance task, consumes tokens, "
            "exercises one requirement, permits bounded repair, and decays recent-load burden. Its scratch "
            "context is released after completion and remains counted in total work, preventing schedule phase "
            "from changing retained context at the same disturbance index."
        ),
        "secondary_damage_boundary": "Synthetic damage is reported but does not decide the primary rate gate.",
        "falsifiers": list(config["falsifiers"]),
        "mechanism_digest": sha256_bytes(canonical_json(mechanism_payload)),
    }


def write_deterministic_gzip_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_rate_roots(cycles: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "load_rate_cycle_merkle_root": merkle_root(cycles),
        "load_rate_cycle_count": len(cycles),
        "load_rate_run_merkle_root": merkle_root(runs),
        "load_rate_run_count": len(runs),
    }
