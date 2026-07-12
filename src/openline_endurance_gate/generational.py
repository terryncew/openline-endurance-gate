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

GENERATIONAL_CYCLE_FIELDS = [
    "world", "mode", "seed", "cycle", "generation", "event_id", "amplitude", "target",
    "truth_delta", "applied_delta", "application_outcome", "difficulty", "common_random_draw",
    "correction_required", "correction_success", "checkpoint", "generation_boundary",
    "active_context_tokens", "external_record_tokens", "context_pressure", "recent_conflict_burden",
    "critical_omission_count", "critical_omission", "handoff_omission_count",
    "continuity_checkpoint_accuracy", "continuity_checkpoint_failed", "retrieval_required", "retrieval_success",
    "retrieval_quarantined", "capsule_full_block_count", "capsule_pointer_count", "capsule_verified",
    "known_dependency_count", "unresolved_dependency_count", "config_accuracy", "requirement_accuracy",
    "invariant_failure_count", "unsafe_attempt", "critical_failure", "first_failure_this_cycle",
    "failed_by_cycle", "total_active_token_work", "total_external_retrievals", "total_quarantines",
]

GENERATIONAL_RUN_FIELDS = [
    "world", "mode", "seed", "declared_horizon", "n_f", "failed", "first_failure_cycle",
    "survival_40", "survival_80", "survival_160", "mean_active_context_tokens_40",
    "mean_active_context_tokens_80", "mean_active_context_tokens_160", "peak_active_context_tokens",
    "mean_checkpoint_accuracy_40", "mean_checkpoint_accuracy_80", "mean_checkpoint_accuracy_160",
    "critical_omissions_40", "critical_omissions_80", "critical_omissions_160",
    "critical_omission_rate_40", "critical_omission_rate_80", "critical_omission_rate_160",
    "external_retrievals", "successful_retrievals", "quarantines", "total_active_token_work",
    "final_config_accuracy", "final_requirement_accuracy",
]

MODES = (
    "continuous_full_history",
    "ordinary_summary_reset",
    "verified_inheritance_capsule",
    "capsule_conflict_aware",
)


@dataclass
class CapsuleEntry:
    requirement: str
    value: int | None
    record_id: str
    record_hash: str
    full_block: bool
    activation_targets: tuple[str, ...]
    unresolved: bool


@dataclass
class GenerationState:
    believed_requirements: dict[str, int]
    config: dict[str, int]
    known_edges: set[str]
    raw_record: list[dict[str, Any]] = field(default_factory=list)
    active_generation: list[dict[str, Any]] = field(default_factory=list)
    unresolved: set[str] = field(default_factory=set)
    capsule_entries: dict[str, CapsuleEntry] = field(default_factory=dict)
    capsule_root: str | None = None
    capsule_verified: bool = False
    summary_explicit: set[str] = field(default_factory=set)
    active_requirements: set[str] = field(default_factory=set)
    total_active_token_work: int = 0
    total_external_retrievals: int = 0
    total_quarantines: int = 0
    first_failure: int | None = None

    @classmethod
    def initial(cls) -> "GenerationState":
        state = cls(dict(INITIAL_REQUIREMENTS), solve(INITIAL_REQUIREMENTS), set(DEPENDENCY_EDGES))
        state.active_requirements = set(REQUIREMENTS)
        previous = "GENESIS"
        for requirement in REQUIREMENTS:
            body = {
                "record_id": f"genesis:{requirement}",
                "cycle": 0,
                "requirement": requirement,
                "truth_value": INITIAL_REQUIREMENTS[requirement],
                "believed_value": INITIAL_REQUIREMENTS[requirement],
                "previous": previous,
            }
            digest = sha256_bytes(canonical_json(body))
            state.raw_record.append({**body, "record_hash": digest, "token_cost": 18})
            previous = digest
        return state


def _conflict_score(left: str, right: str) -> float:
    if left == right:
        return 1.0
    overlap = REQ_TO_FIELDS[left] & REQ_TO_FIELDS[right]
    if not overlap:
        return 0.0
    return len(overlap) / min(len(REQ_TO_FIELDS[left]), len(REQ_TO_FIELDS[right]))


def _relevant_requirements(target: str) -> set[str]:
    relevant = {target}
    for other in REQUIREMENTS:
        if _conflict_score(target, other) > 0.0:
            relevant.add(other)
    return relevant


def _extended_events(seed: int, horizon: int) -> list[Perturbation]:
    events: list[Perturbation] = []
    counts = {"low": 7, "medium": 6, "high": 7}
    generations = math.ceil(horizon / 20)
    for generation in range(generations):
        batch = generate_perturbations(seed * 1009 + generation * 37 + 11, counts)
        for local, event in enumerate(batch):
            cycle = generation * 20 + local + 1
            if cycle > horizon:
                break
            events.append(
                Perturbation(
                    event_id=f"g{seed}-c{cycle:03d}",
                    amplitude=event.amplitude,
                    target=event.target,
                    delta=event.delta,
                    ambiguity=event.ambiguity,
                    correction_required=event.correction_required,
                    token_cost=event.token_cost,
                )
            )
    return events


