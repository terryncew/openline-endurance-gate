from __future__ import annotations

import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canonical import sha256_canonical, sign_object
from cole_portable_core.core import reference_profile, validate_profile

from openline_endurance_gate.succession import (
    MEASUREMENT_REQUEST_SCHEMA,
    SuccessionError,
    assess_succession,
    calibrate_succession,
    canonical_hash,
    issue_measurement_bundle,
    load_json,
    load_jsonl,
    load_private_key,
    make_labeled_observation,
    parse_json_strict,
    verify_calibration_policy,
    verify_measurement_bundle,
)


INPUT_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32))
MEASUREMENT_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
POLICY_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
SCHEMA = "test.agent-quality-micros.v1"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def graph(*, changed: bool = False, unsupported: bool = False) -> dict:
    result = {
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
        "relations": [],
    }
    if not unsupported:
        result["relations"] = [
            {"src": "evidence_1", "dst": "claim_1", "relation_type": "supports"}
        ]
    return result


def make_input(semantic_graph: dict, signals: list[int], trace_id: str) -> tuple[dict, dict]:
    body = {
        "kind": "coherence_input_receipt",
        "receipt_version": "0.1",
        "algorithm_id": "test-canon-producer-0.1",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/olp-wire-canon",
        "attestation": "self",
        "capture_status": "provisional",
        "trace_id": trace_id,
        "capture_loss": False,
        "dropped_span_count": 0,
        "observed_span_count": 1,
        "trace_root": hash_text("trace:" + trace_id),
        "tree_algorithm": "rfc6962-mth-sha256-promote-odd-v1",
        "completion_policy": {
            "type": "root_close_plus_grace",
            "grace_millis": 30_000,
            "semconv_schema_id": "test.otel.v1",
        },
        "seal_reason": "grace_elapsed",
        "semantic_claims": True,
        "typed_event_status": "valid",
        "semantic_graph_hash": sha256_canonical(semantic_graph),
        "signal_schema_id": SCHEMA,
        "signal_points_micros": signals,
        "state_cap": "white",
    }
    receipt = sign_object(body, INPUT_KEY)
    disclosure = {
        "kind": "coherence_input_disclosure",
        "disclosure_version": "0.1",
        "trace_id": trace_id,
        "semantic_graph": semantic_graph,
        "signal_schema_id": SCHEMA,
        "signals": [
            {"sequence": index, "value_micros": value}
            for index, value in enumerate(signals)
        ],
    }
    return receipt, disclosure


def trace_id(run: int, sequence: int, side: int) -> str:
    return hashlib.sha256(f"{run}:{sequence}:{side}".encode()).hexdigest()[:32]


def make_bundle(run: int, sequence: int, high: bool, *, unsupported: bool = False) -> dict:
    current_graph = graph(changed=high, unsupported=unsupported)
    prior_graph = graph()
    signals = ([0, 1_000_000] * 5) if high else [500_000] * 10
    current = make_input(current_graph, signals, trace_id(run, sequence, 1))
    previous = make_input(prior_graph, [500_000] * 10, trace_id(run, sequence, 0))
    request = {
        "schema": MEASUREMENT_REQUEST_SCHEMA,
        "run_id": f"run-{run:03d}",
        "sequence": sequence,
        "current": {"receipt": current[0], "disclosure": current[1]},
        "previous": {"receipt": previous[0], "disclosure": previous[1]},
        "checkpoint_anchor": None,
        "profile": reference_profile(SCHEMA),
    }
    return issue_measurement_bundle(request, MEASUREMENT_KEY)


def paired_observation(run: int, sequence: int, high: bool, beneficial: bool) -> dict:
    bundle = make_bundle(run, sequence, high)
    continued = 200_000 if beneficial else 900_000
    successor = 900_000 if beneficial else 850_000
    return make_labeled_observation(
        bundle,
        sample_id=f"sample-{run:03d}-{sequence}",
        label="succession_beneficial" if beneficial else "continue",
        label_source="paired_run",
        continued_quality_micros=continued,
        successor_quality_micros=successor,
        benefit_margin_micros=100_000,
    )


