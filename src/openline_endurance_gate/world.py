from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .util import clamp

REQUIREMENTS = (
    "retry_demand",
    "latency_floor",
    "risk_tolerance",
    "memory_horizon",
    "handoff_depth",
    "token_capacity",
)

FIELDS = (
    "schema_version",
    "max_retries",
    "retry_backoff_ms",
    "timeout_ms",
    "approval_threshold",
    "risk_limit",
    "memory_ttl",
    "receipt_ttl",
    "max_handoffs",
    "checkpoint_interval",
    "token_budget",
    "evidence_budget",
)

INITIAL_REQUIREMENTS = {
    "retry_demand": 0,
    "latency_floor": 420,
    "risk_tolerance": 0,
    "memory_horizon": 0,
    "handoff_depth": 0,
    "token_capacity": 0,
}

DEPENDENCY_EDGES = {
    "retry_demand->max_retries",
    "retry_demand->retry_backoff_ms",
    "retry_demand->timeout_ms",
    "latency_floor->timeout_ms",
    "risk_tolerance->risk_limit",
    "risk_tolerance->approval_threshold",
    "memory_horizon->memory_ttl",
    "memory_horizon->receipt_ttl",
    "handoff_depth->max_handoffs",
    "handoff_depth->checkpoint_interval",
    "handoff_depth->token_budget",
    "handoff_depth->evidence_budget",
    "handoff_depth->receipt_ttl",
    "token_capacity->token_budget",
    "token_capacity->evidence_budget",
    "max_retries->timeout_ms",
    "retry_backoff_ms->timeout_ms",
    "risk_limit->approval_threshold",
    "memory_ttl->receipt_ttl",
    "max_handoffs->checkpoint_interval",
    "max_handoffs->token_budget",
    "token_budget->evidence_budget",
}

REQ_TO_FIELDS = {
    "retry_demand": {"max_retries", "retry_backoff_ms", "timeout_ms"},
    "latency_floor": {"timeout_ms"},
    "risk_tolerance": {"risk_limit", "approval_threshold"},
    "memory_horizon": {"memory_ttl", "receipt_ttl"},
    "handoff_depth": {"max_handoffs", "checkpoint_interval", "token_budget", "evidence_budget", "receipt_ttl"},
    "token_capacity": {"token_budget", "evidence_budget"},
}

FIELD_DEPENDENCIES = {
    "timeout_ms": {"max_retries", "retry_backoff_ms"},
    "approval_threshold": {"risk_limit"},
    "receipt_ttl": {"memory_ttl", "max_handoffs"},
    "checkpoint_interval": {"max_handoffs"},
    "token_budget": {"max_handoffs"},
    "evidence_budget": {"token_budget"},
}


@dataclass(frozen=True)
class Perturbation:
    event_id: str
    amplitude: str
    target: str
    delta: int
    ambiguity: float
    correction_required: bool
    token_cost: int


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    detail: str