def _conflict_aware_generation(events: list[Perturbation], seed: int, generation: int) -> list[Perturbation]:
    remaining = list(events)
    ordered: list[Perturbation] = []
    while remaining:
        position = len(ordered)
        def score(event: Perturbation) -> tuple[float, float, float]:
            recent = ordered[-3:]
            conflict = sum(_conflict_score(event.target, prior.target) * AMPLITUDE_SCALE[prior.amplitude] for prior in recent)
            original_index = events.index(event)
            displacement = abs(original_index - position) / max(1, len(events) - 1)
            urgency = (1.0 if event.correction_required else 0.0) + 0.35 * AMPLITUDE_SCALE[event.amplitude]
            return (
                conflict + 0.22 * displacement * urgency,
                displacement,
                stable_uniform("generational-order-tie", seed, generation, event.event_id),
            )
        selected = min(remaining, key=score)
        ordered.append(selected)
        remaining.remove(selected)
    return ordered


def schedule_generational_events(seed: int, horizon: int, mode: str, generation_length: int) -> list[Perturbation]:
    events = _extended_events(seed, horizon)
    if mode != "capsule_conflict_aware":
        return events
    ordered: list[Perturbation] = []
    for start in range(0, len(events), generation_length):
        generation = start // generation_length + 1
        ordered.extend(_conflict_aware_generation(events[start : start + generation_length], seed, generation))
    return ordered


def _latest_record(state: GenerationState, requirement: str) -> dict[str, Any]:
    for record in reversed(state.raw_record):
        if record["requirement"] == requirement:
            return record
    raise RuntimeError(requirement)


def _capsule_score(state: GenerationState, requirement: str, cycle: int) -> float:
    latest = _latest_record(state, requirement)
    centrality = len(REQ_TO_FIELDS[requirement]) / max(len(fields) for fields in REQ_TO_FIELDS.values())
    recency = 1.0 / (1.0 + max(0, cycle - int(latest["cycle"])))
    unresolved = 1.0 if requirement in state.unresolved else 0.0
    changed = abs(int(latest["truth_value"]) - INITIAL_REQUIREMENTS[requirement])
    if requirement == "latency_floor":
        changed /= 35.0
    return 1.8 * unresolved + 0.9 * centrality + 0.7 * recency + 0.08 * min(changed, 8.0)


def _capsule_token_count(entries: dict[str, CapsuleEntry], unresolved_count: int) -> int:
    return 38 + 18 * unresolved_count + sum(54 if entry.full_block else 12 for entry in entries.values())


def _build_capsule(state: GenerationState, seed: int, cycle: int, config: dict[str, Any]) -> None:
    budget = int(config["capsule_budget_tokens"])
    ordered = sorted(
        REQUIREMENTS,
        key=lambda requirement: (
            _capsule_score(state, requirement, cycle),
            stable_uniform("capsule-rank", seed, cycle, requirement),
        ),
        reverse=True,
    )
    entries: dict[str, CapsuleEntry] = {}
    used = 38 + 18 * len(state.unresolved) + 12 * len(REQUIREMENTS)
    for requirement in ordered:
        latest = _latest_record(state, requirement)
        full = used + 42 <= budget
        if full:
            used += 42
        record_hash = str(latest["record_hash"])
        if stable_uniform("capsule-pointer-corrupt", seed, cycle, requirement) < float(config["pointer_corruption_rate"]):
            record_hash = sha256_bytes((record_hash + "corrupt").encode("utf-8"))
        value: int | None = int(latest["truth_value"]) if full else None
        if full and stable_uniform("capsule-block-corrupt", seed, cycle, requirement) < float(config["block_corruption_rate"]):
            value = int(value) + (35 if requirement == "latency_floor" else 1)
        activation = tuple(sorted(_relevant_requirements(requirement)))
        entries[requirement] = CapsuleEntry(
            requirement=requirement,
            value=value,
            record_id=str(latest["record_id"]),
            record_hash=record_hash,
            full_block=full,
            activation_targets=activation,
            unresolved=requirement in state.unresolved,
        )
    payload = [
        {
            "requirement": entry.requirement,
            "value": entry.value,
            "record_id": entry.record_id,
            "record_hash": entry.record_hash,
            "full_block": entry.full_block,
            "activation_targets": list(entry.activation_targets),
            "unresolved": entry.unresolved,
        }
        for entry in entries.values()
    ]
    state.capsule_entries = entries
    state.capsule_root = merkle_root(payload)
    state.capsule_verified = True
    rebuilt = dict(INITIAL_REQUIREMENTS)
    known: set[str] = set()
    for requirement, entry in entries.items():
        if not entry.full_block:
            continue
        latest = _latest_record(state, requirement)
        body = {key: latest[key] for key in ("record_id", "cycle", "requirement", "truth_value", "believed_value", "previous")}
        valid = sha256_bytes(canonical_json(body)) == entry.record_hash and int(entry.value) == int(latest["truth_value"])
        if valid:
            rebuilt[requirement] = int(entry.value)
            known.add(requirement)
        else:
            state.total_quarantines += 1
            state.unresolved.add(requirement)
    state.believed_requirements = rebuilt
    state.active_requirements = set(known)
    state.known_edges = {
        edge for edge in DEPENDENCY_EDGES
        if edge.split("->", 1)[0] in known or edge.split("->", 1)[0] in FIELDS
    }
    state.config = solve(rebuilt)
    state.active_generation.clear()


