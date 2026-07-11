from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .amplitude import matched_amplitude_events, matched_packet_witness
from .damage import (
    annotate_failed_before,
    attach_damage,
    compare_models,
    compute_damage,
    damage_diagnostics,
    select_damage_parameters,
)
from .fractography import FRACTOGRAPHY_FIELDS, analyze_fractography
from .integrity import build_public_witness, merkle_root, verify_preregistration
from .receipts import ReceiptSigner, artifact_hashes, create_chain, verify_chain, write_anchor, write_chain
from .sim import calibrate_fresh, generate_perturbations, run_one, schedule_events
from .summarize import aggregate_runs, build_summary
from .tip_capture import (
    TIP_CANDIDATE_FIELDS, TIP_CYCLE_FIELDS, TIP_PROBE_FIELDS, TIP_RUN_FIELDS,
    analyze_tip_capture, simulate_tip_capture, tip_design_witness,
)
from .util import canonical_json, sha256_bytes, sha256_file, write_csv


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
]

RUN_FIELDS = [
    "run_family", "mode", "schedule", "seed", "cycles", "n_f", "failed", "first_failure_cycle",
    "mean_checkpoint_accuracy", "final_config_accuracy", "final_requirement_accuracy", "unsafe_attempts",
    "retry_count", "repair_successes", "total_tokens", "subcritical_first_failure",
]


def load_experiment(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") not in {"openline.endurance.experiment.v1", "openline.endurance.experiment.v2", "openline.endurance.experiment.v3"}:
        raise ValueError("unsupported experiment schema")
    declared = set(map(int, data["training_seeds"] + data["validation_seeds"] + data["heldout_seeds"]))
    if declared != set(map(int, data["seeds"])):
        raise ValueError("train/validation/heldout seeds must partition seeds")
    if not set(map(int, data["training_seeds"])).isdisjoint(map(int, data["validation_seeds"])):
        raise ValueError("training and validation seeds overlap")
    if len(data["modes"]) != 4 or len(data["schedules"]) != 4:
        raise ValueError("default discriminating test requires four modes and four schedules")
    if data.get("schema") in {"openline.endurance.experiment.v2", "openline.endurance.experiment.v3"}:
        required_pairs = int(data["analysis_plan"]["minimum_primary_order_pairs"])
        available_pairs = len(data["heldout_seeds"]) * len(data["modes"])
        if available_pairs < required_pairs:
            raise ValueError(f"powered design has {available_pairs} order pairs but requires {required_pairs}")
        if data.get("randomness_coupling") != "EVENT_BOUND_COMMON_RANDOM_NUMBERS":
            raise ValueError("v2 requires event-bound common random numbers")
        if data.get("amplitude_sweep_design") != "COMMON_PACKET_AMPLITUDE_TRANSFORM":
            raise ValueError("v2 requires matched amplitude packets")
    if data.get("schema") == "openline.endurance.experiment.v3":
        tip = data.get("tip_capture")
        if not isinstance(tip, dict) or tip.get("schema") != "openline.tip-capture.experiment.v1":
            raise ValueError("v3 requires a tip-capture experiment")
        tip_declared = set(map(int, tip["training_seeds"] + tip["validation_seeds"] + tip["heldout_seeds"]))
        if tip_declared != set(map(int, tip["seeds"])):
            raise ValueError("tip-capture train/validation/heldout seeds must partition seeds")
        if len(tip["heldout_seeds"]) < int(tip["analysis_plan"]["minimum_repair_pairs"]):
            raise ValueError("tip-capture heldout seed count is below the preregistered pair floor")
        if "uniform_null" not in tip["attachment_conditions"] or "diffusive_tip_capture" not in tip["attachment_conditions"]:
            raise ValueError("tip-capture requires both a genuine null and diffusive treatment")
        if {"random_repair", "tip_targeted"} - set(tip["repair_policies"]):
            raise ValueError("tip-capture requires matched random and tip-targeted repair policies")
        if tip.get("randomness_coupling") != "PACKET_BOUND_COMMON_RANDOM_NUMBERS":
            raise ValueError("tip-capture requires packet-bound common random numbers")
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
    capture = summary["capture_by_condition"]["diffusive_tip_capture"]
    geometry = summary["geometry_lift"]["diffusive_tip_capture"]
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
        f"- Diffusive frontier capture lift over candidate-count null: {capture['frontier_capture_lift']:.6f}",
        f"- Geometry held-out log-loss gain: {geometry['heldout_logloss_gain']:.8f}",
        f"- Geometry held-out AUC gain: {geometry['heldout_auc_gain']:.8f}",
        f"- Tip-minus-random repair yield median: {repair['median_difference']:.6f} violations prevented per successful repair",
        f"- Repair-yield majority direction: `{repair['majority_direction']}`",
        f"- Positive-direction consistency among non-ties: {repair['positive_direction_consistency']:.6f}",
        f"- Pair counts — tip favored: {repair['positive_count']}; random favored: {repair['negative_count']}; tied: {repair['zero_count']}",
        f"- Receipt ancestry root-recovery median gain: {recovery['median_difference']:.6f} recovery-rate points",
        f"- Burial depth / successful recovery-cost Spearman: {summary['burial_cost_spearman']}",
        "- Even-spread disclosure: selecting the least-captured node in the smallest branch creates an unintended leaf/tip bias; this condition is descriptive and no gate was retuned.",
        "",
        "## Gate results",
        "",
    ]
    for name, gate in summary["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if gate['passed'] else 'FAIL'}**")
    lines.extend(["", "## Boundary", "", summary["claim_boundary"], ""])
    return "\n".join(lines) + "\n"


