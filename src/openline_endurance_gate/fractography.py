from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any

from .util import mean, median


FRACTOGRAPHY_FIELDS = [
    "run_family", "mode", "schedule", "seed", "crack_initiation_cycle", "origin_event_id",
    "origin_target", "origin_amplitude", "peak_cycle", "max_crack_load", "crack_burden",
    "longest_active_span", "repair_half_life_cycles", "first_failure_cycle",
    "cycles_from_crack_to_failure", "dominant_nodes",
]


def _split_nodes(value: Any) -> list[str]:
    if value is None:
        return []
    return [part for part in str(value).split("|") if part]


def _components(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    seen: set[str] = set()
    result: list[set[str]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        component: set[str] = set()
        queue = deque([start])
        seen.add(start)
        while queue:
            node = queue.popleft()
            component.add(node)
            for neighbor in adjacency.get(node, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        result.append(component)
    return result


def analyze_fractography(cycles: list[dict[str, Any]], experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in cycles:
        groups[(str(row["run_family"]), str(row["mode"]), str(row["schedule"]), int(row["seed"]))].append(row)

    run_rows: list[dict[str, Any]] = []
    global_node_counts: Counter[str] = Counter()
    global_edges: set[tuple[str, str]] = set()
    for key, rows in sorted(groups.items()):
        ordered = sorted(rows, key=lambda row: int(row["cycle"]))
        prior_contradictions = 0
        loads: list[int] = []
        node_counts: Counter[str] = Counter()
        active_spans: list[int] = []
        current_span = 0
        for row in ordered:
            contradiction_delta = max(0, int(row["contradiction_count"]) - prior_contradictions)
            prior_contradictions = int(row["contradiction_count"])
            unresolved = _split_nodes(row.get("unresolved_dependencies"))
            invariants = _split_nodes(row.get("invariant_failures"))
            nodes = [f"dependency:{node}" for node in unresolved] + [f"invariant:{node}" for node in invariants]
            if contradiction_delta:
                nodes.append("signal:new_contradiction")
            if int(row.get("unsafe_attempt", 0)):
                nodes.append("signal:unsafe_attempt")
            load = len(unresolved) + len(invariants) + contradiction_delta + int(row.get("unsafe_attempt", 0))
            loads.append(load)
            if load > 0:
                current_span += 1
            else:
                if current_span:
                    active_spans.append(current_span)
                current_span = 0
            node_counts.update(nodes)
            global_node_counts.update(nodes)
            unique = sorted(set(nodes))
            for i, left in enumerate(unique):
                for right in unique[i + 1:]:
                    global_edges.add((left, right))
        if current_span:
            active_spans.append(current_span)

        active_indices = [index for index, load in enumerate(loads) if load > 0]
        initiation_index = active_indices[0] if active_indices else None
        peak_index = max(range(len(loads)), key=lambda idx: loads[idx]) if loads else None
        max_load = max(loads) if loads else 0
        repair_half_life = None
        if peak_index is not None and max_load > 0:
            half = max_load / 2.0
            for index in range(peak_index + 1, len(loads)):
                if loads[index] <= half:
                    repair_half_life = index - peak_index
                    break
        failure_cycles = [int(row["cycle"]) for row in ordered if int(row["first_failure_this_cycle"])]
        failure_cycle = failure_cycles[0] if failure_cycles else None
        origin = ordered[initiation_index] if initiation_index is not None else None
        top_nodes = [node for node, _ in node_counts.most_common(5)]
        run_rows.append(
            {
                "run_family": key[0],
                "mode": key[1],
                "schedule": key[2],
                "seed": key[3],
                "crack_initiation_cycle": int(origin["cycle"]) if origin else None,
                "origin_event_id": origin["event_id"] if origin else None,
                "origin_target": origin["target"] if origin else None,
                "origin_amplitude": origin["amplitude"] if origin else None,
                "peak_cycle": int(ordered[peak_index]["cycle"]) if peak_index is not None else None,
                "max_crack_load": max_load,
                "crack_burden": sum(loads),
                "longest_active_span": max(active_spans) if active_spans else 0,
                "repair_half_life_cycles": repair_half_life,
                "first_failure_cycle": failure_cycle,
                "cycles_from_crack_to_failure": failure_cycle - int(origin["cycle"]) if origin and failure_cycle is not None else None,
                "dominant_nodes": "|".join(top_nodes),
            }
        )

    all_nodes = set(global_node_counts)
    components = _components(all_nodes, global_edges)
    components.sort(key=lambda component: (sum(global_node_counts[node] for node in component), len(component)), reverse=True)
    dominant = components[0] if components else set()
    heldout = set(map(int, experiment["heldout_seeds"]))
    heldout_rows = [row for row in run_rows if int(row["seed"]) in heldout]
    by_mode: dict[str, Any] = {}
    for mode in experiment["modes"]:
        mode_rows = [row for row in heldout_rows if row["mode"] == mode]
        initiated = [row for row in mode_rows if row["crack_initiation_cycle"] is not None]
        half_lives = [float(row["repair_half_life_cycles"]) for row in mode_rows if row["repair_half_life_cycles"] is not None]
        by_mode[mode] = {
            "run_count": len(mode_rows),
            "crack_initiation_rate": len(initiated) / len(mode_rows) if mode_rows else None,
            "median_initiation_cycle": median(float(row["crack_initiation_cycle"]) for row in initiated) if initiated else None,
            "median_max_crack_load": median(float(row["max_crack_load"]) for row in mode_rows) if mode_rows else None,
            "mean_crack_burden": mean(float(row["crack_burden"]) for row in mode_rows) if mode_rows else None,
            "median_empirical_repair_half_life": median(half_lives) if half_lives else None,
        }
    summary = {
        "schema": "openline.endurance.fractography.v1",
        "definition": "A crack is an observed connected burden of unresolved dependencies, invariant failures, new contradictions, or unsafe attempts. It is a diagnostic proxy, not a physical fracture.",
        "run_count": len(run_rows),
        "heldout_run_count": len(heldout_rows),
        "by_mode": by_mode,
        "dominant_crack_cluster": {
            "node_count": len(dominant),
            "nodes": sorted(dominant),
            "weighted_occurrence_count": sum(global_node_counts[node] for node in dominant),
        },
        "top_crack_nodes": [{"node": node, "occurrences": count} for node, count in global_node_counts.most_common(12)],
    }
    return run_rows, summary
