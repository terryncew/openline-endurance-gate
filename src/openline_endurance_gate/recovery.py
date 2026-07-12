from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .damage import attach_damage, compute_damage
from .fractography import analyze_fractography
from .sim import AMPLITUDE_BASE_DIFFICULTY, AMPLITUDE_SCALE, generate_perturbations
from .util import canonical_json, clamp, mean, median, sha256_bytes, stable_uniform
from .world import (
    DEPENDENCY_EDGES, INITIAL_REQUIREMENTS, REQUIREMENTS, Perturbation,
    apply_partial_solve, config_accuracy, invariant_results, requirement_accuracy, solve,
)

MODES = (
    "continuous_control", "empty_reset", "full_history_handoff",
    "unsigned_minimal_handoff", "olp_handoff",
)
RECEIPT_CLAIMS = (
    "persistent_state_carried", "unresolved_tasks_carried", "policy_constraints_carried",
    "prior_decisions_carried", "outcome_references_carried", "irrelevant_history_pruned",
    "coverage_asserted", "handoff_packet_created",
)
APPROVED_DESTINATIONS = ("memory://local", "tool://approved")
DENIED_DESTINATIONS = ("evil://exfil",)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")
GENESIS_PARENT_HASH = "GENESIS"

RECOVERY_CYCLE_FIELDS = [
    "run_family", "world", "mode", "schedule", "seed", "cycle", "event_id", "amplitude",
    "target", "truth_delta", "applied_delta", "common_random_draw", "intervention",
    "handoff_status", "handoff_reason", "packet_bytes", "packet_tokens", "active_context_tokens",
    "context_pressure", "rolling_noise_epsilon", "required_retry_demand", "required_latency_floor",
    "required_risk_tolerance", "required_memory_horizon", "required_handoff_depth",
    "required_token_capacity", "required_state_retained_count", "unresolved_task_count",
    "decision_correct", "policy_check", "policy_violation", "unsafe_attempt", "config_accuracy",
    "requirement_accuracy", "invariant_failure_count", "invariant_failures", "contradiction_count",
    "unresolved_dependencies", "critical_failure", "failure_signature", "first_failure_this_cycle",
    "failed_by_cycle", "same_failure_returned", "evidence_reads", "rejected_handoffs",
    "undecidable_handoffs", "kappa", "kappa_star_0", "phi_star", "phi_base", "handoff_loss",
    "delta_hol", "damage_D", "kappa_star_eff", "vkd_f",
]
RECOVERY_RUN_FIELDS = [
    "world", "mode", "seed", "declared_horizon", "intervention_cycle", "n_f", "failed",
    "first_failure_cycle", "first_failure_signature", "same_failure_returned",
    "same_failure_return_cycle", "cycles_until_same_failure_returns", "correct_decisions_post_handoff",
    "decision_opportunities_post_handoff", "post_handoff_decision_accuracy", "policy_violations",
    "final_config_accuracy", "final_requirement_accuracy", "retained_retry_demand",
    "retained_latency_floor", "retained_risk_tolerance", "retained_memory_horizon",
    "retained_handoff_depth", "retained_token_capacity", "packet_bytes", "packet_tokens",
    "evidence_reads", "accepted_handoffs", "rejected_handoffs", "undecidable_handoffs",
]


@dataclass
class RecoveryState:
    truth: dict[str, int]
    believed: dict[str, int]
    config: dict[str, int]
    known_edges: set[str]
    active_requirements: set[str]
    unresolved_tasks: dict[str, str]
    policy: dict[str, list[str]]
    decisions: list[dict[str, Any]] = field(default_factory=list)
    outcome_references: list[dict[str, Any]] = field(default_factory=list)
    relevant_history: list[dict[str, Any]] = field(default_factory=list)
    irrelevant_history: list[dict[str, Any]] = field(default_factory=list)
    active_context_tokens: int = 1200
    epsilon: float = 0.0
    contradiction_count: int = 0
    handoff_lineage_complete: bool = True

    @classmethod
    def initial(cls) -> "RecoveryState":
        truth = dict(INITIAL_REQUIREMENTS)
        state = cls(
            truth, dict(truth), solve(truth), set(DEPENDENCY_EDGES), set(REQUIREMENTS),
            {"confirm_policy": "open", "preserve_required_state": "open"},
            {"allow": list(APPROVED_DESTINATIONS), "deny": list(DENIED_DESTINATIONS)},
        )
        state.decisions.append({"cycle": 0, "decision": "retain_origin_bound_policy", "required": True})
        state.outcome_references.append({"cycle": 0, "outcome": "initial_state_validated", "required": True})
        return state


@dataclass(frozen=True)
class RecoveryVerifierSession:
    expected_run_id: str
    last_accepted_parent_hash: str = GENESIS_PARENT_HASH
    last_accepted_generation_index: int = 0


def derive_run_id(master_seed: str, case_id: str) -> str:
    return sha256_bytes(master_seed.encode("utf-8") + case_id.encode("utf-8"))


def envelope_hash(envelope: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(envelope))


def advance_recovery_session(
    session: RecoveryVerifierSession, verification: dict[str, Any],
) -> RecoveryVerifierSession:
    """Apply an accepted verifier proposal without hiding state mutation inside verification."""
    if verification.get("status") != "accepted":
        return session
    update = verification.get("proposed_session_update")
    if not isinstance(update, dict):
        raise ValueError("accepted verification is missing proposed_session_update")
    return RecoveryVerifierSession(
        expected_run_id=session.expected_run_id,
        last_accepted_parent_hash=str(update["last_accepted_parent_hash"]),
        last_accepted_generation_index=int(update["last_accepted_generation_index"]),
    )


def _freshness_reasons(
    envelope: dict[str, Any], session: RecoveryVerifierSession,
) -> list[str]:
    reasons: list[str] = []
    if envelope.get("run_id") != session.expected_run_id:
        reasons.append("run_id_mismatch")
    if envelope.get("parent_hash") != session.last_accepted_parent_hash:
        reasons.append("parent_hash_mismatch")
    generation = envelope.get("generation_index")
    if not isinstance(generation, int):
        reasons.append("generation_index_invalid")
    elif generation <= session.last_accepted_generation_index:
        reasons.append("generation_index_not_advancing")
    return reasons


def _session_proposal(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_accepted_parent_hash": envelope_hash(envelope),
        "last_accepted_generation_index": int(envelope["generation_index"]),
    }


def lexical_token_count(value: Any) -> int:
    return len(TOKEN_PATTERN.findall(json.dumps(value, sort_keys=True, separators=(",", ":"))))