def _build_summary(state: GenerationState, seed: int, cycle: int, config: dict[str, Any]) -> None:
    budget = int(config["summary_budget_tokens"])
    capacity = max(2, min(len(REQUIREMENTS), (budget - 36) // 32))
    ordered = sorted(
        REQUIREMENTS,
        key=lambda requirement: (
            _capsule_score(state, requirement, cycle) + 0.10 * stable_uniform("summary-rank-v6", seed, cycle, requirement),
            requirement,
        ),
        reverse=True,
    )
    explicit = set(ordered[:capacity])
    rebuilt = dict(INITIAL_REQUIREMENTS)
    for requirement in explicit:
        latest = _latest_record(state, requirement)
        value = int(latest["truth_value"])
        if stable_uniform("summary-value-error-v6", seed, cycle, requirement) < float(config["summary_value_error_rate"]):
            value += 35 if requirement == "latency_floor" else (1 if stable_uniform("summary-sign-v6", seed, cycle, requirement) < 0.5 else -1)
            state.unresolved.add(requirement)
        rebuilt[requirement] = value
    state.summary_explicit = explicit
    state.believed_requirements = rebuilt
    state.active_requirements = set(explicit)
    state.known_edges = {
        edge for edge in DEPENDENCY_EDGES
        if edge.split("->", 1)[0] in explicit or edge.split("->", 1)[0] in FIELDS
    }
    state.config = solve(rebuilt)
    state.active_generation.clear()


def _activate_capsule(
    state: GenerationState,
    target: str,
    seed: int,
    cycle: int,
    config: dict[str, Any],
) -> tuple[int, int, int]:
    required = set(REQUIREMENTS)
    required_retrievals = 0
    successes = 0
    quarantines = 0
    for requirement in required:
        entry = state.capsule_entries.get(requirement)
        if entry is None or requirement in state.active_requirements:
            continue
        required_retrievals += 1
        state.total_external_retrievals += 1
        if stable_uniform("capsule-activation-miss", seed, cycle, requirement) < float(config["activation_miss_rate"]):
            state.unresolved.add(requirement)
            continue
        record = next((item for item in state.raw_record if item["record_id"] == entry.record_id), None)
        if record is None:
            state.total_quarantines += 1
            quarantines += 1
            state.unresolved.add(requirement)
            continue
        body = {key: record[key] for key in ("record_id", "cycle", "requirement", "truth_value", "believed_value", "previous")}
        valid = sha256_bytes(canonical_json(body)) == entry.record_hash
        if not valid:
            state.total_quarantines += 1
            quarantines += 1
            state.unresolved.add(requirement)
            continue
        state.believed_requirements[requirement] = int(record["truth_value"])
        state.known_edges.update(edge for edge in DEPENDENCY_EDGES if edge.startswith(requirement + "->"))
        state.active_requirements.add(requirement)
        successes += 1
    state.config = solve(state.believed_requirements)
    return required_retrievals, successes, quarantines


def _active_tokens(state: GenerationState, mode: str, config: dict[str, Any], retrievals: int) -> int:
    generation_tokens = sum(int(item["token_cost"]) + 12 for item in state.active_generation)
    if mode == "continuous_full_history":
        return int(config["base_context_tokens"]) + sum(int(item["token_cost"]) + 18 for item in state.raw_record)
    if mode == "ordinary_summary_reset":
        return int(config["summary_budget_tokens"]) + generation_tokens
    return _capsule_token_count(state.capsule_entries, len(state.unresolved)) + generation_tokens + 16 * retrievals


def _context_pressure(tokens: int, mode: str, config: dict[str, Any], world: str) -> float:
    if world == "pressure_disabled_null":
        return 0.0
    start = float(config["context_pressure_start_tokens"])
    width = float(config["context_pressure_width_tokens"])
    raw = clamp((tokens - start) / max(width, 1.0), 0.0, 1.5)
    if mode == "continuous_full_history":
        return raw
    if mode == "ordinary_summary_reset":
        return 0.35 * raw
    return 0.15 * raw


def _recent_conflict(state: GenerationState, target: str, config: dict[str, Any]) -> float:
    window = int(config["interference_window_events"])
    burden = 0.0
    for distance, record in enumerate(reversed(state.active_generation[-window:]), start=1):
        burden += _conflict_score(target, str(record["target"])) * AMPLITUDE_SCALE[str(record["amplitude"])] * math.exp(-distance / 2.0)
    return burden


def _critical_omissions(state: GenerationState, target: str, canonical_before: dict[str, int]) -> list[str]:
    required = set(REQUIREMENTS)
    missing = [requirement for requirement in required if requirement not in state.active_requirements or state.believed_requirements.get(requirement) != canonical_before[requirement]]
    required_edges = {edge for edge in DEPENDENCY_EDGES if edge.split("->", 1)[0] in required}
    if required_edges - state.known_edges:
        missing.append("dependency_edges")
    return sorted(set(missing))


def _unsafe(config_observed: dict[str, int], truth: dict[str, int]) -> bool:
    critical = ("approval_threshold", "risk_limit", "timeout_ms", "receipt_ttl", "evidence_budget")
    for field in critical:
        denom = max(1.0, abs(float(truth[field])))
        if abs(float(config_observed[field]) - float(truth[field])) / denom > 0.18:
            return True
    return any(not result.passed for result in invariant_results(config_observed))


def _append_record(
    state: GenerationState,
    event: Perturbation,
    cycle: int,
    truth_value: int,
    applied_delta: int,
) -> None:
    previous = str(state.raw_record[-1]["record_hash"]) if state.raw_record else "GENESIS"
    body = {
        "record_id": event.event_id,
        "cycle": cycle,
        "requirement": event.target,
        "truth_value": truth_value,
        "believed_value": state.believed_requirements[event.target],
        "previous": previous,
    }
    digest = sha256_bytes(canonical_json(body))
    record = {
        **body,
        "record_hash": digest,
        "token_cost": event.token_cost,
        "target": event.target,
        "amplitude": event.amplitude,
        "applied_delta": applied_delta,
    }
    state.raw_record.append(record)
    state.active_generation.append(record)


def _entry_record(state: GenerationState, entry: CapsuleEntry) -> dict[str, Any] | None:
    return next((item for item in state.raw_record if item["record_id"] == entry.record_id), None)


def _entry_valid(state: GenerationState, entry: CapsuleEntry, canonical: dict[str, int]) -> bool:
    record = _entry_record(state, entry)
    if record is None:
        return False
    body = {key: record[key] for key in ("record_id", "cycle", "requirement", "truth_value", "believed_value", "previous")}
    return (
        sha256_bytes(canonical_json(body)) == entry.record_hash
        and int(record["truth_value"]) == int(canonical[entry.requirement])
        and (entry.value is None or int(entry.value) == int(record["truth_value"]))
    )


def _handoff_witness(
    state: GenerationState,
    mode: str,
    world: str,
    canonical: dict[str, int],
) -> tuple[list[str], float, float]:
    """Evaluate whether the next generation can reconstruct safe state.

    The capsule may keep a requirement as a verified pointer rather than an
    active value. That pointer counts as inherited only when its referenced
    record hashes correctly and carries the current canonical value. This is
    the key distinction between active-context accuracy and continuity.
    """
    if mode in {"verified_inheritance_capsule", "capsule_conflict_aware"}:
        reconstructed = dict(INITIAL_REQUIREMENTS)
        omissions: list[str] = []
        for requirement in REQUIREMENTS:
            entry = state.capsule_entries.get(requirement)
            if entry is None or not _entry_valid(state, entry, canonical):
                omissions.append(requirement)
                continue
            record = _entry_record(state, entry)
            assert record is not None
            reconstructed[requirement] = int(record["truth_value"])
        witness_config = solve(reconstructed)
        return omissions, config_accuracy(witness_config, solve(canonical)), requirement_accuracy(reconstructed, canonical)

    if mode == "continuous_full_history" and world == "pressure_disabled_null":
        # The null removes attention pressure. Full history can therefore
        # reconstruct from its complete external record at the boundary.
        return [], 1.0, 1.0

    omissions = [
        requirement for requirement in REQUIREMENTS
        if requirement not in state.active_requirements
        or state.believed_requirements.get(requirement) != canonical[requirement]
    ]
    return omissions, config_accuracy(state.config, solve(canonical)), requirement_accuracy(state.believed_requirements, canonical)


def _run_one(seed: int, mode: str, config: dict[str, Any], world: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    horizon = int(config["max_horizon_cycles"])
    generation_length = int(config["generation_length_cycles"])
    checkpoint_every = int(config["checkpoint_every_cycles"])
    events = schedule_generational_events(seed, horizon, mode, generation_length)
    canonical = dict(INITIAL_REQUIREMENTS)
    state = GenerationState.initial()
    rows: list[dict[str, Any]] = []

    for cycle, event in enumerate(events, start=1):
        retrieval_required = retrieval_success = retrieval_quarantined = 0
        if mode in {"verified_inheritance_capsule", "capsule_conflict_aware"} and state.capsule_entries:
            retrieval_required, retrieval_success, retrieval_quarantined = _activate_capsule(
                state, event.target, seed, cycle, config
            )

        canonical_before = dict(canonical)
        omissions = _critical_omissions(state, event.target, canonical_before)
        active_tokens = _active_tokens(state, mode, config, retrieval_required)
        pressure = _context_pressure(active_tokens, mode, config, world)
        conflict = _recent_conflict(state, event.target, config)
        repeated = sum(1 for record in state.raw_record if record.get("requirement") == event.target)

        difficulty = (
            float(config["base_difficulty_scale"])
            * (AMPLITUDE_BASE_DIFFICULTY[event.amplitude] + event.ambiguity)
            + float(config["context_pressure_failure_scale"]) * pressure
            + float(config["critical_omission_failure_scale"]) * len(omissions)
            + float(config["interference_failure_scale"]) * conflict
            + float(config["unresolved_failure_scale"]) * min(len(state.unresolved), len(REQUIREMENTS))
        )
        if mode == "continuous_full_history" and world != "pressure_disabled_null":
            difficulty += float(config["repeat_target_confusion_scale"]) * min(repeated, 12) * pressure
        if mode == "ordinary_summary_reset":
            difficulty += float(config["summary_ambiguity_penalty"])
        difficulty = clamp(difficulty, 0.002, float(config["failure_probability_ceiling"]))

        draw = stable_uniform("generational-apply", seed, event.event_id, world)
        applied_delta = event.delta
        outcome = "correct"
        if draw < difficulty:
            kind = stable_uniform("generational-failure-kind", seed, event.event_id, world)
            if kind < 0.55:
                applied_delta = 0
                outcome = "missed"
            elif kind < 0.78:
                applied_delta = -event.delta
                outcome = "reversed"
            else:
                applied_delta = 2 * event.delta
                outcome = "duplicated"

        correction_success = False
        if event.correction_required and applied_delta != event.delta:
            if mode == "continuous_full_history":
                correction_p = clamp(0.84 - 0.38 * pressure, 0.25, 0.84)
            elif mode == "ordinary_summary_reset":
                correction_p = 0.56 + (0.18 if event.target in state.summary_explicit else 0.0)
            else:
                correction_p = 0.62 + 0.20 * (retrieval_success / max(1, retrieval_required))
                correction_p -= 0.08 * retrieval_quarantined
                correction_p = clamp(correction_p, 0.28, 0.90)
            correction_success = stable_uniform("generational-correction", seed, event.event_id, world) < correction_p
            if correction_success:
                applied_delta = event.delta
                outcome = "corrected"

        canonical[event.target] += event.delta
        truth_config = solve(canonical)
        state.believed_requirements[event.target] += applied_delta
        state.active_requirements.add(event.target)
        if applied_delta == event.delta:
            state.unresolved.discard(event.target)
        else:
            state.unresolved.add(event.target)
        state.config = apply_partial_solve(state.config, state.believed_requirements, event.target, state.known_edges)
        _append_record(state, event, cycle, canonical[event.target], applied_delta)

        pre_boundary_cfg_acc = config_accuracy(state.config, truth_config)
        pre_boundary_req_acc = requirement_accuracy(state.believed_requirements, canonical)
        failures = [result.name for result in invariant_results(state.config) if not result.passed]
        unsafe = _unsafe(state.config, truth_config)
        checkpoint = cycle % checkpoint_every == 0
        generation_boundary = cycle % generation_length == 0

        handoff_omissions: list[str] = []
        continuity_accuracy = pre_boundary_cfg_acc
        continuity_req_accuracy = pre_boundary_req_acc
        continuity_failed = False
        if generation_boundary:
            if mode == "ordinary_summary_reset":
                _build_summary(state, seed, cycle, config)
            elif mode in {"verified_inheritance_capsule", "capsule_conflict_aware"}:
                _build_capsule(state, seed, cycle, config)
            elif mode == "continuous_full_history" and world == "pressure_disabled_null":
                state.believed_requirements = dict(canonical)
                state.config = dict(truth_config)
                state.known_edges = set(DEPENDENCY_EDGES)
                state.active_requirements = set(REQUIREMENTS)
                state.unresolved.clear()
                state.active_generation.clear()

            handoff_omissions, continuity_accuracy, continuity_req_accuracy = _handoff_witness(
                state, mode, world, canonical
            )
            continuity_failed = bool(
                handoff_omissions
                or continuity_accuracy < float(config["checkpoint_accuracy_floor"])
            )
            if continuity_failed and state.first_failure is None:
                state.first_failure = cycle
            if mode in {"verified_inheritance_capsule", "capsule_conflict_aware"}:
                state.capsule_verified = not handoff_omissions

        state.total_active_token_work += active_tokens
        rows.append(
            {
                "world": world,
                "mode": mode,
                "seed": seed,
                "cycle": cycle,
                "generation": (cycle - 1) // generation_length + 1,
                "event_id": event.event_id,
                "amplitude": event.amplitude,
                "target": event.target,
                "truth_delta": event.delta,
                "applied_delta": applied_delta,
                "application_outcome": outcome,
                "difficulty": round(difficulty, 10),
                "common_random_draw": round(draw, 10),
                "correction_required": int(event.correction_required),
                "correction_success": int(correction_success),
                "checkpoint": int(checkpoint),
                "generation_boundary": int(generation_boundary),
                "continuity_checkpoint_accuracy": round(continuity_accuracy, 10),
                "handoff_omission_count": len(handoff_omissions),
                "continuity_checkpoint_failed": int(continuity_failed),
                "active_context_tokens": active_tokens,
                "external_record_tokens": sum(int(item["token_cost"]) + 18 for item in state.raw_record),
                "context_pressure": round(pressure, 10),
                "recent_conflict_burden": round(conflict, 10),
                "critical_omission_count": len(omissions),
                "critical_omission": int(bool(omissions)),
                "retrieval_required": retrieval_required,
                "retrieval_success": retrieval_success,
                "retrieval_quarantined": retrieval_quarantined,
                "capsule_full_block_count": sum(int(entry.full_block) for entry in state.capsule_entries.values()),
                "capsule_pointer_count": sum(int(not entry.full_block) for entry in state.capsule_entries.values()),
                "capsule_verified": int(state.capsule_verified),
                "known_dependency_count": len(state.known_edges),
                "unresolved_dependency_count": len(state.unresolved),
                "config_accuracy": round(continuity_accuracy if generation_boundary else pre_boundary_cfg_acc, 10),
                "requirement_accuracy": round(continuity_req_accuracy if generation_boundary else pre_boundary_req_acc, 10),
                "invariant_failure_count": len(failures),
                "unsafe_attempt": int(unsafe),
                "critical_failure": int(continuity_failed),
                "first_failure_this_cycle": int(continuity_failed and state.first_failure == cycle),
                "failed_by_cycle": int(state.first_failure is not None),
                "total_active_token_work": state.total_active_token_work,
                "total_external_retrievals": state.total_external_retrievals,
                "total_quarantines": state.total_quarantines,
            }
        )

    first = state.first_failure
    checkpoints = [row for row in rows if int(row["checkpoint"])]
    def prefix_metric(h: int, key: str) -> float:
        subset = [row for row in rows if int(row["cycle"]) <= h]
        return mean(float(row[key]) for row in subset)
    def checkpoint_metric(h: int) -> float:
        subset = [row for row in checkpoints if int(row["cycle"]) <= h]
        return mean(float(row["config_accuracy"]) for row in subset)
    def omission_count(h: int) -> int:
        return sum(int(row["critical_omission"]) for row in rows if int(row["cycle"]) <= h)

    run = {
        "world": world,
        "mode": mode,
        "seed": seed,
        "declared_horizon": horizon,
        "n_f": first if first is not None else horizon + 1,
        "failed": int(first is not None),
        "first_failure_cycle": first,
        "survival_40": int(first is None or first > 40),
        "survival_80": int(first is None or first > 80),
        "survival_160": int(first is None or first > 160),
        "mean_active_context_tokens_40": round(prefix_metric(40, "active_context_tokens"), 8),
        "mean_active_context_tokens_80": round(prefix_metric(80, "active_context_tokens"), 8),
        "mean_active_context_tokens_160": round(prefix_metric(160, "active_context_tokens"), 8),
        "peak_active_context_tokens": max(int(row["active_context_tokens"]) for row in rows),
        "mean_checkpoint_accuracy_40": round(checkpoint_metric(40), 8),
        "mean_checkpoint_accuracy_80": round(checkpoint_metric(80), 8),
        "mean_checkpoint_accuracy_160": round(checkpoint_metric(160), 8),
        "critical_omissions_40": omission_count(40),
        "critical_omissions_80": omission_count(80),
        "critical_omissions_160": omission_count(160),
        "critical_omission_rate_40": round(omission_count(40) / 40.0, 8),
        "critical_omission_rate_80": round(omission_count(80) / 80.0, 8),
        "critical_omission_rate_160": round(omission_count(160) / 160.0, 8),
        "external_retrievals": state.total_external_retrievals,
        "successful_retrievals": sum(int(row["retrieval_success"]) for row in rows),
        "quarantines": state.total_quarantines,
        "total_active_token_work": state.total_active_token_work,
        "final_config_accuracy": rows[-1]["config_accuracy"],
        "final_requirement_accuracy": rows[-1]["requirement_accuracy"],
    }
    return rows, run

def simulate_generational_endurance(experiment: dict[str, Any], seeds: list[int] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = experiment["generational_endurance"]
    selected = list(map(int, seeds if seeds is not None else config["seeds"]))
    cycles: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for seed in selected:
        for mode in MODES:
            mode_cycles, mode_run = _run_one(seed, mode, config, "main")
            cycles.extend(mode_cycles)
            runs.append(mode_run)
        for mode in ("continuous_full_history", "verified_inheritance_capsule"):
            null_cycles, null_run = _run_one(seed, mode, config, "pressure_disabled_null")
            cycles.extend(null_cycles)
            runs.append(null_run)
    return cycles, runs


def _paired_nf(runs: list[dict[str, Any]], left: str, right: str, world: str, horizon: int, seeds: set[int]) -> list[float]:
    index = {(row["world"], row["mode"], int(row["seed"])): row for row in runs}
    diffs: list[float] = []
    for seed in sorted(seeds):
        left_row = index[(world, left, seed)]
        right_row = index[(world, right, seed)]
        left_nf = min(int(left_row["n_f"]), horizon + 1)
        right_nf = min(int(right_row["n_f"]), horizon + 1)
        diffs.append(float(left_nf - right_nf))
    return diffs


def _mode_summary(runs: list[dict[str, Any]], mode: str, world: str, seeds: set[int]) -> dict[str, Any]:
    selected = [row for row in runs if row["mode"] == mode and row["world"] == world and int(row["seed"]) in seeds]
    summary: dict[str, Any] = {"run_count": len(selected)}
    for horizon in (40, 80, 160):
        summary[f"survival_{horizon}"] = mean(float(row[f"survival_{horizon}"]) for row in selected)
        summary[f"median_n_f_{horizon}"] = median(min(int(row["n_f"]), horizon + 1) for row in selected)
        summary[f"mean_active_context_tokens_{horizon}"] = mean(float(row[f"mean_active_context_tokens_{horizon}"]) for row in selected)
        summary[f"mean_checkpoint_accuracy_{horizon}"] = mean(float(row[f"mean_checkpoint_accuracy_{horizon}"]) for row in selected)
        summary[f"critical_omission_rate_{horizon}"] = mean(float(row[f"critical_omission_rate_{horizon}"]) for row in selected)
    summary["mean_external_retrievals"] = mean(float(row["external_retrievals"]) for row in selected)
    summary["mean_quarantines"] = mean(float(row["quarantines"]) for row in selected)
    return summary


def analyze_generational_endurance(runs: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["generational_endurance"]
    heldout = set(map(int, config["heldout_seeds"]))
    thresholds = config["thresholds"]
    confidence = float(config["analysis_plan"]["confidence_level"])
    resamples = int(config["analysis_plan"]["bootstrap_resamples"])

    modes = {mode: _mode_summary(runs, mode, "main", heldout) for mode in MODES}
    capsule = modes["verified_inheritance_capsule"]
    continuous = modes["continuous_full_history"]
    summary_mode = modes["ordinary_summary_reset"]
    conflict = modes["capsule_conflict_aware"]

    capsule_vs_summary = paired_effect(
        _paired_nf(runs, "verified_inheritance_capsule", "ordinary_summary_reset", "main", 160, heldout),
        confidence, resamples, "v6-capsule-summary",
    )
    conflict_vs_capsule = paired_effect(
        _paired_nf(runs, "capsule_conflict_aware", "verified_inheritance_capsule", "main", 160, heldout),
        confidence, resamples, "v6-conflict-capsule",
    )
    null_capsule_vs_continuous = paired_effect(
        _paired_nf(runs, "verified_inheritance_capsule", "continuous_full_history", "pressure_disabled_null", 160, heldout),
        confidence, resamples, "v6-null-capsule-continuous",
    )

    context_ratio_40 = capsule["mean_active_context_tokens_40"] / continuous["mean_active_context_tokens_40"]
    context_ratio_80 = capsule["mean_active_context_tokens_80"] / continuous["mean_active_context_tokens_80"]
    context_ratio_160 = capsule["mean_active_context_tokens_160"] / continuous["mean_active_context_tokens_160"]
    omission_delta_40 = capsule["critical_omission_rate_40"] - continuous["critical_omission_rate_40"]
    omission_delta_80 = capsule["critical_omission_rate_80"] - continuous["critical_omission_rate_80"]
    omission_delta_160 = capsule["critical_omission_rate_160"] - continuous["critical_omission_rate_160"]
    accuracy_delta_40 = capsule["mean_checkpoint_accuracy_40"] - continuous["mean_checkpoint_accuracy_40"]

    def horizon_gate(horizon: int) -> dict[str, Any]:
        ratio = {40: context_ratio_40, 80: context_ratio_80, 160: context_ratio_160}[horizon]
        omission_delta = {40: omission_delta_40, 80: omission_delta_80, 160: omission_delta_160}[horizon]
        passed = (
            capsule[f"median_n_f_{horizon}"] >= horizon + 1
            and ratio <= float(thresholds["context_ratio_max"])
            and omission_delta <= float(thresholds["critical_omission_rate_margin"])
        )
        return {
            "passed": bool(passed),
            "observed": {
                "median_n_f_censored": capsule[f"median_n_f_{horizon}"],
                "survival_rate": capsule[f"survival_{horizon}"],
                "active_context_ratio_vs_continuous": ratio,
                "critical_omission_rate_delta_vs_continuous": omission_delta,
            },
            "thresholds": {
                "median_n_f_censored_min": horizon + 1,
                "context_ratio_max": thresholds["context_ratio_max"],
                "critical_omission_rate_margin": thresholds["critical_omission_rate_margin"],
            },
        }

    gates = {
        "verified_horizon_40": horizon_gate(40),
        "verified_horizon_80": horizon_gate(80),
        "verified_horizon_160": horizon_gate(160),
        "capsule_accuracy_noninferiority_40": {
            "passed": accuracy_delta_40 >= -float(thresholds["checkpoint_accuracy_loss_max"]),
            "observed_checkpoint_accuracy_delta": accuracy_delta_40,
            "threshold": -float(thresholds["checkpoint_accuracy_loss_max"]),
        },
        "capsule_vs_summary_endurance": {
            "passed": (
                float(capsule_vs_summary["median_difference_cycles"]) >= float(thresholds["material_life_gain_cycles"])
                and float(capsule_vs_summary["exact_sign_flip_p"]) <= float(thresholds["p_max"])
            ),
            "observed": capsule_vs_summary,
            "thresholds": {
                "median_gain_cycles": thresholds["material_life_gain_cycles"],
                "p_max": thresholds["p_max"],
            },
        },
        "conflict_aware_capsule_advantage": {
            "passed": (
                float(conflict_vs_capsule["median_difference_cycles"]) >= float(thresholds["conflict_life_gain_cycles"])
                and float(conflict_vs_capsule["exact_sign_flip_p"]) <= float(thresholds["p_max"])
                and conflict["critical_omission_rate_160"] <= capsule["critical_omission_rate_160"] + float(thresholds["critical_omission_rate_margin"])
            ),
            "observed": conflict_vs_capsule,
            "omission_rate_delta": conflict["critical_omission_rate_160"] - capsule["critical_omission_rate_160"],
            "thresholds": {
                "median_gain_cycles": thresholds["conflict_life_gain_cycles"],
                "p_max": thresholds["p_max"],
            },
        },
        "pressure_disabled_null_specificity": {
            "passed": (
                float(null_capsule_vs_continuous["median_difference_cycles"]) <= float(thresholds["null_materiality_max_cycles"])
                and not (
                    float(null_capsule_vs_continuous["median_difference_cycles"]) > 0.0
                    and float(null_capsule_vs_continuous["exact_sign_flip_p"]) <= float(thresholds["p_max"])
                )
            ),
            "observed": null_capsule_vs_continuous,
            "thresholds": {
                "positive_median_advantage_max_cycles": thresholds["null_materiality_max_cycles"],
                "significant_positive_advantage_p_max": thresholds["p_max"],
            },
            "decision_rule": (
                "Fail if the capsule retains a positive median advantage above the materiality ceiling "
                "or any positive advantage at or below the declared p threshold. Negative values mean "
                "continuous history performs better and do not count as an artificial capsule advantage."
            ),
        },
    }
    passed = sum(int(item["passed"]) for item in gates.values())
    if passed == len(gates):
        status = "SURVIVES_ALL_EXPLORATORY_GENERATIONAL_GATES"
    elif passed == 0:
        status = "FAILS_ALL_EXPLORATORY_GENERATIONAL_GATES"
    else:
        status = "MIXED_EXPLORATORY_GENERATIONAL_RESULT"

    maximum_verified_horizon = 0
    for horizon in (40, 80, 160):
        if gates[f"verified_horizon_{horizon}"]["passed"]:
            maximum_verified_horizon = horizon
        else:
            break

    return {
        "schema": "openline.generational-endurance.summary.v1",
        "status": status,
        "passed_gate_count": passed,
        "gate_count": len(gates),
        "heldout_seed_count": len(heldout),
        "maximum_verified_horizon_cycles": maximum_verified_horizon,
        "modes": modes,
        "effects": {
            "capsule_vs_summary": capsule_vs_summary,
            "conflict_vs_capsule": conflict_vs_capsule,
            "pressure_disabled_capsule_vs_continuous": null_capsule_vs_continuous,
        },
        "compression_witness": {
            "active_context_ratio_40": context_ratio_40,
            "active_context_ratio_80": context_ratio_80,
            "active_context_ratio_160": context_ratio_160,
            "checkpoint_accuracy_delta_40": accuracy_delta_40,
            "critical_omission_delta_40": omission_delta_40,
            "critical_omission_delta_80": omission_delta_80,
            "critical_omission_delta_160": omission_delta_160,
        },
        "gates": gates,
        "claim_boundary": "This seeded toy world tests finite-context inheritance mechanics using the existing Endurance Gate requirement graph. It does not establish that deployed agents possess fatigue, that capsules generalize across models, or that synthetic context pressure matches transformer attention.",
    }


def generational_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["generational_endurance"]
    return {
        "schema": "openline.generational-endurance.design-witness.v1",
        "modes": list(MODES),
        "horizons": list(config["horizons"]),
        "generation_length_cycles": config["generation_length_cycles"],
        "heldout_seed_count": len(config["heldout_seeds"]),
        "common_randomness": config["randomness_coupling"],
        "capsule_budget_tokens": config["capsule_budget_tokens"],
        "summary_budget_tokens": config["summary_budget_tokens"],
        "raw_record_policy": "OUTSIDE_ACTIVE_CONTEXT_RETRIEVABLE_BY_HASH_REFERENCE",
        "null_world": "PRESSURE_DISABLED_COMMON_EVENT_WORLD",
        "conflict_schedule_boundary": "DERIVED_ONLY_FROM_REQUIREMENT_TO_FIELD_OVERLAP_AMPLITUDE_AND_ORIGINAL_POSITION",
        "falsifiers": list(config["falsifiers"]),
        "mechanism_digest": sha256_bytes(canonical_json({
            key: value for key, value in config.items()
            if key not in {"pilot_seeds", "training_seeds", "validation_seeds", "heldout_seeds", "seeds"}
        })),
    }
