#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

EXCLUDED_NAMES = {"RELEASE_MANIFEST.json", "RELEASE_VERIFICATION.json"}
EXCLUDED_PARTS = {".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def actual_files(root: Path) -> set[str]:
    result = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if rel.name in EXCLUDED_NAMES or rel.suffix in {".zip", ".sha256"}:
            continue
        result.add(rel.as_posix())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors = []
    for path in root.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlink:{path.relative_to(root).as_posix()}")
    try:
        manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        verification = json.loads((root / "RELEASE_VERIFICATION.json").read_text(encoding="utf-8"))
        comparison = json.loads((root / "RELEASE_COMPARISON.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [f"metadata:{exc}"]}, indent=2))
        return 1
    if manifest.get("schema") != "agent.successor.release-manifest.v1":
        errors.append("manifest_schema")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        errors.append("manifest_entries")
        entries = []
    listed = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            errors.append("manifest_entry_shape")
            continue
        rel = PurePosixPath(entry["path"])
        if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
            errors.append(f"unsafe_path:{entry['path']}")
            continue
        name = rel.as_posix()
        if name in listed:
            errors.append(f"duplicate_path:{name}")
            continue
        listed.add(name)
        path = root / Path(*rel.parts)
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing:{name}")
        elif path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            errors.append(f"mismatch:{name}")
    actual = actual_files(root)
    if actual != listed:
        errors.append(f"closure:missing={sorted(listed-actual)}:extra={sorted(actual-listed)}")
    if verification.get("passed") is not True:
        errors.append("release_verification_not_passed")
    if verification.get("release_manifest", {}).get("sha256") != manifest_hash(manifest):
        errors.append("release_manifest_hash_mismatch")
    if comparison.get("promotion") != "ADVANCE":
        errors.append("release_comparison_not_advanced")
    result = {"schema": "agent.successor.release-recheck.v1", "valid": not errors, "errors": errors, "entry_count": len(entries), "manifest_sha256": manifest_hash(manifest)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