def combine_summaries(summary: dict[str, Any], tip_summary: dict[str, Any]) -> dict[str, Any]:
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
    combined["claim_label"] = "POWERED_SYNTHETIC_ENDURANCE_AND_TIP_CAPTURE"
    if combined["passed_gate_count"] == combined["gate_count"]:
        combined["theory_status"] = "SURVIVES_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    elif combined["passed_gate_count"] == 0:
        combined["theory_status"] = "FAILS_ALL_PRE_REGISTERED_SYNTHETIC_GATES"
    else:
        combined["theory_status"] = "MIXED_SYNTHETIC_RESULT"
    combined["claim_boundary"] = (
        "The endurance world and the execution-graph world are seeded mechanism tests. "
        "The diffusive attachment treatment deliberately contains stochastic tip capture, while uniform attachment is the null. "
        "Passing shows the instruments recover declared mechanisms and reject nulls where preregistered; it does not show deployed agents obey material fatigue or DLA."
    )
    return combined


def _manifest_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in {".git", ".pytest_cache", "__pycache__"} or part.endswith(".egg-info") for part in path.parts):
            continue
        if rel in {
            "MANIFEST.json",
            "RUN_REPORT.json",
            "TAMPER_REPORT.json",
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
            ("evidence_bundle", evidence),
        ]
    )
    return items


def run_experiment(root: Path, config_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    config_path = (config_path or root / "experiment.json").resolve()
    if config_path != root / "experiment.json":
        shutil.copy2(config_path, root / "experiment.json")
    experiment = load_experiment(root / "experiment.json")
    prereg_errors = verify_preregistration(root)
    if prereg_errors:
        raise RuntimeError(f"preregistration failed: {prereg_errors}")

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
    summary = combine_summaries(summary, tip_summary)

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
    _json_dump(results_dir / "calibration.json", calibration)
    _json_dump(results_dir / "damage_fit.json", fitted_damage)
    _json_dump(results_dir / "damage_diagnostics.json", damage_fit_diagnostics)
    _json_dump(results_dir / "model_comparison.json", model_comparison)
    _json_dump(results_dir / "fractography_summary.json", fractography_summary)
    _json_dump(results_dir / "design_witness.json", _design_witness(experiment))
    _json_dump(results_dir / "tip_capture_design_witness.json", tip_design_witness(experiment))
    _json_dump(results_dir / "tip_capture_summary.json", tip_summary)
    (results_dir / "tip_capture_summary.md").write_text(_tip_summary_markdown(tip_summary), encoding="utf-8")
    _json_dump(
        results_dir / "heldout_witness.json",
        {
            "order_effect": summary["order_effect"],
            "receipt_effect": summary["receipt_effect"],
            "amplitude_effect": summary["amplitude_effect"],
            "robustness_witnesses": summary["robustness_witnesses"],
            "tip_capture": tip_summary,
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
        "public_witness_digest": public_witness["witness_digest"],
        "semantic_verifier": "openline-endurance verify --root . --source-root .",
        "claim_boundary": "signatures prove chain custody under the pinned local key; semantic recomputation tests metric claims; an external publication of the public witness is still required to resist whole-repository replacement",
    }
    signer = ReceiptSigner.generate()
    chain = create_chain(_receipt_items(primary_runs, amplitude_runs, calibration, summary, tip_summary, evidence), signer)
    write_chain(receipts_dir / "experiment.jsonl", chain)
    write_anchor(receipts_dir / "experiment.anchor.json", chain, signer)
    verification = verify_chain(receipts_dir / "experiment.jsonl", receipts_dir / "experiment.anchor.json")
    return {
        "calibration": calibration,
        "summary": summary,
        "tip_capture_summary": tip_summary,
        "receipt_verification": verification,
        "public_witness": public_witness,
        "private_key_persisted": False,
    }