def solve(requirements: dict[str, int]) -> dict[str, int]:
    retry = int(clamp(2 + requirements["retry_demand"], 1, 8))
    backoff = int(clamp(60 + 15 * requirements["retry_demand"], 20, 240))
    timeout = max(int(requirements["latency_floor"]), backoff * (retry + 1))
    risk_limit = int(clamp(62 + requirements["risk_tolerance"], 25, 95))
    approval = int(clamp(risk_limit - 18, 0, risk_limit))
    memory_ttl = int(clamp(120 + 24 * requirements["memory_horizon"], 48, 720))
    handoffs = int(clamp(4 + requirements["handoff_depth"], 1, 16))
    checkpoint = max(1, min(handoffs, (handoffs + 1) // 2))
    token_budget = int(max(256 + 32 * requirements["token_capacity"], 20 * handoffs))
    evidence_budget = int(clamp(72 + 8 * requirements["handoff_depth"] + 8 * requirements["token_capacity"], 32, token_budget // 2))
    receipt_ttl = int(max(memory_ttl * 2, memory_ttl + 12 * handoffs))
    return {
        "schema_version": 1,
        "max_retries": retry,
        "retry_backoff_ms": backoff,
        "timeout_ms": timeout,
        "approval_threshold": approval,
        "risk_limit": risk_limit,
        "memory_ttl": memory_ttl,
        "receipt_ttl": receipt_ttl,
        "max_handoffs": handoffs,
        "checkpoint_interval": checkpoint,
        "token_budget": token_budget,
        "evidence_budget": evidence_budget,
    }


def apply_partial_solve(
    old_config: dict[str, int],
    believed_requirements: dict[str, int],
    target: str,
    known_edges: set[str],
) -> dict[str, int]:
    ideal = solve(believed_requirements)
    updated = dict(old_config)
    frontier = set(REQ_TO_FIELDS[target])
    changed = True
    while changed:
        changed = False
        for field, parents in FIELD_DEPENDENCIES.items():
            if field in frontier:
                continue
            if parents & frontier:
                needed = {f"{parent}->{field}" for parent in parents if f"{parent}->{field}" in DEPENDENCY_EDGES}
                if needed and needed.issubset(known_edges):
                    frontier.add(field)
                    changed = True
    for field in frontier:
        direct_edge = f"{target}->{field}"
        parent_edges = {f"{parent}->{field}" for parent in FIELD_DEPENDENCIES.get(field, set())}
        if direct_edge in known_edges or (parent_edges and parent_edges.issubset(known_edges)):
            updated[field] = ideal[field]
    return updated


def invariant_results(config: dict[str, int]) -> list[InvariantResult]:
    checks: list[tuple[str, Callable[[], bool], str]] = [
        ("schema_is_v1", lambda: config["schema_version"] == 1, "schema_version must equal 1"),
        ("retry_floor", lambda: config["max_retries"] >= 1, "max_retries must be at least 1"),
        ("timeout_covers_retry_window", lambda: config["timeout_ms"] >= config["retry_backoff_ms"] * (config["max_retries"] + 1), "timeout must cover retries and backoff"),
        ("approval_within_risk_limit", lambda: 0 <= config["approval_threshold"] <= config["risk_limit"], "approval threshold must fit the risk envelope"),
        ("risk_limit_bounded", lambda: 25 <= config["risk_limit"] <= 95, "risk limit must remain bounded"),
        ("memory_ttl_positive", lambda: config["memory_ttl"] >= 48, "memory TTL must remain usable"),
        ("receipt_outlives_memory", lambda: config["receipt_ttl"] >= 2 * config["memory_ttl"], "receipt TTL must outlive volatile memory"),
        ("checkpoint_within_handoff_window", lambda: 1 <= config["checkpoint_interval"] <= config["max_handoffs"], "checkpoint must occur before handoff exhaustion"),
        ("handoff_cap_bounded", lambda: 1 <= config["max_handoffs"] <= 16, "handoff cap must remain bounded"),
        ("token_budget_covers_handoffs", lambda: config["token_budget"] >= 20 * config["max_handoffs"], "token budget must cover handoff depth"),
        ("evidence_fits_token_budget", lambda: 32 <= config["evidence_budget"] <= config["token_budget"] // 2, "evidence budget must fit input budget"),
        ("receipt_covers_checkpoint_span", lambda: config["receipt_ttl"] >= config["memory_ttl"] + 12 * config["max_handoffs"], "receipt TTL must cover the checkpoint span"),
    ]
    return [InvariantResult(name, bool(fn()), detail) for name, fn, detail in checks]


def config_accuracy(observed: dict[str, int], truth: dict[str, int]) -> float:
    return sum(observed.get(key) == truth[key] for key in FIELDS) / len(FIELDS)


def requirement_accuracy(observed: dict[str, int], truth: dict[str, int]) -> float:
    return sum(observed.get(key) == truth[key] for key in REQUIREMENTS) / len(REQUIREMENTS)
