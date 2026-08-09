"""Independent verifier for an Agent Successor Benchmark case directory.

This file intentionally does not import ``successor_benchmark``. It re-parses
and recomputes the stored case from JSON and evidence bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


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
ROLES = ("incumbent", "candidate")
REPORT_STATUSES = ("PASS", "FAIL", "UNDECIDABLE")
DIRECTIONS = ("maximize", "minimize")
EVIDENCE_KINDS = ("artifact", "diff", "file", "log", "receipt", "test")
CLAIM_BOUNDARY = (
    "The benchmark verifies registered inputs, evidence hashes, checker signatures, and deterministic "
    "comparison rules. It does not prove checker independence or truth, does not prove an external "
    "timestamp, and does not authorize execution of a replacement."
)


class VerifyError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise VerifyError(f"non_finite_json:{value}")


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerifyError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _shape(value: Any) -> None:
    count = 0
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > MAX_VALUES:
            raise VerifyError("json_value_limit")
        if depth > MAX_DEPTH:
            raise VerifyError("json_depth_limit")
        if isinstance(current, float):
            raise VerifyError("float_in_protocol_object")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif not isinstance(current, (str, int, bool, type(None))):
            raise VerifyError("unsupported_json_value")


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise VerifyError(f"missing_or_unsafe_file:{path.name}")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise VerifyError(f"json_too_large:{path.name}")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs_hook, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid_json:{path.name}") from exc
    _shape(value)
    return value


def _canonical(value: Any) -> bytes:
    _shape(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _hash_obj(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _exact(value: Any, fields: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise VerifyError(f"field_mismatch:{code}")
    return value


def _safe_id(value: Any, code: str, *, metric: bool = False) -> str:
    pattern = SAFE_METRIC_RE if metric else SAFE_ID_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise VerifyError(f"invalid_id:{code}")
    return value


def _hash(value: Any, code: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise VerifyError(f"invalid_hash:{code}")
    return value


def _safe_rel(value: Any, code: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or len(value) > 256:
        raise VerifyError(f"invalid_path:{code}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise VerifyError(f"unsafe_path:{code}")
    return path


def _int(value: Any, code: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise VerifyError(f"invalid_integer:{code}")
    if positive and value <= 0:
        raise VerifyError(f"nonpositive_integer:{code}")
    return value


def _strings(value: Any, code: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise VerifyError(f"invalid_string_list:{code}")
    if any(not isinstance(item, str) or not item or len(item) > 256 for item in value):
        raise VerifyError(f"invalid_string:{code}")
    if value != sorted(set(value)):
        raise VerifyError(f"unsorted_or_duplicate:{code}")
    return list(value)


def _validate_task(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "task_id", "statement"}, "task")
    if value["schema"] != TASK_SCHEMA:
        raise VerifyError("task_schema")
    _safe_id(value["task_id"], "task_id")
    if not isinstance(value["statement"], str) or not value["statement"].strip() or len(value["statement"]) > 20_000:
        raise VerifyError("task_statement")
    return value


def _validate_constraints(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "items"}, "constraints")
    if value["schema"] != CONSTRAINTS_SCHEMA:
        raise VerifyError("constraints_schema")
    _strings(value["items"], "constraints_items")
    return value


def _validate_budget(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "max_tool_calls", "max_wall_time_seconds", "max_cost_micros", "max_output_bytes"}, "budget")
    if value["schema"] != BUDGET_SCHEMA:
        raise VerifyError("budget_schema")
    for field in ("max_tool_calls", "max_wall_time_seconds", "max_output_bytes"):
        _int(value[field], field, positive=True)
    if _int(value["max_cost_micros"], "max_cost_micros") < 0:
        raise VerifyError("negative_cost_budget")
    return value


def _validate_policy(value: Any) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "policy_id", "metrics"}, "policy")
    if value["schema"] != POLICY_SCHEMA:
        raise VerifyError("policy_schema")
    _safe_id(value["policy_id"], "policy_id")
    metrics = value["metrics"]
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 32:
        raise VerifyError("metric_count")
    names: list[str] = []
    for metric in metrics:
        metric = _exact(metric, {"name", "description", "direction", "required", "max_regression", "minimum_improvement"}, "metric")
        name = _safe_id(metric["name"], "metric_name", metric=True)
        names.append(name)
        if not isinstance(metric["description"], str) or not metric["description"].strip() or len(metric["description"]) > 500:
            raise VerifyError("metric_description")
        if metric["direction"] not in DIRECTIONS or not isinstance(metric["required"], bool):
            raise VerifyError("metric_policy")
        if _int(metric["max_regression"], "max_regression") < 0:
            raise VerifyError("negative_max_regression")
        minimum = _int(metric["minimum_improvement"], "minimum_improvement", positive=True)
        if minimum > MAX_METRIC_ABS:
            raise VerifyError("minimum_improvement_too_large")
    if names != sorted(set(names)):
        raise VerifyError("metric_names_not_sorted_unique")
    return value


def _validate_registration(value: Any) -> Mapping[str, Any]:
    fields = {
        "schema", "trial_id", "case_id", "case_index", "planned_case_count", "previous_registration_hash",
        "task_hash", "constraints_hash", "budget_hash", "policy_hash", "repository_state_hash",
        "incumbent_version_hash", "candidate_version_hash", "checker_id", "checker_public_key",
        "blinding_nonce_hash", "registered_at", "claim_boundary",
    }
    value = _exact(value, fields, "registration")
    if value["schema"] != REGISTRATION_SCHEMA:
        raise VerifyError("registration_schema")
    _safe_id(value["trial_id"], "trial_id")
    _safe_id(value["case_id"], "case_id")
    index = _int(value["case_index"], "case_index", positive=True)
    count = _int(value["planned_case_count"], "planned_case_count", positive=True)
    if index > count:
        raise VerifyError("case_index_after_end")
    previous = value["previous_registration_hash"]
    if index == 1:
        if previous is not None:
            raise VerifyError("first_case_has_previous")
    else:
        _hash(previous, "previous_registration_hash")
    for field in ("task_hash", "constraints_hash", "budget_hash", "policy_hash", "repository_state_hash", "incumbent_version_hash", "candidate_version_hash", "blinding_nonce_hash"):
        _hash(value[field], field)
    _safe_id(value["checker_id"], "checker_id")
    if not isinstance(value["checker_public_key"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["checker_public_key"]):
        raise VerifyError("checker_public_key")
    if not isinstance(value["registered_at"], str) or not value["registered_at"].endswith("Z"):
        raise VerifyError("registered_at")
    if value["claim_boundary"] != CLAIM_BOUNDARY:
        raise VerifyError("claim_boundary")
    return value


def _validate_submission(value: Any, role: str, registration: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _exact(value, {"schema", "case_id", "role", "submission_id", "version_hash", "artifact_hash", "evidence"}, f"submission_{role}")
    if value["schema"] != SUBMISSION_SCHEMA or value["case_id"] != registration["case_id"] or value["role"] != role:
        raise VerifyError(f"submission_binding:{role}")
    _safe_id(value["submission_id"], "submission_id")
    expected_version = registration[f"{role}_version_hash"] if role == "incumbent" else registration["candidate_version_hash"]
    if value["version_hash"] != expected_version:
        raise VerifyError(f"version_binding:{role}")
    _hash(value["version_hash"], "version_hash")
    _hash(value["artifact_hash"], "artifact_hash")
    evidence = value["evidence"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= MAX_EVIDENCE_FILES:
        raise VerifyError("submission_evidence_count")
    ids: list[str] = []
    paths: list[str] = []
    for item in evidence:
        item = _exact(item, {"evidence_id", "kind", "path"}, "submission_evidence")
        ids.append(_safe_id(item["evidence_id"], "evidence_id"))
        if item["kind"] not in EVIDENCE_KINDS:
            raise VerifyError("evidence_kind")
        paths.append(_safe_rel(item["path"], "evidence_path").as_posix())
    if ids != sorted(set(ids)) or len(paths) != len(set(paths)):
        raise VerifyError("submission_evidence_not_unique")
    return value


def _scan_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise VerifyError("unsafe_evidence_directory")
    result: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise VerifyError("symlink_in_evidence")
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise VerifyError("unsupported_filesystem_object")
    return result


def _validate_package(package_dir: Path, registration: Mapping[str, Any], task: Mapping[str, Any], constraints: Mapping[str, Any], budget: Mapping[str, Any], policy: Mapping[str, Any]) -> Mapping[str, Any]:
    package = _load(package_dir / "package.json")
    fields = {
        "schema", "case_id", "lane_id", "registration_hash", "task", "constraints", "budget",
        "measurement_contract", "checker_id", "checker_public_key", "submission_hash", "artifact_hash", "evidence_manifest",
    }
    package = _exact(package, fields, "package")
    if package["schema"] != CHECKER_PACKAGE_SCHEMA or package["case_id"] != registration["case_id"]:
        raise VerifyError("package_binding")
    _safe_id(package["lane_id"], "lane_id")
    if package["registration_hash"] != _hash_obj(registration):
        raise VerifyError("package_registration_hash")
    if package["task"] != task or package["constraints"] != constraints or package["budget"] != budget:
        raise VerifyError("package_registered_inputs_changed")
    if package["checker_id"] != registration["checker_id"] or package["checker_public_key"] != registration["checker_public_key"]:
        raise VerifyError("package_checker_binding")
    _hash(package["submission_hash"], "submission_hash")
    _hash(package["artifact_hash"], "artifact_hash")
    expected_contract = [
        {"name": item["name"], "description": item["description"], "value_type": "integer"}
        for item in policy["metrics"]
    ]
    if package["measurement_contract"] != expected_contract:
        raise VerifyError("measurement_contract_mismatch")
    manifest = _exact(package["evidence_manifest"], {"schema", "case_id", "lane_id", "items"}, "evidence_manifest")
    if manifest["schema"] != EVIDENCE_MANIFEST_SCHEMA or manifest["case_id"] != package["case_id"] or manifest["lane_id"] != package["lane_id"]:
        raise VerifyError("evidence_manifest_binding")
    items = manifest["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_EVIDENCE_FILES:
        raise VerifyError("evidence_manifest_count")
    expected_paths: set[str] = set()
    ids: list[str] = []
    total = 0
    for item in items:
        item = _exact(item, {"evidence_id", "kind", "path", "sha256", "bytes"}, "evidence_item")
        ids.append(_safe_id(item["evidence_id"], "evidence_id"))
        if item["kind"] not in EVIDENCE_KINDS:
            raise VerifyError("evidence_kind")
        rel = _safe_rel(item["path"], "evidence_path")
        expected_paths.add(rel.as_posix())
        expected_hash = _hash(item["sha256"], "evidence_sha")
        size = _int(item["bytes"], "evidence_bytes")
        if size < 0 or size > MAX_EVIDENCE_FILE_BYTES:
            raise VerifyError("evidence_file_size")
        total += size
        if total > MAX_EVIDENCE_TOTAL_BYTES:
            raise VerifyError("evidence_total_size")
        path = package_dir / "evidence" / Path(*rel.parts)
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size or _file_hash(path) != expected_hash:
            raise VerifyError(f"evidence_mismatch:{rel.as_posix()}")
    if ids != sorted(set(ids)) or _scan_files(package_dir / "evidence") != expected_paths:
        raise VerifyError("evidence_closure")
    return package


def _validate_report(report: Mapping[str, Any], package: Mapping[str, Any], registration: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = {
        "schema", "checker_id", "checker_public_key", "case_id", "lane_id", "checker_package_hash",
        "evidence_manifest_hash", "status", "metrics", "citations", "critical_failures", "reason_codes",
        "payload_hash", "signature",
    }
    report = _exact(report, fields, "checker_report")
    if report["schema"] != CHECKER_REPORT_SCHEMA:
        raise VerifyError("checker_report_schema")
    if report["checker_id"] != registration["checker_id"] or report["checker_public_key"] != registration["checker_public_key"]:
        raise VerifyError("checker_report_identity")
    if report["case_id"] != package["case_id"] or report["lane_id"] != package["lane_id"]:
        raise VerifyError("checker_report_lane_binding")
    if report["checker_package_hash"] != _hash_obj(package) or report["evidence_manifest_hash"] != _hash_obj(package["evidence_manifest"]):
        raise VerifyError("checker_report_hash_binding")
    if report["status"] not in REPORT_STATUSES:
        raise VerifyError("checker_report_status")
    metric_names = [item["name"] for item in package["measurement_contract"]]
    if not isinstance(report["metrics"], Mapping) or set(report["metrics"]) != set(metric_names):
        raise VerifyError("checker_report_metrics")
    for name in metric_names:
        value = _int(report["metrics"][name], f"metric_{name}")
        if abs(value) > MAX_METRIC_ABS:
            raise VerifyError("metric_value_limit")
    citations = _strings(report["citations"], "citations", nonempty=True)
    ids = {item["evidence_id"] for item in package["evidence_manifest"]["items"]}
    if any(item not in ids for item in citations):
        raise VerifyError("citation_outside_package")
    failures = _strings(report["critical_failures"], "critical_failures")
    _strings(report["reason_codes"], "reason_codes", nonempty=True)
    if report["status"] == "PASS" and failures:
        raise VerifyError("pass_with_critical_failure")
    body = {key: report[key] for key in fields - {"payload_hash", "signature"}}
    if report["payload_hash"] != _hash_obj(body):
        raise VerifyError("checker_report_payload_hash")
    if not isinstance(report["signature"], str) or not SIG_RE.fullmatch(report["signature"]):
        raise VerifyError("checker_report_signature_encoding")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(registration["checker_public_key"])).verify(
            bytes.fromhex(report["signature"]), _canonical(body)
        )
    except (ValueError, InvalidSignature) as exc:
        raise VerifyError("checker_report_signature") from exc
    return report


def _compare(policy: Mapping[str, Any], incumbent: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    if incumbent["status"] == "UNDECIDABLE" or candidate["status"] == "UNDECIDABLE":
        return {"decision": "INCONCLUSIVE", "reason_codes": ["checker_report_undecidable"], "comparisons": []}
    if candidate["status"] != "PASS":
        return {"decision": "KEEP_INCUMBENT", "reason_codes": ["candidate_did_not_pass_checker"], "comparisons": []}
    if candidate["critical_failures"]:
        return {"decision": "KEEP_INCUMBENT", "reason_codes": ["candidate_has_critical_failure"], "comparisons": []}
    comparisons: list[dict[str, Any]] = []
    regressions: list[str] = []
    improvements: list[str] = []
    for metric in policy["metrics"]:
        name = metric["name"]
        inc = incumbent["metrics"][name]
        cand = candidate["metrics"][name]
        improvement = cand - inc if metric["direction"] == "maximize" else inc - cand
        regression = max(-improvement, 0)
        allowed = (not metric["required"]) or regression <= metric["max_regression"]
        material = improvement >= metric["minimum_improvement"]
        if not allowed:
            regressions.append(name)
        if material:
            improvements.append(name)
        comparisons.append({
            "name": name, "incumbent": inc, "candidate": cand, "direction": metric["direction"],
            "improvement": improvement, "required": metric["required"],
            "max_regression": metric["max_regression"], "minimum_improvement": metric["minimum_improvement"],
            "within_required_floor": allowed, "material_improvement": material,
        })
    if regressions:
        return {"decision": "KEEP_INCUMBENT", "reason_codes": ["required_metric_regression:" + ",".join(regressions)], "comparisons": comparisons}
    if not improvements:
        return {"decision": "KEEP_INCUMBENT", "reason_codes": ["no_declared_material_improvement"], "comparisons": comparisons}
    return {"decision": "PROMOTE_CANDIDATE", "reason_codes": ["candidate_preserved_required_floor", "material_improvement:" + ",".join(improvements)], "comparisons": comparisons}


def _validate_manifest(root: Path) -> tuple[Mapping[str, Any], str]:
    manifest = _exact(_load(root / "case_manifest.json"), {"schema", "entries"}, "case_manifest")
    if manifest["schema"] != CASE_MANIFEST_SCHEMA or not isinstance(manifest["entries"], list):
        raise VerifyError("case_manifest_schema")
    listed: set[str] = set()
    for entry in manifest["entries"]:
        entry = _exact(entry, {"path", "sha256", "bytes"}, "case_manifest_entry")
        rel = _safe_rel(entry["path"], "case_manifest_path")
        name = rel.as_posix()
        if name in listed or name in {"case_manifest.json", "verification.json"}:
            raise VerifyError("case_manifest_duplicate_or_reserved")
        listed.add(name)
        expected_hash = _hash(entry["sha256"], "case_manifest_sha")
        expected_size = _int(entry["bytes"], "case_manifest_bytes")
        path = root / Path(*rel.parts)
        if not path.is_file() or path.is_symlink() or path.stat().st_size != expected_size or _file_hash(path) != expected_hash:
            raise VerifyError(f"case_manifest_mismatch:{name}")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in {"case_manifest.json", "verification.json"}
    }
    if actual != listed:
        raise VerifyError(f"case_manifest_closure:missing={sorted(listed-actual)}:extra={sorted(actual-listed)}")
    return manifest, _hash_obj(manifest)


def verify_case_directory(root: Path, *, require_stored_verification: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    decision_name: str | None = None
    report_signatures = False
    evidence_closure = False
    manifest_hash: str | None = None
    try:
        root = root.resolve()
        if not root.is_dir():
            raise VerifyError("case_directory_missing")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise VerifyError(f"symlink_in_case:{path.relative_to(root).as_posix()}")
        manifest, manifest_hash = _validate_manifest(root)
        registration = _validate_registration(_load(root / "registration.json"))
        task = _validate_task(_load(root / "task.json"))
        constraints = _validate_constraints(_load(root / "constraints.json"))
        budget = _validate_budget(_load(root / "budget.json"))
        policy = _validate_policy(_load(root / "policy.json"))
        for field, value in (
            ("task_hash", task), ("constraints_hash", constraints), ("budget_hash", budget), ("policy_hash", policy)
        ):
            if registration[field] != _hash_obj(value):
                raise VerifyError(f"registered_input_hash:{field}")

        preparation = _exact(_load(root / "preparation.json"), {"schema", "case_id", "registration_hash", "precheck_hash", "lane_mapping", "package_hashes"}, "preparation")
        if preparation["schema"] != PREPARATION_SCHEMA or preparation["case_id"] != registration["case_id"] or preparation["registration_hash"] != _hash_obj(registration):
            raise VerifyError("preparation_registration_binding")
        if not isinstance(preparation["lane_mapping"], Mapping) or set(preparation["lane_mapping"]) != set(ROLES):
            raise VerifyError("lane_mapping")
        if not isinstance(preparation["package_hashes"], Mapping) or set(preparation["package_hashes"]) != set(preparation["lane_mapping"].values()):
            raise VerifyError("package_hash_mapping")
        if len(set(preparation["lane_mapping"].values())) != 2:
            raise VerifyError("lane_collision")
        precheck = _load(root / "precheck.json")
        expected_precheck = {
            "schema": PRECHECK_SCHEMA,
            "registration_hash": _hash_obj(registration),
            "package_hashes": sorted(preparation["package_hashes"].values()),
            "checker_reports_present": False,
        }
        if precheck != expected_precheck or preparation["precheck_hash"] != _hash_obj(precheck):
            raise VerifyError("precheck_commitment")

        packages: dict[str, Mapping[str, Any]] = {}
        submissions: dict[str, Mapping[str, Any]] = {}
        for role in ROLES:
            submissions[role] = _validate_submission(_load(root / "sealed_submissions" / f"{role}.json"), role, registration)
            lane = preparation["lane_mapping"][role]
            _safe_id(lane, f"lane_{role}")
            package = _validate_package(root / "checker_packages" / lane, registration, task, constraints, budget, policy)
            if package["submission_hash"] != _hash_obj(submissions[role]) or package["artifact_hash"] != submissions[role]["artifact_hash"]:
                raise VerifyError(f"package_submission_binding:{role}")
            if preparation["package_hashes"].get(lane) != _hash_obj(package):
                raise VerifyError(f"package_hash:{role}")
            # Structural lane blindness: package protocol objects contain no arm role or peer submission.
            if "role" in package or "incumbent" in package or "candidate" in package:
                raise VerifyError("role_field_in_checker_package")
            packages[lane] = package
        evidence_closure = True

        reports: dict[str, Mapping[str, Any]] = {}
        for role in ROLES:
            lane = preparation["lane_mapping"][role]
            report = _validate_report(_load(root / "checker_reports" / f"{role}.json"), packages[lane], registration)
            reports[role] = report
        report_signatures = True

        comparison = _compare(policy, reports["incumbent"], reports["candidate"])
        decision = _exact(
            _load(root / "decision.json"),
            {"schema", "case_id", "registration_hash", "precheck_hash", "policy_hash", "incumbent_version_hash", "candidate_version_hash", "decision", "reason_codes", "comparisons", "checker_report_hashes", "execution_authorized", "claim_boundary"},
            "decision",
        )
        expected_decision = {
            "schema": DECISION_SCHEMA,
            "case_id": registration["case_id"],
            "registration_hash": _hash_obj(registration),
            "precheck_hash": _hash_obj(precheck),
            "policy_hash": _hash_obj(policy),
            "incumbent_version_hash": registration["incumbent_version_hash"],
            "candidate_version_hash": registration["candidate_version_hash"],
            "decision": comparison["decision"],
            "reason_codes": comparison["reason_codes"],
            "comparisons": comparison["comparisons"],
            "checker_report_hashes": {
                "incumbent": _hash_obj(reports["incumbent"]),
                "candidate": _hash_obj(reports["candidate"]),
            },
            "execution_authorized": False,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        if decision != expected_decision:
            raise VerifyError("decision_recompute_mismatch")
        decision_name = decision["decision"]

        if require_stored_verification:
            stored = _exact(
                _load(root / "verification.json"),
                {"schema", "valid", "errors", "recomputed_decision", "manifest_hash", "checker_signatures_verified", "evidence_closure_verified", "claim_boundary"},
                "stored_verification",
            )
            if stored["schema"] != VERIFICATION_SCHEMA or stored["valid"] is not True or stored["errors"] != []:
                raise VerifyError("stored_verification_not_green")
            if stored["recomputed_decision"] != decision_name or stored["manifest_hash"] != manifest_hash:
                raise VerifyError("stored_verification_mismatch")
            if stored["checker_signatures_verified"] is not True or stored["evidence_closure_verified"] is not True or stored["claim_boundary"] != CLAIM_BOUNDARY:
                raise VerifyError("stored_verification_boundary")
    except (OSError, VerifyError, KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))

    return {
        "schema": VERIFICATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "recomputed_decision": decision_name,
        "manifest_hash": manifest_hash,
        "checker_signatures_verified": report_signatures,
        "evidence_closure_verified": evidence_closure,
        "claim_boundary": CLAIM_BOUNDARY,
    }
