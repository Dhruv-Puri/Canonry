"""Proof of Compliance (doc Sections 5.4 'prove', 9.3 provenance).

A tamper-evident digital seal: SHA-256 fingerprint of the approved content plus
who approved it, against which rules and when — cryptographically signed
(Ed25519 via PyNaCl), stored with the record and in a hash-chained ledger.
A verify page answers Verified / Modified / Unknown.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from typing import Any, Dict, Optional

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from db import _now, gen_id, get_knowledge_version

# Where the Ed25519 seed lives. Overridable so a deployment can put it on a
# mounted disk (the database and the key must survive restarts together, or
# seals signed before the restart stop verifying).
KEY_PATH = os.environ.get("CANONRY_SIGNING_KEY") or os.path.join(
    os.path.dirname(__file__), "..", "db", "signing_seed.bin")


def load_signing_key() -> SigningKey:
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    if not os.path.exists(KEY_PATH):
        seed = secrets.token_bytes(32)
        with open(KEY_PATH, "wb") as f:
            f.write(seed)
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    with open(KEY_PATH, "rb") as f:
        return SigningKey(f.read())


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sign_approval(conn: sqlite3.Connection, workspace_id: str, submission_id: str,
                  revision_id: str, content: str, approved_by: str,
                  approver_role: str, self_approved: bool = False) -> Dict[str, Any]:
    signing = load_signing_key()
    pub_fp = hashlib.sha256(bytes(signing.verify_key)).hexdigest()[:16]
    rules_version = conn.execute(
        "SELECT COUNT(*) c FROM rules WHERE workspace_id = ? AND status='approved'",
        (workspace_id,),
    ).fetchone()["c"]
    record = {
        "workspace": workspace_id,
        "submission_id": submission_id,
        "revision_id": revision_id,
        "content_sha256": _fingerprint(content),
        "approved_by": approved_by,
        "approver_role": approver_role,
        # true when the approver also drafted it (self-chosen roles make this possible)
        "self_approved": bool(self_approved),
        "rules_version": int(rules_version),
        # the exact knowledge (rules, facts, terms) in force when this was approved
        "knowledge_version": get_knowledge_version(conn),
        "decided_at": _now(),
        "kind": "ProofOfCompliance/2",
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    sig = signing.sign(canonical).signature.hex()

    poc_id = gen_id("poc")
    # hash-chained ledger entry (tamper-evident history in Postgres later)
    last = conn.execute(
        "SELECT record_json FROM proof_of_compliance ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    prev = last["record_json"] if last else "GENESIS"
    ledger_hash = hashlib.sha256((prev + canonical.hex()).encode()).hexdigest()
    conn.execute(
        "INSERT INTO proof_of_compliance (id, submission_id, revision_id, record_json, "
        "content_sha256, signature, public_key_fingerprint, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (poc_id, submission_id, revision_id, json.dumps({**record, **{"ledger_hash": ledger_hash},
                                                          "record_hash": hashlib.sha256(canonical).hexdigest()}),
         record["content_sha256"], sig, pub_fp, record["decided_at"]),
    )
    conn.commit()
    return {"poc_id": poc_id, "record": {**record, "ledger_hash": ledger_hash}, "signature": sig}


# signed-record fields that identify a person; kept in the record, never shown publicly
_PRIVATE = ("approved_by",)


def _spacing_free(text: str) -> str:
    return "".join(text.split())


def verify(conn: sqlite3.Connection, poc_id: str, published: Optional[str] = None) -> Dict[str, Any]:
    """Public verification of a seal.

    Without `published` text: is the seal genuine and the approved revision intact?
    With it: is this the exact text that was approved? Whitespace-only differences
    (from copying a web page) still verify, with a note saying so.
    """
    row = conn.execute(
        "SELECT * FROM proof_of_compliance WHERE id = ?", (poc_id,)
    ).fetchone()
    if not row:
        return {"status": "unknown", "content_checked": published is not None}
    stored = json.loads(row["record_json"])
    record = {k: v for k, v in stored.items() if k not in ("ledger_hash", "record_hash")}
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    pub = load_signing_key().verify_key
    try:
        VerifyKey(bytes(pub)).verify(canonical, bytes.fromhex(row["signature"]))
        sig_ok = True
    except (BadSignatureError, ValueError):
        sig_ok = False
    rev = conn.execute("SELECT content FROM revisions WHERE id = ?", (row["revision_id"],)).fetchone()
    approved = rev["content"] if rev else None
    status, reason = "unknown", None
    if sig_ok:
        if approved is None or _fingerprint(approved) != row["content_sha256"]:
            status, reason = "modified", "The stored approved revision no longer matches its seal."
        elif published is None:
            status = "verified"
        elif _fingerprint(published) == row["content_sha256"]:
            status = "verified"
        elif _spacing_free(published) == _spacing_free(approved):
            status, reason = "verified", "Matches the approved text apart from spacing and line breaks."
        else:
            status, reason = "modified", "This text differs from the approved text."
    out = {
        "status": status,
        "content_checked": published is not None,
        "record": {k: v for k, v in record.items() if k not in _PRIVATE},
        "public_key_fingerprint": row["public_key_fingerprint"],
        "signature": row["signature"][:32] + "...",
        "signature_valid": sig_ok,
    }
    if reason:
        out["reason"] = reason
    return out
