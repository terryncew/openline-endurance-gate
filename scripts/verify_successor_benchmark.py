#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openline_endurance_gate.successor_verifier import verify_case_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently verify a completed Agent Successor Benchmark case.")
    parser.add_argument("case_dir")
    args = parser.parse_args()
    result = verify_case_directory(Path(args.case_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
