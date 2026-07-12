from __future__ import annotations

import csv
import gzip
import json
import math
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .collision_spacing import (
    analyze_collision_spacing, collision_design_witness, simulate_collision_spacing,
)
from .damage import (
    annotate_failed_before,
    attach_damage,
    compare_models,
    compute_damage,
    damage_diagnostics,
    select_damage_parameters,
)
from .experiment import (
    BASE_SEMANTIC_ARTIFACTS, V6_SEMANTIC_ARTIFACTS, V7_SEMANTIC_ARTIFACTS,
    _design_witness, combine_summaries, load_experiment,
)
from .fractography import analyze_fractography
from .generational import (
    analyze_generational_endurance, generational_design_witness, simulate_generational_endurance,
)
from .state_restoration import (
    analyze_state_restoration, state_restoration_design_witness,
)
from .restoration_stream import cycle_shard_names, stream_state_restoration
from .integrity import (
    build_public_witness, merkle_root, verify_preregistration,
    verify_v040_lineage, verify_v050_lineage, verify_v060_lineage,
)
from .receipts import read_chain, verify_chain
from .release_attestation import verify_release_attestation
from .sim import calibrate_fresh
from .summarize import build_summary
from .tip_capture import analyze_tip_capture, simulate_tip_capture, tip_design_witness
from .util import canonical_json, mean, read_csv, sha256_bytes, sha256_file


INT_FIELDS = {
    "seed", "cycle", "truth_delta", "applied_delta", "correction_required", "correction_success", "checkpoint",
    "checkpoint_failed", "unsafe_attempt", "first_failure_this_cycle", "failed_by_cycle", "failed_before_cycle",
    "invariant_failure_count", "known_dependency_count", "unresolved_dependency_count", "contradiction_count",
    "retry_count", "repair_succeeded", "repaired_invariant_count", "repaired_field_count", "representation_tokens",
    "total_tokens", "subcritical_failure", "cycles", "n_f", "failed", "unsafe_attempts", "repair_successes",
    "subcritical_first_failure", "first_failure_cycle", "crack_initiation_cycle", "peak_cycle", "max_crack_load",
    "crack_burden", "longest_active_span", "repair_half_life_cycles", "cycles_from_crack_to_failure",
    "attached_to_existing", "selected_parent_depth", "selected_parent_is_tip", "selected_parent_capture_window",
    "selected_parent_open_neighbors", "selected_parent_local_density", "top_decile_capture", "new_node_depth",
    "new_node_x", "new_node_y", "walker_used", "walker_start_x", "walker_start_y", "walker_steps",
    "walker_restarts", "walker_fallback", "violation", "system_failure", "active_unresolved", "active_tips",
    "branch_count", "max_burial_depth", "interior_count", "context_length", "repair_attempted",
    "repair_target_depth", "repair_target_was_tip", "repair_success", "repair_policy_budget_used",
    "receipt_enabled", "visible_pointer_losses", "violations", "final_active_unresolved", "final_active_tips",
    "max_active_unresolved", "repair_attempts", "repair_budget_used", "recovery_probes", "recovery_successes", "event_count",
    "unresolved_count", "node_age", "branch_age", "is_tip", "depth", "node_x", "node_y",
    "open_neighbor_count", "local_density", "capture_count_window", "child_count", "shielded_cycles",
    "branch_size", "label", "tip_depth", "receipt_used", "success", "walker_attachment_count",
    "walker_fallback_count",
    "recovery_cost",
    "event_index", "event_time", "gap", "active_conflict_count", "first_failure_this_event",
    "declared_horizon", "last_event_time", "failures", "first_failure_event", "adjacent_conflict_count",
    "conflicting_pair_count", "conflict_degree",
    "generation", "generation_boundary", "handoff_omission_count", "continuity_checkpoint_failed",
    "active_context_tokens", "external_record_tokens", "critical_omission_count", "critical_omission",
    "retrieval_required", "retrieval_success", "retrieval_quarantined", "capsule_full_block_count",
    "capsule_pointer_count", "capsule_verified", "unresolved_dependency_count", "critical_failure",
    "total_active_token_work", "total_external_retrievals", "total_quarantines",
    "survival_40", "survival_80", "survival_160", "survival_320", "peak_active_context_tokens", "critical_omissions_40", "critical_omissions_80",
    "critical_omissions_160", "external_retrievals", "successful_retrievals", "quarantines",
    "capsule_boundary", "restoration_triggered", "restored_requirement_count", "pruned_tokens",
    "ecc_corrections", "critical_omission_count", "total_restorations", "total_pruned_tokens",
    "total_ecc_corrections", "restorations",
}
FLOAT_FIELDS = {
    "difficulty", "config_accuracy", "requirement_accuracy", "context_pressure", "handoff_loss", "kappa",
    "kappa_star_0", "phi_star", "phi_base", "epsilon", "delta_hol", "vkd", "damage_D", "kappa_star_eff",
    "vkd_f", "mean_checkpoint_accuracy", "final_config_accuracy", "final_requirement_accuracy",
    "selected_parent_branch_share", "top_decile_expected_share", "largest_branch_share", "branch_hhi",
    "selected_parent_radial_distance", "radial_distance", "walker_fallback_rate", "mean_walker_steps",
    "mean_burial_depth", "mean_interior_shielded_cycles", "mean_top_decile_capture",
    "mean_top_decile_expected_share", "frontier_capture_lift", "recovery_rate", "mean_recovery_cost",
    "mean_recovery_depth", "branch_capture_share",
    "collision_burden", "damage_before", "damage_after", "failure_probability",
    "common_random_draw", "mean_collision_burden", "peak_collision_burden", "damage_auc", "peak_damage",
    "final_event_damage",
    "continuity_checkpoint_accuracy", "recent_conflict_burden",
    "mean_active_context_tokens_40", "mean_active_context_tokens_80", "mean_active_context_tokens_160",
    "mean_checkpoint_accuracy_40", "mean_checkpoint_accuracy_80",
    "mean_checkpoint_accuracy_160", "critical_omission_rate_40", "critical_omission_rate_80",
    "critical_omission_rate_160", "mean_active_context_tokens_320", "mean_checkpoint_accuracy_320",
    "critical_omission_rate_320", "rolling_noise_epsilon", "structural_defect",
    "coherence_margin_proxy", "stability_lambda_proxy", "mean_epsilon_160", "mean_epsilon_320",
    "minimum_margin_160", "minimum_margin_320",
}


