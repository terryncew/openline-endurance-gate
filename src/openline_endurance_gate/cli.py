from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experiment import run_experiment
from .verification import verify_evidence
from .semantic_phases import finalize_state_restoration_semantics, verify_state_restoration_shard


def main() -> int:
    parser = argparse.ArgumentParser(prog="openline-endurance")
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

    semantic_shard_parser = sub.add_parser("semantic-shard", help="recompute one bounded v0.7 semantic shard")
    semantic_shard_parser.add_argument("--root", default=".")
    semantic_shard_parser.add_argument("--index", type=int, required=True)

    semantic_finalize_parser = sub.add_parser("semantic-finalize", help="combine completed v0.7 semantic shard witnesses")
    semantic_finalize_parser.add_argument("--root", default=".")

    args = parser.parse_args()
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
    path = root / "results" / "state_restoration_summary.json"
    if not path.exists():
        parser.error(f"missing state-restoration result: {path}")
    print(path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
