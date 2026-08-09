"""Receiver-side incumbent-versus-candidate benchmark.

The maintained workflow is deliberately narrow:

* register the comparison before either arm is submitted;
* package each arm separately for a pinned checker;
* accept only checker-signed, evidence-citing integer measurements;
* recommend the candidate only if it preserves every required floor and
  produces at least one pre-declared material improvement.

The module never executes a promotion.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


REGISTRATION_SCHEMA = "agent.successor.registration.v1"
TASK_SCHEMA = "agent.successor.task.v1"
CONSTRAINTS_SCHEMA = "agent.successor.constraints.v1"
BUDGET_SCHEMA = "agent.successor.budget.v1"
POLICY_SCHEMA = "agent.successor.policy.v1"
SUBMISSION_SCHEMA = "agent.successor.submission.v1"
EVIDENCE_MANIFEST_SCHEMA = "agent.successor.evidence-manifest.v1"
CHECKER_PACKAGE_SCHEMA = "agent.successor.checker-package.v1"
PRECHECK_SCHEMA = "agent.successor.precheck.v1"
PREPARATION_SCHEMA = "agent.successor.preparation.v1"
CHECKER_REPORT_SCHEMA = "agent.successor.checker-report.v1"
DECISION_SCHEMA = "agent.successor.decision.v1"
CASE_MANIFEST_SCHEMA = "agent.successor.case-manifest.v1"
VERIFICATION_SCHEMA = "agent.successor.verification.v1"

DECISIONS = ("PROMOTE_CANDIDATE", "KEEP_INCUMBENT", "INCONCLUSIVE")
REPORT_STATUSES = ("PASS", "FAIL", "UNDECIDABLE")
DIRECTIONS = ("maximize", "minimize")
ROLES = ("incumbent", "candidate")
EVIDENCE_KINDS = ("artifact", "diff", "file", "log", "receipt", "test")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SIG_RE = re.compile(r"^[0-9a-f]{128}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SAFE_METRIC_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 64
MAX_VALUES = 100_000
MAX_EVIDENCE_FILES = 64
MAX_EVIDENCE_FILE_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_METRIC_ABS = 10**15

CLAIM_BOUNDARY = (
    "The benchmark verifies registered inputs, evidence hashes, checker signatures, and deterministic "
    "comparison rules. It does not prove checker independence or truth, does not prove an external "
    "timestamp, and does not authorize execution of a replacement."
)


class BenchmarkError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise BenchmarkError(f"non-finite JSON number is not allowed: {value}")


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _shape(value: Any) -> None:
    count = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > MAX_VALUES:
            raise BenchmarkError("JSON value count exceeds limit")
        if depth > MAX_DEPTH:
            raise BenchmarkError("JSON nesting exceeds limit")
        if isinstance(current, float):
            raise BenchmarkError("floating-point values are not allowed in protocol objects")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif not isinstance(current, (str, int, bool, type(None))):
            raise BenchmarkError(f"unsupported JSON value type: {type(current).__name__}")


def load_json(path: Path) -> Any:
    if path.is_symlink():
        raise BenchmarkError(f"symlink input is not allowed: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise BenchmarkError(f"JSON file exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_hook,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise BenchmarkError(f"JSON must be UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid JSON: {path}: {exc}") from exc
    _shape(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    _shape(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    _shape(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _exact(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        actual = sorted(value) if isinstance(value, Mapping) else type(value).__name__
        raise BenchmarkError(f"{name} field mismatch: expected={sorted(fields)} actual={actual}")
    return value


def _safe_id(value: Any, name: str, *, metric: bool = False) -> str:
    pattern = SAFE_METRIC_RE if metric else SAFE_ID_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise BenchmarkError(f"invalid {name}")
    return value


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise BenchmarkError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BenchmarkError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BenchmarkError(f"{name} must be a nonnegative integer")
    return value


def _strings(value: Any, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise BenchmarkError(f"{name} must be a list")
    if any(not isinstance(item, str) or not item or len(item) > 256 for item in value):
        raise BenchmarkError(f"{name} contains an invalid string")
    if value != sorted(set(value)):
        raise BenchmarkError(f"{name} must be sorted and unique")
    return list(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink():
        raise BenchmarkError("checker private key cannot be a symlink")
    text = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise BenchmarkError("private key must contain exactly 32 lowercase-hex bytes")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(text))


def public_key_hex(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def generate_keypair(private_out: Path, public_out: Path, *, force: bool = False) -> None:
    if not force and (private_out.exists() or public_out.exists()):
        raise BenchmarkError("refusing to overwrite an existing key file")
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    private_out.parent.mkdir(parents=True, exist_ok=True)
    private_out.write_text(private + "\n", encoding="ascii")
    try:
        private_out.chmod(0o600)
    except OSError:
        pass
    public_out.parent.mkdir(parents=True, exist_ok=True)
    public_out.write_text(public_key_hex(key) + "\n", encoding="ascii")


def _validate_task(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "task_id", "statement"}, "task")
    if value["schema"] != TASK_SCHEMA:
        raise BenchmarkError("unsupported task schema")
    _safe_id(value["task_id"], "task_id")
    if not isinstance(value["statement"], str) or not value["statement"].strip() or len(value["statement"]) > 20_000:
        raise BenchmarkError("task.statement must be nonempty and at most 20000 characters")
    return value


def _validate_constraints(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "items"}, "constraints")
    if value["schema"] != CONSTRAINTS_SCHEMA:
        raise BenchmarkError("unsupported constraints schema")
    _strings(value["items"], "constraints.items")
    return value


def _validate_budget(value: Any) -> Mapping[str, Any]:
    value = _exact(
        value,
        {"schema", "max_tool_calls", "max_wall_time_seconds", "max_cost_micros", "max_output_bytes"},
        "budget",
    )
    if value["schema"] != BUDGET_SCHEMA:
        raise BenchmarkError("unsupported budget schema")
    for field in ("max_tool_calls", "max_wall_time_seconds", "max_output_bytes"):
        _positive_int(value[field], f"budget.{field}")
    _nonnegative_int(value["max_cost_micros"], "budget.max_cost_micros")
    return value


def _validate_policy(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "policy_id", "metrics"}, "policy")
    if value["schema"] != POLICY_SCHEMA:
        raise BenchmarkError("unsupported policy schema")
    _safe_id(value["policy_id"], "policy_id")
    metrics = value["metrics"]
    if not isinstance(metrics, list) or not metrics or len(metrics) > 32:
        raise BenchmarkError("policy.metrics must contain 1 to 32 metrics")
    names: list[str] = []
    for index, metric in enumerate(metrics):
        metric = _exact(
            metric,
            {"name", "description", "direction", "required", "max_regression", "minimum_improvement"},
            f"policy.metrics[{index}]",
        )
        name = _safe_id(metric["name"], f"metric[{index}].name", metric=True)
        names.append(name)
        if not isinstance(metric["description"], str) or not metric["description"].strip() or len(metric["description"]) > 500:
            raise BenchmarkError(f"metric {name} needs a short description")
        if metric["direction"] not in DIRECTIONS:
            raise BenchmarkError(f"invalid direction for metric {name}")
        if not isinstance(metric["required"], bool):
            raise BenchmarkError(f"metric {name}.required must be boolean")
        _nonnegative_int(metric["max_regression"], f"metric {name}.max_regression")
        minimum = _positive_int(metric["minimum_improvement"], f"metric {name}.minimum_improvement")
        if minimum > MAX_METRIC_ABS:
            raise BenchmarkError(f"metric {name}.minimum_improvement is too large")
    if names != sorted(set(names)):
        raise BenchmarkError("policy metrics must be sorted by unique name")
    return value


def _validate_submission(value: Any, *, role: str, case_id: str, version_hash: str) -> Mapping[str, Any]:
    value = _exact(
        value,
        {"schema", "case_id", "role", "submission_id", "version_hash", "artifact_hash", "evidence"},
        f"{role} submission",
    )
    if value["schema"] != SUBMISSION_SCHEMA:
        raise BenchmarkError("unsupported submission schema")
    if value["case_id"] != case_id or value["role"] != role:
        raise BenchmarkError(f"{role} submission case/role mismatch")
    _safe_id(value["submission_id"], f"{role}.submission_id")
    if value["version_hash"] != version_hash:
        raise BenchmarkError(f"{role} version hash does not match registration")
    _hash(value["version_hash"], f"{role}.version_hash")
    _hash(value["artifact_hash"], f"{role}.artifact_hash")
    evidence = value["evidence"]
    if not isinstance(evidence, list) or not evidence or len(evidence) > MAX_EVIDENCE_FILES:
        raise BenchmarkError(f"{role}.evidence must contain 1 to {MAX_EVIDENCE_FILES} items")
    ids: list[str] = []
    paths: list[str] = []
    for index, item in enumerate(evidence):
        item = _exact(item, {"evidence_id", "kind", "path"}, f"{role}.evidence[{index}]")
        ids.append(_safe_id(item["evidence_id"], f"{role}.evidence_id"))
        if item["kind"] not in EVIDENCE_KINDS:
            raise BenchmarkError(f"unsupported evidence kind: {item['kind']}")
        rel = _safe_relative_path(item["path"], f"{role}.evidence.path")
        paths.append(rel.as_posix())
    if ids != sorted(set(ids)):
        raise BenchmarkError(f"{role} evidence IDs must be sorted and unique")
    if len(paths) != len(set(paths)):
        raise BenchmarkError(f"{role} evidence paths must be unique")
    return value


def _safe_relative_path(value: Any, name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or len(value) > 256:
        raise BenchmarkError(f"invalid {name}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BenchmarkError(f"unsafe {name}: {value}")
    return path


def _scan_regular_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise BenchmarkError(f"evidence root must be a real directory: {root}")
    paths: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BenchmarkError(f"symlink evidence is not allowed: {path}")
        if path.is_file():
            paths.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise BenchmarkError(f"unsupported evidence filesystem object: {path}")
    return paths


def _build_evidence_manifest(
    evidence_root: Path, submission: Mapping[str, Any], *, case_id: str, lane_id: str
) -> dict[str, Any]:
    expected_paths = {str(item["path"]) for item in submission["evidence"]}
    actual_paths = _scan_regular_files(evidence_root)
    if actual_paths != expected_paths:
        raise BenchmarkError(
            f"evidence directory does not match submission index: missing={sorted(expected_paths-actual_paths)} "
            f"extra={sorted(actual_paths-expected_paths)}"
        )
    items: list[dict[str, Any]] = []
    total = 0
    for item in submission["evidence"]:
        rel = _safe_relative_path(item["path"], "evidence path")
        path = evidence_root.joinpath(*rel.parts)
        size = path.stat().st_size
        if size > MAX_EVIDENCE_FILE_BYTES:
            raise BenchmarkError(f"evidence file too large: {rel}")
        total += size
        if total > MAX_EVIDENCE_TOTAL_BYTES:
            raise BenchmarkError("evidence set exceeds total size limit")
        items.append(
            {
                "evidence_id": item["evidence_id"],
                "kind": item["kind"],
                "path": rel.as_posix(),
                "sha256": file_hash(path),
                "bytes": size,
            }
        )
    return {
        "schema": EVIDENCE_MANIFEST_SCHEMA,
        "case_id": case_id,
        "lane_id": lane_id,
        "items": items,
    }


def _copy_evidence(source: Path, manifest: Mapping[str, Any], destination: Path) -> None:
    for item in manifest["items"]:
        rel = _safe_relative_path(item["path"], "evidence path")
        src = source.joinpath(*rel.parts)
        dst = destination / "evidence" / Path(*rel.parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst, follow_symlinks=False)
        if file_hash(dst) != item["sha256"]:
            raise BenchmarkError(f"copied evidence hash mismatch: {rel}")


def _lane_id(blinding_nonce: str, case_id: str, role: str) -> str:
    return hashlib.sha256(f"{blinding_nonce}\x00{case_id}\x00{role}".encode("utf-8")).hexdigest()[:24]


def _measurement_contract(policy: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": item["name"], "description": item["description"], "value_type": "integer"}
        for item in policy["metrics"]
    ]


def _validate_registration(value: Any) -> Mapping[str, Any]:
    value = _exact(
        value,
        {
            "schema", "trial_id", "case_id", "case_index", "planned_case_count",
            "previous_registration_hash", "task_hash", "constraints_hash", "budget_hash",
            "policy_hash", "repository_state_hash", "incumbent_version_hash", "candidate_version_hash",
            "checker_id", "checker_public_key", "blinding_nonce_hash", "registered_at", "claim_boundary",
        },
        "registration",
    )
    if value["schema"] != REGISTRATION_SCHEMA:
        raise BenchmarkError("unsupported registration schema")
    _safe_id(value["trial_id"], "trial_id")
    _safe_id(value["case_id"], "case_id")
    index = _positive_int(value["case_index"], "case_index")
    total = _positive_int(value["planned_case_count"], "planned_case_count")
    if index > total:
        raise BenchmarkError("case_index cannot exceed planned_case_count")
    previous = value["previous_registration_hash"]
    if index == 1:
        if previous is not None:
            raise BenchmarkError("first case must not have previous_registration_hash")
    else:
        _hash(previous, "previous_registration_hash")
    for field in (
        "task_hash", "constraints_hash", "budget_hash", "policy_hash", "repository_state_hash",
        "incumbent_version_hash", "candidate_version_hash", "blinding_nonce_hash",
    ):
        _hash(value[field], field)
    _safe_id(value["checker_id"], "checker_id")
    if not isinstance(value["checker_public_key"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["checker_public_key"]):
        raise BenchmarkError("checker_public_key must be 32 lowercase-hex bytes")
    if value["claim_boundary"] != CLAIM_BOUNDARY:
        raise BenchmarkError("registration claim boundary changed")
    if not isinstance(value["registered_at"], str) or not value["registered_at"].endswith("Z"):
        raise BenchmarkError("registered_at must be a UTC timestamp ending in Z")
    return value


def register_case(
    *,
    trial_id: str,
    case_id: str,
    case_index: int,
    planned_case_count: int,
    previous_registration_path: Path | None,
    task_path: Path,
    constraints_path: Path,
    budget_path: Path,
    policy_path: Path,
    repository_state_hash: str,
    incumbent_version_hash: str,
    candidate_version_hash: str,
    checker_id: str,
    checker_public_key: str,
    blinding_nonce: str,
    output_path: Path,
) -> dict[str, Any]:
    _safe_id(trial_id, "trial_id")
    _safe_id(case_id, "case_id")
    _positive_int(case_index, "case_index")
    _positive_int(planned_case_count, "planned_case_count")
    if case_index > planned_case_count:
        raise BenchmarkError("case_index cannot exceed planned_case_count")
    task = _validate_task(load_json(task_path))
    constraints = _validate_constraints(load_json(constraints_path))
    budget = _validate_budget(load_json(budget_path))
    policy = _validate_policy(load_json(policy_path))
    for value, name in (
        (repository_state_hash, "repository_state_hash"),
        (incumbent_version_hash, "incumbent_version_hash"),
        (candidate_version_hash, "candidate_version_hash"),
    ):
        _hash(value, name)
    _safe_id(checker_id, "checker_id")
    if not isinstance(checker_public_key, str) or not re.fullmatch(r"[0-9a-f]{64}", checker_public_key):
        raise BenchmarkError("checker_public_key must be 32 lowercase-hex bytes")
    if not isinstance(blinding_nonce, str) or len(blinding_nonce) < 16:
        raise BenchmarkError("blinding_nonce must contain at least 16 characters")

    previous_hash: str | None = None
    if case_index == 1:
        if previous_registration_path is not None:
            raise BenchmarkError("case 1 cannot supply a previous registration")
    else:
        if previous_registration_path is None:
            raise BenchmarkError("case_index > 1 requires previous_registration_path")
        previous = _validate_registration(load_json(previous_registration_path))
        if previous["trial_id"] != trial_id:
            raise BenchmarkError("previous registration belongs to another trial")
        if previous["planned_case_count"] != planned_case_count:
            raise BenchmarkError("planned case count changed within trial")
        if previous["case_index"] != case_index - 1:
            raise BenchmarkError("previous registration case index is not contiguous")
        previous_hash = canonical_hash(previous)

    registration = {
        "schema": REGISTRATION_SCHEMA,
        "trial_id": trial_id,
        "case_id": case_id,
        "case_index": case_index,
        "planned_case_count": planned_case_count,
        "previous_registration_hash": previous_hash,
        "task_hash": canonical_hash(task),
        "constraints_hash": canonical_hash(constraints),
        "budget_hash": canonical_hash(budget),
        "policy_hash": canonical_hash(policy),
        "repository_state_hash": repository_state_hash,
        "incumbent_version_hash": incumbent_version_hash,
        "candidate_version_hash": candidate_version_hash,
        "checker_id": checker_id,
        "checker_public_key": checker_public_key,
        "blinding_nonce_hash": hashlib.sha256(blinding_nonce.encode("utf-8")).hexdigest(),
        "registered_at": _utc_now(),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _validate_registration(registration)
    write_json(output_path, registration)
    return registration


def _validate_protocol_inputs(
    registration: Mapping[str, Any], task: Mapping[str, Any], constraints: Mapping[str, Any],
    budget: Mapping[str, Any], policy: Mapping[str, Any], blinding_nonce: str
) -> None:
    expected = {
        "task_hash": canonical_hash(task),
        "constraints_hash": canonical_hash(constraints),
        "budget_hash": canonical_hash(budget),
        "policy_hash": canonical_hash(policy),
        "blinding_nonce_hash": hashlib.sha256(blinding_nonce.encode("utf-8")).hexdigest(),
    }
    for field, actual in expected.items():
        if registration[field] != actual:
            raise BenchmarkError(f"{field} does not match pre-arm registration")


def prepare_case(
    *,
    registration_path: Path,
    task_path: Path,
    constraints_path: Path,
    budget_path: Path,
    policy_path: Path,
    incumbent_submission_path: Path,
    candidate_submission_path: Path,
    incumbent_evidence_dir: Path,
    candidate_evidence_dir: Path,
    blinding_nonce: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise BenchmarkError(f"output directory already exists: {output_dir}")
    registration = _validate_registration(load_json(registration_path))
    task = _validate_task(load_json(task_path))
    constraints = _validate_constraints(load_json(constraints_path))
    budget = _validate_budget(load_json(budget_path))
    policy = _validate_policy(load_json(policy_path))
    _validate_protocol_inputs(registration, task, constraints, budget, policy, blinding_nonce)

    submissions = {
        "incumbent": _validate_submission(
            load_json(incumbent_submission_path), role="incumbent", case_id=registration["case_id"],
            version_hash=registration["incumbent_version_hash"],
        ),
        "candidate": _validate_submission(
            load_json(candidate_submission_path), role="candidate", case_id=registration["case_id"],
            version_hash=registration["candidate_version_hash"],
        ),
    }
    evidence_dirs = {"incumbent": incumbent_evidence_dir, "candidate": candidate_evidence_dir}
    lane_mapping = {role: _lane_id(blinding_nonce, registration["case_id"], role) for role in ROLES}
    if lane_mapping["incumbent"] == lane_mapping["candidate"]:
        raise BenchmarkError("lane identifiers collided")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        for name, value in (
            ("registration.json", registration), ("task.json", task), ("constraints.json", constraints),
            ("budget.json", budget), ("policy.json", policy),
        ):
            write_json(staging / name, value)

        package_hashes: dict[str, str] = {}
        for role in ROLES:
            submission = submissions[role]
            write_json(staging / "sealed_submissions" / f"{role}.json", submission)
            lane_id = lane_mapping[role]
            manifest = _build_evidence_manifest(
                evidence_dirs[role], submission, case_id=registration["case_id"], lane_id=lane_id
            )
            package = {
                "schema": CHECKER_PACKAGE_SCHEMA,
                "case_id": registration["case_id"],
                "lane_id": lane_id,
                "registration_hash": canonical_hash(registration),
                "task": task,
                "constraints": constraints,
                "budget": budget,
                "measurement_contract": _measurement_contract(policy),
                "checker_id": registration["checker_id"],
                "checker_public_key": registration["checker_public_key"],
                "submission_hash": canonical_hash(submission),
                "artifact_hash": submission["artifact_hash"],
                "evidence_manifest": manifest,
            }
            package_dir = staging / "checker_packages" / lane_id
            _copy_evidence(evidence_dirs[role], manifest, package_dir)
            write_json(package_dir / "package.json", package)
            package_hashes[lane_id] = canonical_hash(package)

        precheck = {
            "schema": PRECHECK_SCHEMA,
            "registration_hash": canonical_hash(registration),
            "package_hashes": sorted(package_hashes.values()),
            "checker_reports_present": False,
        }
        write_json(staging / "precheck.json", precheck)
        preparation = {
            "schema": PREPARATION_SCHEMA,
            "case_id": registration["case_id"],
            "registration_hash": canonical_hash(registration),
            "precheck_hash": canonical_hash(precheck),
            "lane_mapping": lane_mapping,
            "package_hashes": package_hashes,
        }
        write_json(staging / "preparation.json", preparation)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return preparation


def _validate_evidence_closure(package_dir: Path) -> Mapping[str, Any]:
    package = load_json(package_dir / "package.json")
    package = _exact(
        package,
        {
            "schema", "case_id", "lane_id", "registration_hash", "task", "constraints", "budget",
            "measurement_contract", "checker_id", "checker_public_key", "submission_hash", "artifact_hash",
            "evidence_manifest",
        },
        "checker package",
    )
    if package["schema"] != CHECKER_PACKAGE_SCHEMA:
        raise BenchmarkError("unsupported checker package schema")
    _safe_id(package["case_id"], "package.case_id")
    _safe_id(package["lane_id"], "package.lane_id")
    _hash(package["registration_hash"], "package.registration_hash")
    _validate_task(package["task"])
    _validate_constraints(package["constraints"])
    _validate_budget(package["budget"])
    _safe_id(package["checker_id"], "package.checker_id")
    if not re.fullmatch(r"[0-9a-f]{64}", str(package["checker_public_key"])):
        raise BenchmarkError("invalid package checker public key")
    _hash(package["submission_hash"], "package.submission_hash")
    _hash(package["artifact_hash"], "package.artifact_hash")
    contract = package["measurement_contract"]
    if not isinstance(contract, list) or not contract:
        raise BenchmarkError("measurement_contract must be nonempty")
    names: list[str] = []
    for index, item in enumerate(contract):
        item = _exact(item, {"name", "description", "value_type"}, f"measurement_contract[{index}]")
        names.append(_safe_id(item["name"], "metric name", metric=True))
        if item["value_type"] != "integer" or not isinstance(item["description"], str) or not item["description"].strip():
            raise BenchmarkError("invalid measurement contract")
    if names != sorted(set(names)):
        raise BenchmarkError("measurement contract metric names must be sorted and unique")

    manifest = package["evidence_manifest"]
    manifest = _exact(manifest, {"schema", "case_id", "lane_id", "items"}, "evidence manifest")
    if manifest["schema"] != EVIDENCE_MANIFEST_SCHEMA or manifest["case_id"] != package["case_id"] or manifest["lane_id"] != package["lane_id"]:
        raise BenchmarkError("evidence manifest binding mismatch")
    items = manifest["items"]
    if not isinstance(items, list) or not items or len(items) > MAX_EVIDENCE_FILES:
        raise BenchmarkError("invalid evidence manifest size")
    expected_paths: set[str] = set()
    ids: list[str] = []
    total = 0
    for index, item in enumerate(items):
        item = _exact(item, {"evidence_id", "kind", "path", "sha256", "bytes"}, f"manifest.items[{index}]")
        ids.append(_safe_id(item["evidence_id"], "evidence_id"))
        if item["kind"] not in EVIDENCE_KINDS:
            raise BenchmarkError("invalid evidence kind")
        rel = _safe_relative_path(item["path"], "evidence path")
        expected_paths.add(rel.as_posix())
        _hash(item["sha256"], "evidence sha256")
        size = _nonnegative_int(item["bytes"], "evidence bytes")
        if size > MAX_EVIDENCE_FILE_BYTES:
            raise BenchmarkError("evidence file exceeds limit")
        total += size
        if total > MAX_EVIDENCE_TOTAL_BYTES:
            raise BenchmarkError("evidence total exceeds limit")
        path = package_dir / "evidence" / Path(*rel.parts)
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise BenchmarkError(f"missing or unsafe evidence file: {rel}")
        if path.stat().st_size != size or file_hash(path) != item["sha256"]:
            raise BenchmarkError(f"evidence file mismatch: {rel}")
    if ids != sorted(set(ids)):
        raise BenchmarkError("evidence IDs must be sorted and unique")
    if _scan_regular_files(package_dir / "evidence") != expected_paths:
        raise BenchmarkError("checker package contains unlisted evidence")
    return package


def sign_checker_report(
    *,
    package_dir: Path,
    status: str,
    metrics: Mapping[str, int],
    citations: Sequence[str],
    critical_failures: Sequence[str],
    reason_codes: Sequence[str],
    checker_private_key_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    package = _validate_evidence_closure(package_dir)
    if status not in REPORT_STATUSES:
        raise BenchmarkError("invalid checker report status")
    key = load_private_key(checker_private_key_path)
    if public_key_hex(key) != package["checker_public_key"]:
        raise BenchmarkError("checker private key does not match registered public key")
    metric_names = [item["name"] for item in package["measurement_contract"]]
    if set(metrics) != set(metric_names):
        raise BenchmarkError(f"checker metrics must exactly match measurement contract: {metric_names}")
    normalized_metrics: dict[str, int] = {}
    for name in metric_names:
        value = metrics[name]
        if not isinstance(value, int) or isinstance(value, bool) or abs(value) > MAX_METRIC_ABS:
            raise BenchmarkError(f"invalid integer value for metric {name}")
        normalized_metrics[name] = value
    evidence_ids = {item["evidence_id"] for item in package["evidence_manifest"]["items"]}
    citations_list = sorted(set(citations))
    if not citations_list or any(item not in evidence_ids for item in citations_list):
        raise BenchmarkError("checker citations must be nonempty and refer only to packaged evidence")
    failures = sorted(set(critical_failures))
    reasons = sorted(set(reason_codes))
    if any(not isinstance(item, str) or not item or len(item) > 256 for item in failures + reasons):
        raise BenchmarkError("critical failures and reason codes must be short nonempty strings")
    if not reasons:
        raise BenchmarkError("at least one reason code is required")
    if status == "PASS" and failures:
        raise BenchmarkError("PASS report cannot contain critical failures")
    body = {
        "schema": CHECKER_REPORT_SCHEMA,
        "checker_id": package["checker_id"],
        "checker_public_key": package["checker_public_key"],
        "case_id": package["case_id"],
        "lane_id": package["lane_id"],
        "checker_package_hash": canonical_hash(package),
        "evidence_manifest_hash": canonical_hash(package["evidence_manifest"]),
        "status": status,
        "metrics": normalized_metrics,
        "citations": citations_list,
        "critical_failures": failures,
        "reason_codes": reasons,
    }
    payload_hash = canonical_hash(body)
    signature = key.sign(canonical_bytes(body)).hex()
    report = {**body, "payload_hash": payload_hash, "signature": signature}
    write_json(output_path, report)
    return report


def _verify_report(report: Mapping[str, Any], package: Mapping[str, Any], expected_key: str) -> Mapping[str, Any]:
    fields = {
        "schema", "checker_id", "checker_public_key", "case_id", "lane_id", "checker_package_hash",
        "evidence_manifest_hash", "status", "metrics", "citations", "critical_failures", "reason_codes",
        "payload_hash", "signature",
    }
    report = _exact(report, fields, "checker report")
    if report["schema"] != CHECKER_REPORT_SCHEMA:
        raise BenchmarkError("unsupported checker report schema")
    if report["checker_id"] != package["checker_id"] or report["checker_public_key"] != expected_key:
        raise BenchmarkError("checker identity/key mismatch")
    if report["case_id"] != package["case_id"] or report["lane_id"] != package["lane_id"]:
        raise BenchmarkError("checker report package binding mismatch")
    if report["checker_package_hash"] != canonical_hash(package):
        raise BenchmarkError("checker report package hash mismatch")
    if report["evidence_manifest_hash"] != canonical_hash(package["evidence_manifest"]):
        raise BenchmarkError("checker report evidence manifest hash mismatch")
    if report["status"] not in REPORT_STATUSES:
        raise BenchmarkError("invalid checker status")
    metric_names = [item["name"] for item in package["measurement_contract"]]
    metrics = report["metrics"]
    if not isinstance(metrics, Mapping) or set(metrics) != set(metric_names):
        raise BenchmarkError("checker report metrics mismatch")
    for name in metric_names:
        value = metrics[name]
        if not isinstance(value, int) or isinstance(value, bool) or abs(value) > MAX_METRIC_ABS:
            raise BenchmarkError(f"invalid checker metric value: {name}")
    citations = _strings(report["citations"], "report.citations", allow_empty=False)
    evidence_ids = {item["evidence_id"] for item in package["evidence_manifest"]["items"]}
    if any(item not in evidence_ids for item in citations):
        raise BenchmarkError("checker report cites evidence outside package")
    failures = _strings(report["critical_failures"], "report.critical_failures")
    _strings(report["reason_codes"], "report.reason_codes", allow_empty=False)
    if report["status"] == "PASS" and failures:
        raise BenchmarkError("PASS report contains a critical failure")
    body = {key: report[key] for key in fields - {"payload_hash", "signature"}}
    if report["payload_hash"] != canonical_hash(body):
        raise BenchmarkError("checker report payload hash mismatch")
    if not isinstance(report["signature"], str) or not SIG_RE.fullmatch(report["signature"]):
        raise BenchmarkError("invalid checker report signature encoding")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(expected_key)).verify(
            bytes.fromhex(report["signature"]), canonical_bytes(body)
        )
    except (ValueError, InvalidSignature) as exc:
        raise BenchmarkError("checker report signature verification failed") from exc
    return report


def compare_reports(
    *, policy: Mapping[str, Any], incumbent_report: Mapping[str, Any], candidate_report: Mapping[str, Any]
) -> dict[str, Any]:
    policy = _validate_policy(policy)
    if incumbent_report["status"] == "UNDECIDABLE" or candidate_report["status"] == "UNDECIDABLE":
        return {
            "decision": "INCONCLUSIVE",
            "reason_codes": ["checker_report_undecidable"],
            "comparisons": [],
        }
    if candidate_report["status"] != "PASS":
        return {
            "decision": "KEEP_INCUMBENT",
            "reason_codes": ["candidate_did_not_pass_checker"],
            "comparisons": [],
        }
    if candidate_report["critical_failures"]:
        return {
            "decision": "KEEP_INCUMBENT",
            "reason_codes": ["candidate_has_critical_failure"],
            "comparisons": [],
        }

    comparisons: list[dict[str, Any]] = []
    regressions: list[str] = []
    improvements: list[str] = []
    for metric in policy["metrics"]:
        name = metric["name"]
        incumbent = incumbent_report["metrics"][name]
        candidate = candidate_report["metrics"][name]
        improvement = candidate - incumbent if metric["direction"] == "maximize" else incumbent - candidate
        regression = max(-improvement, 0)
        material = improvement >= metric["minimum_improvement"]
        allowed = (not metric["required"]) or regression <= metric["max_regression"]
        if not allowed:
            regressions.append(name)
        if material:
            improvements.append(name)
        comparisons.append(
            {
                "name": name,
                "incumbent": incumbent,
                "candidate": candidate,
                "direction": metric["direction"],
                "improvement": improvement,
                "required": metric["required"],
                "max_regression": metric["max_regression"],
                "minimum_improvement": metric["minimum_improvement"],
                "within_required_floor": allowed,
                "material_improvement": material,
            }
        )
    if regressions:
        return {
            "decision": "KEEP_INCUMBENT",
            "reason_codes": ["required_metric_regression:" + ",".join(regressions)],
            "comparisons": comparisons,
        }
    if not improvements:
        return {
            "decision": "KEEP_INCUMBENT",
            "reason_codes": ["no_declared_material_improvement"],
            "comparisons": comparisons,
        }
    return {
        "decision": "PROMOTE_CANDIDATE",
        "reason_codes": ["candidate_preserved_required_floor", "material_improvement:" + ",".join(improvements)],
        "comparisons": comparisons,
    }


def _assert_no_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BenchmarkError(f"symlink is not allowed in case directory: {path}")


def _case_manifest(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).as_posix() not in {"case_manifest.json", "verification.json"}:
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": file_hash(path),
                    "bytes": path.stat().st_size,
                }
            )
    return {"schema": CASE_MANIFEST_SCHEMA, "entries": entries}


def finalize_case(*, prepared_dir: Path, checker_report_paths: Sequence[Path], output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise BenchmarkError(f"output directory already exists: {output_dir}")
    _assert_no_symlinks(prepared_dir)
    registration = _validate_registration(load_json(prepared_dir / "registration.json"))
    policy = _validate_policy(load_json(prepared_dir / "policy.json"))
    preparation = load_json(prepared_dir / "preparation.json")
    preparation = _exact(
        preparation,
        {"schema", "case_id", "registration_hash", "precheck_hash", "lane_mapping", "package_hashes"},
        "preparation",
    )
    if preparation["schema"] != PREPARATION_SCHEMA or preparation["case_id"] != registration["case_id"]:
        raise BenchmarkError("preparation binding mismatch")
    if preparation["registration_hash"] != canonical_hash(registration):
        raise BenchmarkError("preparation registration hash mismatch")
    precheck = load_json(prepared_dir / "precheck.json")
    if precheck != {
        "schema": PRECHECK_SCHEMA,
        "registration_hash": canonical_hash(registration),
        "package_hashes": sorted(preparation["package_hashes"].values()),
        "checker_reports_present": False,
    }:
        raise BenchmarkError("precheck commitment mismatch")
    if preparation["precheck_hash"] != canonical_hash(precheck):
        raise BenchmarkError("precheck hash mismatch")

    packages: dict[str, Mapping[str, Any]] = {}
    for role in ROLES:
        lane_id = preparation["lane_mapping"].get(role)
        _safe_id(lane_id, f"lane_mapping.{role}")
        package_dir = prepared_dir / "checker_packages" / lane_id
        package = _validate_evidence_closure(package_dir)
        if canonical_hash(package) != preparation["package_hashes"].get(lane_id):
            raise BenchmarkError("prepared package hash mismatch")
        packages[lane_id] = package

    if len(checker_report_paths) != 2:
        raise BenchmarkError("exactly two checker reports are required")
    reports_by_lane: dict[str, Mapping[str, Any]] = {}
    for path in checker_report_paths:
        report = load_json(path)
        if not isinstance(report, Mapping):
            raise BenchmarkError("checker report must be an object")
        lane_id = report.get("lane_id")
        if lane_id not in packages or lane_id in reports_by_lane:
            raise BenchmarkError("checker reports must cover each prepared lane exactly once")
        reports_by_lane[lane_id] = _verify_report(report, packages[lane_id], registration["checker_public_key"])

    incumbent_lane = preparation["lane_mapping"]["incumbent"]
    candidate_lane = preparation["lane_mapping"]["candidate"]
    comparison = compare_reports(
        policy=policy,
        incumbent_report=reports_by_lane[incumbent_lane],
        candidate_report=reports_by_lane[candidate_lane],
    )
    decision = {
        "schema": DECISION_SCHEMA,
        "case_id": registration["case_id"],
        "registration_hash": canonical_hash(registration),
        "precheck_hash": canonical_hash(precheck),
        "policy_hash": canonical_hash(policy),
        "incumbent_version_hash": registration["incumbent_version_hash"],
        "candidate_version_hash": registration["candidate_version_hash"],
        "decision": comparison["decision"],
        "reason_codes": comparison["reason_codes"],
        "comparisons": comparison["comparisons"],
        "checker_report_hashes": {
            "incumbent": canonical_hash(reports_by_lane[incumbent_lane]),
            "candidate": canonical_hash(reports_by_lane[candidate_lane]),
        },
        "execution_authorized": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        shutil.rmtree(staging)
        shutil.copytree(prepared_dir, staging)
        write_json(staging / "checker_reports" / "incumbent.json", reports_by_lane[incumbent_lane])
        write_json(staging / "checker_reports" / "candidate.json", reports_by_lane[candidate_lane])
        write_json(staging / "decision.json", decision)
        manifest = _case_manifest(staging)
        write_json(staging / "case_manifest.json", manifest)
        # Independent implementation: it deliberately does not import this module.
        from .successor_verifier import verify_case_directory
        verification = verify_case_directory(staging, require_stored_verification=False)
        if verification["valid"] is not True or verification["recomputed_decision"] != decision["decision"]:
            raise BenchmarkError(f"independent verification failed: {verification['errors']}")
        write_json(staging / "verification.json", verification)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return decision