@pytest.fixture(scope="module")
def calibrated_corpus():
    # Single spikes at sequences 1 and 3 are labeled continue. Only the second
    # consecutive high checkpoint at sequence 4 benefits from succession.
    pattern = [
        (False, False),
        (True, False),
        (False, False),
        (True, False),
        (True, True),
    ]
    observations = [
        paired_observation(run, sequence, high, beneficial)
        for run in range(100)
        for sequence, (high, beneficial) in enumerate(pattern)
    ]
    public_key = MEASUREMENT_KEY.public_key().public_bytes_raw().hex()
    policy = calibrate_succession(
        observations,
        POLICY_KEY,
        expected_measurement_public_keys={public_key},
    )
    return observations, policy


def test_measurement_bundle_is_run_bound_and_recomputed():
    bundle = make_bundle(1, 1, True)
    result = verify_measurement_bundle(bundle)
    assert result["valid"]
    assert result["measurement"]["status"] == "white"
    assert result["measurement"]["digest"]["kappa_micros"] > 0

    changed = copy.deepcopy(bundle)
    changed["run_id"] = "run-attacker"
    assert verify_measurement_bundle(changed)["reason_codes"] == [
        "bundle_signature_or_hash_invalid"
    ]


def test_tampered_derived_metric_is_rejected_before_calibration():
    bundle = make_bundle(2, 1, True)
    changed = copy.deepcopy(bundle)
    changed["measurement_receipt"]["measurement"]["digest"]["kappa_micros"] += 1
    assert not verify_measurement_bundle(changed)["valid"]


def test_paired_label_must_match_declared_outcomes():
    observation = paired_observation(3, 1, False, False)
    observation["label"] = "succession_beneficial"
    policy = calibrate_succession(
        [observation],
        POLICY_KEY,
        expected_measurement_public_keys={MEASUREMENT_KEY.public_key().public_bytes_raw().hex()},
    )
    assert policy["mode"] == "observe_only"
    assert policy["corpus"]["rejected_sample_count"] == 1
    assert "rejected_observations_present" in policy["eligibility"]["reason_codes"]


