from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .successor_benchmark import (
    BenchmarkError,
    finalize_case,
    generate_keypair,
    prepare_case,
    register_case,
    sign_checker_report,
)
from .successor_verifier import verify_case_directory


def _metric(value: str) -> tuple[str, int]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("metric must use NAME=INTEGER")
    name, raw = value.split("=", 1)
    if not name:
        raise argparse.ArgumentTypeError("metric name cannot be empty")
    try:
        number = int(raw, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("metric value must be an integer") from exc
    return name, number


def _metrics(values: list[tuple[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, value in values:
        if name in result:
            raise BenchmarkError(f"duplicate metric: {name}")
        result[name] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-successor-benchmark",
        description="Compare a current agent with a candidate under fixed tasks, constraints, budgets, and evidence rules.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate an Ed25519 checker key pair")
    keygen.add_argument("--private-out", required=True)
    keygen.add_argument("--public-out", required=True)
    keygen.add_argument("--force", action="store_true")

    register = sub.add_parser("register", help="fix the comparison inputs before either arm is submitted")
    register.add_argument("--trial-id", required=True)
    register.add_argument("--case-id", required=True)
    register.add_argument("--case-index", type=int, required=True)
    register.add_argument("--planned-case-count", type=int, required=True)
    register.add_argument("--previous-registration")
    register.add_argument("--task", required=True)
    register.add_argument("--constraints", required=True)
    register.add_argument("--budget", required=True)
    register.add_argument("--policy", required=True)
    register.add_argument("--repository-state-hash", required=True)
    register.add_argument("--incumbent-version-hash", required=True)
    register.add_argument("--candidate-version-hash", required=True)
    register.add_argument("--checker-id", required=True)
    register.add_argument("--checker-public-key", required=True, help="32-byte lowercase-hex Ed25519 public key")
    register.add_argument("--blinding-nonce", required=True, help="receiver-held value used to derive opaque lane identifiers")
    register.add_argument("--out", required=True)

    prepare = sub.add_parser("prepare", help="package both registered arms separately for the checker")
    prepare.add_argument("--registration", required=True)
    prepare.add_argument("--task", required=True)
    prepare.add_argument("--constraints", required=True)
    prepare.add_argument("--budget", required=True)
    prepare.add_argument("--policy", required=True)
    prepare.add_argument("--incumbent-submission", required=True)
    prepare.add_argument("--candidate-submission", required=True)
    prepare.add_argument("--incumbent-evidence", required=True)
    prepare.add_argument("--candidate-evidence", required=True)
    prepare.add_argument("--blinding-nonce", required=True)
    prepare.add_argument("--out", required=True)

    sign = sub.add_parser("checker-sign", help="sign one lane's measured outcomes and cited evidence")
    sign.add_argument("--package", required=True)
    sign.add_argument("--status", choices=("PASS", "FAIL", "UNDECIDABLE"), required=True)
    sign.add_argument("--metric", action="append", type=_metric, required=True, metavar="NAME=INTEGER")
    sign.add_argument("--citation", action="append", required=True)
    sign.add_argument("--critical-failure", action="append", default=[])
    sign.add_argument("--reason-code", action="append", required=True)
    sign.add_argument("--checker-private-key", required=True)
    sign.add_argument("--out", required=True)

    finalize = sub.add_parser("finalize", help="verify both checker reports and compute the comparison result")
    finalize.add_argument("--prepared", required=True)
    finalize.add_argument("--checker-report", action="append", required=True)
    finalize.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="independently recompute a completed case directory")
    verify.add_argument("--case-dir", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "keygen":
            generate_keypair(Path(args.private_out), Path(args.public_out), force=args.force)
            result = {"private_key": args.private_out, "public_key": args.public_out}
        elif args.command == "register":
            result = register_case(
                trial_id=args.trial_id,
                case_id=args.case_id,
                case_index=args.case_index,
                planned_case_count=args.planned_case_count,
                previous_registration_path=Path(args.previous_registration) if args.previous_registration else None,
                task_path=Path(args.task),
                constraints_path=Path(args.constraints),
                budget_path=Path(args.budget),
                policy_path=Path(args.policy),
                repository_state_hash=args.repository_state_hash,
                incumbent_version_hash=args.incumbent_version_hash,
                candidate_version_hash=args.candidate_version_hash,
                checker_id=args.checker_id,
                checker_public_key=args.checker_public_key,
                blinding_nonce=args.blinding_nonce,
                output_path=Path(args.out),
            )
        elif args.command == "prepare":
            result = prepare_case(
                registration_path=Path(args.registration),
                task_path=Path(args.task),
                constraints_path=Path(args.constraints),
                budget_path=Path(args.budget),
                policy_path=Path(args.policy),
                incumbent_submission_path=Path(args.incumbent_submission),
                candidate_submission_path=Path(args.candidate_submission),
                incumbent_evidence_dir=Path(args.incumbent_evidence),
                candidate_evidence_dir=Path(args.candidate_evidence),
                blinding_nonce=args.blinding_nonce,
                output_dir=Path(args.out),
            )
        elif args.command == "checker-sign":
            result = sign_checker_report(
                package_dir=Path(args.package),
                status=args.status,
                metrics=_metrics(args.metric),
                citations=args.citation,
                critical_failures=args.critical_failure,
                reason_codes=args.reason_code,
                checker_private_key_path=Path(args.checker_private_key),
                output_path=Path(args.out),
            )
        elif args.command == "finalize":
            result = finalize_case(
                prepared_dir=Path(args.prepared),
                checker_report_paths=[Path(item) for item in args.checker_report],
                output_dir=Path(args.out),
            )
        elif args.command == "verify":
            result = verify_case_directory(Path(args.case_dir))
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["valid"] else 1
        else:
            parser.error("unsupported command")
            return 2
    except (BenchmarkError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
