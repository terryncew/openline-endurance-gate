from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .amplitude import matched_amplitude_events, matched_packet_witness
from .collision_spacing import (
    COLLISION_EVENT_FIELDS, COLLISION_RUN_FIELDS,
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
from .fractography import FRACTOGRAPHY_FIELDS, analyze_fractography
from .generational import (
    GENERATIONAL_CYCLE_FIELDS, GENERATIONAL_RUN_FIELDS,
    analyze_generational_endurance, generational_design_witness, simulate_generational_endurance,
)
from .load_rate import (
    LOAD_RATE_RUN_FIELDS, analyze_load_rate, load_rate_design_witness, read_gzip_csv,
)
from .rate_streaming import (
    CountedRows, finalize_load_rate_shards, load_rate_shard_names,
    load_rate_shards_ready, stream_load_rate,
)
from .recovery import (
    RECOVERY_RUN_FIELDS, analyze_recovery, recovery_design_witness, run_hostile_controls,
)
from .recovery_streaming import (
    CountedRows as RecoveryCountedRows, finalize_recovery_shards, recovery_shard_names,
    recovery_shards_ready, stream_recovery,
)
from .state_restoration import (
    RESTORATION_CYCLE_FIELDS, RESTORATION_RUN_FIELDS,
    analyze_state_restoration, state_restoration_design_witness,
)
from .restoration_stream import (
    finalize_state_restoration_shards, state_restoration_shards_ready, stream_state_restoration,
)
from .integrity import (
    build_public_witness, merkle_root, verify_preregistration,
    verify_v040_lineage, verify_v050_lineage, verify_v060_lineage, verify_v070_lineage,
    verify_v080_lineage, verify_v090_lineage, verify_v091_lineage,
)
from .receipts import ReceiptSigner, artifact_hashes, create_chain, read_chain, verify_chain, write_anchor, write_chain
from .sim import calibrate_fresh, generate_perturbations, run_one, schedule_events
from .summarize import aggregate_runs, build_summary
from .tip_capture import (
    TIP_CANDIDATE_FIELDS, TIP_CYCLE_FIELDS, TIP_PROBE_FIELDS, TIP_RUN_FIELDS,
    analyze_tip_capture, simulate_tip_capture, tip_design_witness,
)
from .util import canonical_json, read_csv, sha256_bytes, sha256_file, write_csv


PRIMARY_CYCLE_FIELDS = [
    "run_family", "mode", "schedule", "seed", "cycle", "event_id", "amplitude", "target",
    "truth_delta", "applied_delta", "application_outcome", "difficulty", "correction_required",
    "correction_success", "checkpoint", "checkpoint_failed", "unsafe_attempt", "first_failure_this_cycle",
    "failed_by_cycle", "failed_before_cycle", "config_accuracy", "requirement_accuracy",
    "invariant_failure_count", "invariant_failures", "known_dependency_count", "unresolved_dependency_count",
    "unresolved_dependencies", "contradiction_count", "retry_count", "repair_succeeded",
    "repaired_invariant_count", "repaired_field_count", "representation_tokens", "total_tokens",
    "context_pressure", "handoff_loss", "kappa", "kappa_star_0", "phi_star", "phi_base", "epsilon",
    "delta_hol", "vkd", "damage_D", "kappa_star_eff", "vkd_f", "subcritical_failure",
]


BASE_SEMANTIC_ARTIFACTS = [
    "experiment.json",
    "PREREGISTRATION.json",
    "TIP_CAPTURE_PILOT_LOG.json",
    "TIP_CAPTURE_V040_PILOT_LOG.json",
    "results/cycles.csv",
    "results/runs.csv",
    "results/amplitude_cycles.csv",
    "results/amplitude_runs.csv",
    "results/calibration.json",
    "results/damage_fit.json",
    "results/damage_diagnostics.json",
    "results/model_comparison.json",
    "results/fractography_runs.csv",
    "results/fractography_summary.json",
    "results/design_witness.json",
    "results/heldout_witness.json",
    "results/summary.json",
    "results/summary.md",
    "results/cycle_roots.json",
    "results/tip_capture_cycles.csv",
    "results/tip_capture_runs.csv",
    "results/tip_capture_candidates.csv",
    "results/tip_capture_probes.csv",
    "results/tip_capture_summary.json",
    "results/tip_capture_summary.md",
    "results/tip_capture_design_witness.json",
    "COLLISION_SPACING_PILOT_LOG.json",
    "V040_LINEAGE.json",
    "results/collision_spacing_events.csv",
    "results/collision_spacing_runs.csv",
    "results/collision_spacing_summary.json",
    "results/collision_spacing_summary.md",
    "results/collision_spacing_design_witness.json",
]

V6_SEMANTIC_ARTIFACTS = BASE_SEMANTIC_ARTIFACTS + [
    "GENERATIONAL_PILOT_LOG.json",
    "V050_LINEAGE.json",
    "results/generational_cycles.csv",
    "results/generational_runs.csv",
    "results/generational_summary.json",
    "results/generational_summary.md",
    "results/generational_design_witness.json",
]

V7_SEMANTIC_ARTIFACTS = V6_SEMANTIC_ARTIFACTS + [
    "STATE_RESTORATION_PILOT_LOG.json",
    "V060_LINEAGE.json",
    "results/state_restoration_cycles.part-000.csv.gz",
    "results/state_restoration_cycles.part-001.csv.gz",
    "results/state_restoration_cycles.part-002.csv.gz",
    "results/state_restoration_cycles.part-003.csv.gz",
    "results/state_restoration_cycles.part-004.csv.gz",
    "results/state_restoration_cycles.part-005.csv.gz",
    "results/state_restoration_cycles.part-006.csv.gz",
    "results/state_restoration_cycles.part-007.csv.gz",
    "results/state_restoration_runs.csv",
    "results/state_restoration_summary.json",
    "results/state_restoration_summary.md",
    "results/state_restoration_design_witness.json",
]

V8_SEMANTIC_ARTIFACTS = V7_SEMANTIC_ARTIFACTS + [
    "LOAD_RATE_PILOT_LOG.json",
    "V070_LINEAGE.json",
    "V080_LINEAGE.json",
    "results/load_rate_cycles.part-000.csv.gz",
    "results/load_rate_cycles.part-001.csv.gz",
    "results/load_rate_cycles.part-002.csv.gz",
    "results/load_rate_cycles.part-003.csv.gz",
    "results/load_rate_cycles.part-004.csv.gz",
    "results/load_rate_cycles.part-005.csv.gz",
    "results/load_rate_cycles.part-006.csv.gz",
    "results/load_rate_cycles.part-007.csv.gz",
    "results/load_rate_cycles.part-008.csv.gz",
    "results/load_rate_cycles.part-009.csv.gz",
    "results/load_rate_cycles.part-010.csv.gz",
    "results/load_rate_cycles.part-011.csv.gz",
    "results/load_rate_runs.csv",
    "results/load_rate_summary.json",
    "results/load_rate_summary.md",
    "results/load_rate_design_witness.json",
]

V9_SEMANTIC_ARTIFACTS = V8_SEMANTIC_ARTIFACTS + [
    "V090_LINEAGE.json",
    "docs/RECOVERY_PREREGISTRATION.md",
    "docs/RECOVERY_METHODOLOGY.md",
    "docs/RECOVERY_CLAIMS.md",
    "docs/RECOVERY_THREAT_MODEL.md",
    "results/recovery_cycles.part-000.csv.gz",
    "results/recovery_cycles.part-001.csv.gz",
    "results/recovery_cycles.part-002.csv.gz",
    "results/recovery_cycles.part-003.csv.gz",
    "results/recovery_cycles.part-004.csv.gz",
    "results/recovery_cycles.part-005.csv.gz",
    "results/recovery_runs.csv",
    "results/recovery_handoffs.jsonl",
    "results/recovery_summary.json",
    "results/recovery_hostile_controls.json",
    "results/recovery_design_witness.json",
    "RECOVERY_RELEASE_GATE.json",
]

V91_SEMANTIC_ARTIFACTS = V9_SEMANTIC_ARTIFACTS + [
    "results/recovery_cycles.part-006.csv.gz",
    "results/recovery_cycles.part-007.csv.gz",
    "results/recovery_cycles.part-008.csv.gz",
    "results/recovery_cycles.part-009.csv.gz",
    "results/recovery_cycles.part-010.csv.gz",
    "results/recovery_cycles.part-011.csv.gz",
    "V091_LINEAGE.json",
]

RUN_FIELDS = [
    "run_family", "mode", "schedule", "seed", "cycles", "n_f", "failed", "first_failure_cycle",
    "mean_checkpoint_accuracy", "final_config_accuracy", "final_requirement_accuracy", "unsafe_attempts",
    "retry_count", "repair_successes", "total_tokens", "subcritical_first_failure",
]


def load_experiment(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") not in {"openline.endurance.experiment.v1", "openline.endurance.experiment.v2", "openline.endurance.experiment.v3", "openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        raise ValueError("unsupported experiment schema")
    declared = set(map(int, data["training_seeds"] + data["validation_seeds"] + data["heldout_seeds"]))
    if declared != set(map(int, data["seeds"])):
        raise ValueError("train/validation/heldout seeds must partition seeds")
    if not set(map(int, data["training_seeds"])).isdisjoint(map(int, data["validation_seeds"])):
        raise ValueError("training and validation seeds overlap")
    if len(data["modes"]) != 4 or len(data["schedules"]) != 4:
        raise ValueError("default discriminating test requires four modes and four schedules")
    if data.get("schema") in {"openline.endurance.experiment.v2", "openline.endurance.experiment.v3", "openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        required_pairs = int(data["analysis_plan"]["minimum_primary_order_pairs"])
        available_pairs = len(data["heldout_seeds"]) * len(data["modes"])
        if available_pairs < required_pairs:
            raise ValueError(f"powered design has {available_pairs} order pairs but requires {required_pairs}")
        if data.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_NUMBERS":
            raise ValueError("v2 requires event-bound common random numbers")
        if data.get("amplitude_sweep_design") != "COMMON_PACKET_AMPLITUDE_TRANSFORM":
            raise ValueError("v2 requires matched amplitude packets")
    if data.get("schema") in {"openline.endurance.experiment.v3", "openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        tip = data.get("tip_capture")
        expected_tip_schema = "openline.tip-capture.experiment.v2" if data.get("schema") in {"openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"} else "openline.tip-capture.experiment.v1"
        if not isinstance(tip, dict) or tip.get("schema") != expected_tip_schema:
            raise ValueError(f"{data.get('schema')} requires {expected_tip_schema}")
        tip_declared = set(map(int, tip["training_seeds"] + tip["validation_seeds"] + tip["heldout_seeds"]))
        if tip_declared != set(map(int, tip["seeds"])):
            raise ValueError("tip-capture train/validation/heldout seeds must partition seeds")
        if len(tip["heldout_seeds"]) < int(tip["analysis_plan"]["minimum_repair_pairs"]):
            raise ValueError("tip-capture heldout seed count is below the preregistered pair floor")
        required_conditions = {"uniform_null", "diffusive_first_contact"} if data.get("schema") in {"openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"} else {"uniform_null", "diffusive_tip_capture"}
        if required_conditions - set(tip["attachment_conditions"]):
            raise ValueError("tip-capture requires both a genuine null and declared diffusive treatment")
        if {"random_repair", "tip_targeted"} - set(tip["repair_policies"]):
            raise ValueError("tip-capture requires matched random and tip-targeted repair policies")
        if tip.get("randomness_coupling") != "PACKET_BOUND_COMMON_RANDOM_NUMBERS":
            raise ValueError("tip-capture requires packet-bound common random numbers")
        if data.get("schema") in {"openline.endurance.experiment.v4", "openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
            required_walker = {"dla_launch_margin", "dla_kill_margin", "dla_max_steps", "dla_max_restarts", "root_spacing"}
            if required_walker - set(tip):
                raise ValueError("v4/v5 first-contact walker configuration is incomplete")
    if data.get("schema") in {"openline.endurance.experiment.v5", "openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        spacing = data.get("collision_spacing")
        if not isinstance(spacing, dict) or spacing.get("schema") != "openline.collision-spacing.experiment.v1":
            raise ValueError("v5 requires openline.collision-spacing.experiment.v1")
        spacing_declared = set(map(int, spacing["training_seeds"] + spacing["validation_seeds"] + spacing["heldout_seeds"]))
        if spacing_declared != set(map(int, spacing["seeds"])):
            raise ValueError("collision-spacing train/validation/heldout seeds must partition seeds")
        if len(spacing["heldout_seeds"]) < int(spacing["analysis_plan"]["minimum_pairs"]):
            raise ValueError("collision-spacing heldout seed count is below the preregistered pair floor")
        required_schedules = {"clustered", "random_sparse_a", "random_sparse_b", "ulam_spaced", "conflict_aware"}
        if required_schedules != set(spacing["schedules"]):
            raise ValueError("collision-spacing requires the frozen five-condition design")
        if spacing.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_DRAWS_SCHEDULE_EXCLUDED":
            raise ValueError("collision-spacing requires schedule-independent common random draws")
        if int(spacing["events_per_run"]) != sum(int(value) for value in data["amplitude_multiset"].values()):
            raise ValueError("collision-spacing event count must match the endurance perturbation multiset")
    if data.get("schema") in {"openline.endurance.experiment.v6", "openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        generational = data.get("generational_endurance")
        if not isinstance(generational, dict) or generational.get("schema") != "openline.generational-endurance.experiment.v1":
            raise ValueError("v6 requires openline.generational-endurance.experiment.v1")
        declared = set(map(int, generational["training_seeds"] + generational["validation_seeds"] + generational["heldout_seeds"]))
        if declared != set(map(int, generational["seeds"])):
            raise ValueError("generational train/validation/heldout seeds must partition seeds")
        if len(generational["heldout_seeds"]) < int(generational["analysis_plan"]["minimum_pairs"]):
            raise ValueError("generational heldout seed count is below the preregistered pair floor")
        required_modes = {
            "continuous_full_history", "ordinary_summary_reset",
            "verified_inheritance_capsule", "capsule_conflict_aware",
        }
        if required_modes != set(generational["modes"]):
            raise ValueError("generational endurance requires the frozen four-mode design")
        if list(map(int, generational["horizons"])) != [40, 80, 160]:
            raise ValueError("generational endurance requires the frozen 40/80/160 doubling ladder")
        if int(generational["max_horizon_cycles"]) != 160:
            raise ValueError("generational maximum horizon must equal 160")
        if int(generational["generation_length_cycles"]) != 20:
            raise ValueError("generational length must equal the inherited 20-cycle world")
        if generational.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_DRAWS_MODE_EXCLUDED":
            raise ValueError("generational endurance requires event-bound common random draws")
        if int(generational["capsule_budget_tokens"]) != int(generational["summary_budget_tokens"]):
            raise ValueError("capsule and ordinary summary must use equal reset budgets")
    if data.get("schema") in {"openline.endurance.experiment.v7", "openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        restoration = data.get("state_restoration")
        if not isinstance(restoration, dict) or restoration.get("schema") != "openline.state-restoration.experiment.v1":
            raise ValueError("v7 requires openline.state-restoration.experiment.v1")
        declared = set(map(int, restoration["training_seeds"] + restoration["validation_seeds"] + restoration["heldout_seeds"]))
        if declared != set(map(int, restoration["seeds"])):
            raise ValueError("state-restoration train/validation/heldout seeds must partition seeds")
        if len(restoration["heldout_seeds"]) < int(restoration["analysis_plan"]["minimum_pairs"]):
            raise ValueError("state-restoration heldout seed count is below the preregistered pair floor")
        required_modes = {
            "capsule_baseline", "scheduled_prune_80", "fixed_retirement_85",
            "telemetry_breaker", "ecc_digest", "restoration_stack", "sham_retirement_85",
        }
        if required_modes != set(restoration["modes"]):
            raise ValueError("state restoration requires the frozen seven-mode design")
        if list(map(int, restoration["horizons"])) != [160, 320]:
            raise ValueError("state restoration requires the frozen 160/320 ladder")
        if int(restoration["max_horizon_cycles"]) != 320:
            raise ValueError("state restoration maximum horizon must equal 320")
        if restoration.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_DRAWS_MODE_EXCLUDED":
            raise ValueError("state restoration requires event-bound common random draws")
        if int(restoration["fixed_retirement_interval_cycles"]) != 85:
            raise ValueError("the fixed retirement comparator must remain at cycle 85")

    if data.get("schema") in {"openline.endurance.experiment.v8", "openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        rate = data.get("load_rate")
        if not isinstance(rate, dict) or rate.get("schema") != "openline.load-rate.experiment.v1":
            raise ValueError("v8 requires openline.load-rate.experiment.v1")
        declared_rate = set(map(int, rate["training_seeds"] + rate["validation_seeds"] + rate["heldout_seeds"]))
        if declared_rate != set(map(int, rate["seeds"])):
            raise ValueError("load-rate train/validation/heldout seeds must partition seeds")
        if len(rate["heldout_seeds"]) < int(rate["analysis_plan"]["minimum_pairs"]):
            raise ValueError("load-rate heldout seed count is below the preregistered pair floor")
        if set(rate["modes"]) != {"continuous_history", "ordinary_summary", "verified_capsule"}:
            raise ValueError("load-rate requires the frozen three-mode design")
        if set(rate["schedules"]) != {"slow_drip", "steady_load", "sudden_burst", "burst_recovery"}:
            raise ValueError("load-rate requires the frozen four-schedule design")
        if set(rate["worlds"]) != {"rate_sensitive", "rate_disabled_null"}:
            raise ValueError("load-rate requires a rate-sensitive world and rate-disabled null")
        if int(rate["horizon_ticks"]) != 160 or int(rate["block_ticks"]) != 40:
            raise ValueError("load-rate requires four matched 40-tick blocks")
        if rate.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_DRAWS_SCHEDULE_EXCLUDED":
            raise ValueError("load-rate requires schedule-excluded event-bound common random draws")
        if not load_rate_design_witness(data)["all_matching_checks_pass"]:
            raise ValueError("load-rate schedule matching witness failed")
    if data.get("schema") in {"openline.endurance.experiment.v9", "openline.endurance.experiment.v10"}:
        recovery = data.get("recovery")
        if not isinstance(recovery, dict):
            raise ValueError("v9 requires a recovery design")
        declared_recovery = set(map(int, recovery["training_seeds"] + recovery["validation_seeds"] + recovery["heldout_seeds"]))
        if declared_recovery != set(map(int, recovery["seeds"])):
            raise ValueError("recovery train/validation/heldout seeds must partition seeds")
        if set(recovery["modes"]) != {
            "continuous_control", "empty_reset", "full_history_handoff",
            "unsigned_minimal_handoff", "olp_handoff",
        }:
            raise ValueError("recovery requires the frozen five-condition design")
        if int(recovery["horizon_cycles"]) != 320 or int(recovery["intervention_cycle"]) != 80:
            raise ValueError("recovery requires a 320-cycle horizon and intervention at cycle 80")
        if data.get("schema") == "openline.endurance.experiment.v9":
            if recovery.get("freshness_mechanism_status") != "DEFERRED_TO_V0.9.1":
                raise ValueError("v0.9.0 must not silently claim the deferred freshness state machine")
        else:
            if recovery.get("freshness_mechanism_status") != "ACTIVE_STATEFUL_V0.9.1":
                raise ValueError("v0.9.1 requires active stateful freshness verification")
            if int(recovery.get("pass", 0)) != 2 or not recovery.get("master_seed"):
                raise ValueError("v0.9.1 requires the frozen Pass-2 master seed")
            if len(recovery["heldout_seeds"]) != 80:
                raise ValueError("v0.9.1 requires 80 fresh held-out recovery seeds")
            v090_seeds = set(range(9101, 9109)) | set(range(9117, 9157))
            if v090_seeds.intersection(map(int, recovery["seeds"])):
                raise ValueError("v0.9.1 may not reuse a v0.9.0 recovery seed")
    return data


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    order = summary["order_effect"]
    amplitude = summary["amplitude_effect"]
    receipt = summary["receipt_effect"]
    models = summary["model_comparison"]
    lines = [
        "# OpenLine Endurance Gate — Powered Sequence Run",
        "",
        f"**Claim label:** `{summary['claim_label']}`",
        f"**Theory status:** `{summary['theory_status']}`",
        f"**Pre-registered gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Primary observations:** {summary['primary_observation_count']}",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        "",
        "## Primary load-order witness",
        "",
        f"- Paired differences: {order['paired_difference_count']}",
        f"- Median low→high minus high→low: {order['median_difference_cycles']:.3f} cycles",
        f"- 95% bootstrap interval: {order['median_confidence_interval']}",
        f"- Exact sign-flip p: {order['exact_sign_flip_p']:.6g}",
        f"- Classification: `{order['effect_classification']}`",
        "",
        "## Other discriminating witnesses",
        "",
        f"- Matched amplitude low-high median: {amplitude['median_difference_cycles']:.3f} cycles; p={amplitude['exact_sign_flip_p']:.6g}",
        f"- Receipt ancestry median gain: {receipt['median_n_f_gain_cycles']:.3f} cycles; p={receipt['exact_sign_flip_p']:.6g}",
        f"- Damage log-loss gain over current CD: {models['damage_vs_cd_logloss_gain']:.10f}",
        f"- Damage log-loss gain over cycle + operational baseline: {models['damage_vs_strong_baseline_logloss_gain']:.10f}",
        "",
        "## Gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            summary["claim_boundary"],
            "",
            "A passing simulation earns a real-agent experiment. It does not validate the physical analogy.",
        ]
    )
    return "\n".join(lines) + "\n"


def _tip_summary_markdown(summary: dict[str, Any]) -> str:
    capture = summary["capture_by_condition"]["diffusive_first_contact"]
    geometry = summary["geometry_lift"]["diffusive_first_contact"]
    repair = summary["repair_effect"]
    recovery = summary["receipt_recovery_effect"]
    lines = [
        "# OpenLine Execution Tip-Capture — Powered Synthetic Run",
        "",
        f"**Claim label:** `{summary['claim_label']}`",
        f"**Status:** `{summary['status']}`",
        f"**Pre-registered gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Cycle observations:** {summary['cycle_observation_count']}",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        "",
        "## Main witnesses",
        "",
        f"- First-contact frontier capture lift over candidate-count null: {capture['frontier_capture_lift']:.6f}",
        f"- Random-walk fallback rate: {capture['walker_fallback_rate']:.6f}",
        f"- Geometry held-out log-loss gain: {geometry['heldout_logloss_gain']:.8f}",
        f"- Geometry held-out AUC gain: {geometry['heldout_auc_gain']:.8f}",
        f"- Tip-minus-random repair yield median: {repair['median_difference']:.6f} violations prevented per successful repair",
        f"- Repair-yield majority direction: `{repair['majority_direction']}`",
        f"- Positive-direction consistency among non-ties: {repair['positive_direction_consistency']:.6f}",
        f"- Pair counts — tip favored: {repair['positive_count']}; random favored: {repair['negative_count']}; tied: {repair['zero_count']}",
        f"- Receipt ancestry root-recovery median gain: {recovery['median_difference']:.6f} recovery-rate points",
        f"- Burial depth / successful recovery-cost Spearman: {summary['burial_cost_spearman']}",
        "- v0.3.1 lineage: `even_spread` is retired and retained only as the accurately named descriptive `least_capture_balancer` condition.",
        "",
        "## Gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend(["", "## Boundary", "", summary["claim_boundary"], ""])
    return "\n".join(lines) + "\n"


def _collision_summary_markdown(summary: dict[str, Any]) -> str:
    effects = summary["effects"]
    lines = [
        "# OpenLine Collision-Aware Spacing — Exploratory Synthetic Run",
        "",
        f"**Claim label:** `{summary['claim_label']}`",
        f"**Status:** `{summary['status']}`",
        f"**Exploratory gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        "",
        "## Main contrasts",
        "",
        f"- Random sparse minus Ulam collision burden: {effects['ulam_collision']['median_difference']:.6f}; p={effects['ulam_collision']['exact_sign_flip_p']:.6g}",
        f"- Random sparse minus Ulam damage AUC: {effects['ulam_damage']['median_difference']:.6f}; p={effects['ulam_damage']['exact_sign_flip_p']:.6g}",
        f"- Random sparse minus Ulam failures: {effects['ulam_failures']['median_difference']:.6f}; p={effects['ulam_failures']['exact_sign_flip_p']:.6g}",
        f"- Random sparse minus conflict-aware collision burden: {effects['conflict_aware_collision']['median_difference']:.6f}; p={effects['conflict_aware_collision']['exact_sign_flip_p']:.6g}",
        f"- Random sparse minus conflict-aware damage AUC: {effects['conflict_aware_damage']['median_difference']:.6f}; p={effects['conflict_aware_damage']['exact_sign_flip_p']:.6g}",
        "",
        "## Exploratory gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend(["", "## Boundary", "", summary["claim_boundary"], ""])
    return "\n".join(lines) + "\n"


def combine_summaries(summary: dict[str, Any], tip_summary: dict[str, Any], collision_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    combined = dict(summary)
    endurance_gates = dict(combined["gates"])
    combined["endurance_status"] = combined["theory_status"]
    combined["endurance_passed_gate_count"] = combined["passed_gate_count"]
    combined["endurance_gate_count"] = combined["gate_count"]
    combined["tip_capture"] = tip_summary
    gates = {f"endurance/{name}": gate for name, gate in endurance_gates.items()}
    gates.update({f"tip_capture/{name}": gate for name, gate in tip_summary["gates"].items()})
    combined["gates"] = gates
    combined["passed_gate_count"] = sum(int(gate["passed"]) for gate in gates.values())
    combined["gate_count"] = len(gates)
    combined["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_AND_COLLISION_SPACING"
    if combined["passed_gate_count"] == combined["gate_count"]:
        combined["theory_status"] = "SURVIVES_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    elif combined["passed_gate_count"] == 0:
        combined["theory_status"] = "FAILS_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    else:
        combined["theory_status"] = "MIXED_SYNTHETIC_RESULT"
    combined["claim_boundary"] = (
        "The endurance world and the execution-graph world are seeded mechanism tests. "
        "The first-contact treatment uses a lattice random walk independent of the reported exposure heuristic, while uniform attachment is the null. "
        "Passing shows the instruments recover declared mechanisms and reject nulls where preregistered; it does not show deployed agents obey material fatigue or DLA."
    )
    if collision_summary is not None:
        # v0.5 is exploratory. Preserve the v0.4 scientific score exactly and
        # report spacing gates in a separate namespace rather than laundering
        # the legacy 8/10 result into a new denominator.
        combined["collision_spacing"] = collision_summary
        combined["legacy_scientific_result_preserved"] = {
            "status": combined["theory_status"],
            "passed_gate_count": combined["passed_gate_count"],
            "gate_count": combined["gate_count"],
        }
    return combined


def _manifest_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(
            part in {
                ".git", ".pytest_cache", ".venv", "__pycache__", ".load_rate_work",
                ".load_rate_semantic", ".state_restoration_work", ".state_restoration_semantic",
                ".recovery_work", ".recovery_semantic", ".release_preflight_parts",
            } or part.endswith(".egg-info")
            for part in path.parts
        ):
            continue
        if rel in {
            "MANIFEST.json",
            "RUN_REPORT.json",
            "TAMPER_REPORT.json",
            "TAMPER_REPORT.standalone.json",
            "RAW_TAMPER_REPORT.json",
            "ZIP_VERIFICATION.json",
            ".release_preflight.json",
        } or rel.startswith("receipts/"):
            continue
        if rel.endswith((".zip", ".sha256")):
            continue
        entries.append({"path": rel, "sha256": sha256_file(path)})
    return entries


def write_manifest(root: Path) -> dict[str, Any]:
    entries = _manifest_entries(root)
    source_entries = [
        entry for entry in entries
        if entry["path"].startswith(("src/", "tests/", "scripts/", "examples/"))
        or entry["path"] in {"pyproject.toml", "experiment.json", "PREREGISTRATION.json"}
    ]
    manifest = {
        "schema": "openline.endurance.manifest.v2",
        "entry_count": len(entries),
        "entries": entries,
        "source_tree_digest": sha256_bytes(canonical_json(source_entries)),
    }
    _json_dump(root / "MANIFEST.json", manifest)
    return manifest


def _design_witness(experiment: dict[str, Any]) -> dict[str, Any]:
    seed = int(experiment["heldout_seeds"][0])
    base_events = generate_perturbations(seed, experiment["amplitude_multiset"])
    event = base_events[0]
    left = run_one("fresh_ground_truth", "schedule_label_a", seed, [event], experiment, "design_witness", 1.0, 1.0)
    right = run_one("fresh_ground_truth", "schedule_label_b", seed, [event], experiment, "design_witness", 1.0, 1.0)
    excluded = {"schedule"}
    left_row = {key: value for key, value in left.cycles[0].items() if key not in excluded}
    right_row = {key: value for key, value in right.cycles[0].items() if key not in excluded}
    return {
        "schema": "openline.endurance.design-witness.v1",
        "randomness_coupling": experiment["randomness_coupling"],
        "schedule_label_invariance_for_identical_one_cycle_state": left_row == right_row,
        "matched_amplitude_packet": matched_packet_witness(seed, int(experiment["primary_cycles"])),
        "primary_order_pair_count": len(experiment["heldout_seeds"]) * len(experiment["modes"]),
        "minimum_primary_order_pairs": experiment["analysis_plan"]["minimum_primary_order_pairs"],
    }


def _receipt_items(
    primary_runs: list[dict[str, Any]],
    amplitude_runs: list[dict[str, Any]],
    calibration: dict[str, Any],
    summary: dict[str, Any],
    tip_summary: dict[str, Any],
    collision_summary: dict[str, Any],
    evidence: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]] :
    items: list[tuple[str, dict[str, Any]]] = [
        (
            "experiment_contract",
            {
                "claim": "test cumulative coherence damage and load-order effects with event-bound common random numbers and without using D to generate outcomes",
                "result": "preregistered_contract_loaded",
            },
        ),
        ("fresh_calibration", {"claim": "isolated perturbations are subcritical for a fresh agent", "result": calibration}),
    ]
    for row in primary_runs:
        items.append(
            (
                "primary_run",
                {
                    "claim": "one matched schedule-mode-seed run completed",
                    "action": {"mode": row["mode"], "schedule": row["schedule"], "seed": row["seed"]},
                    "result": {"n_f": row["n_f"], "failed": row["failed"], "checkpoint_accuracy": row["mean_checkpoint_accuracy"]},
                    "tokens_used": row["total_tokens"],
                    "next_use": "powered paired schedule and handoff comparison",
                },
            )
        )
    for row in amplitude_runs:
        items.append(
            (
                "amplitude_sweep_run",
                {
                    "claim": "one matched-packet constant-amplitude endurance run completed",
                    "action": {"mode": row["mode"], "schedule": row["schedule"], "seed": row["seed"]},
                    "result": {"n_f": row["n_f"], "failed": row["failed"]},
                    "tokens_used": row["total_tokens"],
                    "next_use": "matched amplitude-to-fatigue-life gradient",
                },
            )
        )
    items.extend(
        [
            (
                "digital_fractography",
                {
                    "claim": "the dominant synthetic crack cluster was reconstructed from unresolved dependencies and invariant failures",
                    "result": summary["fractography"]["dominant_crack_cluster"],
                    "next_use": "locate crack origin and repair behavior before real-agent testing",
                },
            ),
            (
                "heldout_analysis",
                {
                    "claim": "pre-registered endurance gates were evaluated on untouched seeds",
                    "result": {
                        "status": summary["endurance_status"],
                        "passed": summary["endurance_passed_gate_count"],
                        "total": summary["endurance_gate_count"],
                        "order_pairs": summary["order_effect"]["paired_difference_count"],
                    },
                    "next_use": "decide which endurance mechanism survives a real-agent test",
                },
            ),
            (
                "execution_tip_capture",
                {
                    "claim": "frontier geometry, equal-budget repair, null specificity, and root-cause recovery were evaluated on frozen held-out seeds",
                    "result": {
                        "status": tip_summary["status"],
                        "passed": tip_summary["passed_gate_count"],
                        "total": tip_summary["gate_count"],
                        "heldout_seeds": tip_summary["heldout_seed_count"],
                    },
                    "next_use": "separate geometry instrumentation from claims about deployed agents",
                },
            ),
            (
                "collision_aware_spacing",
                {
                    "claim": "matched Ulam, random-sparse, clustered, and conflict-aware spacing conditions were evaluated without changing event order or random draws",
                    "result": {
                        "status": collision_summary["status"],
                        "passed": collision_summary["passed_gate_count"],
                        "total": collision_summary["gate_count"],
                        "heldout_seeds": collision_summary["heldout_seed_count"],
                    },
                    "next_use": "decide whether irregular timing or graph-aware separation deserves a real-agent trace experiment",
                },
            ),
            ("evidence_bundle", evidence),
        ]
    )
    return items


def _run_v5_collision_extension(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    lineage_errors = verify_v040_lineage(root)
    if lineage_errors:
        raise RuntimeError(f"v0.4.0 lineage failed: {lineage_errors}")

    results_dir = root / "results"
    receipts_dir = root / "receipts"
    results_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    collision_events, collision_runs = simulate_collision_spacing(experiment)
    collision_summary = analyze_collision_spacing(collision_runs, experiment)
    old_summary = json.loads((root / "lineage/v0.4.0/results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_TIP_CAPTURE_AND_COLLISION_SPACING"
    summary["collision_spacing"] = collision_summary
    summary["legacy_scientific_result_preserved"] = {
        "status": old_summary["theory_status"],
        "passed_gate_count": old_summary["passed_gate_count"],
        "gate_count": old_summary["gate_count"],
    }

    write_csv(results_dir / "collision_spacing_events.csv", collision_events, COLLISION_EVENT_FIELDS)
    write_csv(results_dir / "collision_spacing_runs.csv", collision_runs, COLLISION_RUN_FIELDS)
    _json_dump(results_dir / "collision_spacing_design_witness.json", collision_design_witness(experiment))
    _json_dump(results_dir / "collision_spacing_summary.json", collision_summary)
    (results_dir / "collision_spacing_summary.md").write_text(_collision_summary_markdown(collision_summary), encoding="utf-8")

    old_heldout = json.loads((root / "lineage/v0.4.0/results/heldout_witness.json").read_text(encoding="utf-8"))
    heldout = dict(old_heldout)
    heldout["collision_spacing"] = collision_summary
    _json_dump(results_dir / "heldout_witness.json", heldout)
    _json_dump(results_dir / "summary.json", summary)
    (results_dir / "summary.md").write_text(
        _summary_markdown(summary) + "\n" + _collision_summary_markdown(collision_summary),
        encoding="utf-8",
    )

    old_roots = json.loads((root / "lineage/v0.4.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    cycle_roots = dict(old_roots)
    cycle_roots["schema"] = "openline.endurance.cycle-roots.v2"
    cycle_roots["collision_spacing_event_merkle_root"] = merkle_root(collision_events)
    cycle_roots["collision_spacing_event_count"] = len(collision_events)
    cycle_roots["collision_spacing_run_merkle_root"] = merkle_root(collision_runs)
    cycle_roots["collision_spacing_run_count"] = len(collision_runs)
    _json_dump(results_dir / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_semantic_artifacts = list(BASE_SEMANTIC_ARTIFACTS)
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"],
        cycle_roots["amplitude_cycle_merkle_root"],
        {
            "tip_capture_cycle_merkle_root": cycle_roots["tip_capture_cycle_merkle_root"],
            "tip_capture_candidate_merkle_root": cycle_roots["tip_capture_candidate_merkle_root"],
            "tip_capture_probe_merkle_root": cycle_roots["tip_capture_probe_merkle_root"],
            "collision_spacing_event_merkle_root": cycle_roots["collision_spacing_event_merkle_root"],
            "collision_spacing_run_merkle_root": cycle_roots["collision_spacing_run_merkle_root"],
        },
        base_semantic_artifacts,
    )
    _json_dump(results_dir / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_semantic_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": "v0.4.0 scientific artifacts are pinned byte-for-byte and v0.5.0 collision-spacing results are independently recomputable",
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        "tip_capture_cycle_merkle_root": cycle_roots["tip_capture_cycle_merkle_root"],
        "tip_capture_candidate_merkle_root": cycle_roots["tip_capture_candidate_merkle_root"],
        "tip_capture_probe_merkle_root": cycle_roots["tip_capture_probe_merkle_root"],
        "collision_spacing_event_merkle_root": cycle_roots["collision_spacing_event_merkle_root"],
        "collision_spacing_run_merkle_root": cycle_roots["collision_spacing_run_merkle_root"],
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": "v0.5 recomputes collision spacing and verifies inherited v0.4 artifacts against a pinned release lineage; it does not rerun the inherited first-contact simulator",
    }

    old_chain = read_chain(root / "lineage/v0.4.0/receipts/experiment.jsonl")
    items = [(receipt["kind"], receipt["payload"]) for receipt in old_chain if receipt["kind"] != "evidence_bundle"]
    items.append((
        "collision_aware_spacing",
        {
            "claim": "matched Ulam, random-sparse, clustered, and conflict-aware spacing conditions were evaluated without changing event order or random draws",
            "result": {
                "status": collision_summary["status"],
                "passed": collision_summary["passed_gate_count"],
                "total": collision_summary["gate_count"],
                "heldout_seeds": collision_summary["heldout_seed_count"],
            },
            "next_use": "test graph-informed spacing on real agent traces; do not treat Ulam as a semantic separator",
        },
    ))
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "summary": summary,
        "collision_spacing_summary": collision_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "v040_lineage_valid": True,
        "private_key_persisted": False,
    }



def _generational_summary_markdown(summary: dict[str, Any]) -> str:
    modes = summary["modes"]
    capsule = modes["verified_inheritance_capsule"]
    continuous = modes["continuous_full_history"]
    ordinary = modes["ordinary_summary_reset"]
    conflict = modes["capsule_conflict_aware"]
    lines = [
        "# OpenLine Generational Endurance — Exploratory Synthetic Run",
        "",
        f"**Status:** `{summary['status']}`",
        f"**Exploratory gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Maximum verified horizon:** {summary['maximum_verified_horizon_cycles']} cycles",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        "",
        "## Horizon and context witness",
        "",
        f"- Capsule survival at 40/80/160: {capsule['survival_40']:.3f} / {capsule['survival_80']:.3f} / {capsule['survival_160']:.3f}",
        f"- Ordinary-summary survival at 40/80/160: {ordinary['survival_40']:.3f} / {ordinary['survival_80']:.3f} / {ordinary['survival_160']:.3f}",
        f"- Continuous-history survival at 40/80/160: {continuous['survival_40']:.3f} / {continuous['survival_80']:.3f} / {continuous['survival_160']:.3f}",
        f"- Capsule active-context ratio versus continuous at 40/80/160: {summary['compression_witness']['active_context_ratio_40']:.3f} / {summary['compression_witness']['active_context_ratio_80']:.3f} / {summary['compression_witness']['active_context_ratio_160']:.3f}",
        f"- Capsule median life versus summary gain: {summary['effects']['capsule_vs_summary']['median_difference_cycles']:.3f} cycles; p={summary['effects']['capsule_vs_summary']['exact_sign_flip_p']:.6g}",
        f"- Conflict-aware capsule versus capsule median gain: {summary['effects']['conflict_vs_capsule']['median_difference_cycles']:.3f} cycles; p={summary['effects']['conflict_vs_capsule']['exact_sign_flip_p']:.6g}",
        f"- Pressure-disabled capsule minus continuous median life: {summary['effects']['pressure_disabled_capsule_vs_continuous']['median_difference_cycles']:.3f} cycles",
        "",
        "## Exploratory gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend([
        "",
        "## Plain-language result",
        "",
        "The verified capsule carried a median lineage through 80 cycles while using less than half the active context of continuous history. It did not clear 160 cycles. Conflict-aware ordering lowered omissions and improved accuracy, but it did not add a statistically detectable life extension over the capsule alone.",
        "",
        "## Boundary",
        "",
        summary["claim_boundary"],
        "",
    ])
    return "\n".join(lines) + "\n"


def _run_v6_generational_extension(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    lineage_errors = verify_v050_lineage(root)
    if lineage_errors:
        raise RuntimeError(f"v0.5.0 lineage failed: {lineage_errors}")

    results_dir = root / "results"
    receipts_dir = root / "receipts"
    results_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    generational_cycles, generational_runs = simulate_generational_endurance(experiment)
    generational_summary = analyze_generational_endurance(generational_runs, experiment)
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

    write_csv(results_dir / "generational_cycles.csv", generational_cycles, GENERATIONAL_CYCLE_FIELDS)
    write_csv(results_dir / "generational_runs.csv", generational_runs, GENERATIONAL_RUN_FIELDS)
    _json_dump(results_dir / "generational_design_witness.json", generational_design_witness(experiment))
    _json_dump(results_dir / "generational_summary.json", generational_summary)
    (results_dir / "generational_summary.md").write_text(
        _generational_summary_markdown(generational_summary), encoding="utf-8"
    )

    old_heldout = json.loads((root / "lineage/v0.5.0/results/heldout_witness.json").read_text(encoding="utf-8"))
    heldout = dict(old_heldout)
    heldout["generational_endurance"] = generational_summary
    _json_dump(results_dir / "heldout_witness.json", heldout)
    _json_dump(results_dir / "summary.json", summary)
    old_summary_markdown = (root / "lineage/v0.5.0/results/summary.md").read_text(encoding="utf-8")
    (results_dir / "summary.md").write_text(
        old_summary_markdown.rstrip() + "\n\n" + _generational_summary_markdown(generational_summary),
        encoding="utf-8",
    )

    old_roots = json.loads((root / "lineage/v0.5.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    cycle_roots = dict(old_roots)
    cycle_roots["schema"] = "openline.endurance.cycle-roots.v3"
    cycle_roots["generational_cycle_merkle_root"] = merkle_root(generational_cycles)
    cycle_roots["generational_cycle_count"] = len(generational_cycles)
    cycle_roots["generational_run_merkle_root"] = merkle_root(generational_runs)
    cycle_roots["generational_run_count"] = len(generational_runs)
    _json_dump(results_dir / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_semantic_artifacts = list(V6_SEMANTIC_ARTIFACTS)
    additional_roots = {
        key: value for key, value in cycle_roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"],
        cycle_roots["amplitude_cycle_merkle_root"],
        additional_roots,
        base_semantic_artifacts,
    )
    _json_dump(results_dir / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_semantic_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": "v0.5.0 scientific artifacts are pinned byte-for-byte and v0.6.0 generational-endurance results are independently recomputable",
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        **additional_roots,
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": "v0.6 recomputes generational endurance and verifies inherited v0.5 artifacts against pinned lineage; it does not rerun inherited first-contact or collision-spacing worlds",
    }

    old_chain = read_chain(root / "lineage/v0.5.0/receipts/experiment.jsonl")
    items = [(receipt["kind"], receipt["payload"]) for receipt in old_chain if receipt["kind"] != "evidence_bundle"]
    items.append((
        "generational_endurance",
        {
            "claim": "finite verified inheritance was tested over a 40/80/160 doubling ladder against continuous history and an equal-budget ordinary summary",
            "result": {
                "status": generational_summary["status"],
                "passed": generational_summary["passed_gate_count"],
                "total": generational_summary["gate_count"],
                "maximum_verified_horizon_cycles": generational_summary["maximum_verified_horizon_cycles"],
                "heldout_seeds": generational_summary["heldout_seed_count"],
            },
            "next_use": "test capsule construction on real agent traces; preserve the 160-cycle and conflict-scheduling failures",
        },
    ))
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "summary": summary,
        "generational_summary": generational_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "v050_lineage_valid": True,
        "private_key_persisted": False,
    }


def _state_restoration_summary_markdown(summary: dict[str, Any]) -> str:
    modes = summary["modes"]
    baseline = modes["capsule_baseline"]
    stack = modes["restoration_stack"]
    lines = [
        "# OpenLine State Restoration — Exploratory Synthetic Run",
        "",
        f"**Status:** `{summary['status']}`",
        f"**Exploratory gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        "",
        "## Endurance witness",
        "",
        f"- Capsule baseline survival at 160/320: {baseline['survival_160']:.3f} / {baseline['survival_320']:.3f}",
        f"- Restoration stack survival at 160/320: {stack['survival_160']:.3f} / {stack['survival_320']:.3f}",
        f"- Stack minus baseline median life: {summary['effects']['stack_vs_baseline']['median_difference_cycles']:.3f} cycles; p={summary['effects']['stack_vs_baseline']['exact_sign_flip_p']:.6g}",
        f"- Fixed retirement minus baseline median life: {summary['effects']['fixed_retirement_vs_baseline']['median_difference_cycles']:.3f} cycles; p={summary['effects']['fixed_retirement_vs_baseline']['exact_sign_flip_p']:.6g}",
        f"- Sham retirement minus baseline median life: {summary['effects']['sham_vs_baseline']['median_difference_cycles']:.3f} cycles",
        "",
        "## Exploratory gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend([
        "",
        "## Boundary",
        "",
        summary["telemetry_boundary"],
        "",
        summary["claim_boundary"],
        "",
    ])
    return "\n".join(lines) + "\n"


def _run_v7_state_restoration_extension(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    lineage_errors = verify_v060_lineage(root)
    if lineage_errors:
        raise RuntimeError(f"v0.6.0 lineage failed: {lineage_errors}")

    results_dir = root / "results"
    receipts_dir = root / "receipts"
    results_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    streamed = (
        finalize_state_restoration_shards(root, experiment)
        if state_restoration_shards_ready(root, experiment)
        else stream_state_restoration(experiment, results_dir / "state_restoration_cycles.csv.gz")
    )
    restoration_runs = streamed["runs"]
    shutil.rmtree(results_dir / ".state_restoration_work", ignore_errors=True)
    restoration_summary = analyze_state_restoration(restoration_runs, experiment)
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

    write_csv(results_dir / "state_restoration_runs.csv", restoration_runs, RESTORATION_RUN_FIELDS)
    _json_dump(results_dir / "state_restoration_design_witness.json", state_restoration_design_witness(experiment))
    _json_dump(results_dir / "state_restoration_summary.json", restoration_summary)
    (results_dir / "state_restoration_summary.md").write_text(
        _state_restoration_summary_markdown(restoration_summary), encoding="utf-8"
    )

    old_heldout = json.loads((root / "lineage/v0.6.0/results/heldout_witness.json").read_text(encoding="utf-8"))
    heldout = dict(old_heldout)
    heldout["state_restoration"] = restoration_summary
    _json_dump(results_dir / "heldout_witness.json", heldout)
    _json_dump(results_dir / "summary.json", summary)
    old_summary_markdown = (root / "lineage/v0.6.0/results/summary.md").read_text(encoding="utf-8")
    (results_dir / "summary.md").write_text(
        old_summary_markdown.rstrip() + "\n\n" + _state_restoration_summary_markdown(restoration_summary),
        encoding="utf-8",
    )

    old_roots = json.loads((root / "lineage/v0.6.0/results/cycle_roots.json").read_text(encoding="utf-8"))
    cycle_roots = dict(old_roots)
    cycle_roots["schema"] = "openline.endurance.cycle-roots.v4"
    cycle_roots["state_restoration_cycle_merkle_root"] = streamed["cycle_merkle_root"]
    cycle_roots["state_restoration_cycle_count"] = streamed["cycle_count"]
    cycle_roots["state_restoration_run_merkle_root"] = streamed["run_merkle_root"]
    cycle_roots["state_restoration_run_count"] = streamed["run_count"]
    _json_dump(results_dir / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_semantic_artifacts = list(V7_SEMANTIC_ARTIFACTS)
    additional_roots = {
        key: value for key, value in cycle_roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"],
        cycle_roots["amplitude_cycle_merkle_root"],
        additional_roots,
        base_semantic_artifacts,
    )
    _json_dump(results_dir / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_semantic_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": "v0.6.0 scientific artifacts are pinned byte-for-byte and v0.7.0 state-restoration results are independently recomputable",
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        **additional_roots,
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": "v0.7 recomputes state restoration and verifies inherited v0.6 artifacts against pinned lineage; synthetic telemetry proxies do not identify a physical 160-cycle law",
    }

    old_chain = read_chain(root / "lineage/v0.6.0/receipts/experiment.jsonl")
    items = [(receipt["kind"], receipt["payload"]) for receipt in old_chain if receipt["kind"] != "evidence_bundle"]
    items.append((
        "state_restoration",
        {
            "claim": "pruning, fixed retirement, telemetry-triggered retirement, digest correction, a combined stack, and sham controls were tested beyond the inherited capsule baseline",
            "result": {
                "status": restoration_summary["status"],
                "passed": restoration_summary["passed_gate_count"],
                "total": restoration_summary["gate_count"],
                "heldout_seeds": restoration_summary["heldout_seed_count"],
            },
            "next_use": "test the surviving restoration policies on real agent traces and preserve every failed gate",
        },
    ))
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "summary": summary,
        "state_restoration_summary": restoration_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "v060_lineage_valid": True,
        "private_key_persisted": False,
    }


def _load_rate_summary_markdown(summary: dict[str, Any]) -> str:
    primary = summary["primary_effect"]
    recovery = summary["recovery_effect"]
    null = summary["null_effect"]
    lines = [
        "# OpenLine Load-Rate Transition — Same Disturbance, Different Speed",
        "",
        f"**Status:** `{summary['status']}`",
        f"**Exploratory gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        f"**Held-out seeds:** {summary['heldout_seed_count']}",
        f"**Cycle observations:** {summary['cycle_observation_count']}",
        "",
        "## Primary contrast",
        "",
        "- Same perturbations, same order, same total load, same ordinary work, same horizon, and the same context cap.",
        f"- Slow minus sudden-burst mean disturbances survived: {primary['mean_difference_disturbances']:.6f}; 95% interval={primary['mean_confidence_interval_disturbances']}; p={primary['exact_sign_flip_p']:.6g}",
        f"- Recovery-window minus continuous-burst mean disturbances survived: {recovery['mean_difference_disturbances']:.6f}; 95% interval={recovery['mean_confidence_interval_disturbances']}; p={recovery['exact_sign_flip_p']:.6g}",
        f"- Rate-disabled null mean difference: {null['mean_difference_disturbances']:.6f}; 95% interval={null['mean_confidence_interval_disturbances']}",
        "- Mode-specific null differences: " + ", ".join(
            f"{mode}={effect['mean_difference_disturbances']:.6f}"
            for mode, effect in summary.get("per_mode_null_effects", {}).items()
        ),
        "",
        "## Exploratory gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend([
        "",
        "## Boundary",
        "",
        summary["claim_boundary"],
        "",
        "Synthetic damage is reported as a secondary diagnostic. It does not decide the primary rate gate.",
        "",
    ])
    return "\n".join(lines) + "\n"


def _run_v8_load_rate_extension(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    is_phase_controlled_replication = str(experiment.get("release_version")) == "0.8.1"
    lineage_errors = (verify_v070_lineage(root) + verify_v080_lineage(root)) if is_phase_controlled_replication else verify_v070_lineage(root)
    if lineage_errors:
        label = "v0.8.0" if is_phase_controlled_replication else "v0.7.0"
        raise RuntimeError(f"{label} lineage failed: {lineage_errors}")
    lineage_root = root / ("lineage/v0.8.0" if is_phase_controlled_replication else "lineage/v0.7.0")

    results_dir = root / "results"
    receipts_dir = root / "receipts"
    results_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    streamed_rate = (
        finalize_load_rate_shards(root, experiment)
        if load_rate_shards_ready(root, experiment)
        else stream_load_rate(experiment, root)
    )
    runs = streamed_rate["runs"]
    # The bounded generation witnesses are transient execution plumbing. The
    # released evidence is the deterministic cycle shards and their global root.
    shutil.rmtree(results_dir / ".load_rate_work", ignore_errors=True)
    rate_summary = analyze_load_rate(CountedRows(streamed_rate["cycle_count"]), runs, experiment)
    design = load_rate_design_witness(experiment)
    old_summary = json.loads((lineage_root / "results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_AND_PHASE_CONTROLLED_LOAD_RATE_REPLICATION" if is_phase_controlled_replication else "POWERED_SYNTHETIC_ENDURANCE_AND_LOAD_RATE_TRANSITION"
    if is_phase_controlled_replication:
        summary["load_rate_v080_result_preserved"] = old_summary.get("load_rate")
    summary["load_rate"] = rate_summary
    summary["legacy_v070_result_preserved"] = {
        "theory_status": old_summary["theory_status"],
        "passed_gate_count": old_summary["passed_gate_count"],
        "gate_count": old_summary["gate_count"],
        "state_restoration_status": old_summary.get("state_restoration", {}).get("status"),
        "state_restoration_passed_gate_count": old_summary.get("state_restoration", {}).get("passed_gate_count"),
        "state_restoration_gate_count": old_summary.get("state_restoration", {}).get("gate_count"),
    }

    write_csv(results_dir / "load_rate_runs.csv", runs, LOAD_RATE_RUN_FIELDS)
    _json_dump(results_dir / "load_rate_design_witness.json", design)
    _json_dump(results_dir / "load_rate_summary.json", rate_summary)
    (results_dir / "load_rate_summary.md").write_text(_load_rate_summary_markdown(rate_summary), encoding="utf-8")

    old_heldout = json.loads((lineage_root / "results/heldout_witness.json").read_text(encoding="utf-8"))
    heldout = dict(old_heldout)
    if is_phase_controlled_replication:
        heldout["load_rate_v080_result_preserved"] = old_heldout.get("load_rate")
    heldout["load_rate"] = rate_summary
    _json_dump(results_dir / "heldout_witness.json", heldout)
    _json_dump(results_dir / "summary.json", summary)
    old_summary_markdown = (lineage_root / "results/summary.md").read_text(encoding="utf-8")
    (results_dir / "summary.md").write_text(
        old_summary_markdown.rstrip() + "\n\n" + _load_rate_summary_markdown(rate_summary),
        encoding="utf-8",
    )

    old_roots = json.loads((lineage_root / "results/cycle_roots.json").read_text(encoding="utf-8"))
    cycle_roots = dict(old_roots)
    cycle_roots["schema"] = "openline.endurance.cycle-roots.v6" if is_phase_controlled_replication else "openline.endurance.cycle-roots.v5"
    if is_phase_controlled_replication:
        cycle_roots["load_rate_v080_cycle_merkle_root"] = old_roots.get("load_rate_cycle_merkle_root")
        cycle_roots["load_rate_v080_cycle_count"] = old_roots.get("load_rate_cycle_count")
        cycle_roots["load_rate_v080_run_merkle_root"] = old_roots.get("load_rate_run_merkle_root")
        cycle_roots["load_rate_v080_run_count"] = old_roots.get("load_rate_run_count")
    cycle_roots.update({
        "load_rate_cycle_merkle_root": streamed_rate["cycle_merkle_root"],
        "load_rate_cycle_count": streamed_rate["cycle_count"],
        "load_rate_run_merkle_root": streamed_rate["run_merkle_root"],
        "load_rate_run_count": streamed_rate["run_count"],
    })
    _json_dump(results_dir / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_semantic_artifacts = list(V8_SEMANTIC_ARTIFACTS)
    additional_roots = {
        key: value for key, value in cycle_roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root, experiment, summary, manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"], cycle_roots["amplitude_cycle_merkle_root"],
        additional_roots, base_semantic_artifacts,
    )
    _json_dump(results_dir / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_semantic_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": ("v0.8.0 is pinned byte-for-byte and v0.8.1 reruns the matched load-rate test after removing the ordinary-work context-retention confound" if is_phase_controlled_replication else "v0.7.0 scientific artifacts are pinned byte-for-byte and v0.8.0 independently tests matched disturbance delivery rates"),
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        **additional_roots,
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": ("v0.8.1 is a fresh-seed phase-controlled synthetic replication. It isolates retained context from spacing; it does not establish a deployed-agent law." if is_phase_controlled_replication else "v0.8 tests rate in a seeded synthetic world; it does not claim AI systems obey fluid mechanics or identify a universal retirement threshold."),
    }

    old_chain = read_chain(lineage_root / "receipts/experiment.jsonl")
    items = [(receipt["kind"], receipt["payload"]) for receipt in old_chain if receipt["kind"] != "evidence_bundle"]
    items.append((
        "load_rate_phase_controlled_replication" if is_phase_controlled_replication else "load_rate_transition",
        {
            "claim": ("fresh-seed matched schedules were rerun after ordinary task scratch context was made ephemeral, removing the discovered schedule-to-context pathway" if is_phase_controlled_replication else "matched disturbance packets were delivered at four rates while ordinary work, order, load, horizon, and context cap remained fixed"),
            "result": {
                "status": rate_summary["status"],
                "passed": rate_summary["passed_gate_count"],
                "total": rate_summary["gate_count"],
                "heldout_seeds": rate_summary["heldout_seed_count"],
                "primary_mean_disturbance_gain": rate_summary["primary_effect"]["mean_difference_disturbances"],
            },
            "next_use": ("treat v0.8.0 as the confounded discovery run and v0.8.1 as the phase-controlled replication" if is_phase_controlled_replication else "only if rate survives, test an activation-envelope intervention in a later preregistered release"),
        },
    ))
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "summary": summary,
        "load_rate_summary": rate_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "v080_lineage_valid": bool(is_phase_controlled_replication),
        "v070_lineage_valid": True,
        "private_key_persisted": False,
    }


def _recovery_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# OpenLine Recovery Intervention — Pass 1",
        "",
        f"**Status:** `{summary['status']}`",
        f"**Preregistered {summary['release']} gates:** {summary['passed_gate_count']}/{summary['gate_count']} passed",
        "",
        "## Held-out condition measurements",
        "",
    ]
    for mode, values in summary["heldout_by_mode"].items():
        lines.append(
            f"- `{mode}`: mean n_f={values['mean_cycles_until_failure']:.3f}; "
            f"post-handoff accuracy={values['mean_post_handoff_decision_accuracy']:.6f}; "
            f"policy violations={values['total_policy_violations']}; "
            f"mean packet bytes={values['mean_packet_bytes']:.1f}"
        )
    lines.extend(["", "## Gates", ""])
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend(["", "## Boundary", "", summary["claim_boundary"], ""])
    if "freshness_binding" in summary:
        lines.extend([
            "Stateful run, parent, and generation freshness binding is active. Stale replay, cross-run copy, and correctly signed omission were tested on fresh seeds.", "",
        ])
    else:
        lines.extend([
            "Freshness/replay state, cross-run binding, and signed omission testing are deferred to v0.9.1 with fresh seeds.", "",
        ])
    return "\n".join(lines)


def _timing_observations(handoffs: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "status": "ENVIRONMENT_SENSITIVE_EXCLUDED_FROM_REPRODUCIBILITY_CLAIMS",
        "units": "nanoseconds", "by_mode": {},
    }
    for mode in ["continuous_control", "empty_reset", "full_history_handoff", "unsigned_minimal_handoff", "olp_handoff"]:
        rows = [row for row in handoffs if row["mode"] == mode]
        output["by_mode"][mode] = {
            field: {
                "median": sorted(int(row[field]) for row in rows)[len(rows) // 2] if rows else None,
                "minimum": min((int(row[field]) for row in rows), default=None),
                "maximum": max((int(row[field]) for row in rows), default=None),
            }
            for field in ("handoff_wall_ns", "handoff_cpu_ns", "verification_wall_ns", "verification_cpu_ns")
        }
    return output


def _run_v9_recovery_extension(root: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    is_v091 = experiment.get("schema") == "openline.endurance.experiment.v10"
    lineage_errors = (
        verify_v090_lineage(root) + verify_v091_lineage(root)
        if is_v091 else verify_v090_lineage(root)
    )
    if lineage_errors:
        label = "v0.9.0" if is_v091 else "v0.8.1"
        raise RuntimeError(f"{label} lineage failed: {lineage_errors}")
    lineage_root = root / ("lineage/v0.9.0" if is_v091 else "lineage/v0.8.1")
    results = root / "results"
    receipts = root / "receipts"
    results.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    streamed = (
        finalize_recovery_shards(root, experiment)
        if recovery_shards_ready(root, experiment) else stream_recovery(experiment, root)
    )
    runs, handoffs = streamed["runs"], streamed["handoffs"]
    shutil.rmtree(results / ".recovery_work", ignore_errors=True)
    cycles: list[dict[str, Any]] = []
    for name in recovery_shard_names(experiment):
        cycles.extend(read_gzip_csv(results / name))
    hostile = run_hostile_controls()
    recovery_summary = analyze_recovery(cycles, runs, experiment, hostile)
    recovery_summary["timing_observations"] = _timing_observations(handoffs)
    design = recovery_design_witness(experiment)

    write_csv(results / "recovery_runs.csv", runs, RECOVERY_RUN_FIELDS)
    with (results / "recovery_handoffs.jsonl").open("w", encoding="utf-8") as handle:
        for observation in handoffs:
            handle.write(json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n")
    _json_dump(results / "recovery_design_witness.json", design)
    _json_dump(results / "recovery_hostile_controls.json", hostile)
    _json_dump(results / "recovery_summary.json", recovery_summary)
    (results / "recovery_summary.md").write_text(_recovery_summary_markdown(recovery_summary), encoding="utf-8")

    gate_paths = [
        *[f"results/{name}" for name in recovery_shard_names(experiment)],
        "results/recovery_runs.csv", "results/recovery_handoffs.jsonl",
        "results/recovery_design_witness.json", "results/recovery_hostile_controls.json",
        "results/recovery_summary.json",
    ]
    module_gate = {
        "schema": "openline.endurance.recovery-release-gate.v2" if is_v091 else "openline.endurance.recovery-release-gate.v1",
        "release": experiment["release_version"],
        "pass": 2 if is_v091 else 1, "scientific_status": recovery_summary["status"],
        "all_preregistered_gates_pass": recovery_summary["passed_gate_count"] == recovery_summary["gate_count"],
        "hostile_controls_pass": hostile["all_passed"], "hostile_control_count": hostile["attack_count"],
        "artifact_hashes": artifact_hashes(root, gate_paths),
        "outer_attestation": "BOUND_BY_EXISTING_RELEASE_ATTESTATION_PIPELINE",
        "freshness_replay_status": "ACTIVE_AND_HOSTILE_TESTED" if is_v091 else "DEFERRED_TO_V0.9.1",
    }
    module_gate["passed"] = bool(module_gate["all_preregistered_gates_pass"] and module_gate["hostile_controls_pass"])
    _json_dump(root / "RECOVERY_RELEASE_GATE.json", module_gate)

    old_summary = json.loads((lineage_root / "results/summary.json").read_text(encoding="utf-8"))
    summary = dict(old_summary)
    summary["claim_label"] = (
        "POWERED_SYNTHETIC_ENDURANCE_AND_STATEFUL_FRESHNESS_BOUND_RECOVERY"
        if is_v091 else "POWERED_SYNTHETIC_ENDURANCE_PHASE_CONTROLLED_LOAD_RATE_AND_RECOVERY_INTERVENTION"
    )
    if is_v091:
        summary["recovery_v090_result_preserved"] = old_summary.get("recovery")
    summary["recovery"] = recovery_summary
    if is_v091:
        summary["legacy_v090_result_preserved"] = {
            "recovery_status": old_summary.get("recovery", {}).get("status"),
            "recovery_passed_gate_count": old_summary.get("recovery", {}).get("passed_gate_count"),
            "recovery_gate_count": old_summary.get("recovery", {}).get("gate_count"),
        }
    else:
        summary["legacy_v081_result_preserved"] = {
            "load_rate": old_summary.get("load_rate"),
            "theory_status": old_summary.get("theory_status"),
            "passed_gate_count": old_summary.get("passed_gate_count"),
            "gate_count": old_summary.get("gate_count"),
        }
    old_heldout = json.loads((lineage_root / "results/heldout_witness.json").read_text(encoding="utf-8"))
    heldout = dict(old_heldout)
    if is_v091:
        heldout["recovery_v090_result_preserved"] = old_heldout.get("recovery")
    heldout["recovery"] = recovery_summary
    _json_dump(results / "heldout_witness.json", heldout)
    _json_dump(results / "summary.json", summary)
    inherited_markdown = (lineage_root / "results/summary.md").read_text(encoding="utf-8")
    (results / "summary.md").write_text(
        inherited_markdown.rstrip() + "\n\n" + _recovery_summary_markdown(recovery_summary), encoding="utf-8",
    )

    cycle_roots = dict(json.loads((lineage_root / "results/cycle_roots.json").read_text(encoding="utf-8")))
    cycle_roots["schema"] = "openline.endurance.cycle-roots.v8" if is_v091 else "openline.endurance.cycle-roots.v7"
    if is_v091:
        cycle_roots.update({
            "recovery_v090_cycle_merkle_root": cycle_roots.get("recovery_cycle_merkle_root"),
            "recovery_v090_cycle_count": cycle_roots.get("recovery_cycle_count"),
            "recovery_v090_run_merkle_root": cycle_roots.get("recovery_run_merkle_root"),
            "recovery_v090_run_count": cycle_roots.get("recovery_run_count"),
            "recovery_v090_handoff_semantic_merkle_root": cycle_roots.get("recovery_handoff_semantic_merkle_root"),
            "recovery_v090_handoff_count": cycle_roots.get("recovery_handoff_count"),
        })
    cycle_roots.update({
        "recovery_cycle_merkle_root": streamed["cycle_merkle_root"],
        "recovery_cycle_count": streamed["cycle_count"],
        "recovery_run_merkle_root": streamed["run_merkle_root"],
        "recovery_run_count": streamed["run_count"],
        "recovery_handoff_semantic_merkle_root": streamed["handoff_semantic_merkle_root"],
        "recovery_handoff_count": streamed["handoff_count"],
    })
    _json_dump(results / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_artifacts = list(V91_SEMANTIC_ARTIFACTS if is_v091 else V9_SEMANTIC_ARTIFACTS)
    additional_roots = {
        key: value for key, value in cycle_roots.items()
        if key.endswith("_merkle_root") and key not in {"primary_cycle_merkle_root", "amplitude_cycle_merkle_root"}
    }
    public_witness = build_public_witness(
        root, experiment, summary, manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"], cycle_roots["amplitude_cycle_merkle_root"],
        additional_roots, base_artifacts,
    )
    _json_dump(results / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": (
            "v0.9.0 is pinned byte-for-byte and v0.9.1 independently tests stateful recovery freshness on fresh seeds"
            if is_v091 else "v0.8.1 is pinned byte-for-byte and v0.9.0 independently tests the preregistered recovery intervention"
        ),
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        **additional_roots, "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance recovery-semantic-shard/finalize",
        "claim_boundary": recovery_summary["claim_boundary"],
    }
    old_chain = read_chain(lineage_root / "receipts/experiment.jsonl")
    items = [(item["kind"], item["payload"]) for item in old_chain if item["kind"] != "evidence_bundle"]
    items.append(("recovery_freshness_binding" if is_v091 else "recovery_intervention", {
        "claim": recovery_summary["claim_boundary"],
        "action": {"conditions": list(experiment["recovery"]["modes"]), "intervention_cycle": 80, "horizon": 320},
        "result": {"status": recovery_summary["status"], "passed": recovery_summary["passed_gate_count"], "total": recovery_summary["gate_count"]},
        "next_use": (
            "Test the stateful verifier on deployed-agent handoff traces without expanding the synthetic claim boundary."
            if is_v091 else "Adversarially test Pass 1, then add stateful replay binding in v0.9.1 with fresh seeds."
        ),
    }))
    items.append(("evidence_bundle", evidence))
    signer = ReceiptSigner.generate()
    chain = create_chain(items, signer)
    write_chain(receipts / "experiment.jsonl", chain)
    write_anchor(receipts / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts / "experiment.jsonl", receipts / "experiment.anchor.json")
    return {
        "summary": summary, "recovery_summary": recovery_summary,
        "recovery_release_gate": module_gate, "receipt_verification": verification,
        "public_witness": public_witness, "v090_lineage_valid": True,
        "v091_lineage_valid": bool(is_v091),
        "private_key_persisted": False,
    }


def run_experiment(root: Path, config_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    config_path = (config_path or root / "experiment.json").resolve()
    if config_path != root / "experiment.json":
        shutil.copy2(config_path, root / "experiment.json")
    experiment = load_experiment(root / "experiment.json")
    prereg_errors = verify_preregistration(root)
    if prereg_errors:
        raise RuntimeError(f"preregistration failed: {prereg_errors}")
    if experiment.get("schema") == "openline.endurance.experiment.v10":
        return _run_v9_recovery_extension(root, experiment)
    if experiment.get("schema") == "openline.endurance.experiment.v9":
        return _run_v9_recovery_extension(root, experiment)
    if experiment.get("schema") == "openline.endurance.experiment.v8":
        return _run_v8_load_rate_extension(root, experiment)
    if experiment.get("schema") == "openline.endurance.experiment.v7":
        return _run_v7_state_restoration_extension(root, experiment)
    if experiment.get("schema") == "openline.endurance.experiment.v6":
        return _run_v6_generational_extension(root, experiment)
    if experiment.get("schema") == "openline.endurance.experiment.v5":
        return _run_v5_collision_extension(root, experiment)

    results_dir = root / "results"
    receipts_dir = root / "receipts"
    shutil.rmtree(results_dir, ignore_errors=True)
    shutil.rmtree(receipts_dir, ignore_errors=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.mkdir(parents=True, exist_ok=True)

    calibration = calibrate_fresh(experiment)
    if not calibration["passed"]:
        raise RuntimeError(f"fresh calibration failed: {calibration['one_shot_pass_rates']}")
    kappa_star_0 = float(calibration["kappa_star_0"])
    phi_base = float(calibration["phi_base"])

    primary_cycles: list[dict[str, Any]] = []
    primary_runs: list[dict[str, Any]] = []
    for seed in map(int, experiment["seeds"]):
        base_events = generate_perturbations(seed, experiment["amplitude_multiset"])
        for schedule in experiment["schedules"]:
            ordered = schedule_events(base_events, schedule, seed)
            for mode in experiment["modes"]:
                result = run_one(mode, schedule, seed, ordered, experiment, "primary", kappa_star_0, phi_base)
                primary_cycles.extend(result.cycles)
                primary_runs.append(result.summary)

    annotate_failed_before(primary_cycles)
    fitted_damage = select_damage_parameters(primary_cycles, experiment)
    final_damage = compute_damage(primary_cycles, fitted_damage["parameters"])
    attach_damage(primary_cycles, final_damage, float(experiment["phi_min"]))
    for row in primary_cycles:
        row.pop("candidate_D", None)
    model_comparison = compare_models(primary_cycles, experiment)
    damage_fit_diagnostics = damage_diagnostics(primary_cycles, fitted_damage)

    amplitude_cycles: list[dict[str, Any]] = []
    amplitude_runs: list[dict[str, Any]] = []
    for seed in map(int, experiment["seeds"]):
        for amplitude in ("low", "medium", "high"):
            events = matched_amplitude_events(seed, amplitude, int(experiment["primary_cycles"]))
            schedule = f"constant_{amplitude}"
            for mode in experiment["modes"]:
                result = run_one(mode, schedule, seed, events, experiment, "amplitude_sweep", kappa_star_0, phi_base)
                amplitude_cycles.extend(result.cycles)
                amplitude_runs.append(result.summary)

    fractography_runs, fractography_summary = analyze_fractography(primary_cycles, experiment)
    summary = build_summary(
        primary_cycles,
        primary_runs,
        amplitude_runs,
        calibration,
        fitted_damage,
        damage_fit_diagnostics,
        model_comparison,
        fractography_summary,
        experiment,
    )

    tip_cycles, tip_runs, tip_candidates, tip_probes = simulate_tip_capture(experiment)
    tip_summary = analyze_tip_capture(tip_cycles, tip_runs, tip_candidates, tip_probes, experiment)
    collision_events, collision_runs = simulate_collision_spacing(experiment)
    collision_summary = analyze_collision_spacing(collision_runs, experiment)
    summary = combine_summaries(summary, tip_summary, collision_summary)

    amplitude_fields = [field for field in PRIMARY_CYCLE_FIELDS if field not in {"damage_D", "kappa_star_eff", "vkd_f", "failed_before_cycle"}]
    write_csv(results_dir / "cycles.csv", primary_cycles, PRIMARY_CYCLE_FIELDS)
    write_csv(results_dir / "runs.csv", primary_runs, RUN_FIELDS)
    write_csv(results_dir / "amplitude_cycles.csv", amplitude_cycles, amplitude_fields)
    write_csv(results_dir / "amplitude_runs.csv", amplitude_runs, RUN_FIELDS)
    write_csv(results_dir / "mode_summary.csv", aggregate_runs(primary_runs, ("mode",)))
    write_csv(results_dir / "schedule_summary.csv", aggregate_runs(primary_runs, ("schedule",)))
    write_csv(results_dir / "mode_schedule_summary.csv", aggregate_runs(primary_runs, ("mode", "schedule")))
    write_csv(results_dir / "fractography_runs.csv", fractography_runs, FRACTOGRAPHY_FIELDS)
    write_csv(results_dir / "tip_capture_cycles.csv", tip_cycles, TIP_CYCLE_FIELDS)
    write_csv(results_dir / "tip_capture_runs.csv", tip_runs, TIP_RUN_FIELDS)
    write_csv(results_dir / "tip_capture_candidates.csv", tip_candidates, TIP_CANDIDATE_FIELDS)
    write_csv(results_dir / "tip_capture_probes.csv", tip_probes, TIP_PROBE_FIELDS)
    write_csv(results_dir / "collision_spacing_events.csv", collision_events, COLLISION_EVENT_FIELDS)
    write_csv(results_dir / "collision_spacing_runs.csv", collision_runs, COLLISION_RUN_FIELDS)
    _json_dump(results_dir / "calibration.json", calibration)
    _json_dump(results_dir / "damage_fit.json", fitted_damage)
    _json_dump(results_dir / "damage_diagnostics.json", damage_fit_diagnostics)
    _json_dump(results_dir / "model_comparison.json", model_comparison)
    _json_dump(results_dir / "fractography_summary.json", fractography_summary)
    _json_dump(results_dir / "design_witness.json", _design_witness(experiment))
    _json_dump(results_dir / "tip_capture_design_witness.json", tip_design_witness(experiment))
    _json_dump(results_dir / "tip_capture_summary.json", tip_summary)
    (results_dir / "tip_capture_summary.md").write_text(_tip_summary_markdown(tip_summary), encoding="utf-8")
    _json_dump(results_dir / "collision_spacing_design_witness.json", collision_design_witness(experiment))
    _json_dump(results_dir / "collision_spacing_summary.json", collision_summary)
    (results_dir / "collision_spacing_summary.md").write_text(_collision_summary_markdown(collision_summary), encoding="utf-8")
    _json_dump(
        results_dir / "heldout_witness.json",
        {
            "order_effect": summary["order_effect"],
            "receipt_effect": summary["receipt_effect"],
            "amplitude_effect": summary["amplitude_effect"],
            "robustness_witnesses": summary["robustness_witnesses"],
            "tip_capture": tip_summary,
            "collision_spacing": collision_summary,
            "gates": summary["gates"],
        },
    )
    _json_dump(results_dir / "summary.json", summary)
    (results_dir / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")

    cycle_roots = {
        "schema": "openline.endurance.cycle-roots.v1",
        "primary_cycle_merkle_root": merkle_root(primary_cycles),
        "primary_cycle_count": len(primary_cycles),
        "amplitude_cycle_merkle_root": merkle_root(amplitude_cycles),
        "amplitude_cycle_count": len(amplitude_cycles),
        "tip_capture_cycle_merkle_root": merkle_root(tip_cycles),
        "tip_capture_cycle_count": len(tip_cycles),
        "tip_capture_candidate_merkle_root": merkle_root(tip_candidates),
        "tip_capture_candidate_count": len(tip_candidates),
        "tip_capture_probe_merkle_root": merkle_root(tip_probes),
        "tip_capture_probe_count": len(tip_probes),
        "collision_spacing_event_merkle_root": merkle_root(collision_events),
        "collision_spacing_event_count": len(collision_events),
        "collision_spacing_run_merkle_root": merkle_root(collision_runs),
        "collision_spacing_run_count": len(collision_runs),
    }
    _json_dump(results_dir / "cycle_roots.json", cycle_roots)

    manifest = write_manifest(root)
    base_semantic_artifacts = list(BASE_SEMANTIC_ARTIFACTS)
    public_witness = build_public_witness(
        root,
        experiment,
        summary,
        manifest["source_tree_digest"],
        cycle_roots["primary_cycle_merkle_root"],
        cycle_roots["amplitude_cycle_merkle_root"],
        {
            "tip_capture_cycle_merkle_root": cycle_roots["tip_capture_cycle_merkle_root"],
            "tip_capture_candidate_merkle_root": cycle_roots["tip_capture_candidate_merkle_root"],
            "tip_capture_probe_merkle_root": cycle_roots["tip_capture_probe_merkle_root"],
            "collision_spacing_event_merkle_root": cycle_roots["collision_spacing_event_merkle_root"],
            "collision_spacing_run_merkle_root": cycle_roots["collision_spacing_run_merkle_root"],
        },
        base_semantic_artifacts,
    )
    _json_dump(results_dir / "public_witness.json", public_witness)
    manifest = write_manifest(root)
    semantic_artifacts = base_semantic_artifacts + ["results/public_witness.json", "MANIFEST.json"]
    evidence = {
        "claim": "the powered summary is bound to preregistered source and independently recomputable observations",
        "artifact_hashes": artifact_hashes(root, semantic_artifacts),
        "source_tree_digest": manifest["source_tree_digest"],
        "primary_cycle_merkle_root": cycle_roots["primary_cycle_merkle_root"],
        "amplitude_cycle_merkle_root": cycle_roots["amplitude_cycle_merkle_root"],
        "tip_capture_cycle_merkle_root": cycle_roots["tip_capture_cycle_merkle_root"],
        "tip_capture_candidate_merkle_root": cycle_roots["tip_capture_candidate_merkle_root"],
        "tip_capture_probe_merkle_root": cycle_roots["tip_capture_probe_merkle_root"],
        "collision_spacing_event_merkle_root": cycle_roots["collision_spacing_event_merkle_root"],
        "collision_spacing_run_merkle_root": cycle_roots["collision_spacing_run_merkle_root"],
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": "signatures prove chain custody under the pinned local key; semantic recomputation tests metric claims; an external publication of the public witness is still required to resist whole-repository replacement",
    }
    signer = ReceiptSigner.generate()
    chain = create_chain(_receipt_items(primary_runs, amplitude_runs, calibration, summary, tip_summary, collision_summary, evidence), signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "calibration": calibration,
        "summary": summary,
        "tip_capture_summary": tip_summary,
        "collision_spacing_summary": collision_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "private_key_persisted": False,
    }
