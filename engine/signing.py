"""Proof of Compliance (doc Sections 5.4 'prove', 9.3 provenance).

A tamper-evident digital seal: SHA-256 fingerprint of the approved text or file
plus who approved it, against which rules and when — cryptographically signed
(Ed25519 via PyNaCl), stored with the record and in a hash-chained ledger.

Text and file revisions share one signed record (`ProofOfCompliance/3`). A file
seal covers the original uploaded bytes; the stamped copy embeds that signed
record and the engine also stores a hash of the stamped copy, so a metadata-only
stamp never creates a self-referential hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Any, Dict, Optional

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from db import _now, gen_id, get_knowledge_version

# Where the Ed25519 seed lives. Overridable so a deployment can keep the key in
# the environment (durable) or on a mounted disk together with the database.
KEY_PATH = os.environ.get("CANONRY_SIGNING_KEY") or os.path.join(
    os.path.dirname(__file__), "..", "db", "signing_seed.bin")


def load_signing_key() -> SigningKey:
    seed = (os.environ.get("CANONRY_SIGNING_SEED") or "").strip()
    if seed:
        try:
            raw = bytes.fromhex(seed)
        except ValueError as exc:
            raise RuntimeError("CANONRY_SIGNING_SEED must be 64 hex characters (32 bytes).") from exc
        if len(raw) != 32:
            raise RuntimeError("CANONRY_SIGNING_SEED must be 64 hex characters (32 bytes).")
        return SigningKey(raw)
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    if not os.path.exists(KEY_PATH):
        with open(KEY_PATH, "wb") as f:
            f.write(secrets.token_bytes(32))
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    with open(KEY_PATH, "rb") as f:
        return SigningKey(f.read())


def _fingerprint_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_approval(conn, workspace_id: str, submission_id: str, revision_id: str,
                  content: Optional[str], approved_by: str, approver_role: str,
                  self_approved: bool = False, asset: Optional[Dict[str, Any]] = None,
                  pack_versions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Sign an approval. `asset` is {asset_id, filename, mime, bytes} for a file."""
    signing = load_signing_key()
    pub_fp = hashlib.sha256(bytes(signing.verify_key)).hexdigest()[:16]
    rules_version = conn.execute(
        "SELECT COUNT(*) c FROM rules WHERE workspace_id = ? AND status='approved'",
        (workspace_id,),
    ).fetchone()["c"]
    content_kind = "file" if asset else "text"
    if asset:
        content_sha = _fingerprint_bytes(bytes(asset["bytes"]))
    else:
        content_sha = _fingerprint_text(content or "")
    record = {
        "workspace": workspace_id,
        "submission_id": submission_id,
        "revision_id": revision_id,
        "content_sha256": content_sha,
        "content_kind": content_kind,
        "asset_id": asset.get("asset_id") if asset else None,
        "filename": asset.get("filename") if asset else None,
        "mime": asset.get("mime") if asset else None,
        "approved_by": approved_by,
        "approver_role": approver_role,
        # true when the approver also drafted it (self-chosen roles make this possible)
        "self_approved": bool(self_approved),
        "rules_version": int(rules_version),
        # the exact knowledge (rules, facts, terms and packs) in force at approval
        "knowledge_version": get_knowledge_version(conn),
        "pack_versions": pack_versions or {},
        "decided_at": _now(),
        "kind": "ProofOfCompliance/3",
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    sig = signing.sign(canonical).signature.hex()

    poc_id = gen_id("poc")
    # hash-chained ledger entry (tamper-evident history)
    last = conn.execute(
        "SELECT record_json FROM proof_of_compliance ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    prev = last["record_json"] if last else "GENESIS"
    ledger_hash = hashlib.sha256((prev + canonical.hex()).encode()).hexdigest()
    conn.execute(
        "INSERT INTO proof_of_compliance (id, submission_id, revision_id, record_json, "
        "content_sha256, signature, public_key_fingerprint, created_at, asset_id, content_kind) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (poc_id, submission_id, revision_id, json.dumps({**record, "ledger_hash": ledger_hash,
                                                          "record_hash": hashlib.sha256(canonical).hexdigest()}),
         record["content_sha256"], sig, pub_fp, record["decided_at"],
         record.get("asset_id"), content_kind),
    )
    conn.commit()
    return {"poc_id": poc_id, "record": {**record, "ledger_hash": ledger_hash}, "signature": sig}


# signed-record fields that identify a person; kept in the record, never shown publicly
_PRIVATE = ("approved_by",)


def _spacing_free(text: str) -> str:
    return "".join(text.split())


def _load_poc(conn, poc_id: str):
    row = conn.execute("SELECT * FROM proof_of_compliance WHERE id = ?", (poc_id,)).fetchone()
    if not row:
        return None, None, None
    stored = json.loads(row["record_json"])
    record = {k: v for k, v in stored.items() if k not in ("ledger_hash", "record_hash")}
    return row, record, stored


