#!/usr/bin/env python3
"""Deterministic synthetic mechanism check for the succession calibrator.

This is not a deployed-agent benchmark. It constructs a labeled world in
which isolated spikes should not trigger and two consecutive high checkpoints
should. The check proves that issuance, recomputation, calibration, persistence,
and hostile controls behave as implemented.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cole_portable_core.canonical import sha256_canonical, sign_object
from cole_portable_core.core import reference_profile, validate_profile

from openline_endurance_gate.succession import (
    MEASUREMENT_REQUEST_SCHEMA,
    SuccessionError,
    assess_succession,
    calibrate_succession,
    issue_measurement_bundle,
    make_labeled_observation,
    parse_json_strict,
    verify_calibration_policy,
    verify_measurement_bundle,
)


INPUT_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32))
MEASUREMENT_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
POLICY_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
SIGNAL_SCHEMA = "synthetic.agent-quality-micros.v1"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def graph(*, changed: bool, unsupported: bool = False) -> dict:
    return {
        "claims": [
            {
                "id": "claim_1",
                "content_hash": hash_text("changed" if changed else "stable"),
                "material": True,
            }
        ],
        "evidence": [
            {"id": "evidence_1", "content_hash": hash_text("evidence"), "observed": True}
        ],
        "relations": [] if unsupported else [
            {"src": "evidence_1", "dst": "claim_1", "relation_type": "supports"}
        ],
    }


def trace_id(run: int, sequence: int, side: int) -> str:
    return hashlib.sha256(f"{run}:{sequence}:{side}".encode("ascii")).hexdigest()[:32]


def input_pair(semantic_graph: dict, signals: list[int], identifier: str) -> tuple[dict, dict]:
    body = {
        "kind": "coherence_input_receipt",
        "receipt_version": "0.1",
        "algorithm_id": "synthetic-canon-producer-0.1",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/olp-wire-canon",
        "attestation": "self",
        "capture_status": "provisional",
        "trace_id": identifier,
        "capture_loss": False,
        "dropped_span_count": 0,
        "observed_span_count": 1,
        "trace_root": hash_text("trace:" + identifier),
        "tree_algorithm": "rfc6962-mth-sha256-promote-odd-v1",
        "completion_policy": {
            "type": "root_close_plus_grace",
            "grace_millis": 30_000,
            "semconv_schema_id": "synthetic.otel.v1",
        },
        "seal_reason": "grace_elapsed",
        "semantic_claims": True,
        "typed_event_status": "valid",
        "semantic_graph_hash": sha256_canonical(semantic_graph),
        "signal_schema_id": SIGNAL_SCHEMA,
        "signal_points_micros": signals,
        "state_cap": "white",
    }
    receipt = sign_object(body, INPUT_KEY)
    disclosure = {
        "kind": "coherence_input_disclosure",
        "disclosure_version": "0.1",
        "trace_id": identifier,
        "semantic_graph": semantic_graph,
        "signal_schema_id": SIGNAL_SCHEMA,
        "signals": [
            {"sequence": index, "value_micros": value}
            for index, value in enumerate(signals)
        ],
    }
    return receipt, disclosure


def bundle(run: int, sequence: int, high: bool, *, unsupported: bool = False) -> dict:
    signals = [0, 1_000_000] * 5 if high else [500_000] * 10
    current = input_pair(graph(changed=high, unsupported=unsupported), signals, trace_id(run, sequence, 1))
    previous = input_pair(graph(changed=False), [500_000] * 10, trace_id(run, sequence, 0))
    request = {
        "schema": MEASUREMENT_REQUEST_SCHEMA,
        "run_id": f"run-{run:03d}",
        "sequence": sequence,
        "current": {"receipt": current[0], "disclosure": current[1]},
        "previous": {"receipt": previous[0], "disclosure": previous[1]},
        "checkpoint_anchor": None,
        "profile": reference_profile(SIGNAL_SCHEMA),
    }
    return issue_measurement_bundle(request, MEASUREMENT_KEY)


def observation(run: int, sequence: int, high: bool, beneficial: bool) -> dict:
    return make_labeled_observation(
        bundle(run, sequence, high),
        sample_id=f"sample-{run:03d}-{sequence}",
        label="succession_beneficial" if beneficial else "continue",
        label_source="paired_run",
        continued_quality_micros=200_000 if beneficial else 900_000,
        successor_quality_micros=900_000 if beneficial else 850_000,
        benefit_margin_micros=100_000,
    )


def check(condition: bool, name: str, checks: list[dict]) -> None:
    checks.append({"check": name, "passed": bool(condition)})
    if not condition:
        raise AssertionError(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="optionally write the exact JSON report to this path")
    args = parser.parse_args()
    checks: list[dict] = []
    signer = MEASUREMENT_KEY.public_key().public_bytes_raw().hex()
    policy_signer = POLICY_KEY.public_key().public_bytes_raw().hex()

    clean = bundle(900, 1, True)
    check(verify_measurement_bundle(clean, expected_public_keys={signer})["valid"], "clean_bundle_recomputes", checks)
    tampered = copy.deepcopy(clean)
    tampered["run_id"] = "run-attacker"
    check(not verify_measurement_bundle(tampered)["valid"], "run_binding_tamper_rejected", checks)
    nesting_rejected = False
    try:
        parse_json_strict("[" * 1000 + "1" + "]" * 1000)
    except SuccessionError:
        nesting_rejected = True
    check(nesting_rejected, "hostile_json_nesting_rejected", checks)

    pattern = [(False, False), (True, False), (False, False), (True, False), (True, True)]
    observations = [
        observation(run, sequence, high, beneficial)
        for run in range(100)
        for sequence, (high, beneficial) in enumerate(pattern)
    ]
    policy = calibrate_succession(
        observations,
        POLICY_KEY,
        expected_measurement_public_keys={signer},
    )
    check(policy["mode"] == "calibrated_advisory", "five_hundred_samples_activate_advisory", checks)
    check(policy["corpus"]["admitted_sample_count"] == 500, "all_samples_admitted", checks)
    check(policy["holdout_validation"]["balanced_accuracy_micros"] == 1_000_000, "heldout_mechanism_recovered", checks)
    check(
        all(
            policy["holdout_validation"][observed] >= policy["validation_requirements"][required]
            for observed, required in (
                ("balanced_accuracy_micros", "minimum_balanced_accuracy_micros"),
                ("specificity_micros", "minimum_specificity_micros"),
                ("sensitivity_micros", "minimum_sensitivity_micros"),
            )
        ),
        "declared_holdout_floors_met",
        checks,
    )
    check(policy["persistence"]["persistence_window"] >= 2, "isolated_spike_requires_persistence", checks)
    check(verify_calibration_policy(policy, expected_public_key=policy_signer)["valid"], "signed_policy_verifies", checks)
    validate_profile(policy["cole_profile"])
    check(policy["cole_profile"]["calibration_sample_count"] == 500, "cole_profile_is_exact_and_calibrated", checks)

    run_rows = [row for row in observations if row["bundle"]["run_id"] == "run-000"]
    early = assess_succession(
        run_rows[1]["bundle"],
        policy,
        history=[run_rows[0]["bundle"]],
        expected_policy_public_key=policy_signer,
    )
    check(early["disposition"] != "succession_candidate", "single_spike_does_not_trigger", checks)
    candidate = assess_succession(
        run_rows[4]["bundle"],
        policy,
        history=[row["bundle"] for row in run_rows[:4]],
        expected_policy_public_key=policy_signer,
    )
    check(candidate["disposition"] == "succession_candidate", "repeated_signal_yields_candidate", checks)
    check(candidate["automatic_retirement_authorized"] is False, "automatic_retirement_stays_forbidden", checks)
    check(candidate["handoff"]["required_before_source_retirement"] is True, "handoff_precedes_source_retirement", checks)

    incomplete = bundle(901, 4, True, unsupported=True)
    refused = assess_succession(
        incomplete,
        policy,
        expected_policy_public_key=policy_signer,
    )
    check(refused["disposition"] == "insufficient_evidence", "signed_unsupported_bundle_refused", checks)
    check(refused["support"]["ucr_micros"] == 1_000_000, "ucr_reported_separately", checks)

    cross_run_rejected = False
    try:
        assess_succession(
            observations[5]["bundle"],
            policy,
            history=[observations[0]["bundle"]],
            expected_policy_public_key=policy_signer,
        )
    except SuccessionError:
        cross_run_rejected = True
    check(cross_run_rejected, "cross_run_history_rejected", checks)

    bad_policy = copy.deepcopy(policy)
    bad_policy["automatic_retirement_authorized"] = True
    check(not verify_calibration_policy(bad_policy)["valid"], "policy_tamper_rejected", checks)

    missing_policy_pin_rejected = False
    try:
        assess_succession(observations[0]["bundle"], policy)
    except SuccessionError:
        missing_policy_pin_rejected = True
    check(missing_policy_pin_rejected, "receiver_policy_key_pin_required", checks)

    noisy = copy.deepcopy(observations)
    for item in noisy:
        run_number = int(item["bundle"]["run_id"].split("-")[-1])
        beneficial = (run_number % 2) == 0
        item["label"] = "succession_beneficial" if beneficial else "continue"
        item["outcome"].update(
            {
                "continued_quality_micros": 200_000 if beneficial else 900_000,
                "successor_quality_micros": 900_000 if beneficial else 850_000,
                "benefit_margin_micros": 100_000,
            }
        )
    noisy_policy = calibrate_succession(
        noisy,
        POLICY_KEY,
        expected_measurement_public_keys={signer},
    )
    check(
        noisy_policy["mode"] == "observe_only"
        and any(
            reason.startswith("holdout_") and reason.endswith("_below_declared_floor")
            for reason in noisy_policy["eligibility"]["reason_codes"]
        ),
        "poor_holdout_stays_observation_only",
        checks,
    )

    report = {
        "schema": "openline.succession.synthetic-selftest.v1",
        "claim_boundary": (
            "Synthetic mechanism check only. This does not estimate deployed-agent benefit or establish a universal succession threshold."
        ),
        "cole_algorithm_id": policy["cole_algorithm_id"],
        "submitted_samples": len(observations),
        "train_samples": policy["split"]["train_sample_count"],
        "holdout_samples": policy["split"]["holdout_sample_count"],
        "policy_mode": policy["mode"],
        "holdout_validation": policy["holdout_validation"],
        "persistence": {
            key: policy["persistence"][key]
            for key in ("minimum_metric_breaches", "persistence_window", "persistence_required")
        },
        "checks": checks,
        "passed_check_count": sum(int(item["passed"]) for item in checks),
        "check_count": len(checks),
        "passed": all(item["passed"] for item in checks),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