def _coerce_row(row: dict[str, str]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in row.items():
        if value == "":
            converted[key] = None
        elif key in INT_FIELDS:
            converted[key] = int(float(value))
        elif key in FLOAT_FIELDS:
            converted[key] = float(value)
        else:
            converted[key] = value
    return converted


def _coerce(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [_coerce_row(row) for row in rows]


def _csv_merkle_root(path: Path) -> tuple[str, int]:
    """Compute the canonical row Merkle root without retaining CSV rows.

    This is equivalent to ``merkle_root(_coerce(read_csv(path)))`` but keeps
    verifier memory bounded by the leaf hashes rather than the full graph.
    """
    leaves: list[str] = []
    count = 0
    opener = gzip.open if path.suffix == ".gz" else Path.open
    if path.suffix == ".gz":
        handle_context = opener(path, "rt", newline="", encoding="utf-8")
    else:
        handle_context = opener(path, "r", newline="", encoding="utf-8")
    with handle_context as handle:
        for raw in csv.DictReader(handle):
            leaves.append(sha256_bytes(canonical_json(_coerce_row(raw))))
            count += 1
    if not leaves:
        return sha256_bytes(b""), 0
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [
            sha256_bytes(bytes.fromhex(level[index]) + bytes.fromhex(level[index + 1]))
            for index in range(0, len(level), 2)
        ]
    return level[0], count


def _close(a: Any, b: Any, tol: float = 1e-8) -> bool:
    if (a is None and b == "") or (b is None and a == ""):
        return True
    if isinstance(a, tuple):
        a = list(a)
    if isinstance(b, tuple):
        b = list(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_close(a[key], b[key], tol) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(left, right, tol) for left, right in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(float(a)) and math.isnan(float(b)):
            return True
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    return a == b


def recompute_runs(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in cycles:
        groups[(str(row["run_family"]), str(row["mode"]), str(row["schedule"]), int(row["seed"]))].append(row)
    runs = []
    for key, rows in groups.items():
        rows = sorted(rows, key=lambda item: int(item["cycle"]))
        failures = [int(row["cycle"]) for row in rows if int(row["first_failure_this_cycle"])]
        first = failures[0] if failures else None
        checkpoints = [float(row["config_accuracy"]) for row in rows if int(row["checkpoint"])]
        runs.append(
            {
                "run_family": key[0],
                "mode": key[1],
                "schedule": key[2],
                "seed": key[3],
                "cycles": len(rows),
                "n_f": first if first is not None else len(rows) + 1,
                "failed": int(first is not None),
                "first_failure_cycle": first,
                "mean_checkpoint_accuracy": round(mean(checkpoints), 8) if checkpoints else None,
                "final_config_accuracy": rows[-1]["config_accuracy"],
                "final_requirement_accuracy": rows[-1]["requirement_accuracy"],
                "unsafe_attempts": sum(int(row["unsafe_attempt"]) for row in rows),
                "retry_count": int(rows[-1]["retry_count"]),
                "repair_successes": sum(int(row["repair_succeeded"]) for row in rows),
                "total_tokens": int(rows[-1]["total_tokens"]),
                "subcritical_first_failure": int(any(int(row["subcritical_failure"]) for row in rows)),
            }
        )
    return sorted(runs, key=lambda row: (row["run_family"], row["seed"], row["schedule"], row["mode"]))


def _sorted_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (row["run_family"], int(row["seed"]), str(row["schedule"]), str(row["mode"])))


def verify_manifest(root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.exists():
        return ["manifest_missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        path = root / entry["path"]
        if not path.exists():
            errors.append(f"manifest_missing:{entry['path']}")
        elif sha256_file(path) != entry["sha256"]:
            errors.append(f"manifest_hash_mismatch:{entry['path']}")
    source_entries = [
        entry for entry in manifest["entries"]
        if entry["path"].startswith(("src/", "tests/", "scripts/", "examples/"))
        or entry["path"] in {"pyproject.toml", "experiment.json", "PREREGISTRATION.json"}
    ]
    if sha256_bytes(canonical_json(source_entries)) != manifest["source_tree_digest"]:
        errors.append("source_tree_digest_mismatch")
    return errors


def _v5_expected_summary(root: Path, collision_summary: dict[str, Any]) -> dict[str, Any]:
    old_summary = json.loads((root / "lineage/v0.4.0/results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_AND_COLLISION_SPACING"
    summary["collision_spacing"] = collision_summary
    summary["legacy_scientific_result_preserved"] = {
        "status": old_summary["theory_status"],
        "passed_gate_count": old_summary["passed_gate_count"],
        "gate_count": old_summary["gate_count"],
    }
    return summary


def _verify_v5_semantics(root: Path, experiment: dict[str, Any], manifest: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    semantic_errors: list[str] = []
    spacing = experiment["collision_spacing"]
    stored_event_root, stored_event_count = _csv_merkle_root(root / "results/collision_spacing_events.csv")
    stored_run_root, stored_run_count = _csv_merkle_root(root / "results/collision_spacing_runs.csv")
    stored_runs = _coerce(read_csv(root / "results/collision_spacing_runs.csv"))
    expected_runs = len(spacing["seeds"]) * len(spacing["schedules"])
    expected_events = expected_runs * int(spacing["events_per_run"])
    if stored_run_count != expected_runs:
        semantic_errors.append(f"collision_spacing_run_count:{stored_run_count}:{expected_runs}")
    if stored_event_count != expected_events:
        semantic_errors.append(f"collision_spacing_event_count:{stored_event_count}:{expected_events}")

    collision_events, collision_runs = simulate_collision_spacing(experiment)
    fresh_event_root = merkle_root(collision_events)
    fresh_run_root = merkle_root(collision_runs)
    if fresh_event_root != stored_event_root:
        semantic_errors.append("collision_spacing_events_recompute_mismatch")
    if fresh_run_root != stored_run_root:
        semantic_errors.append("collision_spacing_runs_recompute_mismatch")
    if not _close(collision_runs, stored_runs, 1e-7):
        semantic_errors.append("collision_spacing_run_metrics_recompute_mismatch")

    collision_summary = analyze_collision_spacing(collision_runs, experiment)
    stored_collision_summary = json.loads((root / "results/collision_spacing_summary.json").read_text(encoding="utf-8"))
    if not _close(collision_summary, stored_collision_summary, 1e-7):
        semantic_errors.append("collision_spacing_summary_recompute_mismatch")
    design = collision_design_witness(experiment)
    stored_design = json.loads((root / "results/collision_spacing_design_witness.json").read_text(encoding="utf-8"))
    if not _close(design, stored_design):
        semantic_errors.append("collision_spacing_design_witness_recompute_mismatch")

    summary = _v5_expected_summary(root, collision_summary)
    stored_summary = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))
    if not _close(summary, stored_summary, 1e-7):
        semantic_errors.append("summary_semantic_recompute_mismatch")

    roots = json.loads((root / "lineage/v0.4.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    roots = dict(roots)
    roots["schema"] = "openline.endurance.cycle-roots.v2"
    roots["collision_spacing_event_merkle_root"] = fresh_event_root
    roots["collision_spacing_event_count"] = len(collision_events)
    roots["collision_spacing_run_merkle_root"] = fresh_run_root
    roots["collision_spacing_run_count"] = len(collision_runs)
    stored_roots = json.loads((root / "results/cycle_roots.json").read_text(encoding="utf-8"))
    if not _close(roots, stored_roots):
        semantic_errors.append("cycle_merkle_root_recompute_mismatch")
    for key in (
        "primary_cycle_merkle_root",
        "amplitude_cycle_merkle_root",
        "tip_capture_cycle_merkle_root",
        "tip_capture_candidate_merkle_root",
        "tip_capture_probe_merkle_root",
        "collision_spacing_event_merkle_root",
        "collision_spacing_run_merkle_root",
    ):
        if evidence.get(key) != roots.get(key):
            semantic_errors.append(f"evidence_{key}_mismatch")

    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        roots["primary_cycle_merkle_root"],
        roots["amplitude_cycle_merkle_root"],
        {
            "tip_capture_cycle_merkle_root": roots["tip_capture_cycle_merkle_root"],
            "tip_capture_candidate_merkle_root": roots["tip_capture_candidate_merkle_root"],
            "tip_capture_probe_merkle_root": roots["tip_capture_probe_merkle_root"],
            "collision_spacing_event_merkle_root": roots["collision_spacing_event_merkle_root"],
            "collision_spacing_run_merkle_root": roots["collision_spacing_run_merkle_root"],
        },
        list(BASE_SEMANTIC_ARTIFACTS),
    )
    stored_public_witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
    if not _close(public_witness, stored_public_witness):
        semantic_errors.append("public_witness_recompute_mismatch")
    if evidence.get("public_witness_digest") != public_witness["witness_digest"]:
        semantic_errors.append("evidence_public_witness_digest_mismatch")
    return semantic_errors



def _v6_expected_summary(root: Path, generational_summary: dict[str, Any]) -> dict[str, Any]:
    old_summary = json.loads((root / "lineage/v0.5.0/results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_COLLISION_SPACING_AND_GENERATIONAL_INHERITANCE"
    summary["generational_endurance"] = generational_summary
    summary["legacy_v050_result_preserved"] = {
        "status": old_summary["theory_status"],
        "passed_gate_count": old_summary["passed_gate_count"],
        "gate_count": old_summary["gate_count"],
        "collision_spacing": old_summary.get("collision_spacing", {}),
    }
    return summary


def _verify_v6_semantics(root: Path, experiment: dict[str, Any], manifest: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    semantic_errors: list[str] = []
    config = experiment["generational_endurance"]
    stored_cycle_root, stored_cycle_count = _csv_merkle_root(root / "results/generational_cycles.csv")
    stored_run_root, stored_run_count = _csv_merkle_root(root / "results/generational_runs.csv")
    stored_runs = _coerce(read_csv(root / "results/generational_runs.csv"))
    expected_runs = len(config["seeds"]) * 6
    expected_cycles = expected_runs * int(config["max_horizon_cycles"])
    if stored_run_count != expected_runs:
        semantic_errors.append(f"generational_run_count:{stored_run_count}:{expected_runs}")
    if stored_cycle_count != expected_cycles:
        semantic_errors.append(f"generational_cycle_count:{stored_cycle_count}:{expected_cycles}")

    cycles, runs = simulate_generational_endurance(experiment)
    fresh_cycle_root = merkle_root(cycles)
    fresh_run_root = merkle_root(runs)
    if fresh_cycle_root != stored_cycle_root:
        semantic_errors.append("generational_cycles_recompute_mismatch")
    if fresh_run_root != stored_run_root:
        semantic_errors.append("generational_runs_recompute_mismatch")
    if not _close(runs, stored_runs, 1e-7):
        semantic_errors.append("generational_run_metrics_recompute_mismatch")

    generational_summary = analyze_generational_endurance(runs, experiment)
    stored_generational_summary = json.loads((root / "results/generational_summary.json").read_text(encoding="utf-8"))
    if not _close(generational_summary, stored_generational_summary, 1e-7):
        semantic_errors.append("generational_summary_recompute_mismatch")
    design = generational_design_witness(experiment)
    stored_design = json.loads((root / "results/generational_design_witness.json").read_text(encoding="utf-8"))
    if not _close(design, stored_design):
        semantic_errors.append("generational_design_witness_recompute_mismatch")

    summary = _v6_expected_summary(root, generational_summary)
    stored_summary = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))
    if not _close(summary, stored_summary, 1e-7):
        semantic_errors.append("summary_semantic_recompute_mismatch")

    roots = json.loads((root / "lineage/v0.5.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    roots = dict(roots)
    roots["schema"] = "openline.endurance.cycle-roots.v3"
    roots["generational_cycle_merkle_root"] = fresh_cycle_root
    roots["generational_cycle_count"] = len(cycles)
    roots["generational_run_merkle_root"] = fresh_run_root
    roots["generational_run_count"] = len(runs)
    stored_roots = json.loads((root / "results/cycle_roots.json").read_text(encoding="utf-8"))
    if not _close(roots, stored_roots):
        semantic_errors.append("cycle_merkle_root_recompute_mismatch")
    for key, value in roots.items():
        if key.endswith("_merkle_root") and evidence.get(key) != value:
            semantic_errors.append(f"evidence_{key}_mismatch")

    additional_roots = {
        key: value for key, value in roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        roots["primary_cycle_merkle_root"],
        roots["amplitude_cycle_merkle_root"],
        additional_roots,
        list(V6_SEMANTIC_ARTIFACTS),
    )
    stored_public_witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
    if not _close(public_witness, stored_public_witness):
        semantic_errors.append("public_witness_recompute_mismatch")
    if evidence.get("public_witness_digest") != public_witness["witness_digest"]:
        semantic_errors.append("evidence_public_witness_digest_mismatch")
    return semantic_errors


def _v7_expected_summary(root: Path, restoration_summary: dict[str, Any]) -> dict[str, Any]:
    old_summary = json.loads((root / "lineage/v0.6.0/results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_COLLISION_SPACING_GENERATIONAL_INHERITANCE_AND_STATE_RESTORATION"
    summary["state_restoration"] = restoration_summary
    summary["legacy_v060_result_preserved"] = {
        "status": old_summary.get("generational_endurance", {}).get("status"),
        "passed_gate_count": old_summary.get("generational_endurance", {}).get("passed_gate_count"),
        "gate_count": old_summary.get("generational_endurance", {}).get("gate_count"),
        "maximum_verified_horizon_cycles": old_summary.get("generational_endurance", {}).get("maximum_verified_horizon_cycles"),
    }
    return summary


def _verify_v7_semantics_from_streamed(
    root: Path,
    experiment: dict[str, Any],
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    streamed: dict[str, Any],
    initial_errors: list[str] | None = None,
) -> list[str]:
    semantic_errors: list[str] = list(initial_errors or [])
    config = experiment["state_restoration"]
    stored_run_root, stored_run_count = _csv_merkle_root(root / "results/state_restoration_runs.csv")
    stored_runs = _coerce(read_csv(root / "results/state_restoration_runs.csv"))
    expected_runs = len(config["seeds"]) * 9
    expected_cycles = expected_runs * int(config["max_horizon_cycles"])
    if stored_run_count != expected_runs:
        semantic_errors.append(f"state_restoration_run_count:{stored_run_count}:{expected_runs}")
    if int(streamed["cycle_count"]) != expected_cycles:
        semantic_errors.append(f"state_restoration_cycle_count:{streamed['cycle_count']}:{expected_cycles}")
    if int(streamed["run_count"]) != expected_runs:
        semantic_errors.append(f"state_restoration_fresh_run_count:{streamed['run_count']}:{expected_runs}")

    runs = streamed["runs"]
    fresh_cycle_root = streamed["cycle_merkle_root"]
    fresh_run_root = streamed["run_merkle_root"]
    if fresh_run_root != stored_run_root:
        semantic_errors.append("state_restoration_runs_recompute_mismatch")
    if not _close(runs, stored_runs, 1e-7):
        semantic_errors.append("state_restoration_run_metrics_recompute_mismatch")

    restoration_summary = analyze_state_restoration(runs, experiment)
    stored_restoration_summary = json.loads((root / "results/state_restoration_summary.json").read_text(encoding="utf-8"))
    if not _close(restoration_summary, stored_restoration_summary, 1e-7):
        semantic_errors.append("state_restoration_summary_recompute_mismatch")
    design = state_restoration_design_witness(experiment)
    stored_design = json.loads((root / "results/state_restoration_design_witness.json").read_text(encoding="utf-8"))
    if not _close(design, stored_design):
        semantic_errors.append("state_restoration_design_witness_recompute_mismatch")

    summary = _v7_expected_summary(root, restoration_summary)
    stored_summary = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))
    if not _close(summary, stored_summary, 1e-7):
        semantic_errors.append("summary_semantic_recompute_mismatch")

    roots = json.loads((root / "lineage/v0.6.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    roots = dict(roots)
    roots["schema"] = "openline.endurance.cycle-roots.v4"
    roots["state_restoration_cycle_merkle_root"] = fresh_cycle_root
    roots["state_restoration_cycle_count"] = int(streamed["cycle_count"])
    roots["state_restoration_run_merkle_root"] = fresh_run_root
    roots["state_restoration_run_count"] = int(streamed["run_count"])
    stored_roots = json.loads((root / "results/cycle_roots.json").read_text(encoding="utf-8"))
    if not _close(roots, stored_roots):
        semantic_errors.append("cycle_merkle_root_recompute_mismatch")
    for key, value in roots.items():
        if key.endswith("_merkle_root") and evidence.get(key) != value:
            semantic_errors.append(f"evidence_{key}_mismatch")

    additional_roots = {
        key: value for key, value in roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        roots["primary_cycle_merkle_root"],
        roots["amplitude_cycle_merkle_root"],
        additional_roots,
        list(V7_SEMANTIC_ARTIFACTS),
    )
    stored_public_witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
    if not _close(public_witness, stored_public_witness):
        semantic_errors.append("public_witness_recompute_mismatch")
    if evidence.get("public_witness_digest") != public_witness["witness_digest"]:
        semantic_errors.append("evidence_public_witness_digest_mismatch")
    return semantic_errors


def _verify_v7_semantics(root: Path, experiment: dict[str, Any], manifest: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    shard_errors: list[str] = []
    stored_shards = [root / "results" / name for name in cycle_shard_names(experiment)]
    missing_shards = [path.name for path in stored_shards if not path.exists()]
    shard_errors.extend(f"state_restoration_cycle_shard_missing:{name}" for name in missing_shards)
    with tempfile.TemporaryDirectory(prefix="openline-v7-verify-") as temp_dir:
        fresh_base = Path(temp_dir) / "state_restoration_cycles.csv.gz"
        streamed = stream_state_restoration(experiment, fresh_base)
        fresh_shards = [Path(path) for path in streamed["cycle_artifacts"]]
        if not missing_shards:
            if len(stored_shards) != len(fresh_shards):
                shard_errors.append("state_restoration_cycle_shard_count_mismatch")
            else:
                for stored_path, fresh_path in zip(stored_shards, fresh_shards):
                    if sha256_file(stored_path) != sha256_file(fresh_path):
                        shard_errors.append(f"state_restoration_cycle_shard_recompute_mismatch:{stored_path.name}")
        return _verify_v7_semantics_from_streamed(
            root, experiment, manifest, evidence, streamed, shard_errors
        )

def verify_evidence(
    root: Path,
    source_root: Path | None = None,
    full_semantic: bool = True,
    verify_release: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    source_root = (source_root or root).resolve()
    errors: list[str] = []
    chain_result = verify_chain(root / "receipts/experiment.jsonl", root / "receipts/experiment.anchor.json")
    errors.extend(chain_result["errors"])
    chain = read_chain(root / "receipts/experiment.jsonl")
    evidence_receipts = [receipt for receipt in chain if receipt.get("kind") == "evidence_bundle"]
    if len(evidence_receipts) != 1:
        errors.append("evidence_receipt_count_mismatch")
        evidence = {}
    else:
        evidence = evidence_receipts[0]["payload"]
        for relative, expected in evidence.get("artifact_hashes", {}).items():
            path = root / relative
            if not path.exists():
                errors.append(f"evidence_missing:{relative}")
            elif sha256_file(path) != expected:
                errors.append(f"evidence_hash_mismatch:{relative}")
    errors.extend(verify_manifest(source_root))
    errors.extend(verify_preregistration(source_root))
    manifest = json.loads((source_root / "MANIFEST.json").read_text(encoding="utf-8"))
    if evidence.get("source_tree_digest") != manifest.get("source_tree_digest"):
        errors.append("evidence_source_digest_mismatch")

    experiment_for_branch = load_experiment(root / "experiment.json")
    if experiment_for_branch.get("schema") == "openline.endurance.experiment.v7":
        errors.extend(verify_v060_lineage(root))
        semantic_errors = _verify_v7_semantics(root, experiment_for_branch, manifest, evidence) if full_semantic else []
        errors.extend(semantic_errors)
        release_result = (
            verify_release_attestation(root)
            if verify_release
            else {"valid": True, "skipped": True, "errors": []}
        )
        if verify_release:
            errors.extend(release_result["errors"])
        return {
            "valid": not errors,
            "chain": chain_result,
            "artifact_binding_valid": not any(
                error == "evidence_receipt_count_mismatch"
                or error.startswith("evidence_missing:")
                or error.startswith("evidence_hash_mismatch:")
                or error == "evidence_source_digest_mismatch"
                or error.startswith("manifest_")
                or error.startswith("preregistration_")
                or error.startswith("v060_lineage_")
                or error == "source_tree_digest_mismatch"
                for error in errors
            ),
            "semantic_recomputation_valid": not semantic_errors,
            "lineage_binding_valid": not any(error.startswith("v060_lineage_") for error in errors),
            "release_attestation_valid": bool(release_result["valid"]),
            "release_attestation": release_result,
            "errors": errors,
        }
    if experiment_for_branch.get("schema") == "openline.endurance.experiment.v6":
        errors.extend(verify_v050_lineage(root))
        semantic_errors = _verify_v6_semantics(root, experiment_for_branch, manifest, evidence) if full_semantic else []
        errors.extend(semantic_errors)
        release_result = (
            verify_release_attestation(root)
            if verify_release
            else {"valid": True, "skipped": True, "errors": []}
        )
        if verify_release:
            errors.extend(release_result["errors"])
        return {
            "valid": not errors,
            "chain": chain_result,
            "artifact_binding_valid": not any(
                error == "evidence_receipt_count_mismatch"
                or error.startswith("evidence_missing:")
                or error.startswith("evidence_hash_mismatch:")
                or error == "evidence_source_digest_mismatch"
                or error.startswith("manifest_")
                or error.startswith("preregistration_")
                or error.startswith("v050_lineage_")
                or error == "source_tree_digest_mismatch"
                for error in errors
            ),
            "semantic_recomputation_valid": not semantic_errors,
            "lineage_binding_valid": not any(error.startswith("v050_lineage_") for error in errors),
            "release_attestation_valid": bool(release_result["valid"]),
            "release_attestation": release_result,
            "errors": errors,
        }
    if experiment_for_branch.get("schema") == "openline.endurance.experiment.v5":
        errors.extend(verify_v040_lineage(root))
        semantic_errors = _verify_v5_semantics(root, experiment_for_branch, manifest, evidence) if full_semantic else []
        errors.extend(semantic_errors)
        return {
            "valid": not errors,
            "chain": chain_result,
            "artifact_binding_valid": not any(
                error == "evidence_receipt_count_mismatch"
                or error.startswith("evidence_missing:")
                or error.startswith("evidence_hash_mismatch:")
                or error == "evidence_source_digest_mismatch"
                or error.startswith("manifest_")
                or error.startswith("preregistration_")
                or error.startswith("v040_lineage_")
                or error == "source_tree_digest_mismatch"
                for error in errors
            ),
            "semantic_recomputation_valid": not semantic_errors,
            "lineage_binding_valid": not any(error.startswith("v040_lineage_") for error in errors),
            "errors": errors,
        }

    semantic_errors: list[str] = []
    if full_semantic:
        experiment = load_experiment(root / "experiment.json")
        primary_cycles = _coerce(read_csv(root / "results/cycles.csv"))
        stored_primary_runs = _coerce(read_csv(root / "results/runs.csv"))
        amplitude_cycles = _coerce(read_csv(root / "results/amplitude_cycles.csv"))
        stored_amplitude_runs = _coerce(read_csv(root / "results/amplitude_runs.csv"))
        # Bind the large stored graph artifacts as streams before regenerating
        # the experiment. Canonical row Merkle equality is exact here and avoids
        # retaining hundreds of thousands of stored row dictionaries.
        stored_tip_cycle_root, stored_tip_cycle_count = _csv_merkle_root(root / "results/tip_capture_cycles.csv")
        stored_tip_runs = _coerce(read_csv(root / "results/tip_capture_runs.csv"))
        stored_tip_candidate_root, _ = _csv_merkle_root(root / "results/tip_capture_candidates.csv")
        stored_tip_probe_root, _ = _csv_merkle_root(root / "results/tip_capture_probes.csv")
        stored_collision_event_root, stored_collision_event_count = _csv_merkle_root(root / "results/collision_spacing_events.csv")
        stored_collision_run_root, stored_collision_run_count = _csv_merkle_root(root / "results/collision_spacing_runs.csv")
        stored_collision_runs = _coerce(read_csv(root / "results/collision_spacing_runs.csv"))
        expected_primary = len(experiment["seeds"]) * len(experiment["modes"]) * len(experiment["schedules"]) * int(experiment["primary_cycles"])
        expected_amplitude = len(experiment["seeds"]) * len(experiment["modes"]) * 3 * int(experiment["primary_cycles"])
        if len(primary_cycles) != expected_primary:
            semantic_errors.append(f"primary_observation_count:{len(primary_cycles)}:{expected_primary}")
        if len(amplitude_cycles) != expected_amplitude:
            semantic_errors.append(f"amplitude_observation_count:{len(amplitude_cycles)}:{expected_amplitude}")
        tip_config = experiment["tip_capture"]
        expected_tip_cycles = len(tip_config["seeds"]) * len(tip_config["attachment_conditions"]) * len(tip_config["repair_policies"]) * int(tip_config["cycles"])
        if stored_tip_cycle_count != expected_tip_cycles:
            semantic_errors.append(f"tip_capture_observation_count:{stored_tip_cycle_count}:{expected_tip_cycles}")
        spacing_config = experiment["collision_spacing"]
        expected_collision_runs = len(spacing_config["seeds"]) * len(spacing_config["schedules"])
        expected_collision_events = expected_collision_runs * int(spacing_config["events_per_run"])
        if stored_collision_run_count != expected_collision_runs:
            semantic_errors.append(f"collision_spacing_run_count:{stored_collision_run_count}:{expected_collision_runs}")
        if stored_collision_event_count != expected_collision_events:
            semantic_errors.append(f"collision_spacing_event_count:{stored_collision_event_count}:{expected_collision_events}")

        recomputed_primary_runs = recompute_runs(primary_cycles)
        recomputed_amplitude_runs = recompute_runs(amplitude_cycles)
        if not _close(_sorted_runs(recomputed_primary_runs), _sorted_runs(stored_primary_runs), 1e-7):
            semantic_errors.append("run_metrics_recompute_mismatch")
        if not _close(_sorted_runs(recomputed_amplitude_runs), _sorted_runs(stored_amplitude_runs), 1e-7):
            semantic_errors.append("amplitude_run_metrics_recompute_mismatch")

        calibration = calibrate_fresh(experiment)
        stored_calibration = json.loads((root / "results/calibration.json").read_text(encoding="utf-8"))
        if not _close(calibration, stored_calibration):
            semantic_errors.append("calibration_recompute_mismatch")

        annotate_failed_before(primary_cycles)
        selected = select_damage_parameters(primary_cycles, experiment)
        stored_damage = json.loads((root / "results/damage_fit.json").read_text(encoding="utf-8"))
        if not _close(selected, stored_damage, 1e-7):
            semantic_errors.append("damage_parameter_recompute_mismatch")
        damage_map = compute_damage(primary_cycles, selected["parameters"])
        stored_damage_values = [float(row["damage_D"]) for row in primary_cycles]
        attach_damage(primary_cycles, damage_map, float(experiment["phi_min"]))
        for row in primary_cycles:
            row.pop("candidate_D", None)
        if any(abs(float(row["damage_D"]) - old) > 1e-8 for row, old in zip(primary_cycles, stored_damage_values)):
            semantic_errors.append("damage_series_recompute_mismatch")

        model_comparison = compare_models(primary_cycles, experiment)
        stored_models = json.loads((root / "results/model_comparison.json").read_text(encoding="utf-8"))
        if not _close(model_comparison, stored_models, 1e-7):
            semantic_errors.append("model_comparison_recompute_mismatch")
        diagnostics = damage_diagnostics(primary_cycles, selected)
        stored_diagnostics = json.loads((root / "results/damage_diagnostics.json").read_text(encoding="utf-8"))
        if not _close(diagnostics, stored_diagnostics, 1e-7):
            semantic_errors.append("damage_diagnostics_recompute_mismatch")

        fractography_runs, fractography_summary = analyze_fractography(primary_cycles, experiment)
        stored_fractography_runs = _coerce(read_csv(root / "results/fractography_runs.csv"))
        stored_fractography_summary = json.loads((root / "results/fractography_summary.json").read_text(encoding="utf-8"))
        if not _close(fractography_runs, stored_fractography_runs, 1e-7):
            semantic_errors.append("fractography_runs_recompute_mismatch")
        if not _close(fractography_summary, stored_fractography_summary, 1e-7):
            semantic_errors.append("fractography_summary_recompute_mismatch")

        endurance_summary = build_summary(
            primary_cycles,
            recomputed_primary_runs,
            recomputed_amplitude_runs,
            calibration,
            selected,
            diagnostics,
            model_comparison,
            fractography_summary,
            experiment,
        )

        tip_cycles, tip_runs, tip_candidates, tip_probes = simulate_tip_capture(experiment)
        # Raw graph artifacts are large. Canonical Merkle equality is an exact
        # semantic comparison and avoids a second Python-level walk across
        # every field after deterministic recomputation.
        stored_tip_roots = {
            "cycles": stored_tip_cycle_root,
            "candidates": stored_tip_candidate_root,
            "probes": stored_tip_probe_root,
        }
        fresh_tip_roots = {
            "cycles": merkle_root(tip_cycles),
            "candidates": merkle_root(tip_candidates),
            "probes": merkle_root(tip_probes),
        }
        if fresh_tip_roots["cycles"] != stored_tip_roots["cycles"]:
            semantic_errors.append("tip_capture_cycles_recompute_mismatch")
        if not _close(tip_runs, stored_tip_runs, 1e-7):
            semantic_errors.append("tip_capture_runs_recompute_mismatch")
        if fresh_tip_roots["candidates"] != stored_tip_roots["candidates"]:
            semantic_errors.append("tip_capture_candidates_recompute_mismatch")
        if fresh_tip_roots["probes"] != stored_tip_roots["probes"]:
            semantic_errors.append("tip_capture_probes_recompute_mismatch")
        tip_summary = analyze_tip_capture(tip_cycles, tip_runs, tip_candidates, tip_probes, experiment)
        stored_tip_summary = json.loads((root / "results/tip_capture_summary.json").read_text(encoding="utf-8"))
        if not _close(tip_summary, stored_tip_summary, 1e-7):
            semantic_errors.append("tip_capture_summary_recompute_mismatch")
        tip_design = tip_design_witness(experiment)
        stored_tip_design = json.loads((root / "results/tip_capture_design_witness.json").read_text(encoding="utf-8"))
        if not _close(tip_design, stored_tip_design):
            semantic_errors.append("tip_capture_design_witness_recompute_mismatch")

        collision_events, collision_runs = simulate_collision_spacing(experiment)
        fresh_collision_event_root = merkle_root(collision_events)
        fresh_collision_run_root = merkle_root(collision_runs)
        if fresh_collision_event_root != stored_collision_event_root:
            semantic_errors.append("collision_spacing_events_recompute_mismatch")
        if fresh_collision_run_root != stored_collision_run_root:
            semantic_errors.append("collision_spacing_runs_recompute_mismatch")
        if not _close(collision_runs, stored_collision_runs, 1e-7):
            semantic_errors.append("collision_spacing_run_metrics_recompute_mismatch")
        collision_summary = analyze_collision_spacing(collision_runs, experiment)
        stored_collision_summary = json.loads((root / "results/collision_spacing_summary.json").read_text(encoding="utf-8"))
        if not _close(collision_summary, stored_collision_summary, 1e-7):
            semantic_errors.append("collision_spacing_summary_recompute_mismatch")
        collision_design = collision_design_witness(experiment)
        stored_collision_design = json.loads((root / "results/collision_spacing_design_witness.json").read_text(encoding="utf-8"))
        if not _close(collision_design, stored_collision_design):
            semantic_errors.append("collision_spacing_design_witness_recompute_mismatch")

        summary = combine_summaries(endurance_summary, tip_summary, collision_summary)
        stored_summary = json.loads((root / "results/summary.json").read_text(encoding="utf-8"))
        if not _close(summary, stored_summary, 1e-7):
            semantic_errors.append("summary_semantic_recompute_mismatch")

        roots = {
            "schema": "openline.endurance.cycle-roots.v1",
            "primary_cycle_merkle_root": merkle_root(primary_cycles),
            "primary_cycle_count": len(primary_cycles),
            "amplitude_cycle_merkle_root": merkle_root(amplitude_cycles),
            "amplitude_cycle_count": len(amplitude_cycles),
            "tip_capture_cycle_merkle_root": fresh_tip_roots["cycles"],
            "tip_capture_cycle_count": len(tip_cycles),
            "tip_capture_candidate_merkle_root": fresh_tip_roots["candidates"],
            "tip_capture_candidate_count": len(tip_candidates),
            "tip_capture_probe_merkle_root": fresh_tip_roots["probes"],
            "tip_capture_probe_count": len(tip_probes),
            "collision_spacing_event_merkle_root": fresh_collision_event_root,
            "collision_spacing_event_count": len(collision_events),
            "collision_spacing_run_merkle_root": fresh_collision_run_root,
            "collision_spacing_run_count": len(collision_runs),
        }
        stored_roots = json.loads((root / "results/cycle_roots.json").read_text(encoding="utf-8"))
        if not _close(roots, stored_roots):
            semantic_errors.append("cycle_merkle_root_recompute_mismatch")
        if evidence.get("primary_cycle_merkle_root") != roots["primary_cycle_merkle_root"]:
            semantic_errors.append("evidence_primary_cycle_root_mismatch")
        if evidence.get("amplitude_cycle_merkle_root") != roots["amplitude_cycle_merkle_root"]:
            semantic_errors.append("evidence_amplitude_cycle_root_mismatch")
        if evidence.get("tip_capture_cycle_merkle_root") != roots["tip_capture_cycle_merkle_root"]:
            semantic_errors.append("evidence_tip_capture_cycle_root_mismatch")
        if evidence.get("tip_capture_candidate_merkle_root") != roots["tip_capture_candidate_merkle_root"]:
            semantic_errors.append("evidence_tip_capture_candidate_root_mismatch")
        if evidence.get("tip_capture_probe_merkle_root") != roots["tip_capture_probe_merkle_root"]:
            semantic_errors.append("evidence_tip_capture_probe_root_mismatch")
        if evidence.get("collision_spacing_event_merkle_root") != roots["collision_spacing_event_merkle_root"]:
            semantic_errors.append("evidence_collision_spacing_event_root_mismatch")
        if evidence.get("collision_spacing_run_merkle_root") != roots["collision_spacing_run_merkle_root"]:
            semantic_errors.append("evidence_collision_spacing_run_root_mismatch")

        design = _design_witness(experiment)
        stored_design = json.loads((root / "results/design_witness.json").read_text(encoding="utf-8"))
        if not _close(design, stored_design):
            semantic_errors.append("design_witness_recompute_mismatch")

        public_witness = build_public_witness(
            root,
            experiment,
            summary,
            manifest["source_tree_digest"],
            roots["primary_cycle_merkle_root"],
            roots["amplitude_cycle_merkle_root"],
            {
                "tip_capture_cycle_merkle_root": roots["tip_capture_cycle_merkle_root"],
                "tip_capture_candidate_merkle_root": roots["tip_capture_candidate_merkle_root"],
                "tip_capture_probe_merkle_root": roots["tip_capture_probe_merkle_root"],
                "collision_spacing_event_merkle_root": roots["collision_spacing_event_merkle_root"],
                "collision_spacing_run_merkle_root": roots["collision_spacing_run_merkle_root"],
            },
            list(BASE_SEMANTIC_ARTIFACTS),
        )
        stored_public_witness = json.loads((root / "results/public_witness.json").read_text(encoding="utf-8"))
        if not _close(public_witness, stored_public_witness):
            semantic_errors.append("public_witness_recompute_mismatch")
        if evidence.get("public_witness_digest") != public_witness["witness_digest"]:
            semantic_errors.append("evidence_public_witness_digest_mismatch")

    errors.extend(semantic_errors)
    return {
        "valid": not errors,
        "chain": chain_result,
        "artifact_binding_valid": not any(
            error == "evidence_receipt_count_mismatch"
            or error.startswith("evidence_missing:")
            or error.startswith("evidence_hash_mismatch:")
            or error == "evidence_source_digest_mismatch"
            or error.startswith("manifest_")
            or error.startswith("preregistration_")
            or error == "source_tree_digest_mismatch"
            for error in errors
        ),
        "semantic_recomputation_valid": not semantic_errors,
        "errors": errors,
    }
