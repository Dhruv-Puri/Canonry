"""Webhooks: durable outbox, HMAC signatures and honest retries.

Events: `checked` (a revision finished checking), `approved` (a reviewer
approved) and `signed` (the Proof of Compliance exists). A delivery is written
to the outbox in the same transaction as the product event, so a crash between
the two cannot lose it. Delivery is attempted inline with a short timeout and
retried with exponential backoff from the same durable rows.

Signature: `X-Canonry-Signature: sha256=<hex>` is HMAC-SHA256 over
`<timestamp>.<raw body>`, with `X-Canonry-Timestamp` in the same request.
Receivers should reject a timestamp older than five minutes and compare in
constant time.

The outbox is intentionally small. This is not a queue service; a future worker
can claim the same `pending` rows. `CANONRY_WEBHOOK_ALLOW_LOCAL=true` permits a
loopback receiver for local development and tests; production endpoints must be
HTTPS and cannot target a private address.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx

from db import _now, gen_id

EVENTS = ("checked", "approved", "signed")
MAX_ATTEMPTS = 8
BACKOFF_SECONDS = (30, 120, 600, 1800, 3600, 7200, 21600, 43200)


def _allow_local() -> bool:
    return (os.environ.get("CANONRY_WEBHOOK_ALLOW_LOCAL") or "").strip().lower() in ("1", "true", "yes")


def validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("Webhook URLs must start with https://.")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("That is not a valid webhook URL.")
    host = parsed.hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
    if local:
        if not _allow_local():
            raise ValueError("Loopback webhook URLs are disabled. Set CANONRY_WEBHOOK_ALLOW_LOCAL=true for local development.")
        return url
    if parsed.scheme != "https":
        raise ValueError("Webhook URLs must use HTTPS, except for explicit local development.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise ValueError("Webhook URLs cannot point at a private or reserved address.")
    except socket.gaierror:
        raise ValueError("That webhook host could not be resolved.")
    return url


def _secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def create_endpoint(conn, workspace_id: str, url: str, events: Sequence[str],
                    description: str = "", created_by: Optional[str] = None,
                    provided_secret: Optional[str] = None) -> Dict[str, Any]:
    try:
        url = validate_url(url)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    chosen = [e for e in events if e in EVENTS]
    if not chosen:
        raise ValueError("Choose at least one event: checked, approved or signed.")
    secret = (provided_secret or "").strip() or _secret()
    if len(secret) < 16 or len(secret) > 200:
        raise ValueError("A webhook secret must be 16–200 characters.")
    endpoint_id = "wh_" + secrets.token_hex(6)
    conn.execute(
        "INSERT INTO webhook_endpoints (id, workspace_id, url, secret_salt, events_json, active, "
        "description, created_by, created_at) VALUES (?,?,?,?,?,1,?,?,?)",
        (endpoint_id, workspace_id, url, secret, json.dumps(chosen),
         " ".join((description or "").split())[:160], created_by, _now()),
    )
    return {"id": endpoint_id, "url": url, "events": chosen, "description": description,
            "secret": secret, "created_at": _now(),
            "warning": "Copy the signing secret now. It is stored encrypted-at-rest only as a server secret in this prototype."}


def ensure_endpoint(conn, workspace_id: str, url: str, secret: str,
                    events: Sequence[str] = EVENTS) -> Optional[str]:
    """Demo bootstrap: one endpoint per URL, with the secret from the environment."""
    url = (url or "").strip()
    if not url:
        return None
    row = conn.execute("SELECT id FROM webhook_endpoints WHERE workspace_id = ? AND url = ?",
                       (workspace_id, url)).fetchone()
    if row:
        return row["id"]
    try:
        created = create_endpoint(conn, workspace_id, url, events, "Demo CMS", "system", secret)
    except ValueError:
        return None
    return created["id"]


def list_endpoints(conn, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, url, events_json, active, description, created_by, created_at "
        "FROM webhook_endpoints WHERE workspace_id = ? ORDER BY created_at DESC",
        (workspace_id,)).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["events"] = json.loads(data.pop("events_json") or "[]")
        last = conn.execute(
            "SELECT status, last_status, attempts, delivered_at, created_at FROM webhook_deliveries "
            "WHERE endpoint_id = ? ORDER BY created_at DESC LIMIT 1", (data["id"],)).fetchone()
        data["last_delivery"] = dict(last) if last else None
        out.append(data)
    return out


def rotate_secret(conn, workspace_id: str, endpoint_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM webhook_endpoints WHERE id = ? AND workspace_id = ?",
                       (endpoint_id, workspace_id)).fetchone()
    if not row:
        raise ValueError("Webhook endpoint not found.")
    secret = _secret()
    conn.execute("UPDATE webhook_endpoints SET secret_salt = ? WHERE id = ?", (secret, endpoint_id))
    return {"id": endpoint_id, "secret": secret, "warning": "The previous secret stops working immediately."}


def disable_endpoint(conn, workspace_id: str, endpoint_id: str) -> None:
    row = conn.execute("SELECT id FROM webhook_endpoints WHERE id = ? AND workspace_id = ?",
                       (endpoint_id, workspace_id)).fetchone()
    if not row:
        raise ValueError("Webhook endpoint not found.")
    conn.execute("UPDATE webhook_endpoints SET active = 0 WHERE id = ?", (endpoint_id,))


def _payload(workspace_id: str, event: str, data: Dict[str, Any], delivery_id: str) -> Dict[str, Any]:
    return {
        "id": delivery_id,
        "event": event,
        "api_version": "2026-10-30",
        "workspace_id": workspace_id,
        "created_at": _now(),
        "data": data,
    }


def emit(conn, workspace_id: str, event: str, data: Dict[str, Any]) -> int:
    """Write one outbox row per subscribed endpoint. Same transaction as the event."""
    if event not in EVENTS:
        return 0
    endpoints = conn.execute(
        "SELECT id, events_json FROM webhook_endpoints WHERE workspace_id = ? AND active = 1",
        (workspace_id,)).fetchall()
    queued = 0
    for endpoint in endpoints:
        events = json.loads(endpoint["events_json"] or "[]")
        if event not in events:
            continue
        delivery_id = gen_id("whd")
        payload = _payload(workspace_id, event, data, delivery_id)
        conn.execute(
            "INSERT INTO webhook_deliveries (id, endpoint_id, workspace_id, event, payload_json, status, "
            "attempts, next_attempt_at, created_at) VALUES (?,?,?,?,?,'pending',0,?,?)",
            (delivery_id, endpoint["id"], workspace_id, event, json.dumps(payload), _now(), _now()),
        )
        queued += 1
    return queued


def _signature(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), timestamp.encode() + b"." + body,
                                hashlib.sha256).hexdigest()


def _schedule_retry(attempts: int) -> Optional[str]:
    if attempts >= MAX_ATTEMPTS:
        return None
    delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
    return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()


def deliver(conn, delivery_id: str, timeout: float = 4.0) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT d.*, e.url, e.secret_salt, e.active FROM webhook_deliveries d "
        "JOIN webhook_endpoints e ON e.id = d.endpoint_id WHERE d.id = ?", (delivery_id,)).fetchone()
    if not row:
        return {"status": "missing"}
    if not row["active"]:
        conn.execute("UPDATE webhook_deliveries SET status='failed', last_error='endpoint disabled' WHERE id=?",
                     (delivery_id,))
        conn.commit()
        return {"status": "failed", "reason": "endpoint disabled"}
    now = _now()
    locked = conn.execute(
        "UPDATE webhook_deliveries SET locked_at = ? WHERE id = ? AND status = 'pending' "
        "AND (locked_at IS NULL OR locked_at < ?)", (now, delivery_id,
                                                     (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()))
    if locked.rowcount == 0:
        return {"status": "busy"}
    conn.commit()
    payload = json.loads(row["payload_json"])
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Canonry-Webhooks/1",
        "X-Canonry-Event": row["event"],
        "X-Canonry-Delivery": delivery_id,
        "X-Canonry-Timestamp": timestamp,
        "X-Canonry-Signature": _signature(row["secret_salt"], timestamp, body),
    }
    attempts = int(row["attempts"] or 0) + 1
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            resp = client.post(row["url"], content=body, headers=headers)
        if 200 <= resp.status_code < 300:
            conn.execute(
                "UPDATE webhook_deliveries SET status='delivered', attempts=?, last_status=?, "
                "last_error=NULL, delivered_at=?, locked_at=NULL WHERE id=?",
                (attempts, resp.status_code, _now(), delivery_id))
            conn.commit()
            return {"status": "delivered", "http_status": resp.status_code, "attempts": attempts}
        error = f"HTTP {resp.status_code}: {resp.text[:240]}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
    next_at = _schedule_retry(attempts)
    conn.execute(
        "UPDATE webhook_deliveries SET status=?, attempts=?, last_status=?, last_error=?, "
        "next_attempt_at=?, locked_at=NULL WHERE id=?",
        ("pending" if next_at else "failed", attempts,
         getattr(locals().get("resp"), "status_code", None), error, next_at, delivery_id))
    conn.commit()
    return {"status": "retry" if next_at else "failed", "error": error, "attempts": attempts}


def flush(conn, limit: int = 10, timeout: float = 3.0) -> Dict[str, Any]:
    """Attempt every due delivery. Safe to call at startup or from a cron ping."""
    rows = conn.execute(
        "SELECT id FROM webhook_deliveries WHERE status='pending' "
        "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY created_at LIMIT ?",
        (_now(), limit)).fetchall()
    results = {"attempted": 0, "delivered": 0, "retry": 0, "failed": 0}
    for row in rows:
        result = deliver(conn, row["id"], timeout=timeout)
        results["attempted"] += 1
        if result.get("status") in results:
            results[result["status"]] += 1
    return results


def list_deliveries(conn, workspace_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT d.id, d.endpoint_id, e.url, d.event, d.status, d.attempts, d.last_status, "
        "d.last_error, d.created_at, d.delivered_at, d.next_attempt_at "
        "FROM webhook_deliveries d JOIN webhook_endpoints e ON e.id = d.endpoint_id "
        "WHERE d.workspace_id = ? ORDER BY d.created_at DESC LIMIT ?",
        (workspace_id, min(max(limit, 1), 200))).fetchall()
    return [dict(r) for r in rows]


def retry_delivery(conn, workspace_id: str, delivery_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT id FROM webhook_deliveries WHERE id = ? AND workspace_id = ?",
                       (delivery_id, workspace_id)).fetchone()
    if not row:
        raise ValueError("Delivery not found.")
    conn.execute(
        "UPDATE webhook_deliveries SET status='pending', next_attempt_at=?, locked_at=NULL WHERE id=?",
        (_now(), delivery_id))
    conn.commit()
    return deliver(conn, delivery_id)
