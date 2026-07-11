from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from .util import canonical_json, sha256_bytes, sha256_file


@dataclass
class ReceiptSigner:
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "ReceiptSigner":
        return cls(Ed25519PrivateKey.generate())

    @property
    def public_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode("ascii")

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self.private_key.sign(payload)).decode("ascii")

    def private_raw(self) -> bytes:
        return self.private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _receipt_body(kind: str, index: int, parent_hash: str | None, payload: dict[str, Any], public_key: str) -> dict[str, Any]:
    return {
        "schema": "openline.endurance.receipt.v1",
        "index": index,
        "kind": kind,
        "parent_hash": parent_hash,
        "signer_public_key": public_key,
        "payload": payload,
    }


def create_chain(items: list[tuple[str, dict[str, Any]]], signer: ReceiptSigner) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    parent: str | None = None
    for index, (kind, payload) in enumerate(items):
        body = _receipt_body(kind, index, parent, payload, signer.public_b64)
        receipt_hash = sha256_bytes(canonical_json(body))
        signature = signer.sign(bytes.fromhex(receipt_hash))
        receipt = {**body, "receipt_hash": receipt_hash, "signature": signature}
        chain.append(receipt)
        parent = receipt_hash
    return chain


def chain_digest(chain: list[dict[str, Any]]) -> str:
    return sha256_bytes("".join(str(item["receipt_hash"]) for item in chain).encode("ascii"))


def write_chain(path: Path, chain: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for receipt in chain:
            handle.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")


def write_anchor(path: Path, chain: list[dict[str, Any]], signer: ReceiptSigner) -> dict[str, Any]:
    body = {
        "schema": "openline.endurance.anchor.v1",
        "expected_count": len(chain),
        "expected_tail_hash": chain[-1]["receipt_hash"] if chain else None,
        "chain_digest": chain_digest(chain),
        "signer_public_key": signer.public_b64,
    }
    anchor_hash = sha256_bytes(canonical_json(body))
    anchor = {**body, "anchor_hash": anchor_hash, "signature": signer.sign(bytes.fromhex(anchor_hash))}
    path.write_text(json.dumps(anchor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return anchor


def read_chain(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_chain(chain_path: Path, anchor_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    chain = read_chain(chain_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    try:
        public_raw = base64.b64decode(anchor["signer_public_key"])
        public = Ed25519PublicKey.from_public_bytes(public_raw)
    except Exception as exc:
        return {"valid": False, "errors": [f"invalid_anchor_public_key:{exc}"]}
    expected_parent = None
    for expected_index, receipt in enumerate(chain):
        body = {key: receipt[key] for key in ("schema", "index", "kind", "parent_hash", "signer_public_key", "payload")}
        computed_hash = sha256_bytes(canonical_json(body))
        if receipt.get("index") != expected_index:
            errors.append(f"index_mismatch:{expected_index}")
        if receipt.get("parent_hash") != expected_parent:
            errors.append(f"parent_mismatch:{expected_index}")
        if receipt.get("receipt_hash") != computed_hash:
            errors.append(f"hash_mismatch:{expected_index}")
        if receipt.get("signer_public_key") != anchor.get("signer_public_key"):
            errors.append(f"signer_mismatch:{expected_index}")
        try:
            public.verify(base64.b64decode(receipt["signature"]), bytes.fromhex(computed_hash))
        except Exception:
            errors.append(f"signature_invalid:{expected_index}")
        expected_parent = computed_hash
    anchor_body = {key: anchor[key] for key in ("schema", "expected_count", "expected_tail_hash", "chain_digest", "signer_public_key")}
    anchor_hash = sha256_bytes(canonical_json(anchor_body))
    if anchor.get("anchor_hash") != anchor_hash:
        errors.append("anchor_hash_mismatch")
    try:
        public.verify(base64.b64decode(anchor["signature"]), bytes.fromhex(anchor_hash))
    except Exception:
        errors.append("anchor_signature_invalid")
    if int(anchor.get("expected_count", -1)) != len(chain):
        errors.append("completeness_count_mismatch")
    tail = chain[-1]["receipt_hash"] if chain else None
    if anchor.get("expected_tail_hash") != tail:
        errors.append("completeness_tail_mismatch")
    if anchor.get("chain_digest") != chain_digest(chain):
        errors.append("completeness_digest_mismatch")
    return {
        "valid": not errors,
        "integrity_valid": not any("completeness" in error for error in errors),
        "completeness_verified": not any(error.startswith("completeness") for error in errors),
        "count": len(chain),
        "tail_hash": tail,
        "chain_digest": chain_digest(chain),
        "errors": errors,
    }


def artifact_hashes(root: Path, relative_paths: list[str]) -> dict[str, str]:
    return {relative: sha256_file(root / relative) for relative in sorted(relative_paths)}