def _signature_ok(record: Dict[str, Any], signature_hex: str) -> bool:
    if not isinstance(record, dict) or not isinstance(signature_hex, str):
        return False  # an embedded proof is untrusted input: wrong types are simply not a valid seal
    try:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        VerifyKey(bytes(load_signing_key().verify_key)).verify(canonical, bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


def _asset_bytes(conn, asset_id: Optional[str]) -> Optional[bytes]:
    if not asset_id:
        return None
    row = conn.execute("SELECT bytes FROM asset_data WHERE asset_id = ?", (asset_id,)).fetchone()
    return bytes(row["bytes"]) if row else None


def verify(conn, poc_id: str, published: Optional[str] = None) -> Dict[str, Any]:
    """Public verification of a text seal (the original Round 2 behaviour)."""
    row, record, _stored = _load_poc(conn, poc_id)
    if not row:
        return {"status": "unknown", "content_checked": published is not None}
    if record.get("content_kind") == "file":
        return {
            "status": "unknown",
            "content_checked": published is not None,
            "reason": "This is a file seal. Upload the published file to check it.",
            "record": {k: v for k, v in record.items() if k not in _PRIVATE},
            "public_key_fingerprint": row["public_key_fingerprint"],
            "signature_valid": _signature_ok(record, row["signature"]),
            "content_kind": "file",
        }
    sig_ok = _signature_ok(record, row["signature"])
    rev = conn.execute("SELECT content FROM revisions WHERE id = ?", (row["revision_id"],)).fetchone()
    approved = rev["content"] if rev else None
    status, reason = "unknown", None
    if sig_ok:
        if approved is None or _fingerprint_text(approved) != row["content_sha256"]:
            status, reason = "modified", "The stored approved revision no longer matches its seal."
        elif published is None:
            status = "verified"
        elif _fingerprint_text(published) == row["content_sha256"]:
            status = "verified"
        elif _spacing_free(published) == _spacing_free(approved):
            status, reason = "verified", "Matches the approved text apart from spacing and line breaks."
        else:
            status, reason = "modified", "This text differs from the approved text."
    out = {
        "status": status,
        "content_checked": published is not None,
        "content_kind": "text",
        "record": {k: v for k, v in record.items() if k not in _PRIVATE},
        "public_key_fingerprint": row["public_key_fingerprint"],
        "signature": row["signature"][:32] + "...",
        "signature_valid": sig_ok,
    }
    if reason:
        out["reason"] = reason
    return out


def verify_file(conn, poc_id: str, data: bytes) -> Dict[str, Any]:
    """Verify an original or stamped file against a file seal.

    The signed record covers the original bytes. A stamped copy carries the same
    record in its metadata and its own hash is stored in the database, so the
    published file can be checked without a self-referential hash.
    """
    import stamping  # local import: stamping is only needed for file seals

    row, record, _stored = _load_poc(conn, poc_id)
    if not row:
        return {"status": "unknown", "content_checked": True, "reason": "Unknown Proof of Compliance id."}
    if record.get("content_kind") != "file":
        return {"status": "unknown", "content_checked": True, "reason": "This is a text seal. Check the pasted text."}
    envelope = stamping.extract_record(data)
    embedded = envelope.get("record") if envelope else None
    signature = envelope.get("signature") if envelope else row["signature"]
    sig_ok = _signature_ok(record, row["signature"])
    embedded_ok = bool(embedded) and _signature_ok(embedded, signature or "")
    file_hash = _fingerprint_bytes(data)
    original_hash = row["content_sha256"]
    stamped_hash = row["stamped_sha256"]
    status, reason = "modified", "This file is neither the approved original nor its stamped copy."
    if file_hash == original_hash:
        status, reason = "verified", None
    elif stamped_hash and file_hash == stamped_hash:
        if sig_ok and (embedded is None or embedded_ok):
            status, reason = "verified", None
        else:
            status, reason = "signature_invalid", "The embedded proof could not be verified."
    elif embedded and embedded_ok and embedded.get("content_sha256") == record.get("content_sha256"):
        # A real seal copied onto other bytes proves nothing about those bytes:
        # the file was changed after it was stamped (or the seal was moved).
        status, reason = "modified", ("This file carries the seal of this approval, but its content was changed "
                                      "after it was stamped.")
    elif not sig_ok:
        status, reason = "signature_invalid", "The stored seal signature does not verify."
    out = {
        "status": status,
        "content_checked": True,
        "content_kind": "file",
        "record": {k: v for k, v in record.items() if k not in _PRIVATE},
        "public_key_fingerprint": row["public_key_fingerprint"],
        "signature_valid": sig_ok,
        "stamped": bool(envelope),
        "file_sha256": file_hash,
    }
    if reason:
        out["reason"] = reason
    return out