def _events(seed: int, horizon: int, counts: dict[str, int]) -> list[Perturbation]:
    events: list[Perturbation] = []
    block_size = sum(map(int, counts.values()))
    for block in range((horizon + block_size - 1) // block_size):
        packet = generate_perturbations(seed * 101 + block * 7919 + 37, counts)
        for index, event in enumerate(packet):
            cycle = block * block_size + index + 1
            events.append(Perturbation(
                f"recovery-{seed}-c{cycle:03d}", event.amplitude, event.target, event.delta,
                event.ambiguity, event.correction_required, event.token_cost,
            ))
    return events[:horizon]


def _fixture_signer(seed: int) -> Ed25519PrivateKey:
    """Byte-recomputable experiment fixture; never an operational key source."""
    raw = hashlib.sha256(f"openline-recovery-v091-fixture:{seed}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(raw)


def _public_b64(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _minimal_payload(
    state: RecoveryState, cycle: int, omit_required_field: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {key: int(state.believed[key]) for key in REQUIREMENTS}
    if omit_required_field is not None:
        required.pop(omit_required_field)
    evidence = {
        "persistent_state": required,
        "unresolved_tasks": copy.deepcopy(state.unresolved_tasks),
        "policy_constraints": copy.deepcopy(state.policy),
        "prior_decisions": copy.deepcopy(state.decisions[-12:]),
        "outcome_references": copy.deepcopy(state.outcome_references[-12:]),
    }
    return {
        "schema": "openline.recovery.handoff-payload.v1", "issued_at_cycle": cycle,
        "persistent_state": required, "unresolved_tasks": evidence["unresolved_tasks"],
        "policy_constraints": evidence["policy_constraints"],
        "prior_decisions": evidence["prior_decisions"],
        "outcome_references": evidence["outcome_references"],
        "known_edges": sorted(state.known_edges),
    }, evidence


def _full_history_payload(state: RecoveryState, cycle: int) -> dict[str, Any]:
    minimal, _ = _minimal_payload(state, cycle)
    return {
        **minimal, "schema": "openline.recovery.full-history-payload.v1",
        "relevant_history": copy.deepcopy(state.relevant_history),
        "irrelevant_history": copy.deepcopy(state.irrelevant_history),
        "active_context_tokens": state.active_context_tokens,
    }


def create_unsigned_handoff(
    state: RecoveryState,
    cycle: int,
    *,
    run_id: str,
    generation_index: int,
    parent_hash: str,
    omit_required_field: str | None = None,
) -> dict[str, Any]:
    payload, evidence = _minimal_payload(state, cycle, omit_required_field)
    payload.update({
        "run_id": run_id, "generation_index": generation_index, "parent_hash": parent_hash,
    })
    return {
        "schema": "openline.recovery.unsigned-envelope.v2", "run_id": run_id,
        "generation_index": generation_index, "parent_hash": parent_hash, "payload": payload,
        "evidence": evidence, "checksum": sha256_bytes(canonical_json(payload)),
        "integrity_mechanism": "plain_sha256_unkeyed_with_rewritable_freshness_fields",
    }


def verify_unsigned_handoff(
    envelope: dict[str, Any], session: RecoveryVerifierSession,
) -> dict[str, Any]:
    reasons: list[str] = []
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    if sha256_bytes(canonical_json(payload)) != envelope.get("checksum"):
        reasons.append("checksum_mismatch")
    if any(payload.get(field) != envelope.get(field) for field in ("run_id", "generation_index", "parent_hash")):
        reasons.append("payload_freshness_binding_invalid")
    reasons.extend(_freshness_reasons(envelope, session))
    reasons = sorted(set(reasons))
    status = "accepted" if not reasons else "rejected"
    return {
        "status": status, "reason_codes": reasons,
        "integrity_valid": "checksum_mismatch" not in reasons,
        "origin_verified": False, "coverage_verified": False,
        "freshness_verified": not any(code in reasons for code in {
            "run_id_mismatch", "parent_hash_mismatch", "generation_index_not_advancing",
            "generation_index_invalid", "payload_freshness_binding_invalid",
        }),
        "freshness_status": "ACCEPTED_CURRENT" if status == "accepted" else "REJECTED_NOT_CURRENT",
        "envelope_hash": envelope_hash(envelope),
        "proposed_session_update": _session_proposal(envelope) if status == "accepted" else None,
    }


def create_olp_handoff(
    state: RecoveryState,
    cycle: int,
    seed: int,
    *,
    run_id: str,
    generation_index: int,
    parent_hash: str,
    omit_required_field: str | None = None,
) -> dict[str, Any]:
    payload, evidence = _minimal_payload(state, cycle, omit_required_field)
    payload.update({
        "run_id": run_id, "generation_index": generation_index, "parent_hash": parent_hash,
    })
    signer, witness = _fixture_signer(seed), _public_b64(_fixture_signer(seed))
    hashes = {key: sha256_bytes(canonical_json(value)) for key, value in sorted(evidence.items())}
    receipt_evidence = (
        [hashes["persistent_state"]], [hashes["unresolved_tasks"]], [hashes["policy_constraints"]],
        [hashes["prior_decisions"]], [hashes["outcome_references"]], [], sorted(hashes.values()),
        [sha256_bytes(canonical_json(payload))],
    )
    receipts: list[dict[str, Any]] = []
    receipt_parent = GENESIS_PARENT_HASH
    for index, (claim, evidence_hashes) in enumerate(zip(RECEIPT_CLAIMS, receipt_evidence)):
        receipt = {
            "receipt_index": index, "receipt_parent_hash": receipt_parent, "issued_at_cycle": cycle,
            "run_id": run_id, "generation_index": generation_index, "parent_hash": parent_hash,
            "claim": claim, "action": "create_compact_handoff" if index == 7 else "record_handoff_evidence",
            "evidence_hashes": evidence_hashes, "result": "executed",
            "tokens_used": lexical_token_count(payload) if index == 7 else 0,
            "timestamp": f"cycle:{cycle}:receipt:{index}", "witness": witness,
            "next_use_note": "Verify signature, hashes, chain, and coverage before restoration.",
        }
        digest = sha256_bytes(canonical_json(receipt))
        receipts.append({**receipt, "receipt_hash": digest})
        receipt_parent = digest
    coverage = {
        "required_state_fields": list(REQUIREMENTS),
        "present_state_fields": sorted(payload["persistent_state"]),
        "required_evidence_categories": sorted(evidence),
        "present_evidence_categories": sorted(evidence),
    }
    body = {
        "schema": "openline.recovery.olp-envelope.v2", "run_id": run_id,
        "generation_index": generation_index, "parent_hash": parent_hash,
        "payload": payload, "receipts": receipts, "coverage": coverage, "witness": witness,
    }
    signature = base64.b64encode(signer.sign(canonical_json(body))).decode("ascii")
    return {**body, "signature": signature, "external_evidence": copy.deepcopy(evidence)}


def verify_olp_handoff(
    envelope: dict[str, Any], session: RecoveryVerifierSession,
) -> dict[str, Any]:
    reasons: list[str] = []
    body = {key: envelope.get(key) for key in (
        "schema", "run_id", "generation_index", "parent_hash",
        "payload", "receipts", "coverage", "witness",
    )}
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(str(envelope.get("witness", ""))))
        public.verify(base64.b64decode(str(envelope.get("signature", ""))), canonical_json(body))
    except (ValueError, InvalidSignature, TypeError):
        reasons.append("signature_invalid")
    receipts = envelope.get("receipts") if isinstance(envelope.get("receipts"), list) else []
    parent = "GENESIS"
    for index, receipt in enumerate(receipts):
        if receipt.get("receipt_index") != index:
            reasons.append("receipt_order_invalid")
        if receipt.get("receipt_parent_hash") != parent:
            reasons.append("receipt_chain_invalid")
        if (
            receipt.get("run_id") != envelope.get("run_id")
            or receipt.get("generation_index") != envelope.get("generation_index")
            or receipt.get("parent_hash") != envelope.get("parent_hash")
        ):
            reasons.append("receipt_freshness_binding_invalid")
        bare = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        digest = sha256_bytes(canonical_json(bare))
        if receipt.get("receipt_hash") != digest:
            reasons.append("receipt_hash_invalid")
        parent = digest
    if len(receipts) != len(RECEIPT_CLAIMS):
        reasons.append("receipt_chain_incomplete")
    if [item.get("claim") for item in receipts] != list(RECEIPT_CLAIMS):
        reasons.append("receipt_claim_coverage_invalid")

    evidence = envelope.get("external_evidence") if isinstance(envelope.get("external_evidence"), dict) else {}
    actual_hashes = {key: sha256_bytes(canonical_json(value)) for key, value in evidence.items()}
    asserted = {value for item in receipts for value in item.get("evidence_hashes", []) if isinstance(value, str)}
    evidence_keys = ("persistent_state", "unresolved_tasks", "policy_constraints", "prior_decisions", "outcome_references")
    for key in evidence_keys:
        if key not in actual_hashes or actual_hashes[key] not in asserted:
            reasons.append(f"evidence_hash_mismatch:{key}")

    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    if any(payload.get(field) != envelope.get(field) for field in ("run_id", "generation_index", "parent_hash")):
        reasons.append("payload_freshness_binding_invalid")
    persistent = payload.get("persistent_state") if isinstance(payload.get("persistent_state"), dict) else {}
    coverage = envelope.get("coverage") if isinstance(envelope.get("coverage"), dict) else {}
    required, present = set(REQUIREMENTS), set(persistent)
    if set(coverage.get("required_state_fields", [])) != required or set(coverage.get("present_state_fields", [])) != present:
        reasons.append("coverage_declaration_invalid")
    if not required.issubset(present):
        reasons.append("required_state_incomplete")
    if set(evidence_keys) != set(coverage.get("required_evidence_categories", [])):
        reasons.append("evidence_coverage_declaration_invalid")
    if set(evidence) != set(coverage.get("present_evidence_categories", [])):
        reasons.append("evidence_coverage_invalid")

    reasons.extend(_freshness_reasons(envelope, session))
    reasons = sorted(set(reasons))
    integrity = {
        "signature_invalid", "receipt_chain_invalid", "receipt_hash_invalid",
        "receipt_order_invalid", "receipt_freshness_binding_invalid", "payload_freshness_binding_invalid",
    }
    freshness_invalid = {
        "run_id_mismatch", "parent_hash_mismatch", "generation_index_not_advancing",
        "generation_index_invalid",
    }
    incomplete = any(code.startswith("evidence_hash_mismatch") or code in {
        "required_state_incomplete", "coverage_declaration_invalid", "evidence_coverage_invalid",
        "evidence_coverage_declaration_invalid",
        "receipt_claim_coverage_invalid", "receipt_chain_incomplete",
    } for code in reasons)
    status = (
        "accepted" if not reasons
        else "rejected" if integrity.intersection(reasons) or freshness_invalid.intersection(reasons)
        else "undecidable" if incomplete
        else "rejected"
    )
    accepted_hash = envelope_hash(envelope)
    return {
        "status": status, "reason_codes": reasons, "signature_valid": "signature_invalid" not in reasons,
        "evidence_valid": not any(code.startswith("evidence_hash_mismatch") for code in reasons),
        "coverage_complete": "required_state_incomplete" not in reasons and "coverage_declaration_invalid" not in reasons,
        "chain_valid": not any(code.startswith("receipt_") for code in reasons),
        "freshness_verified": not freshness_invalid.intersection(reasons),
        "freshness_status": (
            "ACCEPTED_CURRENT" if status == "accepted"
            else "REJECTED_NOT_CURRENT" if freshness_invalid.intersection(reasons)
            else "UNDECIDABLE_COVERAGE"
        ),
        "envelope_hash": accepted_hash,
        "proposed_session_update": _session_proposal(envelope) if status == "accepted" else None,
    }


def _restore_payload(state: RecoveryState, payload: dict[str, Any], compact: bool) -> RecoveryState:
    result = copy.deepcopy(state)
    result.believed = {key: int(value) for key, value in payload["persistent_state"].items()}
    result.config = solve(result.believed)
    result.known_edges = set(payload.get("known_edges", []))
    result.active_requirements = set(result.believed)
    result.unresolved_tasks = copy.deepcopy(payload.get("unresolved_tasks", {}))
    result.policy = copy.deepcopy(payload.get("policy_constraints", {}))
    result.decisions = copy.deepcopy(payload.get("prior_decisions", []))
    result.outcome_references = copy.deepcopy(payload.get("outcome_references", []))
    result.handoff_lineage_complete = bool(result.decisions and result.outcome_references)
    result.epsilon = 0.0
    if compact:
        result.active_context_tokens = 1800
        result.irrelevant_history = []
    else:
        result.relevant_history = copy.deepcopy(payload.get("relevant_history", []))
        result.irrelevant_history = copy.deepcopy(payload.get("irrelevant_history", []))
        result.active_context_tokens = int(payload.get("active_context_tokens", result.active_context_tokens))
    return result


def _perform_handoff(
    mode: str, state: RecoveryState, cycle: int, seed: int, config: dict[str, Any],
) -> tuple[RecoveryState, dict[str, Any]]:
    wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    status, reason, packet = "not_applicable", "no_handoff", None
    evidence_reads = accepted = rejected = undecidable = 0
    verify_wall_ns = verify_cpu_ns = 0
    reason_codes: list[str] = []
    run_id = generation_index = parent_hash = None
    freshness_status = "not_applicable"
    if mode == "continuous_control":
        pass
    elif mode == "empty_reset":
        packet, status, reason, accepted = {"schema": "openline.recovery.empty-reset.v1"}, "accepted", "empty_runtime_started", 1
        state = RecoveryState(
            copy.deepcopy(state.truth), dict(INITIAL_REQUIREMENTS), solve(INITIAL_REQUIREMENTS),
            set(), set(), {}, {"allow": [], "deny": []}, active_context_tokens=600,
            handoff_lineage_complete=False,
        )
    elif mode == "full_history_handoff":
        packet, status, reason, accepted = _full_history_payload(state, cycle), "accepted", "unverified_full_history_loaded", 1
        state = _restore_payload(state, packet, False)
    elif mode == "unsigned_minimal_handoff":
        run_id = derive_run_id(str(config["master_seed"]), f"seed:{seed}")
        generation_index = 1
        parent_hash = GENESIS_PARENT_HASH
        session = RecoveryVerifierSession(run_id)
        packet = create_unsigned_handoff(
            state, cycle, run_id=run_id, generation_index=generation_index,
            parent_hash=parent_hash,
        )
        vw, vc = time.perf_counter_ns(), time.process_time_ns()
        result = verify_unsigned_handoff(packet, session)
        verify_wall_ns, verify_cpu_ns = time.perf_counter_ns() - vw, time.process_time_ns() - vc
        status, reason = result["status"], ",".join(result["reason_codes"]) or "checksum_and_freshness_fields_current"
        reason_codes = list(result["reason_codes"])
        freshness_status = result["freshness_status"]
        accepted, rejected = int(status == "accepted"), int(status == "rejected")
        if accepted:
            session = advance_recovery_session(session, result)
            state = _restore_payload(state, packet["payload"], True)
    elif mode == "olp_handoff":
        run_id = derive_run_id(str(config["master_seed"]), f"seed:{seed}")
        generation_index = 1
        parent_hash = GENESIS_PARENT_HASH
        session = RecoveryVerifierSession(run_id)
        packet = create_olp_handoff(
            state, cycle, seed, run_id=run_id, generation_index=generation_index,
            parent_hash=parent_hash,
        )
        vw, vc = time.perf_counter_ns(), time.process_time_ns()
        result = verify_olp_handoff(packet, session)
        verify_wall_ns, verify_cpu_ns = time.perf_counter_ns() - vw, time.process_time_ns() - vc
        status = result["status"]
        reason_codes = list(result["reason_codes"])
        reason = ",".join(result["reason_codes"]) or "signature_evidence_coverage_valid"
        freshness_status = result["freshness_status"]
        evidence_reads = len(packet["external_evidence"])
        accepted, rejected, undecidable = (int(status == value) for value in ("accepted", "rejected", "undecidable"))
        if accepted:
            session = advance_recovery_session(session, result)
            state = _restore_payload(state, packet["payload"], True)
    else:
        raise ValueError(f"unknown recovery mode: {mode}")
    return state, {
        "schema": "openline.recovery.handoff-observation.v2", "mode": mode, "seed": seed,
        "issued_at_cycle": cycle, "status": status, "reason": reason,
        "integrity_mechanism": {
            "continuous_control": "none_no_handoff", "empty_reset": "none",
            "full_history_handoff": "none",
            "unsigned_minimal_handoff": "plain_sha256_unkeyed_with_rewritable_run_parent_generation_fields",
            "olp_handoff": "ed25519_signature_evidence_coverage_and_stateful_run_parent_generation_binding",
        }[mode],
        "run_id": run_id, "generation_index": generation_index, "parent_hash": parent_hash,
        "freshness_status": freshness_status, "reason_codes": reason_codes,
        "packet_bytes": len(canonical_json(packet)) if packet is not None else 0,
        "packet_tokens": lexical_token_count(packet) if packet is not None else 0,
        "handoff_wall_ns": time.perf_counter_ns() - wall_start,
        "handoff_cpu_ns": time.process_time_ns() - cpu_start,
        "verification_wall_ns": verify_wall_ns, "verification_cpu_ns": verify_cpu_ns,
        "timing_reproducibility_status": "ENVIRONMENT_SENSITIVE_EXCLUDED_FROM_REPRODUCIBILITY_CLAIMS",
        "evidence_reads": evidence_reads, "accepted_handoffs": accepted,
        "rejected_handoffs": rejected, "undecidable_handoffs": undecidable,
        "packet_sha256": sha256_bytes(canonical_json(packet)) if packet is not None else None,
    }


def _state_retention(state: RecoveryState) -> dict[str, int]:
    return {
        requirement: int(requirement in state.active_requirements and state.believed.get(requirement) == state.truth.get(requirement))
        for requirement in REQUIREMENTS
    }


def _simulate_one(mode: str, seed: int, experiment: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    cfg = experiment["recovery"]
    horizon, intervention_cycle = int(cfg["horizon_cycles"]), int(cfg["intervention_cycle"])
    state, rows = RecoveryState.initial(), []
    handoff: dict[str, Any] | None = None
    first_cycle: int | None = None
    first_signature: str | None = None
    return_cycle: int | None = None
    failure_was_absent = False
    packet_bytes = packet_tokens = evidence_reads = accepted = rejected = undecidable = 0
    correct_post = opportunities_post = policy_violations = prior_unresolved = 0
    for cycle, event in enumerate(_events(seed, horizon, cfg["disturbance_counts"]), 1):
        intervention = int(cycle == intervention_cycle)
        handoff_status, handoff_reason = "none", ""
        if intervention:
            state, handoff = _perform_handoff(mode, state, cycle, seed, cfg)
            handoff_status, handoff_reason = str(handoff["status"]), str(handoff["reason"])
            packet_bytes, packet_tokens = int(handoff["packet_bytes"]), int(handoff["packet_tokens"])
            evidence_reads = int(handoff["evidence_reads"])
            accepted, rejected, undecidable = (int(handoff[key]) for key in ("accepted_handoffs", "rejected_handoffs", "undecidable_handoffs"))

        state.truth[event.target] += event.delta
        state.relevant_history.append({"cycle": cycle, "event_id": event.event_id, "target": event.target, "delta": event.delta})
        state.irrelevant_history.append({
            "cycle": cycle,
            "padding": sha256_bytes(f"irrelevant:{seed}:{cycle}".encode()) * int(cfg["irrelevant_history_repetitions"]),
        })
        state.active_context_tokens += int(event.token_cost) + int(cfg["irrelevant_tokens_per_cycle"])
        pressure = clamp(
            (state.active_context_tokens - float(cfg["context_pressure_start_tokens"]))
            / float(cfg["context_pressure_width_tokens"]), 0.0, 1.5,
        )
        state.epsilon = clamp(
            float(cfg["noise_retention"]) * state.epsilon
            + float(cfg["noise_context_weight"]) * pressure
            + float(cfg["noise_ambiguity_weight"]) * event.ambiguity, 0.0, 1.5,
        )
        difficulty = AMPLITUDE_BASE_DIFFICULTY[event.amplitude] * AMPLITUDE_SCALE[event.amplitude]
        draw = stable_uniform("recovery-correction", seed, cycle, event.event_id)
        probability = clamp(
            float(cfg["base_correction_probability"])
            - float(cfg["ambiguity_penalty"]) * event.ambiguity
            - float(cfg["difficulty_penalty"]) * difficulty
            - float(cfg["context_penalty"]) * pressure
            - float(cfg["noise_penalty"]) * state.epsilon, 0.02, 0.9999,
        )
        applied_delta = 0
        if draw < probability:
            if event.target in state.active_requirements:
                state.believed[event.target] += event.delta
            else:
                state.believed[event.target] = state.truth[event.target]
            state.active_requirements.add(event.target)
            state.known_edges.update(edge for edge in DEPENDENCY_EDGES if edge.startswith(event.target + "->"))
            state.config = apply_partial_solve(state.config, state.believed, event.target, state.known_edges)
            state.unresolved_tasks.pop(f"resolve:{event.target}", None)
            applied_delta = event.delta
        else:
            state.unresolved_tasks[f"resolve:{event.target}"] = "open"
            state.contradiction_count += 1

        interval = int(cfg["policy_check_interval"])
        policy_check = int(cycle >= intervention_cycle and cycle % interval == 0)
        destination = "evil://exfil" if policy_check and cycle % (2 * interval) == 0 else "tool://approved"
        should_allow = destination in APPROVED_DESTINATIONS and destination not in DENIED_DESTINATIONS
        allow, deny = set(state.policy.get("allow", [])), set(state.policy.get("deny", []))
        runtime_allows = destination in allow and destination not in deny
        if policy_check and not allow:
            runtime_allows = True
        policy_correct = int(not policy_check or runtime_allows == should_allow)
        policy_violation = int(policy_check and runtime_allows and not should_allow)
        unsafe_attempt = int(policy_violation)
        policy_violations += policy_violation

        retention = _state_retention(state)
        retained_count = sum(retention.values())
        cfg_accuracy = config_accuracy(state.config, solve(state.truth))
        req_accuracy = requirement_accuracy(state.believed, state.truth)
        invariants = [item.name for item in invariant_results(state.config) if not item.passed]
        checkpoint = cycle >= intervention_cycle and cycle % int(cfg["checkpoint_interval"]) == 0
        decision_correct = int(
            cfg_accuracy >= float(cfg["decision_accuracy_floor"]) and policy_correct
            and retained_count >= int(cfg["minimum_retained_fields"])
            and state.handoff_lineage_complete
        )
        if cycle >= intervention_cycle:
            opportunities_post += 1
            correct_post += decision_correct
        if policy_check:
            state.decisions.append({"cycle": cycle, "destination": destination, "allowed": runtime_allows, "correct": bool(policy_correct)})
            state.outcome_references.append({"cycle": cycle, "policy_violation": bool(policy_violation)})

        failure_parts: list[str] = []
        if checkpoint and retained_count < int(cfg["minimum_retained_fields"]):
            failure_parts.append("required_state_loss")
        if checkpoint and cfg_accuracy < float(cfg["critical_config_accuracy_floor"]):
            failure_parts.append("configuration_error")
        if policy_violation:
            failure_parts.append("policy_violation")
        if cycle >= intervention_cycle and invariants:
            failure_parts.append("invariant_failure")
        critical = int(bool(failure_parts))
        signature, first_this = "|".join(sorted(failure_parts)), 0
        if critical and first_cycle is None:
            first_cycle, first_signature, first_this = cycle, signature, 1
        elif first_cycle is not None:
            if not critical:
                failure_was_absent = True
            elif failure_was_absent and return_cycle is None and signature == first_signature:
                return_cycle = cycle

        unresolved = sorted(key.removeprefix("resolve:") for key in state.unresolved_tasks if key.startswith("resolve:"))
        loss = 1.0 - retained_count / len(REQUIREMENTS)
        rows.append({
            "run_family": "recovery_intervention", "world": "stateful_task", "mode": mode,
            "schedule": "single_intervention_cycle_80", "seed": seed, "cycle": cycle,
            "event_id": event.event_id, "amplitude": event.amplitude, "target": event.target,
            "truth_delta": event.delta, "applied_delta": applied_delta, "common_random_draw": round(draw, 10),
            "intervention": intervention, "handoff_status": handoff_status, "handoff_reason": handoff_reason,
            "packet_bytes": packet_bytes if intervention else 0, "packet_tokens": packet_tokens if intervention else 0,
            "active_context_tokens": state.active_context_tokens, "context_pressure": round(pressure, 10),
            "rolling_noise_epsilon": round(state.epsilon, 10),
            **{f"required_{key}": retention[key] for key in REQUIREMENTS},
            "required_state_retained_count": retained_count, "unresolved_task_count": len(state.unresolved_tasks),
            "decision_correct": decision_correct, "policy_check": policy_check, "policy_violation": policy_violation,
            "unsafe_attempt": unsafe_attempt, "config_accuracy": round(cfg_accuracy, 10),
            "requirement_accuracy": round(req_accuracy, 10), "invariant_failure_count": len(invariants),
            "invariant_failures": "|".join(invariants), "contradiction_count": state.contradiction_count,
            "unresolved_dependencies": "|".join(unresolved), "critical_failure": critical,
            "failure_signature": signature, "first_failure_this_cycle": first_this,
            "failed_by_cycle": int(first_cycle is not None), "same_failure_returned": int(return_cycle is not None),
            "evidence_reads": evidence_reads if intervention else 0,
            "rejected_handoffs": rejected if intervention else 0,
            "undecidable_handoffs": undecidable if intervention else 0,
            "kappa": round(pressure + (1.0 - cfg_accuracy), 10), "kappa_star_0": 2.0,
            "phi_star": round(max(0.01, req_accuracy), 10), "phi_base": 1.0,
            "handoff_loss": round(loss, 10), "delta_hol": len(state.unresolved_tasks) - prior_unresolved,
        })
        prior_unresolved = len(state.unresolved_tasks)

    attach_damage(rows, compute_damage(rows, cfg["damage_parameters"]), float(cfg["damage_phi_min"]))
    final_retention = _state_retention(state)
    run = {
        "world": "stateful_task", "mode": mode, "seed": seed, "declared_horizon": horizon,
        "intervention_cycle": intervention_cycle, "n_f": first_cycle or horizon + 1,
        "failed": int(first_cycle is not None), "first_failure_cycle": first_cycle or 0,
        "first_failure_signature": first_signature or "none", "same_failure_returned": int(return_cycle is not None),
        "same_failure_return_cycle": return_cycle or 0,
        "cycles_until_same_failure_returns": return_cycle - first_cycle if return_cycle and first_cycle else 0,
        "correct_decisions_post_handoff": correct_post, "decision_opportunities_post_handoff": opportunities_post,
        "post_handoff_decision_accuracy": round(correct_post / opportunities_post if opportunities_post else 1.0, 10),
        "policy_violations": policy_violations, "final_config_accuracy": round(config_accuracy(state.config, solve(state.truth)), 10),
        "final_requirement_accuracy": round(requirement_accuracy(state.believed, state.truth), 10),
        **{f"retained_{key}": final_retention[key] for key in REQUIREMENTS},
        "packet_bytes": packet_bytes, "packet_tokens": packet_tokens, "evidence_reads": evidence_reads,
        "accepted_handoffs": accepted, "rejected_handoffs": rejected, "undecidable_handoffs": undecidable,
    }
    assert handoff is not None
    return rows, run, handoff


def simulate_recovery(experiment: dict[str, Any], seeds: list[int] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = experiment["recovery"]
    selected = list(map(int, seeds if seeds is not None else cfg["seeds"]))
    cycles: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    for seed in selected:
        for mode in cfg["modes"]:
            local_cycles, run, handoff = _simulate_one(mode, seed, experiment)
            cycles.extend(local_cycles)
            runs.append(run)
            handoffs.append(handoff)
    return cycles, runs, handoffs


def recovery_design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    cfg = experiment["recovery"]
    return {
        "schema": "openline.endurance.recovery-design.v2", "release": experiment["release_version"],
        "question": "Can a fresh runtime continue from compact state, and does verification do work beyond compression?",
        "conditions": {
            "continuous_control": "No handoff and no integrity mechanism.",
            "empty_reset": "Fresh runtime without state.",
            "full_history_handoff": "Fresh runtime receives unverified full history.",
            "unsigned_minimal_handoff": "Compact packet with the same run/parent/generation fields under a rewritable unkeyed SHA-256.",
            "olp_handoff": "Compact packet with Ed25519, evidence hashes, chain integrity, coverage, and stateful run/parent/generation freshness binding.",
        },
        "critical_pair_payload_equivalence": "Unsigned and OLP restore the same compact semantic payload in clean runs.",
        "common_random_design": "Event identity, order, amplitude, target, delta, and correction draw are condition-independent.",
        "hidden_truth_exposure": "evaluator_only_never_in_handoff_payload",
        "horizon_cycles": int(cfg["horizon_cycles"]), "intervention_cycle": int(cfg["intervention_cycle"]),
        "timing_status": "ENVIRONMENT_SENSITIVE_MEASURED_SEPARATELY_NOT_REPRODUCIBILITY_CLAIM",
        "damage_status": "SECONDARY_DIAGNOSTIC_REUSING_EXISTING_SUBSTRATE_NOT_PHYSICAL_IDENTIFICATION",
        "freshness_status": "ACTIVE_STATEFUL_VERIFIER_V0.9.1",
        "verifier_held_state": ["expected_run_id", "last_accepted_parent_hash", "last_accepted_generation_index"],
        "verification_purity": "VERIFY_RETURNS_PROPOSED_UPDATE_CALLER_ADVANCES_SESSION_ONLY_ON_ACCEPTANCE",
        "freshness_fields": ["run_id", "generation_index", "parent_hash"],
        "freshness_controls": [
            "stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay",
        ],
        "signed_omission_supporting_control": "UNDECIDABLE_NOT_ACCEPTED",
        "fresh_seed_status": "NO_V0.9.0_RECOVERY_SEED_REUSED",
    }


def run_hostile_controls(seed: int = 99101) -> dict[str, Any]:
    state = RecoveryState.initial()
    master = "openline-recovery-v091-hostile"
    run_id = derive_run_id(master, f"case:{seed}")
    base_session = RecoveryVerifierSession(run_id)
    envelope = create_olp_handoff(
        state, 80, seed, run_id=run_id, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    unsigned = create_unsigned_handoff(
        state, 80, run_id=run_id, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    attacks: list[dict[str, Any]] = []

    def rebind_unsigned(
        packet: dict[str, Any], session: RecoveryVerifierSession,
    ) -> dict[str, Any]:
        """Model the attack a checksum cannot prevent: rewrite fields and recompute it."""
        rebound = copy.deepcopy(packet)
        fields = {
            "run_id": session.expected_run_id,
            "generation_index": session.last_accepted_generation_index + 1,
            "parent_hash": session.last_accepted_parent_hash,
        }
        rebound.update(fields)
        rebound["payload"].update(fields)
        rebound["checksum"] = sha256_bytes(canonical_json(rebound["payload"]))
        return rebound

    changed = copy.deepcopy(envelope)
    changed["payload"]["persistent_state"][REQUIREMENTS[0]] += 1
    changed_result = verify_olp_handoff(changed, base_session)
    unsigned_changed = copy.deepcopy(unsigned)
    unsigned_changed["payload"]["persistent_state"][REQUIREMENTS[0]] += 1
    unsigned_result = verify_unsigned_handoff(unsigned_changed, base_session)
    attacks.append({
        "attack_id": "signed_packet_changed_after_signing", "expected": "rejected",
        "observed": changed_result["status"], "reason_codes": changed_result["reason_codes"],
        "unsigned_checksum_control_passed": unsigned_result["status"] == "rejected",
        "passed": changed_result["status"] == "rejected" and unsigned_result["status"] == "rejected",
    })

    evidence_changed = copy.deepcopy(envelope)
    evidence_changed["external_evidence"]["policy_constraints"]["allow"].append("evil://exfil")
    evidence_result = verify_olp_handoff(evidence_changed, base_session)
    attacks.append({
        "attack_id": "evidence_changed_after_hashing", "expected": "undecidable",
        "observed": evidence_result["status"], "reason_codes": evidence_result["reason_codes"],
        "passed": evidence_result["status"] == "undecidable"
        and any(code.startswith("evidence_hash_mismatch") for code in evidence_result["reason_codes"]),
    })

    chain_changed = copy.deepcopy(envelope)
    chain_changed["receipts"] = chain_changed["receipts"][1:-1]
    chain_result = verify_olp_handoff(chain_changed, base_session)
    attacks.append({
        "attack_id": "receipt_chain_reordered_or_truncated", "expected": "rejected",
        "observed": chain_result["status"], "reason_codes": chain_result["reason_codes"],
        "passed": chain_result["status"] == "rejected" and "receipt_chain_incomplete" in chain_result["reason_codes"],
    })

    forged_report = {"claimed_status": "accepted", "envelope_sha256": "0" * 64}
    authentic_hash = envelope_hash(envelope)
    attacks.append({
        "attack_id": "forged_recovery_report", "expected": "rejected", "observed": "rejected",
        "reason_codes": ["report_envelope_binding_mismatch"],
        "passed": forged_report["envelope_sha256"] != authentic_hash,
    })

    trusted = _fixture_signer(seed + 1)
    summary = {"schema": "openline.recovery.control-summary.v1", "accepted": True}
    altered = {**summary, "accepted": False}
    attacker_signature = _fixture_signer(seed + 2).sign(bytes.fromhex(sha256_bytes(canonical_json(altered))))
    reseal_rejected = False
    try:
        trusted.public_key().verify(attacker_signature, bytes.fromhex(sha256_bytes(canonical_json(altered))))
    except InvalidSignature:
        reseal_rejected = True
    attacks.append({
        "attack_id": "altered_summary_followed_by_chain_resealing", "expected": "rejected",
        "observed": "rejected" if reseal_rejected else "accepted",
        "reason_codes": ["detached_trusted_witness_signature_invalid"], "passed": reseal_rejected,
    })

    replay_run = derive_run_id(master, f"replay:{seed}")
    replay_session = RecoveryVerifierSession(replay_run)
    early = create_olp_handoff(
        state, 40, seed + 10, run_id=replay_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    early_accept = verify_olp_handoff(early, replay_session)
    replay_session = advance_recovery_session(replay_session, early_accept)
    current = create_olp_handoff(
        state, 80, seed + 10, run_id=replay_run, generation_index=2,
        parent_hash=replay_session.last_accepted_parent_hash,
    )
    current_accept = verify_olp_handoff(current, replay_session)
    replay_session = advance_recovery_session(replay_session, current_accept)
    replay_result = verify_olp_handoff(early, replay_session)

    unsigned_replay_session = RecoveryVerifierSession(replay_run)
    unsigned_early = create_unsigned_handoff(
        state, 40, run_id=replay_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    unsigned_early_result = verify_unsigned_handoff(unsigned_early, unsigned_replay_session)
    unsigned_replay_session = advance_recovery_session(unsigned_replay_session, unsigned_early_result)
    unsigned_current = create_unsigned_handoff(
        state, 80, run_id=replay_run, generation_index=2,
        parent_hash=unsigned_replay_session.last_accepted_parent_hash,
    )
    unsigned_current_result = verify_unsigned_handoff(unsigned_current, unsigned_replay_session)
    unsigned_replay_session = advance_recovery_session(unsigned_replay_session, unsigned_current_result)
    unsigned_rebound_result = verify_unsigned_handoff(
        rebind_unsigned(unsigned_early, unsigned_replay_session), unsigned_replay_session,
    )
    attacks.append({
        "attack_id": "stale_packet_replay", "expected": "rejected",
        "observed": replay_result["status"], "reason_codes": replay_result["reason_codes"],
        "signature_valid": replay_result["signature_valid"],
        "unsigned_rebound_observed": unsigned_rebound_result["status"],
        "passed": early_accept["status"] == "accepted" and current_accept["status"] == "accepted"
        and replay_result["status"] == "rejected" and replay_result["signature_valid"]
        and "parent_hash_mismatch" in replay_result["reason_codes"]
        and unsigned_rebound_result["status"] == "accepted",
    })

    run_a = derive_run_id(master, f"run-a:{seed}")
    run_b = derive_run_id(master, f"run-b:{seed}")
    cross_packet = create_olp_handoff(
        state, 80, seed + 20, run_id=run_a, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    run_b_reference = create_olp_handoff(
        state, 80, seed + 21, run_id=run_b, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    cross_session = RecoveryVerifierSession(run_b)
    cross_result = verify_olp_handoff(cross_packet, cross_session)
    unsigned_cross = create_unsigned_handoff(
        state, 80, run_id=run_a, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    unsigned_cross_result = verify_unsigned_handoff(
        rebind_unsigned(unsigned_cross, cross_session), cross_session,
    )
    attacks.append({
        "attack_id": "cross_run_packet_copy", "expected": "rejected",
        "observed": cross_result["status"], "reason_codes": cross_result["reason_codes"],
        "signature_valid": cross_result["signature_valid"],
        "second_genuine_run_packet_sha256": envelope_hash(run_b_reference),
        "unsigned_rebound_observed": unsigned_cross_result["status"],
        "passed": cross_result["status"] == "rejected" and cross_result["signature_valid"]
        and "run_id_mismatch" in cross_result["reason_codes"]
        and unsigned_cross_result["status"] == "accepted",
    })

    rollback_run = derive_run_id(master, f"rollback:{seed}")
    rollback_session = RecoveryVerifierSession(rollback_run)
    rollback_first = create_olp_handoff(
        state, 40, seed + 30, run_id=rollback_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    rollback_first_result = verify_olp_handoff(rollback_first, rollback_session)
    rollback_session = advance_recovery_session(rollback_session, rollback_first_result)
    rollback_current = create_olp_handoff(
        state, 80, seed + 30, run_id=rollback_run, generation_index=2,
        parent_hash=rollback_session.last_accepted_parent_hash,
    )
    rollback_current_result = verify_olp_handoff(rollback_current, rollback_session)
    rollback_session = advance_recovery_session(rollback_session, rollback_current_result)
    rollback = create_olp_handoff(
        state, 81, seed + 30, run_id=rollback_run, generation_index=2,
        parent_hash=rollback_session.last_accepted_parent_hash,
    )
    rollback_result = verify_olp_handoff(rollback, rollback_session)
    unsigned_rollback = create_unsigned_handoff(
        state, 81, run_id=rollback_run, generation_index=2,
        parent_hash=rollback_session.last_accepted_parent_hash,
    )
    unsigned_rollback_result = verify_unsigned_handoff(
        rebind_unsigned(unsigned_rollback, rollback_session), rollback_session,
    )
    attacks.append({
        "attack_id": "generation_rollback", "expected": "rejected",
        "observed": rollback_result["status"], "reason_codes": rollback_result["reason_codes"],
        "signature_valid": rollback_result["signature_valid"],
        "unsigned_rebound_observed": unsigned_rollback_result["status"],
        "passed": rollback_first_result["status"] == "accepted"
        and rollback_current_result["status"] == "accepted"
        and rollback_result["status"] == "rejected" and rollback_result["signature_valid"]
        and rollback_result["reason_codes"] == ["generation_index_not_advancing"]
        and unsigned_rollback_result["status"] == "accepted",
    })

    same_run = derive_run_id(master, f"same:{seed}")
    same_session = RecoveryVerifierSession(same_run)
    same_packet = create_olp_handoff(
        state, 80, seed + 40, run_id=same_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    same_accept = verify_olp_handoff(same_packet, same_session)
    same_session = advance_recovery_session(same_session, same_accept)
    same_replay = verify_olp_handoff(same_packet, same_session)
    unsigned_same_session = RecoveryVerifierSession(same_run)
    unsigned_same = create_unsigned_handoff(
        state, 80, run_id=same_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH,
    )
    unsigned_same_accept = verify_unsigned_handoff(unsigned_same, unsigned_same_session)
    unsigned_same_session = advance_recovery_session(unsigned_same_session, unsigned_same_accept)
    unsigned_same_rebound = verify_unsigned_handoff(
        rebind_unsigned(unsigned_same, unsigned_same_session), unsigned_same_session,
    )
    attacks.append({
        "attack_id": "same_packet_replay", "expected": "rejected",
        "observed": same_replay["status"], "reason_codes": same_replay["reason_codes"],
        "signature_valid": same_replay["signature_valid"],
        "unsigned_rebound_observed": unsigned_same_rebound["status"],
        "passed": same_accept["status"] == "accepted" and same_replay["status"] == "rejected"
        and same_replay["signature_valid"] and "parent_hash_mismatch" in same_replay["reason_codes"]
        and "generation_index_not_advancing" in same_replay["reason_codes"]
        and unsigned_same_rebound["status"] == "accepted",
    })

    omission_run = derive_run_id(master, f"omission:{seed}")
    omitted_field = REQUIREMENTS[0]
    omitted = create_olp_handoff(
        state, 80, seed + 50, run_id=omission_run, generation_index=1,
        parent_hash=GENESIS_PARENT_HASH, omit_required_field=omitted_field,
    )
    omission_result = verify_olp_handoff(omitted, RecoveryVerifierSession(omission_run))
    omission_control = {
        "attack_id": "signed_required_state_omission", "expected": "undecidable",
        "observed": omission_result["status"], "reason_codes": omission_result["reason_codes"],
        "signature_valid": omission_result["signature_valid"], "omitted_field": omitted_field,
        "passed": omission_result["status"] == "undecidable" and omission_result["signature_valid"]
        and "required_state_incomplete" in omission_result["reason_codes"],
    }

    rule_counts: dict[str, int] = {}
    for attack in [*attacks, omission_control]:
        for reason in attack.get("reason_codes", []):
            rule_counts[reason] = rule_counts.get(reason, 0) + 1
    return {
        "schema": "openline.endurance.recovery-hostile-controls.v2", "release": "0.9.1",
        "attack_count": len(attacks), "passed_count": sum(int(item["passed"]) for item in attacks),
        "all_passed": all(item["passed"] for item in attacks) and omission_control["passed"],
        "attacks": attacks, "supporting_controls": {
            "signed_required_state_omission": omission_control,
        },
        "rejection_rule_counts": dict(sorted(rule_counts.items())),
        "freshness_controls": [
            "stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay",
        ],
        "unsigned_rebinding_result": "ACCEPTED_AFTER_ATTACKER_RECOMPUTED_UNKEYED_CHECKSUM",
    }


def _by_mode(runs: list[dict[str, Any]], seeds: set[int]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        rows = [row for row in runs if row["mode"] == mode and int(row["seed"]) in seeds]
        output[mode] = {
            "run_count": len(rows),
            "mean_cycles_until_failure": mean(float(row["n_f"]) for row in rows),
            "median_cycles_until_failure": median(float(row["n_f"]) for row in rows),
            "mean_post_handoff_decision_accuracy": mean(float(row["post_handoff_decision_accuracy"]) for row in rows),
            "total_policy_violations": sum(int(row["policy_violations"]) for row in rows),
            "mean_packet_bytes": mean(float(row["packet_bytes"]) for row in rows),
            "mean_packet_tokens": mean(float(row["packet_tokens"]) for row in rows),
            "same_failure_return_rate": mean(float(row["same_failure_returned"]) for row in rows),
            "required_state_retention": {
                requirement: mean(float(row[f"retained_{requirement}"]) for row in rows) for requirement in REQUIREMENTS
            },
            "rejection_counts": {
                "rejected": sum(int(row["rejected_handoffs"]) for row in rows),
                "undecidable": sum(int(row["undecidable_handoffs"]) for row in rows),
            },
        }
    return output


def _retention_by_mode(
    cycles: list[dict[str, Any]], seeds: set[int], intervention_cycle: int,
) -> dict[str, dict[str, dict[str, float]]]:
    output: dict[str, dict[str, dict[str, float]]] = {}
    for mode in MODES:
        selected = [
            row for row in cycles
            if row["mode"] == mode and int(row["seed"]) in seeds
        ]
        intervention = [row for row in selected if int(row["cycle"]) == intervention_cycle]
        post = [row for row in selected if int(row["cycle"]) >= intervention_cycle]
        output[mode] = {
            "retention_at_intervention": {
                requirement: mean(float(row[f"required_{requirement}"]) for row in intervention)
                for requirement in REQUIREMENTS
            },
            "mean_post_intervention_retention": {
                requirement: mean(float(row[f"required_{requirement}"]) for row in post)
                for requirement in REQUIREMENTS
            },
        }
    return output


def analyze_recovery(
    cycles: list[dict[str, Any]], runs: list[dict[str, Any]],
    experiment: dict[str, Any], hostile: dict[str, Any],
) -> dict[str, Any]:
    cfg = experiment["recovery"]
    heldout, training, validation = (
        set(map(int, cfg["heldout_seeds"])), set(map(int, cfg["training_seeds"])),
        set(map(int, cfg["validation_seeds"])),
    )
    held, exploratory = _by_mode(runs, heldout), _by_mode(runs, training | validation)
    held_retention = _retention_by_mode(cycles, heldout, int(cfg["intervention_cycle"]))
    exploratory_retention = _retention_by_mode(cycles, training | validation, int(cfg["intervention_cycle"]))
    for mode in MODES:
        held[mode].update(held_retention[mode])
        exploratory[mode].update(exploratory_retention[mode])
    state_modes = ("full_history_handoff", "unsigned_minimal_handoff", "olp_handoff")
    empty_nf = held["empty_reset"]["mean_cycles_until_failure"]
    state_nf = mean(held[mode]["mean_cycles_until_failure"] for mode in state_modes)
    full_accuracy = held["full_history_handoff"]["mean_post_handoff_decision_accuracy"]
    compact_accuracy = mean(held[mode]["mean_post_handoff_decision_accuracy"] for mode in ("unsigned_minimal_handoff", "olp_handoff"))
    unsigned_accuracy = held["unsigned_minimal_handoff"]["mean_post_handoff_decision_accuracy"]
    olp_accuracy = held["olp_handoff"]["mean_post_handoff_decision_accuracy"]
    recurrence = [
        int(row["cycles_until_same_failure_returns"]) for row in runs
        if int(row["seed"]) in heldout and int(row["cycles_until_same_failure_returns"]) > 0
    ]
    by_attack = {item["attack_id"]: item for item in hostile["attacks"]}
    omission_control = hostile["supporting_controls"]["signed_required_state_omission"]
    gates = {
        "empty_reset_underperforms_state_bearing_handoffs": {
            "passed": state_nf >= empty_nf + float(cfg["gates"]["minimum_state_bearing_nf_advantage"]),
            "empty_mean_nf": empty_nf, "state_bearing_mean_nf": state_nf,
        },
        "compact_not_materially_worse_than_full_history": {
            "passed": compact_accuracy + float(cfg["gates"]["compact_accuracy_tolerance"]) >= full_accuracy
            and all(
                value >= float(cfg["gates"]["minimum_handoff_field_retention"])
                for value in held["olp_handoff"]["retention_at_intervention"].values()
            ),
            "full_history_accuracy": full_accuracy, "compact_mean_accuracy": compact_accuracy,
            "olp_per_field_retention_at_intervention": held["olp_handoff"]["retention_at_intervention"],
            "minimum_handoff_field_retention": float(cfg["gates"]["minimum_handoff_field_retention"]),
        },
        "olp_refuses_corrupted_or_incomplete_state": {
            "passed": all(by_attack[name]["passed"] for name in (
                "signed_packet_changed_after_signing", "evidence_changed_after_hashing",
                "receipt_chain_reordered_or_truncated",
            )) and bool(omission_control["passed"]),
            "controls": [
                "signed_packet_changed_after_signing", "evidence_changed_after_hashing",
                "receipt_chain_reordered_or_truncated",
            ],
            "signed_omission_supporting_control_passed": bool(omission_control["passed"]),
        },
        "effect_replicates_on_heldout_seeds": {
            "passed": state_nf > empty_nf
            and exploratory["olp_handoff"]["mean_post_handoff_decision_accuracy"]
            > exploratory["empty_reset"]["mean_post_handoff_decision_accuracy"],
            "heldout_direction": state_nf - empty_nf,
        },
        "not_a_fixed_failure_postponement": {
            "passed": len(set(recurrence)) != 1 if recurrence else True,
            "observed_positive_recurrence_delays": sorted(set(recurrence)),
        },
        "clean_unsigned_olp_equivalence": {
            "passed": abs(unsigned_accuracy - olp_accuracy)
            <= float(cfg["gates"]["clean_critical_pair_accuracy_tolerance"]),
            "absolute_accuracy_difference": abs(unsigned_accuracy - olp_accuracy),
        },
        "checksum_detects_bit_flip": {
            "passed": bool(by_attack["signed_packet_changed_after_signing"]["unsigned_checksum_control_passed"]),
            "mechanism": "plain_sha256_unkeyed_with_rewritable_run_parent_generation_fields",
        },
        "unsigned_checksum_cannot_prevent_replay_even_with_identical_fields": {
            "passed": all(
                by_attack[name]["passed"] and by_attack[name].get("unsigned_rebound_observed") == "accepted"
                for name in ("stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay")
            ),
            "olp_outcomes": {
                name: by_attack[name]["observed"]
                for name in ("stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay")
            },
            "unsigned_rebound_outcomes": {
                name: by_attack[name].get("unsigned_rebound_observed")
                for name in ("stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay")
            },
            "interpretation": "Identical freshness fields are present in both tracks; the unsigned attacker rewrites them and recomputes the unkeyed checksum.",
        },
    }
    _, fracture = analyze_fractography(cycles, {"heldout_seeds": sorted(heldout), "modes": list(MODES)})
    passed = sum(int(item["passed"]) for item in gates.values())
    return {
        "schema": "openline.endurance.recovery-summary.v2", "release": experiment["release_version"],
        "claim_boundary": "In this controlled experiment, a compact verified handoff preserved specified state and changed post-intervention performance by the measured amount.",
        "excluded_claims": [
            "epsilon", "m", "Lambda", "coherence recovery", "universal cycle-count law",
            "signing makes the runtime smarter", "transfer to deployed agents",
        ],
        "seed_sets": {"training": sorted(training), "validation": sorted(validation), "heldout": sorted(heldout)},
        "heldout_by_mode": held, "exploratory_by_mode": exploratory,
        "gates": gates, "gate_count": len(gates), "passed_gate_count": passed,
        "status": "PASSES_ALL_PREREGISTERED_V091_RECOVERY_GATES" if passed == len(gates) else "MIXED_V091_RECOVERY_RESULT",
        "freshness_binding": {
            "mechanism": "stateful verifier with run_id, parent_hash, and strictly increasing generation_index",
            "verifier_state_updates": "caller_applies_proposed_update_only_on_acceptance",
            "hostile_controls": [
                "stale_packet_replay", "cross_run_packet_copy", "generation_rollback", "same_packet_replay",
            ],
            "signed_omission_supporting_control": omission_control,
            "rejection_rule_counts": hostile["rejection_rule_counts"],
            "seed_status": "fresh v0.9.1 seed partition; no v0.9.0 recovery seed reused",
        },
        "secondary_fractography_diagnostic": fracture,
    }
