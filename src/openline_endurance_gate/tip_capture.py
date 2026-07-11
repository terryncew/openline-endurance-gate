from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from .statistics import bootstrap_interval, paired_effect
from .util import clamp, mean, median, safe_log, stable_uniform
from .world import DEPENDENCY_EDGES, REQUIREMENTS

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
SEVERITY_BASE = {"low": 0.045, "medium": 0.095, "high": 0.165}
EVENT_TYPES = (
    "failed_assumption",
    "unresolved_tool_result",
    "retry_dependency",
    "temporary_workaround",
    "memory_mutation",
    "handoff_ambiguity",
)

TIP_CYCLE_FIELDS = [
    "condition", "policy", "seed", "cycle", "event_id", "event_type", "severity", "target",
    "attached_to_existing", "selected_parent_id", "selected_parent_depth", "selected_parent_is_tip",
    "selected_parent_capture_window", "selected_parent_branch_share", "top_decile_capture",
    "top_decile_expected_share", "new_node_id", "root_id", "new_node_depth", "violation",
    "system_failure", "first_failure_this_cycle", "active_unresolved", "active_tips", "branch_count",
    "largest_branch_share", "branch_hhi", "mean_burial_depth", "max_burial_depth", "interior_count",
    "mean_interior_shielded_cycles", "retry_count", "context_length", "repair_attempted",
    "repair_target_id", "repair_target_depth", "repair_target_was_tip", "repair_success",
    "repair_policy_budget_used", "receipt_enabled", "visible_pointer_losses",
]

TIP_RUN_FIELDS = [
    "condition", "policy", "seed", "cycles", "violations", "first_failure_cycle", "n_f",
    "final_active_unresolved", "final_active_tips", "max_active_unresolved", "max_burial_depth",
    "mean_top_decile_capture", "mean_top_decile_expected_share", "frontier_capture_lift",
    "largest_branch_share", "branch_hhi", "repair_attempts", "repair_successes", "repair_budget_used",
    "recovery_probes", "recovery_successes", "recovery_rate", "mean_recovery_cost",
    "mean_recovery_depth", "mean_interior_shielded_cycles", "receipt_enabled",
]

TIP_CANDIDATE_FIELDS = [
    "condition", "seed", "cycle", "event_id", "node_id", "label", "event_count", "context_length",
    "unresolved_count", "retry_count", "node_age", "branch_age", "is_tip", "depth",
    "capture_count_window", "branch_capture_share", "child_count", "shielded_cycles", "branch_size",
]

TIP_PROBE_FIELDS = [
    "condition", "policy", "seed", "cycle", "tip_id", "tip_depth", "receipt_used", "success",
    "recovery_cost", "failure_reason",
]

BASELINE_FEATURES = [
    "event_count", "context_length", "unresolved_count", "retry_count", "node_age", "branch_age",
]
GEOMETRY_FEATURES = BASELINE_FEATURES + [
    "is_tip", "depth", "capture_count_window", "branch_capture_share", "child_count",
    "shielded_cycles", "branch_size",
]


@dataclass(frozen=True)
class TipPacket:
    event_id: str
    event_type: str
    severity: str
    target: str
    token_cost: int
    shock: float


@dataclass
class IssueNode:
    node_id: str
    root_id: str
    parent_id: str | None
    receipt_parent_id: str | None
    visible_parent_id: str | None
    dependency_edge: str
    event_type: str
    target: str
    created_cycle: int
    last_touched_cycle: int
    depth: int
    defect_strength: float
    active: bool = True
    repaired_cycle: int | None = None
    direct_captures: int = 0
    capture_cycles: list[int] = field(default_factory=list)
    children: set[str] = field(default_factory=set)


@dataclass
class TipState:
    nodes: dict[str, IssueNode] = field(default_factory=dict)
    active: set[str] = field(default_factory=set)
    violations: int = 0
    retries: int = 0
    context_length: int = 0
    first_failure_cycle: int | None = None
    repair_attempts: int = 0
    repair_successes: int = 0
    repair_budget_used: int = 0
    visible_pointer_losses: int = 0


