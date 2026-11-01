"""Versioned public API: workspace-scoped keys, scopes and idempotency.

Keys are shown once and stored only as a SHA-256 hash; the prefix is stored so
the settings screen can list a key without being able to use it. Every request
authenticates to exactly one workspace, so an API key can never read another
tenant's submissions, files or seals.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from fastapi import HTTPException, Request

from db import INTEGRITY_ERRORS, _now

KEY_PREFIX_LENGTH = 16
SCOPES = ("check", "read", "admin")
IDEMPOTENCY_TTL_HOURS = 24


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_key(conn, workspace_id: str, name: str, scopes: Sequence[str],
               created_by: Optional[str]) -> Dict[str, Any]:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise HTTPException(422, "Give the API key a name.")
    requested = [s for s in scopes if s in SCOPES] or ["check", "read"]
    if "admin" in requested:
        requested = ["check", "read", "admin"]
    raw = "ck_live_" + secrets.token_urlsafe(28)
    key_id = "key_" + secrets.token_hex(6)
    prefix = raw[:KEY_PREFIX_LENGTH]
    conn.execute(
        "INSERT INTO api_keys (id, workspace_id, name, prefix, key_hash, scopes_json, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (key_id, workspace_id, name, prefix, _hash(raw), json.dumps(requested), created_by, _now()),
    )
    return {"id": key_id, "name": name, "prefix": prefix, "key": raw, "scopes": requested,
            "created_at": _now(), "warning": "Copy this key now. Only its hash is stored."}


def ensure_demo_key(conn, workspace_id: str, name: str, raw: str,
                    scopes: Sequence[str] = ("check", "read")) -> Optional[str]:
    """Demo bootstrap from a deployment secret. The raw value is never stored,
    only its hash; setting the same value on the CMS is what lets it call us."""
    raw = (raw or "").strip()
    if not raw.startswith("ck_live_") or len(raw) > 128:
        return None
    prefix = raw[:KEY_PREFIX_LENGTH]
    if conn.execute("SELECT 1 FROM api_keys WHERE prefix = ?", (prefix,)).fetchone():
        return None
    key_id = "key_" + secrets.token_hex(6)
    conn.execute(
        "INSERT INTO api_keys (id, workspace_id, name, prefix, key_hash, scopes_json, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (key_id, workspace_id, name[:80], prefix, _hash(raw),
         json.dumps([s for s in scopes if s in SCOPES] or ["check", "read"]), "system", _now()))
    return key_id


def list_keys(conn, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, prefix, scopes_json, created_by, created_at, last_used_at, revoked_at "
        "FROM api_keys WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["scopes"] = json.loads(data.pop("scopes_json") or "[]")
        out.append(data)
    return out


def revoke_key(conn, workspace_id: str, key_id: str) -> None:
    row = conn.execute("SELECT id FROM api_keys WHERE id = ? AND workspace_id = ?",
                       (key_id, workspace_id)).fetchone()
    if not row:
        raise HTTPException(404, "API key not found.")
    conn.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?", (_now(), key_id))


def _bearer(req: Request) -> str:
    header = (req.headers.get("authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, {"code": "missing_key", "message": "Send an API key as: Authorization: Bearer <key>."})
    token = header[7:].strip()
    if not token.startswith("ck_live_") or len(token) > 128:
        raise HTTPException(401, {"code": "invalid_key", "message": "That API key is not valid."})
    return token


def authenticate(req: Request, conn, scope: str) -> Dict[str, Any]:
    raw = _bearer(req)
    row = conn.execute(
        "SELECT * FROM api_keys WHERE prefix = ? AND revoked_at IS NULL",
        (raw[:KEY_PREFIX_LENGTH],)).fetchone()
    if not row or not hmac.compare_digest(row["key_hash"], _hash(raw)):
        raise HTTPException(401, {"code": "invalid_key", "message": "That API key is not valid."})
    scopes = json.loads(row["scopes_json"] or "[]")
    if scope not in scopes and "admin" not in scopes:
        raise HTTPException(403, {"code": "insufficient_scope",
                                  "message": f"This key lacks the '{scope}' scope."})
    conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_now(), row["id"]))
    return dict(row)


def require_scope(key: Dict[str, Any], scope: str) -> None:
    scopes = key.get("scopes") or json.loads(key.get("scopes_json") or "[]")
    if scope not in scopes and "admin" not in scopes:
        raise HTTPException(403, {"code": "insufficient_scope",
                                  "message": f"This key lacks the '{scope}' scope."})


def idempotency_key(req: Request) -> Optional[str]:
    value = (req.headers.get("idempotency-key") or "").strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value):
        raise HTTPException(422, {"code": "bad_idempotency_key",
                                  "message": "Idempotency-Key must be 8–128 URL-safe characters."})
    return value


def request_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def lookup_idempotent(conn, workspace_id: str, key: Optional[str], endpoint: str,
                      payload_hash: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    row = conn.execute(
        "SELECT request_hash, response_json, status FROM idempotency "
        "WHERE workspace_id = ? AND key = ? AND endpoint = ?",
        (workspace_id, key, endpoint)).fetchone()
    if not row:
        return None
    if row["request_hash"] != payload_hash:
        raise HTTPException(409, {"code": "idempotency_conflict",
                                  "message": "This Idempotency-Key was already used with a different request."})
    if not row["status"]:
        raise HTTPException(409, {"code": "idempotency_in_progress",
                                  "message": "A request with this Idempotency-Key is still running. "
                                             "Retry in a few seconds to get its answer."})
    return {"status": row["status"], "body": json.loads(row["response_json"] or "{}")}


def claim_idempotent(conn, workspace_id: str, key: Optional[str], endpoint: str,
                     payload_hash: str) -> Optional[Dict[str, Any]]:
    """Return the stored answer for a repeated key, or claim the key for this
    request (committed at once, status 0 = running), so two simultaneous
    retries can never both do the work."""
    if not key:
        return None
    cached = lookup_idempotent(conn, workspace_id, key, endpoint, payload_hash)
    if cached:
        return cached
    expires = (datetime.now(timezone.utc) + timedelta(hours=IDEMPOTENCY_TTL_HOURS)).isoformat()
    try:
        conn.execute(
            "INSERT INTO idempotency (workspace_id, key, endpoint, request_hash, response_json, status, "
            "created_at, expires_at) VALUES (?,?,?,?,NULL,0,?,?)",
            (workspace_id, key, endpoint, payload_hash, _now(), expires))
        conn.commit()
    except INTEGRITY_ERRORS:
        conn.rollback()
        return lookup_idempotent(conn, workspace_id, key, endpoint, payload_hash)
    return None


def release_idempotent(conn, workspace_id: str, key: Optional[str], endpoint: str) -> None:
    """The claimed request failed: free the key so a retry can run."""
    if not key:
        return
    conn.rollback()
    conn.execute("DELETE FROM idempotency WHERE workspace_id = ? AND key = ? AND endpoint = ? AND status = 0",
                 (workspace_id, key, endpoint))
    conn.commit()


def store_idempotent(conn, workspace_id: str, key: Optional[str], endpoint: str,
                     payload_hash: str, status: int, body: Dict[str, Any]) -> None:
    if not key:
        return
    conn.execute(
        "UPDATE idempotency SET response_json = ?, status = ? WHERE workspace_id = ? AND key = ? AND endpoint = ?",
        (json.dumps(body), status, workspace_id, key, endpoint))


def cleanup_idempotency(conn) -> None:
    try:
        conn.execute("DELETE FROM idempotency WHERE expires_at < ?", (_now(),))
    except Exception:
        pass
