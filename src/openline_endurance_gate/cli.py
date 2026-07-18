from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .experiment import run_experiment
from .verification import verify_evidence
from .semantic_phases import finalize_state_restoration_semantics, verify_state_restoration_shard
from .rate_semantic import finalize_load_rate_semantics, verify_load_rate_shard
from .rate_streaming import generate_load_rate_shard
from .recovery_semantic import finalize_recovery_semantics, verify_recovery_shard
from .recovery_streaming import generate_recovery_shard


def main() -> int:
    parser = argparse.ArgumentParser(prog="openline-endurance")
    from . import __version__
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run the preregistered powered endurance experiment")
    run_parser.add_argument("--root", default=".")
    run_parser.add_argument("--config", default=None)

    verify_parser = sub.add_parser("verify", help="verify signatures, preregistration, artifacts, and semantic recomputation")
    verify_parser.add_argument("--root", default=".")
    verify_parser.add_argument("--source-root", default=None)
    verify_parser.add_argument("--fast", action="store_true", help="check custody and artifact hashes without metric recomputation")
    verify_parser.add_argument(
        "--skip-release-attestation",
        action="store_true",
        help="release-build preflight only: verify scientific custody before rebuilding the detached outer attestation",
    )

    witness_parser = sub.add_parser("witness", help="print the compact public witness for external anchoring")
    witness_parser.add_argument("--root", default=".")

    fracture_parser = sub.add_parser("fracture", help="print the endurance digital-fractography summary")
    fracture_parser.add_argument("--root", default=".")

    tip_parser = sub.add_parser("tip-capture", help="print the execution tip-capture summary")
    tip_parser.add_argument("--root", default=".")

    spacing_parser = sub.add_parser("collision-spacing", help="print the exploratory collision-aware spacing summary")
    spacing_parser.add_argument("--root", default=".")

    generational_parser = sub.add_parser("generational", help="print the verified inheritance capsule summary")
    generational_parser.add_argument("--root", default=".")

    restoration_parser = sub.add_parser("state-restoration", help="print the pruning, retirement, and error-correction summary")
    restoration_parser.add_argument("--root", default=".")

    rate_parser = sub.add_parser("load-rate", help="print the same-disturbance different-speed summary")
    rate_parser.add_argument("--root", default=".")

    recovery_parser = sub.add_parser("recovery", help="print the recovery intervention summary")
    recovery_parser.add_argument("--root", default=".")

    recovery_generate_parser = sub.add_parser("recovery-generate-shard", help="generate one bounded v0.9 recovery evidence shard")
    recovery_generate_parser.add_argument("--root", default=".")
    recovery_generate_parser.add_argument("--index", type=int, required=True)

    recovery_semantic_shard_parser = sub.add_parser("recovery-semantic-shard", help="recompute one bounded v0.9 semantic shard")
    recovery_semantic_shard_parser.add_argument("--root", default=".")
    recovery_semantic_shard_parser.add_argument("--index", type=int, required=True)

    recovery_semantic_finalize_parser = sub.add_parser("recovery-semantic-finalize", help="combine completed v0.9 recovery witnesses")
    recovery_semantic_finalize_parser.add_argument("--root", default=".")

    succession_init_parser = sub.add_parser(
        "succession-init",
        help="create a guided local COLE succession-calibration workspace",
    )
    succession_init_parser.add_argument("--root", default="succession-calibration")
    succession_init_parser.add_argument("--force", action="store_true")

    succession_keygen_parser = sub.add_parser(
        "succession-keygen",
        help="generate a local Ed25519 keypair for measurements or policies",
    )
    succession_keygen_parser.add_argument("--private-out", required=True)
    succession_keygen_parser.add_argument("--public-out", required=True)
    succession_keygen_parser.add_argument("--force", action="store_true")

    succession_measure_parser = sub.add_parser(
        "succession-measure",
        help="issue and recompute-verify a run-bound COLE measurement bundle",
    )
    succession_measure_parser.add_argument("--request", required=True)
    succession_measure_parser.add_argument("--key", required=True, help="32-byte lowercase-hex private-key file")
    succession_measure_parser.add_argument("--out", required=True)
    succession_measure_parser.add_argument(
        "--reference-profile",
        metavar="SIGNAL_SCHEMA_ID",
        help="replace request.profile with COLE's uncalibrated reference profile for this signal schema",
    )

    succession_label_parser = sub.add_parser(
        "succession-label",
        help="create a paired continue-vs-successor calibration label",
    )
    succession_label_parser.add_argument("--bundle", required=True)
    succession_label_parser.add_argument("--sample-id", required=True)
    succession_label_parser.add_argument("--continued-quality-micros", type=int, required=True)
    succession_label_parser.add_argument("--successor-quality-micros", type=int, required=True)
    succession_label_parser.add_argument("--benefit-margin-micros", type=int, required=True)
    succession_label_parser.add_argument("--out", required=True)

    succession_review_label_parser = sub.add_parser(
        "succession-label-review",
        help="create a human-review label bound to a review artifact hash",
    )
    succession_review_label_parser.add_argument("--bundle", required=True)
    succession_review_label_parser.add_argument("--sample-id", required=True)
    succession_review_label_parser.add_argument(
        "--label", choices=("continue", "succession_beneficial"), required=True
    )
    succession_review_label_parser.add_argument("--review-reference-hash", required=True)
    succession_review_label_parser.add_argument("--out", required=True)

    succession_calibrate_parser = sub.add_parser(
        "succession-calibrate",
        help="fit and sign an agent-specific advisory policy from verified labeled checkpoints",
    )
    succession_calibrate_parser.add_argument("--observations", required=True)
    succession_calibrate_parser.add_argument("--policy-key", required=True)
    succession_calibrate_parser.add_argument(
        "--expected-measurement-key",
        action="append",
        default=[],
        help="trusted public-key hex or a file containing it; repeat for multiple measurement signers",
    )
    succession_calibrate_parser.add_argument("--out", required=True)
    succession_calibrate_parser.add_argument(
        "--cole-profile-out",
        help="write the activated exact COLE profile; no file is written while observation-only",
    )
    succession_calibrate_parser.add_argument(
        "--critical-specificity-micros", type=int, default=950_000
    )
    succession_calibrate_parser.add_argument(
        "--minimum-holdout-balanced-accuracy-micros", type=int, default=600_000
    )
    succession_calibrate_parser.add_argument(
        "--minimum-holdout-specificity-micros", type=int, default=950_000
    )
    succession_calibrate_parser.add_argument(
        "--minimum-holdout-sensitivity-micros", type=int, default=500_000
    )
    succession_calibrate_parser.add_argument("--max-persistence-window", type=int, default=5)

    succession_assess_parser = sub.add_parser(
        "succession-assess",
        help="measure a checkpoint against a signed policy without authorizing automatic retirement",
    )
    succession_assess_parser.add_argument("--bundle", required=True)
    succession_assess_parser.add_argument("--policy", required=True)
    succession_assess_parser.add_argument(
        "--history",
        help="optional JSONL of earlier measurement bundles from the same run in sequence order",
    )
    succession_assess_parser.add_argument(
        "--expected-policy-key",
        required=True,
        help="trusted receiver policy public-key hex or a file containing it",
    )
    succession_assess_parser.add_argument("--out")


    rate_generate_parser = sub.add_parser("load-rate-generate-shard", help="generate one bounded v0.8 evidence shard")
    rate_generate_parser.add_argument("--root", default=".")
    rate_generate_parser.add_argument("--index", type=int, required=True)

    rate_semantic_shard_parser = sub.add_parser("load-rate-semantic-shard", help="recompute one bounded v0.8 semantic shard")
    rate_semantic_shard_parser.add_argument("--root", default=".")
    rate_semantic_shard_parser.add_argument("--index", type=int, required=True)

    rate_semantic_finalize_parser = sub.add_parser("load-rate-semantic-finalize", help="combine completed v0.8 semantic shard witnesses")
    rate_semantic_finalize_parser.add_argument("--root", default=".")

    semantic_shard_parser = sub.add_parser("semantic-shard", help="recompute one bounded v0.7 semantic shard")
    semantic_shard_parser.add_argument("--root", default=".")
    semantic_shard_parser.add_argument("--index", type=int, required=True)

    semantic_finalize_parser = sub.add_parser("semantic-finalize", help="combine completed v0.7 semantic shard witnesses")
    semantic_finalize_parser.add_argument("--root", default=".")

    args = parser.parse_args()

    if args.command.startswith("succession-"):
        from .succession import (
            SuccessionError,
            _cole_api,
            append_jsonl,
            assess_succession,
            calibrate_succession,
            generate_keypair,
            initialize_workspace,
            issue_measurement_bundle,
            load_json,
            load_jsonl,
            load_private_key,
            make_labeled_observation,
            write_json,
        )

        def public_key_value(value: str) -> str:
            candidate = Path(value)
            return candidate.read_text(encoding="ascii").strip() if candidate.is_file() else value

        try:
            if args.command == "succession-init":
                result = initialize_workspace(Path(args.root), force=args.force)
            elif args.command == "succession-keygen":
                result = generate_keypair(
                    Path(args.private_out), Path(args.public_out), force=args.force
                )
            elif args.command == "succession-measure":
                request = load_json(Path(args.request))
                if args.reference_profile is not None:
                    request = dict(request)
                    request["profile"] = _cole_api()["reference_profile"](args.reference_profile)
                result = issue_measurement_bundle(request, load_private_key(Path(args.key)))
                write_json(Path(args.out), result)
                result = {
                    "written": args.out,
                    "bundle_hash": result["payload_hash"],
                    "measurement_receipt_hash": result["measurement_receipt"]["payload_hash"],
                    "status": result["measurement_receipt"]["measurement"]["status"],
                    "digest": result["measurement_receipt"]["measurement"]["digest"],
                    "support": result["measurement_receipt"]["measurement"]["support"],
                }
            elif args.command == "succession-label":
                bundle = load_json(Path(args.bundle))
                expected_label = (
                    "succession_beneficial"
                    if args.successor_quality_micros - args.continued_quality_micros
                    >= args.benefit_margin_micros
                    else "continue"
                )
                observation = make_labeled_observation(
                    bundle,
                    sample_id=args.sample_id,
                    label=expected_label,
                    label_source="paired_run",
                    continued_quality_micros=args.continued_quality_micros,
                    successor_quality_micros=args.successor_quality_micros,
                    benefit_margin_micros=args.benefit_margin_micros,
                )
                append_jsonl(Path(args.out), observation)
                result = {"appended": args.out, "sample_id": args.sample_id, "label": expected_label}
            elif args.command == "succession-label-review":
                observation = make_labeled_observation(
                    load_json(Path(args.bundle)),
                    sample_id=args.sample_id,
                    label=args.label,
                    label_source="review",
                    review_reference_hash=args.review_reference_hash,
                )
                append_jsonl(Path(args.out), observation)
                result = {"appended": args.out, "sample_id": args.sample_id, "label": args.label}
            elif args.command == "succession-calibrate":
                pins = {public_key_value(value) for value in args.expected_measurement_key}
                policy = calibrate_succession(
                    load_jsonl(Path(args.observations)),
                    load_private_key(Path(args.policy_key)),
                    expected_measurement_public_keys=pins or None,
                    critical_specificity_micros=args.critical_specificity_micros,
                    minimum_holdout_balanced_accuracy_micros=(
                        args.minimum_holdout_balanced_accuracy_micros
                    ),
                    minimum_holdout_specificity_micros=args.minimum_holdout_specificity_micros,
                    minimum_holdout_sensitivity_micros=args.minimum_holdout_sensitivity_micros,
                    max_persistence_window=args.max_persistence_window,
                )
                write_json(Path(args.out), policy)
                profile_written = None
                if args.cole_profile_out and policy["cole_profile"] is not None:
                    write_json(Path(args.cole_profile_out), policy["cole_profile"])
                    profile_written = args.cole_profile_out
                result = {
                    "written": args.out,
                    "policy_hash": policy["payload_hash"],
                    "mode": policy["mode"],
                    "admitted_sample_count": policy["corpus"]["admitted_sample_count"],
                    "rejected_sample_count": policy["corpus"]["rejected_sample_count"],
                    "reason_codes": policy["eligibility"]["reason_codes"],
                    "cole_profile_written": profile_written,
                    "automatic_retirement_authorized": False,
                }
            else:
                history = load_jsonl(Path(args.history)) if args.history else []
                result = assess_succession(
                    load_json(Path(args.bundle)),
                    load_json(Path(args.policy)),
                    history=history,
                    expected_policy_public_key=public_key_value(args.expected_policy_key),
                )
                if args.out:
                    write_json(Path(args.out), result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        except (OSError, UnicodeError, SuccessionError) as exc:
            print(json.dumps({"error": str(exc), "command": args.command}, indent=2), file=sys.stderr)
            return 2

    root = Path(args.root)
    if args.command == "run":
        result = run_experiment(root, Path(args.config) if args.config else None)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify":
        result = verify_evidence(
            root,
            Path(args.source_root) if args.source_root else None,
            full_semantic=not args.fast,
            verify_release=not args.skip_release_attestation,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    if args.command == "load-rate-generate-shard":
        experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
        result = generate_load_rate_shard(root, experiment, args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "recovery-generate-shard":
        experiment = json.loads((root / "experiment.json").read_text(encoding="utf-8"))
        result = generate_recovery_shard(root, experiment, args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "recovery-semantic-shard":
        result = verify_recovery_shard(root, args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if args.command == "recovery-semantic-finalize":
        result = finalize_recovery_semantics(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    if args.command == "load-rate-semantic-shard":
        result = verify_load_rate_shard(root, args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if args.command == "load-rate-semantic-finalize":
        result = finalize_load_rate_semantics(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    if args.command == "semantic-shard":
        result = verify_state_restoration_shard(root, args.index)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if args.command == "semantic-finalize":
        result = finalize_state_restoration_semantics(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    if args.command == "witness":
        path = root / "results" / "public_witness.json"
        if not path.exists():
            parser.error(f"missing witness: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "fracture":
        path = root / "results" / "fractography_summary.json"
        if not path.exists():
            parser.error(f"missing fractography result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "tip-capture":
        path = root / "results" / "tip_capture_summary.json"
        if not path.exists():
            parser.error(f"missing tip-capture result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "collision-spacing":
        path = root / "results" / "collision_spacing_summary.json"
        if not path.exists():
            parser.error(f"missing collision-spacing result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "generational":
        path = root / "results" / "generational_summary.json"
        if not path.exists():
            parser.error(f"missing generational result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "load-rate":
        path = root / "results" / "load_rate_summary.json"
        if not path.exists():
            parser.error(f"missing load-rate result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "recovery":
        path = root / "results" / "recovery_summary.json"
        if not path.exists():
            parser.error(f"missing recovery result: {path}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    path = root / "results" / "state_restoration_summary.json"
    if not path.exists():
        parser.error(f"missing state-restoration result: {path}")
    print(path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
