#!/usr/bin/env python3
"""Normalize an overlayed CI checkout to the sealed release file set.

This is intended for an ephemeral CI checkout. It never edits Git history or
pushes a commit. The release manifest remains the authority for which files
belong to the maintained release.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

METADATA = {"RELEASE_MANIFEST.json", "RELEASE_VERIFICATION.json"}
IGNORED_PARTS = {".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist"}


def load_allowed(root: Path) -> set[str]:
    manifest_path = root / "RELEASE_MANIFEST.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema") != "agent.successor.release-manifest.v1":
        raise SystemExit("unsupported release manifest")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise SystemExit("release manifest entries are invalid")
    allowed = set(METADATA)
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SystemExit("release manifest contains an invalid entry")
        allowed.add(entry["path"])
    return allowed


def extras(root: Path, allowed: set[str]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in rel.parts):
            continue
        name = rel.as_posix()
        if path.suffix in {".zip", ".sha256"}:
            continue
        if name not in allowed:
            found.append(path)
    return found


def remove_empty_parents(path: Path, root: Path) -> None:
    parent = path.parent
    while parent != root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize an ephemeral checkout to the sealed release manifest.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--apply", action="store_true", help="remove unmanifested files from this checkout")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    allowed = load_allowed(root)
    extra = extras(root, allowed)
    if args.apply:
        for path in extra:
            if path.is_symlink() or path.is_file():
                path.unlink()
                remove_empty_parents(path, root)
        remaining = extras(root, allowed)
        result = {"removed": len(extra), "remaining": [p.relative_to(root).as_posix() for p in remaining]}
        print(json.dumps(result, sort_keys=True))
        return 0 if not remaining else 1
    result = {"extra_count": len(extra), "extras": [p.relative_to(root).as_posix() for p in extra]}
    print(json.dumps(result, sort_keys=True))
    return 0 if not extra else 1


if __name__ == "__main__":
    raise SystemExit(main())