def test_small_or_unpinned_corpus_cannot_activate():
    observations = [paired_observation(4, 0, False, False), paired_observation(4, 1, True, True)]
    policy = calibrate_succession(observations, POLICY_KEY, expected_measurement_public_keys=None)
    assert policy["mode"] == "observe_only"
    assert policy["automatic_retirement_authorized"] is False
    assert "measurement_signer_keys_not_pinned" in policy["eligibility"]["reason_codes"]
    assessment = assess_succession(
        observations[-1]["bundle"],
        policy,
        expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    assert assessment["disposition"] == "observe_only"
    assert assessment["automatic_retirement_authorized"] is False


def test_500_verified_grouped_samples_activate_exact_cole_profile(calibrated_corpus):
    _, policy = calibrated_corpus
    verification = verify_calibration_policy(
        policy,
        expected_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    assert verification["valid"]
    assert policy["mode"] == "calibrated_advisory"
    assert policy["corpus"]["admitted_sample_count"] == 500
    assert policy["split"]["train_run_count"] + policy["split"]["holdout_run_count"] == 100
    assert policy["split"]["train_run_count"] > 0
    assert policy["split"]["holdout_run_count"] > 0
    assert policy["holdout_validation"]["balanced_accuracy_micros"] == 1_000_000
    assert policy["persistence"]["persistence_window"] >= 2
    validate_profile(policy["cole_profile"])
    assert policy["cole_profile"]["calibration_status"] == "calibrated"


def test_single_spike_prepares_but_repeated_signal_becomes_candidate(calibrated_corpus):
    observations, policy = calibrated_corpus
    run_rows = [row for row in observations if row["bundle"]["run_id"] == "run-000"]

    first_spike = assess_succession(
        run_rows[1]["bundle"],
        policy,
        history=[run_rows[0]["bundle"]],
        expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    assert first_spike["disposition"] in {"prepare_handoff", "continue_observation"}
    assert first_spike["automatic_retirement_authorized"] is False

    candidate = assess_succession(
        run_rows[4]["bundle"],
        policy,
        history=[row["bundle"] for row in run_rows[:4]],
        expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    assert candidate["disposition"] == "succession_candidate"
    assert candidate["handoff"]["required_before_source_retirement"] is True
    assert candidate["receiver_approval_required"] is True
    assert candidate["attestation"] == "local_recomputation_unsigned"


def test_signed_but_unsupported_evidence_cannot_trigger(calibrated_corpus):
    _, policy = calibrated_corpus
    unsupported = make_bundle(201, 4, True, unsupported=True)
    result = assess_succession(
        unsupported,
        policy,
        expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    assert result["disposition"] == "insufficient_evidence"
    assert result["support"]["ucr_micros"] == 1_000_000
    assert result["automatic_retirement_authorized"] is False


def test_cross_run_and_out_of_order_history_fail_closed(calibrated_corpus):
    observations, policy = calibrated_corpus
    with pytest.raises(SuccessionError, match="crosses run_id"):
        assess_succession(
            observations[5]["bundle"],
            policy,
            history=[observations[0]["bundle"]],
            expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
        )
    run_rows = [row for row in observations if row["bundle"]["run_id"] == "run-000"]
    with pytest.raises(SuccessionError, match="strictly increasing"):
        assess_succession(
            run_rows[2]["bundle"],
            policy,
            history=[run_rows[1]["bundle"], run_rows[0]["bundle"]],
            expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
        )


def test_policy_tamper_fails_signature():
    observations = [paired_observation(301, 0, False, False)]
    policy = calibrate_succession(observations, POLICY_KEY, expected_measurement_public_keys=None)
    changed = copy.deepcopy(policy)
    changed["automatic_retirement_authorized"] = True
    assert not verify_calibration_policy(changed)["valid"]


def test_json_nesting_is_bounded_without_recursion_crash():
    text = "[" * 1000 + "1" + "]" * 1000
    with pytest.raises(SuccessionError):
        parse_json_strict(text)


def test_non_utf8_artifacts_fail_closed(tmp_path):
    artifact = tmp_path / "hostile.json"
    artifact.write_bytes(b"\xff")
    with pytest.raises(SuccessionError, match="not valid UTF-8"):
        load_json(artifact)
    with pytest.raises(SuccessionError, match="not valid UTF-8"):
        load_jsonl(artifact)
    with pytest.raises(SuccessionError, match="lowercase ASCII hex"):
        load_private_key(artifact)


def test_assessment_hash_binds_the_separate_metrics(calibrated_corpus):
    observations, policy = calibrated_corpus
    result = assess_succession(
        observations[0]["bundle"],
        policy,
        expected_policy_public_key=POLICY_KEY.public_key().public_bytes_raw().hex(),
    )
    body = dict(result)
    observed_hash = body.pop("assessment_hash")
    assert observed_hash == canonical_hash(body)
    assert set(result["metrics"]) == {
        "kappa_micros", "epsilon_micros", "delta_hol_micros", "phi_star_micros"
    }
    assert "health_score" not in json.dumps(result).lower()


def test_receiver_policy_key_is_required(calibrated_corpus):
    observations, policy = calibrated_corpus
    with pytest.raises(SuccessionError, match="expected_policy_public_key is required"):
        assess_succession(observations[0]["bundle"], policy)


def test_poor_holdout_result_remains_observation_only(calibrated_corpus):
    observations, _ = calibrated_corpus
    noisy = copy.deepcopy(observations)
    for observation in noisy:
        run_number = int(observation["bundle"]["run_id"].split("-")[-1])
        beneficial = (run_number % 2) == 0
        observation["label"] = "succession_beneficial" if beneficial else "continue"
        observation["outcome"].update(
            {
                "continued_quality_micros": 200_000 if beneficial else 900_000,
                "successor_quality_micros": 900_000 if beneficial else 850_000,
                "benefit_margin_micros": 100_000,
            }
        )
    policy = calibrate_succession(
        noisy,
        POLICY_KEY,
        expected_measurement_public_keys={MEASUREMENT_KEY.public_key().public_bytes_raw().hex()},
    )
    assert policy["mode"] == "observe_only"
    assert any(
        reason.startswith("holdout_") and reason.endswith("_below_declared_floor")
        for reason in policy["eligibility"]["reason_codes"]
    )