def generate_tip_packets(seed: int, cycles: int) -> list[TipPacket]:
    severities = ["low", "medium", "high"] * ((cycles + 2) // 3)
    severities = severities[:cycles]
    # Deterministic Fisher-Yates using stable draws, so every policy and condition gets the same packet multiset.
    for index in range(len(severities) - 1, 0, -1):
        swap = int(stable_uniform("tip-severity-shuffle", seed, index) * (index + 1))
        severities[index], severities[swap] = severities[swap], severities[index]
    packets: list[TipPacket] = []
    for cycle, severity in enumerate(severities, start=1):
        event_type = EVENT_TYPES[int(stable_uniform("tip-event-type", seed, cycle) * len(EVENT_TYPES)) % len(EVENT_TYPES)]
        target = REQUIREMENTS[int(stable_uniform("tip-target", seed, cycle) * len(REQUIREMENTS)) % len(REQUIREMENTS)]
        token_cost = 18 + 7 * (SEVERITY_RANK[severity] + 1) + int(8 * stable_uniform("tip-token", seed, cycle))
        shock = 0.02 + 0.11 * stable_uniform("tip-shock", seed, cycle)
        packets.append(TipPacket(f"tc-{seed}-{cycle:03d}", event_type, severity, target, token_cost, shock))
    return packets


def _active_children(state: TipState, node: IssueNode) -> list[str]:
    return sorted(child for child in node.children if child in state.active)


def _is_tip(state: TipState, node: IssueNode) -> bool:
    return node.active and not _active_children(state, node)


def _active_tips(state: TipState) -> list[IssueNode]:
    return [state.nodes[node_id] for node_id in sorted(state.active) if _is_tip(state, state.nodes[node_id])]


def _branch_nodes(state: TipState) -> dict[str, list[IssueNode]]:
    result: dict[str, list[IssueNode]] = defaultdict(list)
    for node_id in state.active:
        node = state.nodes[node_id]
        result[node.root_id].append(node)
    return result


def _capture_count(node: IssueNode, cycle: int, window: int) -> int:
    floor = cycle - window
    return sum(capture > floor for capture in node.capture_cycles)


def _branch_capture_share(state: TipState, node: IssueNode, cycle: int, window: int) -> float:
    branch_counts: dict[str, int] = defaultdict(int)
    total = 0
    for candidate_id in state.active:
        candidate = state.nodes[candidate_id]
        count = _capture_count(candidate, cycle, window)
        branch_counts[candidate.root_id] += count
        total += count
    return branch_counts[node.root_id] / total if total else 0.0


def _exposure_rank(state: TipState, cycle: int, window: int) -> list[IssueNode]:
    # Observable, lexicographic heuristic. It is deliberately not the diffusive attachment algorithm.
    return sorted(
        (state.nodes[node_id] for node_id in state.active),
        key=lambda node: (
            int(_is_tip(state, node)),
            _capture_count(node, cycle, window),
            node.last_touched_cycle,
            node.depth,
            node.node_id,
        ),
        reverse=True,
    )


def _choose_uniform(nodes: list[IssueNode], draw: float) -> IssueNode:
    return nodes[min(len(nodes) - 1, int(draw * len(nodes)))]


def _choose_parent(state: TipState, packet: TipPacket, condition: str, seed: int, cycle: int, config: dict[str, Any]) -> IssueNode | None:
    if not state.active:
        return None
    if stable_uniform("tip-root-injection", seed, packet.event_id) < float(config["root_injection_probability"]):
        return None
    active = [state.nodes[node_id] for node_id in sorted(state.active)]
    draw = stable_uniform("tip-attachment", seed, packet.event_id)
    if condition == "uniform_null":
        return _choose_uniform(active, draw)
    if condition == "even_spread":
        branches = _branch_nodes(state)
        min_size = min(len(nodes) for nodes in branches.values())
        roots = sorted(root for root, nodes in branches.items() if len(nodes) == min_size)
        root = roots[min(len(roots) - 1, int(draw * len(roots)))]
        candidates = sorted(
            branches[root],
            key=lambda node: (node.direct_captures, node.last_touched_cycle, node.depth, node.node_id),
        )
        return candidates[0]
    if condition == "diffusive_tip_capture":
        tips = _active_tips(state)
        selected = _choose_uniform(tips, draw)
        step = 0
        penetration = float(config["penetration_probability"])
        while selected.parent_id in state.active:
            if stable_uniform("tip-penetration", seed, packet.event_id, step) >= penetration:
                break
            selected = state.nodes[str(selected.parent_id)]
            step += 1
        return selected
    raise ValueError(f"unknown attachment condition: {condition}")


def _candidate_row(state: TipState, node: IssueNode, condition: str, seed: int, cycle: int, packet: TipPacket, selected: bool, window: int) -> dict[str, Any]:
    branches = _branch_nodes(state)
    root = state.nodes[node.root_id]
    return {
        "condition": condition,
        "seed": seed,
        "cycle": cycle,
        "event_id": packet.event_id,
        "node_id": node.node_id,
        "label": int(selected),
        "event_count": cycle - 1,
        "context_length": state.context_length,
        "unresolved_count": len(state.active),
        "retry_count": state.retries,
        "node_age": cycle - node.created_cycle,
        "branch_age": cycle - root.created_cycle,
        "is_tip": int(_is_tip(state, node)),
        "depth": node.depth,
        "capture_count_window": _capture_count(node, cycle, window),
        "branch_capture_share": round(_branch_capture_share(state, node, cycle, window), 10),
        "child_count": len(_active_children(state, node)),
        "shielded_cycles": cycle - node.last_touched_cycle,
        "branch_size": len(branches[node.root_id]),
    }


def _sample_candidate_rows(state: TipState, selected: IssueNode, condition: str, seed: int, cycle: int, packet: TipPacket, config: dict[str, Any]) -> list[dict[str, Any]]:
    window = int(config["capture_window_cycles"])
    negatives = [state.nodes[node_id] for node_id in state.active if node_id != selected.node_id]
    negatives.sort(key=lambda node: stable_uniform("tip-negative-sample", seed, packet.event_id, node.node_id))
    negatives = negatives[: int(config["negative_candidates_per_event"])]
    return [_candidate_row(state, selected, condition, seed, cycle, packet, True, window)] + [
        _candidate_row(state, node, condition, seed, cycle, packet, False, window) for node in negatives
    ]


def _pointer_decay(state: TipState, seed: int, condition: str, cycle: int, config: dict[str, Any]) -> int:
    losses = 0
    pressure = min(1.0, state.context_length / max(1.0, float(config["context_pressure_scale"])))
    for node_id in sorted(state.active):
        node = state.nodes[node_id]
        if node.visible_parent_id is None:
            continue
        probability = (
            float(config["visible_pointer_loss_base"])
            + float(config["visible_pointer_loss_depth_scale"]) * node.depth
            + float(config["visible_pointer_loss_pressure_scale"]) * pressure
        )
        if stable_uniform("tip-pointer-loss", seed, condition, node.node_id, cycle) < probability:
            node.visible_parent_id = None
            losses += 1
    state.visible_pointer_losses += losses
    return losses


def _repair_target(state: TipState, policy: str, seed: int, condition: str, cycle: int, config: dict[str, Any]) -> IssueNode | None:
    if not state.active or policy in {"no_intervention", "logging_only"}:
        return None
    active = [state.nodes[node_id] for node_id in sorted(state.active)]
    if policy == "random_repair":
        return _choose_uniform(active, stable_uniform("tip-random-repair", seed, condition, cycle))
    if policy == "oldest_first":
        return min(active, key=lambda node: (node.created_cycle, node.node_id))
    if policy == "tip_targeted":
        return _exposure_rank(state, cycle, int(config["capture_window_cycles"]))[0]
    raise ValueError(f"unknown repair policy: {policy}")


def _repair(state: TipState, target: IssueNode, seed: int, condition: str, cycle: int, config: dict[str, Any]) -> bool:
    state.repair_attempts += 1
    state.repair_budget_used += 1
    success_probability = clamp(
        float(config["repair_success_base"]) - float(config["repair_depth_penalty"]) * target.depth,
        0.25,
        0.97,
    )
    success = stable_uniform("tip-repair-success", seed, condition, cycle, target.node_id) < success_probability
    if not success:
        return False
    target.active = False
    target.repaired_cycle = cycle
    state.active.discard(target.node_id)
    state.repair_successes += 1
    # Interior repair can reduce inherited defect even when descendants remain. This gives oldest/root repair a real path to win.
    for child_id in _active_children(state, target):
        child = state.nodes[child_id]
        child.defect_strength *= float(config["interior_repair_defect_multiplier"])
    return True


def _recovery_probe(state: TipState, seed: int, condition: str, policy: str, cycle: int, receipt_enabled: bool, config: dict[str, Any]) -> dict[str, Any] | None:
    tips = _active_tips(state)
    if not tips:
        return None
    tip = max(tips, key=lambda node: (node.depth, node.direct_captures, node.node_id))
    current = tip
    cost = 1
    max_steps = int(config["recovery_budget_steps"])
    failure_reason: str | None = None
    success = False
    while cost <= max_steps:
        if current.parent_id is None:
            success = True
            break
        if receipt_enabled:
            if stable_uniform("tip-receipt-reference", seed, condition, policy, cycle, current.node_id) < float(config["receipt_reference_error"]):
                failure_reason = "receipt_reference_unavailable"
                break
            parent_id = current.receipt_parent_id
        else:
            parent_id = current.visible_parent_id
            if parent_id is None:
                failure_reason = "visible_parent_lost"
                break
        if parent_id is None or parent_id not in state.nodes:
            failure_reason = "parent_missing"
            break
        current = state.nodes[parent_id]
        cost += 1
    if not success and failure_reason is None:
        failure_reason = "recovery_budget_exhausted"
    return {
        "condition": condition,
        "policy": policy,
        "seed": seed,
        "cycle": cycle,
        "tip_id": tip.node_id,
        "tip_depth": tip.depth,
        "receipt_used": int(receipt_enabled),
        "success": int(success),
        "recovery_cost": cost,
        "failure_reason": failure_reason,
    }


def _graph_metrics(state: TipState, cycle: int) -> dict[str, Any]:
    branches = _branch_nodes(state)
    total = max(1, len(state.active))
    shares = [len(nodes) / total for nodes in branches.values()]
    interiors = [state.nodes[node_id] for node_id in state.active if _active_children(state, state.nodes[node_id])]
    depths = [state.nodes[node_id].depth for node_id in state.active]
    return {
        "active_tips": len(_active_tips(state)),
        "branch_count": len(branches),
        "largest_branch_share": max(shares) if shares else 0.0,
        "branch_hhi": sum(share * share for share in shares),
        "mean_burial_depth": mean(depths) if depths else 0.0,
        "max_burial_depth": max(depths) if depths else 0,
        "interior_count": len(interiors),
        "mean_interior_shielded_cycles": mean(cycle - node.last_touched_cycle for node in interiors) if interiors else 0.0,
    }


def run_tip_capture_one(condition: str, policy: str, seed: int, packets: list[TipPacket], config: dict[str, Any], collect_candidates: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = TipState()
    cycles: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    top_hits: list[int] = []
    top_expected: list[float] = []
    max_active = 0
    max_depth = 0
    receipt_enabled = policy != "no_intervention"
    window = int(config["capture_window_cycles"])
    dependency_edges = sorted(DEPENDENCY_EDGES)

    for cycle, packet in enumerate(packets, start=1):
        parent = _choose_parent(state, packet, condition, seed, cycle, config)
        attached = parent is not None
        top_hit = 0
        expected_share = 0.0
        parent_depth = -1
        parent_is_tip = 0
        parent_window = 0
        parent_branch_share = 0.0
        if parent is not None:
            ranked = _exposure_rank(state, cycle, window)
            top_n = max(1, math.ceil(0.10 * len(ranked)))
            top_ids = {node.node_id for node in ranked[:top_n]}
            top_hit = int(parent.node_id in top_ids)
            expected_share = top_n / len(ranked)
            top_hits.append(top_hit)
            top_expected.append(expected_share)
            if collect_candidates:
                candidates.extend(_sample_candidate_rows(state, parent, condition, seed, cycle, packet, config))
            parent_depth = parent.depth
            parent_is_tip = int(_is_tip(state, parent))
            parent_window = _capture_count(parent, cycle, window)
            parent_branch_share = _branch_capture_share(state, parent, cycle, window)
            parent.direct_captures += 1
            parent.capture_cycles.append(cycle)
            parent.last_touched_cycle = cycle

        node_id = f"{condition[:2]}-{seed}-{cycle:03d}"
        if parent is None:
            root_id = node_id
            depth = 0
            inherited = 0.0
        else:
            root_id = parent.root_id
            depth = parent.depth + 1
            inherited = float(config["defect_inheritance"]) * parent.defect_strength
        defect = clamp(SEVERITY_BASE[packet.severity] + packet.shock + inherited, 0.0, 1.5)
        edge = dependency_edges[int(stable_uniform("tip-dependency-edge", seed, packet.event_id) * len(dependency_edges)) % len(dependency_edges)]
        node = IssueNode(
            node_id=node_id,
            root_id=root_id,
            parent_id=parent.node_id if parent else None,
            receipt_parent_id=parent.node_id if parent else None,
            visible_parent_id=parent.node_id if parent else None,
            dependency_edge=edge,
            event_type=packet.event_type,
            target=packet.target,
            created_cycle=cycle,
            last_touched_cycle=cycle,
            depth=depth,
            defect_strength=defect,
        )
        state.nodes[node_id] = node
        state.active.add(node_id)
        if parent is not None:
            parent.children.add(node_id)

        state.context_length += packet.token_cost
        active_before_violation = len(state.active)
        branch_recent = 0 if parent is None else _capture_count(parent, cycle, window)
        violation_probability = clamp(
            SEVERITY_BASE[packet.severity]
            + float(config["defect_violation_scale"]) * defect
            + float(config["active_burden_violation_scale"]) * min(active_before_violation, 18)
            + float(config["branch_recurrence_violation_scale"]) * min(branch_recent, 5),
            0.01,
            0.88,
        )
        violation = stable_uniform("tip-violation", seed, packet.event_id) < violation_probability
        if violation:
            state.violations += 1
            state.retries += 1
        failure = bool(violation and (defect >= float(config["failure_defect_threshold"]) or active_before_violation >= int(config["failure_active_threshold"])))
        first_failure_now = failure and state.first_failure_cycle is None
        if first_failure_now:
            state.first_failure_cycle = cycle

        losses = _pointer_decay(state, seed, condition, cycle, config)

        repair_attempted = 0
        repair_target_id: str | None = None
        repair_target_depth = -1
        repair_target_was_tip = 0
        repair_success = 0
        if cycle % int(config["repair_every_cycles"]) == 0:
            target = _repair_target(state, policy, seed, condition, cycle, config)
            if target is not None:
                repair_attempted = 1
                repair_target_id = target.node_id
                repair_target_depth = target.depth
                repair_target_was_tip = int(_is_tip(state, target))
                repair_success = int(_repair(state, target, seed, condition, cycle, config))

        if cycle % int(config["recovery_probe_every_cycles"]) == 0:
            probe = _recovery_probe(state, seed, condition, policy, cycle, receipt_enabled, config)
            if probe is not None:
                probes.append(probe)

        metrics = _graph_metrics(state, cycle)
        max_active = max(max_active, len(state.active))
        max_depth = max(max_depth, int(metrics["max_burial_depth"]))
        cycles.append({
            "condition": condition,
            "policy": policy,
            "seed": seed,
            "cycle": cycle,
            "event_id": packet.event_id,
            "event_type": packet.event_type,
            "severity": packet.severity,
            "target": packet.target,
            "attached_to_existing": int(attached),
            "selected_parent_id": parent.node_id if parent else None,
            "selected_parent_depth": parent_depth,
            "selected_parent_is_tip": parent_is_tip,
            "selected_parent_capture_window": parent_window,
            "selected_parent_branch_share": round(parent_branch_share, 10),
            "top_decile_capture": top_hit,
            "top_decile_expected_share": round(expected_share, 10),
            "new_node_id": node_id,
            "root_id": root_id,
            "new_node_depth": depth,
            "violation": int(violation),
            "system_failure": int(failure),
            "first_failure_this_cycle": int(first_failure_now),
            "active_unresolved": len(state.active),
            "active_tips": metrics["active_tips"],
            "branch_count": metrics["branch_count"],
            "largest_branch_share": round(metrics["largest_branch_share"], 10),
            "branch_hhi": round(metrics["branch_hhi"], 10),
            "mean_burial_depth": round(metrics["mean_burial_depth"], 10),
            "max_burial_depth": metrics["max_burial_depth"],
            "interior_count": metrics["interior_count"],
            "mean_interior_shielded_cycles": round(metrics["mean_interior_shielded_cycles"], 10),
            "retry_count": state.retries,
            "context_length": state.context_length,
            "repair_attempted": repair_attempted,
            "repair_target_id": repair_target_id,
            "repair_target_depth": repair_target_depth,
            "repair_target_was_tip": repair_target_was_tip,
            "repair_success": repair_success,
            "repair_policy_budget_used": state.repair_budget_used,
            "receipt_enabled": int(receipt_enabled),
            "visible_pointer_losses": losses,
        })

    successful_probes = [probe for probe in probes if int(probe["success"])]
    final_metrics = _graph_metrics(state, len(packets))
    run = {
        "condition": condition,
        "policy": policy,
        "seed": seed,
        "cycles": len(packets),
        "violations": state.violations,
        "first_failure_cycle": state.first_failure_cycle,
        "n_f": state.first_failure_cycle if state.first_failure_cycle is not None else len(packets) + 1,
        "final_active_unresolved": len(state.active),
        "final_active_tips": final_metrics["active_tips"],
        "max_active_unresolved": max_active,
        "max_burial_depth": max_depth,
        "mean_top_decile_capture": mean(top_hits) if top_hits else None,
        "mean_top_decile_expected_share": mean(top_expected) if top_expected else None,
        "frontier_capture_lift": mean(top_hits) - mean(top_expected) if top_hits else None,
        "largest_branch_share": final_metrics["largest_branch_share"],
        "branch_hhi": final_metrics["branch_hhi"],
        "repair_attempts": state.repair_attempts,
        "repair_successes": state.repair_successes,
        "repair_budget_used": state.repair_budget_used,
        "recovery_probes": len(probes),
        "recovery_successes": len(successful_probes),
        "recovery_rate": len(successful_probes) / len(probes) if probes else None,
        "mean_recovery_cost": mean(float(probe["recovery_cost"]) for probe in successful_probes) if successful_probes else None,
        "mean_recovery_depth": mean(float(probe["tip_depth"]) for probe in probes) if probes else None,
        "mean_interior_shielded_cycles": final_metrics["mean_interior_shielded_cycles"],
        "receipt_enabled": int(receipt_enabled),
    }
    return cycles, run, candidates, probes


def simulate_tip_capture(experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    config = experiment["tip_capture"]
    cycles: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    for seed in map(int, config["seeds"]):
        packets = generate_tip_packets(seed, int(config["cycles"]))
        for condition in config["attachment_conditions"]:
            for policy in config["repair_policies"]:
                collect = policy == "logging_only"
                cycle_rows, run, candidate_rows, probe_rows = run_tip_capture_one(
                    condition, policy, seed, packets, config, collect_candidates=collect
                )
                cycles.extend(cycle_rows)
                runs.append(run)
                candidates.extend(candidate_rows)
                probes.extend(probe_rows)
    return cycles, runs, candidates, probes


def _standardize(rows: list[dict[str, Any]], features: list[str], stats: dict[str, list[float]] | None = None) -> tuple[list[list[float]], dict[str, list[float]]]:
    if stats is None:
        stats = {}
        for feature in features:
            values = [float(row[feature]) for row in rows]
            mu = mean(values)
            variance = mean((value - mu) ** 2 for value in values)
            stats[feature] = [mu, math.sqrt(max(variance, 1e-12))]
    matrix = [[1.0] + [(float(row[feature]) - stats[feature][0]) / stats[feature][1] for feature in features] for row in rows]
    return matrix, stats


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _fit_logistic(rows: list[dict[str, Any]], features: list[str], l2: float, epochs: int) -> dict[str, Any]:
    x, stats = _standardize(rows, features)
    y = [int(row["label"]) for row in rows]
    prevalence = clamp(mean(y), 1e-5, 1 - 1e-5)
    weights = [math.log(prevalence / (1 - prevalence))] + [0.0] * len(features)
    n = max(1, len(rows))
    for epoch in range(epochs):
        gradient = [0.0] * len(weights)
        for vector, target in zip(x, y):
            prediction = _sigmoid(sum(weight * value for weight, value in zip(weights, vector)))
            error = prediction - target
            for index, value in enumerate(vector):
                gradient[index] += error * value
        rate = 0.35 / math.sqrt(epoch + 1.0)
        weights[0] -= rate * gradient[0] / n
        for index in range(1, len(weights)):
            weights[index] -= rate * (gradient[index] / n + l2 * weights[index])
    return {"features": features, "weights": weights, "stats": stats, "l2": l2, "epochs": epochs, "solver": "deterministic_full_batch_gradient"}


def _predict(model: dict[str, Any], rows: list[dict[str, Any]]) -> list[float]:
    matrix, _ = _standardize(rows, list(model["features"]), model["stats"])
    return [_sigmoid(sum(weight * value for weight, value in zip(model["weights"], vector))) for vector in matrix]


def _fast_auc(labels: list[int], predictions: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(predictions, labels), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    rank = 1
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (rank + (rank + end - index - 1)) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        rank += end - index
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _metrics(rows: list[dict[str, Any]], predictions: list[float]) -> dict[str, Any]:
    labels = [int(row["label"]) for row in rows]
    return {
        "row_count": len(rows),
        "positive_count": sum(labels),
        "log_loss": -mean(label * safe_log(prediction) + (1 - label) * safe_log(1 - prediction) for label, prediction in zip(labels, predictions)),
        "brier": mean((prediction - label) ** 2 for label, prediction in zip(labels, predictions)),
        "auc": _fast_auc(labels, predictions),
    }


def _per_seed_logloss(rows: list[dict[str, Any]], baseline_predictions: list[float], geometry_predictions: list[float]) -> list[float]:
    grouped: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for row, base, geom in zip(rows, baseline_predictions, geometry_predictions):
        grouped[int(row["seed"])].append((int(row["label"]), base, geom))
    gains: list[float] = []
    for seed in sorted(grouped):
        values = grouped[seed]
        base_loss = -mean(label * safe_log(base) + (1 - label) * safe_log(1 - base) for label, base, _ in values)
        geom_loss = -mean(label * safe_log(geom) + (1 - label) * safe_log(1 - geom) for label, _, geom in values)
        gains.append(base_loss - geom_loss)
    return gains


def geometry_lift(candidates: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["tip_capture"]
    train = set(map(int, config["training_seeds"]))
    validation = set(map(int, config["validation_seeds"]))
    heldout = set(map(int, config["heldout_seeds"]))
    result: dict[str, Any] = {}
    for condition in config["attachment_conditions"]:
        condition_rows = [row for row in candidates if row["condition"] == condition]
        train_rows = [row for row in condition_rows if int(row["seed"]) in train]
        validation_rows = [row for row in condition_rows if int(row["seed"]) in validation]
        fit_rows = [row for row in condition_rows if int(row["seed"]) in train | validation]
        test_rows = [row for row in condition_rows if int(row["seed"]) in heldout]
        l2 = float(config["geometry_model_l2"])
        epochs = int(config["geometry_model_epochs"])
        train_baseline = _fit_logistic(train_rows, BASELINE_FEATURES, l2, epochs)
        train_geometry = _fit_logistic(train_rows, GEOMETRY_FEATURES, l2, epochs)
        validation_baseline_metrics = _metrics(validation_rows, _predict(train_baseline, validation_rows))
        validation_geometry_metrics = _metrics(validation_rows, _predict(train_geometry, validation_rows))
        baseline = _fit_logistic(fit_rows, BASELINE_FEATURES, l2, epochs)
        geometry = _fit_logistic(fit_rows, GEOMETRY_FEATURES, l2, epochs)
        baseline_predictions = _predict(baseline, test_rows)
        geometry_predictions = _predict(geometry, test_rows)
        baseline_metrics = _metrics(test_rows, baseline_predictions)
        geometry_metrics = _metrics(test_rows, geometry_predictions)
        seed_gains = _per_seed_logloss(test_rows, baseline_predictions, geometry_predictions)
        result[condition] = {
            "baseline": baseline_metrics,
            "geometry": geometry_metrics,
            "heldout_logloss_gain": baseline_metrics["log_loss"] - geometry_metrics["log_loss"],
            "heldout_auc_gain": (geometry_metrics["auc"] - baseline_metrics["auc"]) if geometry_metrics["auc"] is not None and baseline_metrics["auc"] is not None else None,
            "per_seed_logloss_gains": seed_gains,
            "mean_seed_logloss_gain": mean(seed_gains),
            "seed_gain_confidence_interval": bootstrap_interval(
                seed_gains,
                mean,
                float(config["analysis_plan"]["confidence_level"]),
                int(config["analysis_plan"]["bootstrap_resamples"]),
                f"geometry-{condition}",
            ),
            "validation_baseline": validation_baseline_metrics,
            "validation_geometry": validation_geometry_metrics,
            "baseline_model": baseline,
            "geometry_model": geometry,
            "fit_seed_count": len(train | validation),
            "heldout_seed_count": len(heldout),
        }
    return result


def _runs_by_key(runs: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    return {(str(row["condition"]), str(row["policy"]), int(row["seed"])): row for row in runs}


def _paired_policy_values(runs: list[dict[str, Any]], condition: str, left: str, right: str, heldout: set[int], field: str) -> list[float]:
    mapping = _runs_by_key(runs)
    values: list[float] = []
    for seed in sorted(heldout):
        left_row = mapping[(condition, left, seed)]
        right_row = mapping[(condition, right, seed)]
        values.append(float(left_row[field]) - float(right_row[field]))
    return values


def _spearman(xs: Iterable[float], ys: Iterable[float]) -> float | None:
    x = list(map(float, xs))
    y = list(map(float, ys))
    if len(x) < 3 or len(x) != len(y):
        return None
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        result = [0.0] * len(values)
        index = 0
        while index < len(order):
            end = index + 1
            while end < len(order) and values[order[end]] == values[order[index]]:
                end += 1
            rank_value = (index + 1 + end) / 2.0
            for position in range(index, end):
                result[order[position]] = rank_value
            index = end
        return result
    rx = ranks(x)
    ry = ranks(y)
    mx, my = mean(rx), mean(ry)
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return numerator / denominator if denominator else None




def _report_effect_units(
    effect: dict[str, Any],
    *,
    unit: str,
    positive_direction: str,
    negative_direction: str,
) -> dict[str, Any]:
    """Return an honestly labeled reporting view of a paired effect.

    ``paired_effect`` is shared with cycle-to-failure analysis and therefore
    uses historical ``*_cycles`` field names. Tip-capture effects have other
    units (repair yield, violation count, or recovery-rate points). This
    adapter changes labels only; it does not alter values, tests, thresholds,
    or gate decisions.
    """
    result = dict(effect)
    result["median_difference"] = result.pop("median_difference_cycles")
    result["mean_difference"] = result.pop("mean_difference_cycles")
    result["effect_unit"] = unit
    result["positive_direction"] = positive_direction
    result["negative_direction"] = negative_direction
    positive = int(result["positive_count"])
    negative = int(result["negative_count"])
    nonzero = int(result["nonzero_pair_count"])
    total = int(result["paired_difference_count"])
    if positive > negative:
        majority = positive_direction
    elif negative > positive:
        majority = negative_direction
    else:
        majority = "no_nonzero_majority"
    result["majority_direction"] = majority
    result["positive_direction_consistency"] = positive / nonzero if nonzero else 0.0
    result["majority_direction_consistency"] = max(positive, negative) / nonzero if nonzero else 0.0
    result["positive_direction_rate_all_pairs"] = positive / total if total else 0.0
    result.pop("directional_consistency", None)
    return result

def analyze_tip_capture(cycles: list[dict[str, Any]], runs: list[dict[str, Any]], candidates: list[dict[str, Any]], probes: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["tip_capture"]
    heldout = set(map(int, config["heldout_seeds"]))
    thresholds = config["theory_thresholds"]
    analysis = config["analysis_plan"]
    heldout_runs = [row for row in runs if int(row["seed"]) in heldout]
    logging_runs = [row for row in heldout_runs if row["policy"] == "logging_only"]

    capture_by_condition: dict[str, Any] = {}
    for condition in config["attachment_conditions"]:
        rows = [row for row in logging_runs if row["condition"] == condition]
        observed = mean(float(row["mean_top_decile_capture"]) for row in rows if row["mean_top_decile_capture"] is not None)
        expected = mean(float(row["mean_top_decile_expected_share"]) for row in rows if row["mean_top_decile_expected_share"] is not None)
        attachment_rows = [
            row for row in cycles
            if int(row["seed"]) in heldout
            and row["policy"] == "logging_only"
            and row["condition"] == condition
            and int(row["attached_to_existing"])
        ]
        selected_tip_rate = (
            mean(float(row["selected_parent_is_tip"]) for row in attachment_rows)
            if attachment_rows else None
        )
        capture_by_condition[condition] = {
            "run_count": len(rows),
            "observed_top_decile_capture": observed,
            "expected_random_share": expected,
            "frontier_capture_lift": observed - expected,
            "selected_parent_observation_count": len(attachment_rows),
            "selected_parent_tip_rate": selected_tip_rate,
            "mean_largest_branch_share": mean(float(row["largest_branch_share"]) for row in rows),
            "mean_branch_hhi": mean(float(row["branch_hhi"]) for row in rows),
            "median_max_burial_depth": median(float(row["max_burial_depth"]) for row in rows),
            "mean_interior_shielded_cycles": mean(float(row["mean_interior_shielded_cycles"]) for row in rows),
        }

    geometry = geometry_lift(candidates, experiment)

    diffusive = "diffusive_tip_capture"
    tip_random_yields: list[float] = []
    tip_random_violation_diffs: list[float] = []
    mapping = _runs_by_key(runs)
    for seed in sorted(heldout):
        control = mapping[(diffusive, "logging_only", seed)]
        tip = mapping[(diffusive, "tip_targeted", seed)]
        random_row = mapping[(diffusive, "random_repair", seed)]
        tip_yield = (float(control["violations"]) - float(tip["violations"])) / max(1.0, float(tip["repair_successes"]))
        random_yield = (float(control["violations"]) - float(random_row["violations"])) / max(1.0, float(random_row["repair_successes"]))
        tip_random_yields.append(tip_yield - random_yield)
        tip_random_violation_diffs.append(float(random_row["violations"]) - float(tip["violations"]))
    repair_effect = _report_effect_units(
        paired_effect(
            tip_random_yields,
            float(analysis["confidence_level"]),
            int(analysis["bootstrap_resamples"]),
            "tip-repair-yield",
        ),
        unit="violations_prevented_per_successful_repair",
        positive_direction="tip_targeted_higher_yield_than_random_repair",
        negative_direction="random_repair_higher_yield_than_tip_targeted",
    )
    repair_effect["paired_violation_difference_random_minus_tip"] = _report_effect_units(
        paired_effect(
            tip_random_violation_diffs,
            float(analysis["confidence_level"]),
            int(analysis["bootstrap_resamples"]),
            "tip-repair-violations",
        ),
        unit="violations_random_minus_tip_targeted",
        positive_direction="tip_targeted_fewer_violations_than_random_repair",
        negative_direction="random_repair_fewer_violations_than_tip_targeted",
    )
    repair_effect["comparison"] = "tip-targeted minus random future violations prevented per successful repair, paired within held-out seed under diffusive attachment"

    null_violation_diffs = _paired_policy_values(runs, "uniform_null", "random_repair", "tip_targeted", heldout, "violations")
    null_repair_effect = _report_effect_units(
        paired_effect(
            null_violation_diffs,
            float(analysis["confidence_level"]),
            int(analysis["bootstrap_resamples"]),
            "null-tip-random",
        ),
        unit="violations_random_minus_tip_targeted",
        positive_direction="tip_targeted_fewer_violations_than_random_repair",
        negative_direction="random_repair_fewer_violations_than_tip_targeted",
    )

    recovery_gains: list[float] = []
    dynamics_differences: list[float] = []
    for condition in config["attachment_conditions"]:
        for seed in sorted(heldout):
            raw = mapping[(condition, "no_intervention", seed)]
            logged = mapping[(condition, "logging_only", seed)]
            recovery_gains.append(float(logged["recovery_rate"]) - float(raw["recovery_rate"]))
            dynamics_differences.append(float(logged["violations"]) - float(raw["violations"]))
    recovery_effect = _report_effect_units(
        paired_effect(
            recovery_gains,
            float(analysis["confidence_level"]),
            int(analysis["bootstrap_resamples"]),
            "receipt-recovery",
        ),
        unit="recovery_rate_points_logging_minus_no_intervention",
        positive_direction="receipt_logging_higher_recovery_rate",
        negative_direction="no_intervention_higher_recovery_rate",
    )
    recovery_effect["max_absolute_dynamics_difference"] = max(abs(value) for value in dynamics_differences) if dynamics_differences else None

    heldout_probes = [probe for probe in probes if int(probe["seed"]) in heldout]
    successful = [probe for probe in heldout_probes if int(probe["success"])]
    burial_cost_correlation = _spearman(
        [float(probe["tip_depth"]) for probe in successful],
        [float(probe["recovery_cost"]) for probe in successful],
    )

    diff_capture = capture_by_condition[diffusive]
    null_capture = capture_by_condition["uniform_null"]
    diff_geometry = geometry[diffusive]
    null_geometry = geometry["uniform_null"]
    geometry_ci = diff_geometry["seed_gain_confidence_interval"]
    gates = {
        "frontier_capture_concentration": {
            "passed": bool(
                diff_capture["frontier_capture_lift"] >= float(thresholds["frontier_capture_lift_min"])
                and diff_capture["frontier_capture_lift"] - null_capture["frontier_capture_lift"] >= float(thresholds["frontier_capture_lift_over_null_min"])
            ),
            "observed": {"diffusive": diff_capture, "uniform_null": null_capture},
            "thresholds": {
                "frontier_capture_lift_min": thresholds["frontier_capture_lift_min"],
                "lift_over_null_min": thresholds["frontier_capture_lift_over_null_min"],
            },
        },
        "geometry_adds_heldout_prediction": {
            "passed": bool(
                diff_geometry["heldout_logloss_gain"] >= float(thresholds["geometry_logloss_gain_min"])
                and diff_geometry["heldout_auc_gain"] is not None
                and diff_geometry["heldout_auc_gain"] >= float(thresholds["geometry_auc_gain_min"])
                and geometry_ci[0] is not None
                and float(geometry_ci[0]) > 0.0
            ),
            "observed": diff_geometry,
            "thresholds": {
                "logloss_gain_min": thresholds["geometry_logloss_gain_min"],
                "auc_gain_min": thresholds["geometry_auc_gain_min"],
                "seed_gain_ci_lower_gt": 0.0,
            },
        },
        "null_geometry_specificity": {
            "passed": bool(abs(null_geometry["heldout_logloss_gain"]) <= float(thresholds["null_geometry_logloss_gain_abs_max"])),
            "observed": null_geometry,
            "threshold": thresholds["null_geometry_logloss_gain_abs_max"],
        },
        "tip_targeted_repair_yield": {
            "passed": bool(
                repair_effect["paired_difference_count"] >= int(analysis["minimum_repair_pairs"])
                and repair_effect["median_difference"] >= float(thresholds["repair_yield_gain_min"])
                and repair_effect["exact_sign_flip_p"] <= float(thresholds["repair_p_max"])
            ),
            "observed": repair_effect,
            "null_condition_witness": null_repair_effect,
            "thresholds": {
                "minimum_pairs": analysis["minimum_repair_pairs"],
                "yield_gain_min": thresholds["repair_yield_gain_min"],
                "p_max": thresholds["repair_p_max"],
            },
        },
        "receipt_ancestry_root_recovery": {
            "passed": bool(
                recovery_effect["median_difference"] >= float(thresholds["root_recovery_gain_min"])
                and recovery_effect["max_absolute_dynamics_difference"] <= float(thresholds["logging_dynamics_tolerance"])
            ),
            "observed": recovery_effect,
            "thresholds": {
                "recovery_gain_min": thresholds["root_recovery_gain_min"],
                "logging_dynamics_tolerance": thresholds["logging_dynamics_tolerance"],
            },
        },
    }
    passed = sum(int(gate["passed"]) for gate in gates.values())
    status = "SURVIVES_ALL_PRE_REGISTERED_TIP_CAPTURE_GATES" if passed == len(gates) else "FAILS_ALL_PRE_REGISTERED_TIP_CAPTURE_GATES" if passed == 0 else "MIXED_TIP_CAPTURE_RESULT"
    return {
        "schema": "openline.tip-capture.summary.v2",
        "claim_label": "POWERED_SYNTHETIC_EXECUTION_TIP_CAPTURE",
        "status": status,
        "passed_gate_count": passed,
        "gate_count": len(gates),
        "cycle_observation_count": len(cycles),
        "run_count": len(runs),
        "candidate_observation_count": len(candidates),
        "probe_count": len(probes),
        "heldout_seed_count": len(heldout),
        "capture_by_condition": capture_by_condition,
        "geometry_lift": geometry,
        "repair_effect": repair_effect,
        "null_repair_effect": null_repair_effect,
        "receipt_recovery_effect": recovery_effect,
        "burial_cost_spearman": burial_cost_correlation,
        "diagnostic_witnesses": {
            "burial_depth_recovery_cost_spearman": burial_cost_correlation,
            "boundary": "Descriptive only. Successful parent-pointer traversal mechanically scales with path depth, so this is excluded from gate counting."
        },
        "reporting_disclosures": {
            "even_spread_leaf_bias": {
                "present": True,
                "mechanism": "even_spread selects the least directly captured node inside the smallest active branch; in this graph, low-capture candidates are frequently leaves, so the condition has an unintended tip-selection bias",
                "observed_selected_parent_tip_rate": capture_by_condition["even_spread"]["selected_parent_tip_rate"],
                "comparison_tip_rates": {
                    condition: values["selected_parent_tip_rate"]
                    for condition, values in capture_by_condition.items()
                },
                "gate_status": "descriptive_design_artifact; no gate, seed, threshold, mechanism, or result was changed in v0.3.1",
            },
            "direction_reporting": "majority_direction and positive_direction_consistency are reported separately; ties remain in zero_count and are excluded from consistency denominators",
        },
        "gates": gates,
        "claim_boundary": "This is a seeded mechanism-recovery test. The diffusive condition deliberately contains a stochastic tip-capture process; success shows the instrumentation can detect and exploit that process while the null condition checks specificity. It does not establish that deployed agents follow DLA or any physical fracture law.",
    }


def tip_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    config = experiment["tip_capture"]
    seed = int(config["heldout_seeds"][0])
    packets = generate_tip_packets(seed, int(config["cycles"]))
    no_cycles, no_run, _, _ = run_tip_capture_one("uniform_null", "no_intervention", seed, packets, config, False)
    log_cycles, log_run, _, _ = run_tip_capture_one("uniform_null", "logging_only", seed, packets, config, False)
    dynamic_fields = [
        "cycle", "event_id", "selected_parent_id", "new_node_id", "root_id", "new_node_depth", "violation",
        "system_failure", "active_unresolved", "active_tips", "branch_count", "largest_branch_share", "branch_hhi",
        "mean_burial_depth", "max_burial_depth", "retry_count", "context_length",
    ]
    dynamics_match = all(
        {field: left[field] for field in dynamic_fields} == {field: right[field] for field in dynamic_fields}
        for left, right in zip(no_cycles, log_cycles)
    )
    return {
        "schema": "openline.tip-capture.design-witness.v1",
        "seed_count_declared_before_run": len(config["seeds"]),
        "heldout_seed_count": len(config["heldout_seeds"]),
        "minimum_repair_pairs": config["analysis_plan"]["minimum_repair_pairs"],
        "matched_packets_across_conditions_and_policies": True,
        "logging_only_dynamics_match_no_intervention": dynamics_match and no_run["violations"] == log_run["violations"],
        "null_attachment_condition": "uniform_null",
        "diffusive_attachment_is_stochastic": 0.0 < float(config["penetration_probability"]) < 1.0,
        "exposure_rank_is_not_attachment_function": True,
        "repair_budget_interval_cycles": config["repair_every_cycles"],
        "candidate_model_policy": "logging_only_only_to_avoid_intervention_confound",
    }
