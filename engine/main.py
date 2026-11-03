"""Canonry analysis engine — FastAPI web/API (doc Section 9.3).

Background job queue for the event build = FastAPI background tasks; the flow
is small documents, so checks run inline but through the same job-table seam
(check_runs row) that a Redis queue adapter replaces later.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import hashlib
import secrets
import sqlite3
import traceback
import zipfile
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import access
import api
import assets
import claims
import compliance
import contract
import webhooks
import documents
import gateway
import images
import knowledge
import pipeline
import policy
import quota
import signing
import stamping
import vision
import workflow
import db as dbmod
from db import (
    _now, audit, connect, create_session, gen_id, get_knowledge_version,
    init_schema, resolve_session,
)
from seed import seed

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]{2,}$")
ROLES = ("creator", "reviewer", "agency", "admin")
DEMO_MODE = os.environ.get("CANONRY_DEMO_MODE", "false").strip().lower() in ("1", "true", "yes")
COOKIE_SECURE = os.environ.get("CANONRY_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes") if DEMO_MODE else os.environ.get("CANONRY_COOKIE_SECURE", "true").strip().lower() in ("1", "true", "yes")
APP_ORIGINS = {origin.strip().rstrip("/").lower() for origin in os.environ.get("CANONRY_APP_ORIGINS", "http://localhost:3000").split(",") if origin.strip()}
# where /verify links point: the web app; by default the first allowed web origin
PUBLIC_WEB_URL = (os.environ.get("CANONRY_PUBLIC_WEB_URL")
                  or (os.environ.get("CANONRY_APP_ORIGINS") or "").split(",")[0].strip()
                  or "http://localhost:3000").rstrip("/")
INVITE_TTL_HOURS = 72


def pack_versions(conn, workspace_id: str) -> Dict[str, str]:
    """Pack versions in force, recorded in the signed seal (compliance module fills this)."""
    try:
        import compliance
        return compliance.enabled_pack_versions(conn, workspace_id)
    except Exception:
        return {}

app = FastAPI(title="Canonry engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=sorted(APP_ORIGINS), allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "Authorization", "X-Canon-Session"])


JSON_BODY_LIMIT = 2 * 1024 * 1024  # 200,000 characters of content, even fully \u-escaped, fit


@app.middleware("http")
async def refuse_oversized_json(request: Request, call_next):
    # a JSON body is parsed whole into memory; refuse a huge one before reading it
    # (files have their own limits on the upload routes)
    if (request.headers.get("content-type") or "").lower().startswith("application/json"):
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > JSON_BODY_LIMIT:
            return JSONResponse({"detail": {"code": "too_large",
                                            "message": "This request is larger than the 2 MB limit for JSON."}},
                                status_code=413)
    return await call_next(request)


@app.middleware("http")
async def no_store_sensitive_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/me", "/workspace", "/invitations", "/rules", "/facts", "/terms", "/submissions", "/insights", "/alerts", "/verify")):
        response.headers["Cache-Control"] = "private, no-store"
    if request.url.path in ("/login", "/join") and response.status_code < 400:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def _startup() -> None:
    quota.limits()  # a malformed CANONRY_AI_DAILY_* setting stops the boot with a clear message
    init_schema()
    if not DEMO_MODE:
        _ensure_production_workspace()
        _ensure_bootstrap_admin()
    else:
        seed()
        _seed_demo_submission()
    _ensure_integration_endpoint()
    _ensure_demo_api_key()
    _start_publisher_demo()
    _flush_outbox_on_boot()


PUBLISHER_NAME = "Demo publisher"


def _publisher_enabled() -> bool:
    setting = (os.environ.get("CANONRY_PUBLISHER_DEMO") or "").strip().lower()
    return setting in ("1", "true", "yes") if setting else DEMO_MODE


def _start_publisher_demo() -> None:
    """Mount the demo publisher (cms/app.py) at /cms on this engine, with its own
    API key and a signed webhook endpoint pointing back at this engine. One
    deployment, no extra service: the publisher still talks to Canonry only
    through the public API and verifies every webhook signature."""
    if not _publisher_enabled() or getattr(app.state, "publisher", None):
        return
    import importlib.util
    import httpx

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cms", "app.py")
    if not os.path.exists(path):
        return
    spec = importlib.util.spec_from_file_location("canonry_demo_publisher", path)
    cms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cms)  # type: ignore[union-attr]

    # the engine's own public address, for the webhook it sends to the publisher
    public = (os.environ.get("CANONRY_PUBLIC_ENGINE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    hook_url = f"{public}/cms/webhooks/canonry" if public else ""
    conn = connect(service=True)
    try:
        ws = _ws(conn)
        # a fresh key each boot (only its hash is stored); earlier ones are revoked
        conn.execute("UPDATE api_keys SET revoked_at = ? WHERE workspace_id = ? AND name = ? "
                     "AND created_by = 'system' AND revoked_at IS NULL", (_now(), ws, PUBLISHER_NAME))
        raw_key = api.create_key(conn, ws, PUBLISHER_NAME, ["check", "read"], "system")["key"]
        endpoint_id, note = None, ""
        if hook_url:
            # an endpoint left from an earlier address stops receiving
            conn.execute("UPDATE webhook_endpoints SET active = 0 WHERE workspace_id = ? AND description = ? "
                         "AND created_by = 'system' AND url <> ?", (ws, PUBLISHER_NAME, hook_url))
            row = conn.execute("SELECT id FROM webhook_endpoints WHERE workspace_id = ? AND url = ?",
                               (ws, hook_url)).fetchone()
            if row:
                endpoint_id = row["id"]
            else:
                try:
                    endpoint_id = webhooks.create_endpoint(conn, ws, hook_url, webhooks.EVENTS,
                                                           PUBLISHER_NAME, "system")["id"]
                except ValueError as exc:
                    note = f"Canonry cannot send webhooks to {hook_url}: {exc}"
        else:
            note = ("Canonry does not know its own public address, so it cannot send this publisher its "
                    "webhooks. Set CANONRY_PUBLIC_ENGINE_URL (engine/run_local.py does this for you).")
        conn.commit()
    finally:
        conn.close()

    def secret() -> str:
        # read on every webhook, so "Rotate secret" in Canonry keeps working
        if not endpoint_id:
            return ""
        c = connect(service=True)
        try:
            row = c.execute("SELECT secret_salt FROM webhook_endpoints WHERE id = ?", (endpoint_id,)).fetchone()
            return row["secret_salt"] if row else ""
        finally:
            c.close()

    cms.configure(api_key=raw_key, webhook_secret=secret,
                  db_path=os.path.join(os.path.dirname(os.path.abspath(dbmod.DB_PATH)), "cms.db"),
                  canonry_url=PUBLIC_WEB_URL, transport=httpx.ASGITransport(app=app),
                  webhooks_ready=bool(endpoint_id), note=note)
    app.state.publisher = cms
    app.add_api_route("/cms", lambda: cms.render_home("cms/"), methods=["GET"], include_in_schema=False)
    app.mount("/cms", cms.app)


def _ensure_integration_endpoint() -> None:
    """Optional demo wiring: a CMS URL and secret from the environment become one
    active webhook endpoint. Nothing is created unless both are set."""
    url = (os.environ.get("CANONRY_CMS_WEBHOOK_URL") or "").strip()
    secret = (os.environ.get("CANONRY_CMS_WEBHOOK_SECRET") or "").strip()
    if not url or not secret:
        return
    conn = connect(service=True)
    try:
        webhooks.ensure_endpoint(conn, _ws(conn), url, secret)
        conn.commit()
    finally:
        conn.close()


def _ensure_demo_api_key() -> None:
    """Optional demo wiring: a pre-agreed key on the engine and the CMS. The raw
    value lives only in deployment secrets; the database stores its hash."""
    raw = (os.environ.get("CANONRY_CMS_API_KEY") or "").strip()
    if not raw:
        return
    conn = connect(service=True)
    try:
        api.ensure_demo_key(conn, _ws(conn), os.environ.get("CANONRY_CMS_KEY_NAME", "Demo CMS"), raw)
        conn.commit()
    finally:
        conn.close()


def _flush_outbox_on_boot() -> None:
    conn = connect(service=True)
    try:
        webhooks.flush(conn, limit=10, timeout=2.0)
    finally:
        conn.close()


def webhook_tick() -> Dict[str, Any]:
    """One pass over the outbox: every delivery whose retry time has come."""
    conn = connect(service=True)
    try:
        return webhooks.flush(conn, limit=20, timeout=3.0)
    finally:
        conn.close()


async def _webhook_retry_loop(every: float) -> None:
    # retries follow their schedule even when no new product event happens
    while True:
        await asyncio.sleep(every)
        try:
            await run_in_threadpool(webhook_tick)
        except Exception:  # noqa: BLE001 - a bad receiver must never stop the loop
            traceback.print_exc()


@app.on_event("startup")
async def _start_webhook_retries() -> None:
    every = float(os.environ.get("CANONRY_WEBHOOK_RETRY_SECONDS") or 15)
    if every > 0:
        app.state.webhook_retries = asyncio.create_task(_webhook_retry_loop(every))


@app.on_event("shutdown")
async def _stop_webhook_retries() -> None:
    task = getattr(app.state, "webhook_retries", None)
    if task:
        task.cancel()


def _ensure_production_workspace() -> None:
    """Create an empty workspace for a fresh production install, never demo data."""
    conn = connect(service=True)
    try:
        if not conn.execute("SELECT 1 FROM workspaces LIMIT 1").fetchone():
            name = " ".join(os.environ.get("CANONRY_WORKSPACE_NAME", "Canonry Workspace").split())
            if not name or len(name) > 100:
                raise RuntimeError("CANONRY_WORKSPACE_NAME must be 1–100 characters.")
            conn.execute(
                "INSERT INTO workspaces (id, name, slug, created_at) VALUES (?,?,?,?)",
                (gen_id("ws"), name, "canonry", _now()),
            )
        # every built-in check cites a rule from the start (baseline rules until
        # the workspace's own rulebook is imported); the India pack is on by default
        policy.ensure_bindings(conn, _ws(conn))
        compliance.ensure_pack(conn, _ws(conn))
        conn.commit()
    finally:
        conn.close()


# The launch post from plan Section 1, so a fresh deployment opens on a real,
# already-checked example instead of an empty workspace.
DEMO_POST = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams "
             "and fully ISO 27001 certified. Plans start at just ₹999/month!")


def _seed_demo_submission() -> None:
    """First boot only: if the workspace has no submissions at all, add the demo
    launch post as Arjun and run it through the normal check pipeline."""
    conn = connect(service=True)
    try:
        if conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]:
            return
        arjun = conn.execute("SELECT * FROM users WHERE email = 'arjun@quillmark'").fetchone()
        if not arjun:
            return
        sid = gen_id("sub")
        conn.execute(
            "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
            "VALUES (?,?,?,?,?,?,'Draft',?)",
            (sid, arjun["workspace_id"], "Launch post — Pulse 2.0", "social", "ai-assisted", arjun["email"], _now()),
        )
        audit(conn, "system", "seed_demo_submission", f"{sid}: launch post (plan Section 1)")
        run_check_for_submission(conn, sid, DEMO_POST)
        # Round 3 demo assets: one PDF with real page/line findings and one social
        # image with a retired logo, an off-brand block and no alt text.
        demo_assets = (
            ("Launch one-pager — Pulse 2.0", "quillmark_pulse_onepager.pdf", "web", "in-house", ""),
            ("Social launch card — Pulse 2.0", "social_launch.png", "social", "ai-assisted", ""),
        )
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo")
        for title, filename, channel, source_type, alt in demo_assets:
            path = os.path.join(data_dir, filename)
            if not os.path.exists(path):
                continue
            with open(path, "rb") as fh:
                raw_file = fh.read()
            dsid = gen_id("sub")
            conn.execute(
                "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
                "VALUES (?,?,?,?,?,?,'Draft',?)",
                (dsid, arjun["workspace_id"], title, channel, source_type, arjun["email"], _now()),
            )
            try:
                demo_asset = assets.create_asset(conn, arjun["workspace_id"], dsid, filename, raw_file, alt, arjun["email"])
                audit(conn, "system", "seed_demo_asset", f"{dsid}: {filename}")
                run_check_for_submission(conn, dsid, demo_asset["extracted_text"], arjun["email"], asset=demo_asset)
            except (assets.UploadError, documents.DocumentError, images.ImageError):
                continue
        conn.commit()
    finally:
        conn.close()


def _ensure_bootstrap_admin() -> None:
    email = os.environ.get("CANONRY_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("CANONRY_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        raise RuntimeError("Set CANONRY_BOOTSTRAP_ADMIN_EMAIL to a valid initial administrator address "
                           "(production mode), or set CANONRY_DEMO_MODE=true for a local demo.")
    if len(password) < 12:
        raise RuntimeError("Set CANONRY_BOOTSTRAP_ADMIN_PASSWORD to at least 12 characters "
                           "(production mode), or set CANONRY_DEMO_MODE=true for a local demo.")
    conn = connect(service=True)
    try:
        existing = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        password_hash = _password_hash(password)
        if existing and existing["role"] == "admin" and existing["password_hash"]:
            return
        if existing:
            conn.execute("UPDATE users SET role='admin', password_hash=? WHERE id=?", (password_hash, existing["id"]))
            uid = existing["id"]
        else:
            uid = gen_id("usr")
            conn.execute(
                "INSERT INTO users (id, workspace_id, email, name, role, created_at, password_hash) VALUES (?,?,?,?,?,?,?)",
                (uid, _ws(conn), email, email.split("@")[0].title(), "admin", _now(), password_hash),
            )
        audit(conn, email, "bootstrap_admin", "Initial administrator provisioned from deployment environment.")
        conn.commit()
    finally:
        conn.close()


def _user(req: Request, conn=None):
    """Resolve the session with the service role, then scope the request connection
    to that user's workspace so Postgres RLS applies to every query that follows."""
    token = req.cookies.get("canonry_session") or req.headers.get("x-canon-session")
    service = connect(service=True)
    try:
        user = resolve_session(service, token)
    finally:
        service.close()
    if not user:
        raise HTTPException(401, "Sign in required")
    if conn is not None:
        dbmod.set_workspace(conn, user["workspace_id"])
    return user


def _ws(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
    return row["id"]


def _lock_submission(conn, sid: str) -> None:
    """Serialise writers on one submission: a double click or a second tab waits
    for the first request to commit, then reads the status and revision it left.
    SQLite takes the database write lock now; Postgres locks the row."""
    if dbmod.dialect() == "sqlite":
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute("UPDATE submissions SET id = id WHERE id = ?", (sid,))
    else:
        conn.execute("SELECT id FROM submissions WHERE id = ? FOR UPDATE", (sid,))


STALE_REVISION = ("This draft has changed since you opened it (in another tab or by someone else). "
                  "Reload the page to see the latest version, then try again.")


def _require_latest_revision(conn, sid: str, revision_id: str) -> None:
    latest = conn.execute(
        "SELECT id FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
    if latest and latest["id"] != revision_id:
        raise HTTPException(409, STALE_REVISION)


def _visible_sub(conn: sqlite3.Connection, user, sid: str, action: Optional[str] = None):
    """The submission, if this user may see it and (given an action) its status
    allows that action; otherwise 404 (no hint it exists) or 409 (with why)."""
    sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
    if not sub or not access.can_see_submission(user, sub):
        raise HTTPException(404, "Submission not found")
    why = workflow.blocked(sub["status"], action) if action else None
    if why:
        raise HTTPException(409, why)
    return sub


# ---- auth -------------------------------------------------------------------

class LoginIn(BaseModel):
    email: str
    password: Optional[str] = None


@app.post("/login")
def login(body: LoginIn, req: Request):
    _require_same_origin(req)
    conn = connect(service=True)
    try:
        email = body.email.strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise HTTPException(422, "Enter a valid email address.")
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if DEMO_MODE:
            # The password-free path is limited to local judge/demo mode.
            if not user:
                uid = gen_id("usr")
                conn.execute(
                    "INSERT INTO users (id, workspace_id, email, name, role, created_at) VALUES (?,?,?,?,?,?)",
                    (uid, _ws(conn), email, email.split("@")[0].title(), "creator", _now()),
                )
                user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        elif (not body.password or not 12 <= len(body.password) <= 256 or not user
              or not user["password_hash"] or not _password_matches(body.password, user["password_hash"])):
            raise HTTPException(401, "Email or password is incorrect.")
        token = create_session(conn, user["id"])
        resp = JSONResponse(_public_user(user))
        _set_session_cookie(resp, token)
        audit(conn, user["email"], "login", "demo login" if DEMO_MODE else "password login")
        conn.commit()
        return resp
    finally:
        conn.close()


def _set_session_cookie(resp: JSONResponse, token: str) -> None:
    # A session cookie on purpose: closing the browser signs the person out, so
    # the next visit starts at the welcome screen instead of mid-flow.
    resp.set_cookie("canonry_session", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", path="/")


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310_000)
        return secrets.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _require_same_origin(req: Request) -> None:
    origin = req.headers.get("origin")
    if origin:
        if origin.rstrip("/").lower() not in APP_ORIGINS:
            raise HTTPException(403, "Cross-origin requests are not allowed.")
        if req.headers.get("referer"):
            referer_origin = re.match(r"^https?://[^/]+", req.headers["referer"], re.IGNORECASE)
            if referer_origin and referer_origin.group(0).rstrip("/").lower() != origin.rstrip("/").lower():
                raise HTTPException(403, "Cross-origin requests are not allowed.")
        return
    referer = req.headers.get("referer")
    if referer:
        referer_origin = re.match(r"^https?://[^/]+", referer, re.IGNORECASE)
        if referer_origin and referer_origin.group(0).rstrip("/").lower() in APP_ORIGINS:
            return
    if not DEMO_MODE and req.method not in ("GET", "HEAD", "OPTIONS") and req.url.hostname not in ("localhost", "127.0.0.1", "testserver"):
        raise HTTPException(403, "A same-origin request is required.")


def _clean_name(name: Any) -> str:
    name = " ".join(str(name or "").split())
    if not 2 <= len(name) <= 40:
        raise HTTPException(422, "Name must be 2–40 characters.")
    return name


def _clean_role(role: Any) -> str:
    if role not in ROLES:
        raise HTTPException(422, "Role must be creator, reviewer, agency or admin.")
    return role


def _public_user(user) -> Dict[str, Any]:
    return {"id": user["id"], "name": user["name"], "role": user["role"], "email": user["email"]}


@app.post("/join")
def join(body: Dict[str, Any], req: Request):
    """Demo mode permits self-selected personas. Production requires an invitation."""
    _require_same_origin(req)
    name = _clean_name(body.get("name"))
    password = str(body.get("password") or "")
    if DEMO_MODE:
        email = str(body.get("email") or "").strip().lower()
        if not email:
            email = f"{gen_id('usr')}@guest.canonry"
        role = _clean_role(body.get("role", "creator"))
    else:
        if not 12 <= len(password) <= 256:
            raise HTTPException(422, "Password must be 12–256 characters.")
        email = str(body.get("email") or "").strip().lower()
        role = "creator"
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    invitation = str(body.get("invitation") or "").strip()
    conn = connect(service=True)
    try:
        if not DEMO_MODE:
            conn.execute("BEGIN IMMEDIATE")
            if not invitation:
                raise HTTPException(403, "A valid workspace invitation is required.")
            invite_hash = hashlib.sha256(invitation.encode("utf-8")).hexdigest()
            inv = conn.execute("SELECT * FROM invitations WHERE token_hash=?", (invite_hash,)).fetchone()
            now = _now()
            if not inv or inv["consumed_at"] or inv["expires_at"] <= now or inv["email"].lower() != email:
                conn.rollback()
                raise HTTPException(403, "This invitation is invalid, expired, or for a different email.")
            consumed = conn.execute(
                "UPDATE invitations SET consumed_at=? WHERE token_hash=? AND consumed_at IS NULL AND expires_at>? AND lower(email)=?",
                (now, invite_hash, now, email),
            )
            if consumed.rowcount != 1:
                conn.rollback()
                raise HTTPException(403, "This invitation has already been used or expired.")
            role = _clean_role(inv["role"])
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            if not DEMO_MODE:
                conn.rollback()
            raise HTTPException(409, "An account already exists for this email. Sign in instead.")
        uid = gen_id("usr")
        password_hash = _password_hash(password) if password else None
        conn.execute(
            "INSERT INTO users (id, workspace_id, email, name, role, created_at, password_hash) VALUES (?,?,?,?,?,?,?)",
            (uid, _ws(conn), email, name, role, _now(), password_hash),
        )
        audit(conn, email, "join", f"{name} joined as {role}" + (" via invitation" if not DEMO_MODE else " (demo mode)"))
        token = create_session(conn, uid)
        resp = JSONResponse(_public_user(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()))
        _set_session_cookie(resp, token)
        conn.commit()
        return resp
    finally:
        conn.close()


@app.patch("/me")
def update_me(req: Request, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        name = _clean_name(body["name"]) if "name" in body else user["name"]
        if "role" in body and not DEMO_MODE:
            raise HTTPException(403, "Roles are assigned through workspace invitations.")
        role = _clean_role(body["role"]) if "role" in body else user["role"]
        conn.execute("UPDATE users SET name = ?, role = ? WHERE id = ?", (name, role, user["id"]))
        changes = []
        if role != user["role"]:
            changes.append(f"{user['role']} -> {role}")
        if name != user["name"]:
            changes.append(f"renamed {user['name']} -> {name}")
        if changes:
            audit(conn, user["email"], "profile_change", "; ".join(changes))
        conn.commit()
        # the same shape as /me: without the email, the page forgot whose drafts were whose after a role switch
        return {"id": user["id"], "name": name, "role": role, "email": user["email"]}
    finally:
        conn.close()


@app.post("/logout")
def logout(req: Request):
    _require_same_origin(req)
    token = req.cookies.get("canonry_session") or req.headers.get("x-canon-session")
    conn = connect(service=True)
    try:
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            conn.execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
            conn.commit()
    finally:
        conn.close()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("canonry_session")
    return resp


@app.get("/me")
def me(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        return _public_user(user)
    finally:
        conn.close()


@app.get("/workspace")
def workspace(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        ws = _ws(conn)
        if user["role"] == "admin":
            users = [dict(u) for u in conn.execute("SELECT id, name, email, role FROM users").fetchall()]
        else:
            users = [_public_user(user)]
        rules = conn.execute("SELECT COUNT(*) c FROM rules WHERE status='approved'").fetchone()["c"]
        facts = conn.execute("SELECT COUNT(*) c FROM facts WHERE confidential=0").fetchone()["c"]
        terms = conn.execute("SELECT COUNT(*) c FROM terms").fetchone()["c"]
        vague = [dict(r) for r in conn.execute(
            "SELECT id, statement, vague_flag FROM rules WHERE vague_flag IS NOT NULL").fetchall()]
        return {
            "workspace": ws, "rules": rules, "facts": facts, "terms": terms,
            "users": users, "vague_rules": vague,
            "knowledge_version": get_knowledge_version(conn),
            "me": _public_user(user),
        }
    finally:
        conn.close()


# ---- knowledge base ----------------------------------------------------------

def _kb(fn, *args):
    """Run a knowledge write and turn its refusals into HTTP errors."""
    try:
        return fn(*args)
    except knowledge.KBError as e:
        raise HTTPException(e.status, e.detail)


def _kb_fields(body: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in body.items() if k not in ("reason", "expected_version", "version")}


@app.post("/kb/{kind}")
def kb_create(req: Request, kind: str, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        return _kb(knowledge.create, conn, _ws(conn), kind, _kb_fields(body), user, body.get("reason"))
    finally:
        conn.close()


@app.put("/kb/{kind}/{entity_id}")
def kb_update(req: Request, kind: str, entity_id: str, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        return _kb(knowledge.update, conn, _ws(conn), kind, entity_id, _kb_fields(body),
                   body.get("expected_version"), user, body.get("reason"))
    finally:
        conn.close()


@app.post("/kb/{kind}/{entity_id}/retire")
def kb_retire(req: Request, kind: str, entity_id: str, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        return _kb(knowledge.retire, conn, _ws(conn), kind, entity_id, body.get("expected_version"),
                   user, body.get("reason"))
    finally:
        conn.close()


@app.post("/kb/{kind}/{entity_id}/restore")
def kb_restore(req: Request, kind: str, entity_id: str, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        return _kb(knowledge.restore, conn, _ws(conn), kind, entity_id, body.get("version"),
                   body.get("expected_version"), user, body.get("reason"))
    finally:
        conn.close()


@app.get("/kb/stale-approvals")
def kb_stale_approvals(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        return {"items": access.filter_visible(conn, user, knowledge.stale_approvals(conn, _ws(conn)))}
    finally:
        conn.close()


@app.get("/kb/{kind}/{entity_id}/history")
def kb_history(req: Request, kind: str, entity_id: str):
    conn = connect()
    try:
        user = _user(req, conn)
        if kind not in knowledge.ENTITIES:
            raise HTTPException(404, "Unknown knowledge type.")
        versions = knowledge.history(conn, _ws(conn), knowledge.ENTITIES[kind], entity_id)
        if kind == "facts":
            for v in versions:
                v["snapshot"] = access.redact_fact(v["snapshot"], user)
        return {"versions": versions}
    finally:
        conn.close()


@app.get("/invitations/{token}")
def invitation_info(token: str):
    if DEMO_MODE:
        raise HTTPException(404, "Invitation not found.")
    if len(token) > 256:
        raise HTTPException(404, "Invitation not found.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = connect()
    try:
        inv = conn.execute("SELECT email, role, expires_at, consumed_at FROM invitations WHERE token_hash=?", (token_hash,)).fetchone()
        if not inv or inv["consumed_at"] or inv["expires_at"] <= _now():
            raise HTTPException(404, "Invitation is invalid, expired, or already used.")
        return {"email": inv["email"], "role": inv["role"], "expires_at": inv["expires_at"]}
    finally:
        conn.close()


@app.post("/invitations")
def create_invitation(req: Request, body: Dict[str, Any]):
    if DEMO_MODE:
        raise HTTPException(409, "Invitations are only used when demo mode is disabled.")
    _require_same_origin(req)
    email = str(body.get("email") or "").strip().lower()
    role = str(body.get("role") or "creator")
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if role not in ROLES:
        raise HTTPException(422, "Role must be creator, reviewer, agency or admin.")
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] != "admin":
            raise HTTPException(403, "Only workspace admins can invite members.")
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "An account already exists for this email.")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO invitations (token_hash,email,role,created_by,created_at,expires_at) VALUES (?,?,?,?,?,?)",
            (token_hash, email, role, user["email"], now.isoformat(), (now + timedelta(hours=INVITE_TTL_HOURS)).isoformat()),
        )
        audit(conn, user["email"], "invite_member", f"{email} invited as {role}")
        conn.commit()
        return {"email": email, "role": role, "invitation": token, "expires_at": (now + timedelta(hours=INVITE_TTL_HOURS)).isoformat()}
    finally:
        conn.close()


@app.post("/rules/import")
def rules_import(req: Request, body: Dict[str, Any]):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/owners import guidelines")
        ws = req.state.ws = _ws(conn)
        lines = (body.get("csv") or "").strip().splitlines()
        if not lines:
            raise HTTPException(400, "Paste CSV with header: id,category,statement,do_example,dont_example,severity")
        # quoted fields may contain commas ("Ink #101828, Teal #0E7C7B")
        rows = list(csv.DictReader(io.StringIO("\n".join(lines))))
        added, updated, flagged, skipped = 0, 0, [], []
        for r in rows:
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("statement"):
                continue
            fields = {"category": r.get("category") or "General", "statement": r["statement"],
                      "do_example": r.get("do_example"), "dont_example": r.get("dont_example"),
                      "severity": r.get("severity") or "medium", "status": "approved"}
            # every row goes through the versioned write path: new rules are created,
            # existing ones get a new version; nothing is overwritten in place
            try:
                cur = knowledge.snapshot(conn, ws, "rule", r["id"]) if r.get("id") else None
                if cur:
                    res = knowledge.update(conn, ws, "rules", r["id"], fields, cur["version"], user, "CSV import")
                    updated += 1
                else:
                    res = knowledge.create(conn, ws, "rules", {**fields, "id": r.get("id")}, user, "CSV import")
                    added += 1
            except knowledge.KBError as e:
                skipped.append({"id": r.get("id"), "reason": e.detail})
                continue
            ent = res["entity"]
            if ent["vague_flag"]:
                flagged.append({"id": ent["id"], "statement": ent["statement"], "flag": ent["vague_flag"],
                                "rewrite_suggestion": rewrite_suggestion(ent["statement"], ent["vague_flag"])})
        audit(conn, user["email"], "import_rules",
              f"imported {added} new, {updated} updated, {len(flagged)} flagged, {len(skipped)} skipped")
        conn.commit()
        return {"added": added, "updated": updated, "flagged": flagged, "skipped": skipped}
    finally:
        conn.close()


def rewrite_suggestion(stmt: str, flag: str) -> str:
    if flag == "vague_contradictory":
        return "Split the rule: one requirement per rule, then approve each separately."
    if flag == "vague_duplicate":
        return "Merge with the existing rule on this topic; keep one canonical statement."
    return "Make it checkable: state one requirement plus one do and one don't example."


def _document_paragraphs(filename: str, data: bytes) -> List[tuple[str, str]]:
    """Return (text, style) paragraphs from Markdown/text or DOCX without executing content."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix in ("md", "markdown", "txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "Document text must be UTF-8.") from exc
        out: List[tuple[str, str]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if match:
                out.append((match.group(2).strip(), f"Heading{len(match.group(1))}"))
            else:
                line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
                line = re.sub(r"`([^`]+)`", r"\1", line)
                line = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
                line = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)", lambda m: m.group(1) or m.group(2), line)
                out.append((line, ""))
        return out
    if suffix != "docx":
        raise HTTPException(415, "Choose a Markdown (.md), text (.txt), or Word (.docx) document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 15 * 1024 * 1024:
                raise HTTPException(413, "DOCX document text exceeds the 15 MB extraction limit.")
            if info.file_size > 0 and info.file_size / max(info.compress_size, 1) > 100:
                raise HTTPException(413, "DOCX document has an unsafe compression ratio.")
            xml = archive.read(info)
        root = ElementTree.fromstring(xml)
    except (KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise HTTPException(422, "This file is not a readable DOCX document.") from exc
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    out = []
    for paragraph in root.findall(".//w:body/w:p", ns):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns)).strip()
        if not text:
            continue
        style = paragraph.find("./w:pPr/w:pStyle", ns)
        style_name = style.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "") if style is not None else ""
        out.append((text, style_name))
    return out


async def _read_limited_body(req: Request, limit: int, label: str = "5 MB") -> bytes:
    length = req.headers.get("content-length")
    if length:
        try:
            if int(length) > limit:
                raise HTTPException(413, f"This file exceeds the {label} limit.")
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length header.") from exc
    chunks = []
    total = 0
    async for chunk in req.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"This file exceeds the {label} limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/rules/import-document")
async def preview_rule_document(req: Request, filename: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers and admins can import guidelines.")
    finally:
        conn.close()
    data = await _read_limited_body(req, 5 * 1024 * 1024)
    return _parse_uploaded_document(filename, data)


def _parse_uploaded_document(filename: str, data: bytes) -> Dict[str, Any]:
    if not isinstance(filename, str) or len(filename) > 200:
        raise HTTPException(422, "Filename is too long.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Document exceeds the 5 MB import limit.")
    paragraphs = _document_paragraphs(filename, data)
    proposals = []
    category = "Imported guideline"
    ignored = 0
    for text, style in paragraphs:
        if style.lower().startswith("heading") or style.lower().startswith("title") or text.startswith("# "):
            category = re.sub(r"\s+", " ", text).strip()[:80] or category
            continue
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 10:
            ignored += 1
            continue
        if len(proposals) >= 150:
            ignored += 1
            continue
        proposals.append({"category": category, "statement": text[:2000], "severity": "medium", "status": "draft"})
    return {"proposals": proposals, "ignored": ignored, "source": filename,
            "message": "Review and edit these draft suggestions. Nothing is approved until an admin changes its status."}


@app.post("/rules/import-drafts")
def import_rule_drafts(req: Request, body: Dict[str, Any]):
    _require_same_origin(req)
    proposals = body.get("proposals")
    if not isinstance(proposals, list) or not 1 <= len(proposals) <= 150:
        raise HTTPException(422, "Choose between 1 and 150 reviewed rule suggestions.")
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers and admins can import guidelines.")
        ws = _ws(conn)
        validated = []
        for item in proposals:
            if not isinstance(item, dict):
                raise HTTPException(422, "Each suggestion must be a rule object.")
            fields = {"category": item.get("category"), "statement": item.get("statement"),
                      "do_example": item.get("do_example"), "dont_example": item.get("dont_example"),
                      "severity": item.get("severity", "medium"), "status": "draft"}
            try:
                knowledge._values(conn, ws, "rule", fields, None)
            except knowledge.KBError as exc:
                raise HTTPException(exc.status, exc.detail) from exc
            validated.append(fields)
        created = []
        for fields in validated:
            try:
                result = knowledge.create(conn, ws, "rules", fields, user, "Imported document; requires owner approval.")
            except knowledge.KBError as exc:
                raise HTTPException(exc.status, exc.detail) from exc
            created.append(result["entity"])
        audit(conn, user["email"], "import_rule_drafts", f"created {len(created)} draft rules from reviewed document suggestions")
        conn.commit()
        return {"created": created, "count": len(created)}
    finally:
        conn.close()


@app.get("/rules")
def get_rules(req: Request):
    conn = connect()
    try:
        _user(req, conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM rules ORDER BY id").fetchall()]
        return {"rules": rows}
    finally:
        conn.close()


def _rule_impact(conn: sqlite3.Connection, ws: str, dont: str) -> List[Dict[str, Any]]:
    """Approved content whose latest revision contains a word from the rule's
    don't-example (the phrase a draft must not ship)."""
    impacts: List[Dict[str, Any]] = []
    # words the *dont- example* shares with approved content
    banned_tokens = [w for w in (dont or "").replace(",", " ").split() if len(w) > 4]
    approved = conn.execute(
        "SELECT s.id, s.title, s.status, v.content FROM submissions s JOIN revisions v ON v.submission_id = s.id "
        "WHERE s.workspace_id=? AND s.status IN ('Approved','Signed','Exempt-approved') "
        "AND v.revision_no = (SELECT MAX(revision_no) FROM revisions WHERE submission_id = s.id) "
        "ORDER BY s.title",
        (ws,),
    ).fetchall()
    seen = set()
    for a in approved:
        for tok in banned_tokens:
            if tok and tok in a["content"] and a["id"] not in seen:
                seen.add(a["id"])
                impacts.append({"submission_id": a["id"], "title": a["title"], "status": a["status"],
                                "because": f"contains \"{tok}\" (from the don't-example)"})
                break
    return impacts


@app.post("/rules/{rule_id}/preview-change")
def preview_rule_change(req: Request, rule_id: str, body: Dict[str, Any]):
    """Rule tests & change preview (doc 5.4): which examples and past approved
    content would fail if this edit goes live. The body may carry the *proposed*
    statement/do/don't values, so a rule owner sees the impact of an unsaved
    edit — what would newly break, and what would stop being flagged."""
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in knowledge.EDITORS:
            raise HTTPException(403, "Only reviewers and admins change rules.")
        ws = _ws(conn)
        rule = conn.execute("SELECT * FROM rules WHERE id=? AND workspace_id=?", (rule_id, ws)).fetchone()
        if not rule:
            raise HTTPException(404, "Rule not found")
        dont = body["dont_example"] if "dont_example" in body else rule["dont_example"]
        do = body["do_example"] if "do_example" in body else rule["do_example"]
        current = _rule_impact(conn, ws, rule["dont_example"] or "")
        proposed = _rule_impact(conn, ws, dont or "")
        current_ids = {i["submission_id"] for i in current}
        proposed_ids = {i["submission_id"] for i in proposed}
        new_breakages = [i for i in proposed if i["submission_id"] not in current_ids]
        resolved = [i for i in current if i["submission_id"] not in proposed_ids]
        return {"rule": rule_id, "new_examples_would_be_tests": bool(do or dont),
                "proposed": {"statement": body.get("statement") or rule["statement"],
                             "do_example": do, "dont_example": dont},
                "impacted_approved_content": proposed, "impacted_count": len(proposed),
                "new_breakages": new_breakages, "resolved": resolved,
                "impacted": {"before": len(current), "after": len(proposed),
                             "new_breakages": len(new_breakages), "resolved": len(resolved)}}
    finally:
        conn.close()


@app.get("/facts")
def get_facts(req: Request, hashes: Optional[str] = None):
    conn = connect()
    try:
        user = _user(req, conn)
        ws = _ws(conn)
        rows = conn.execute("SELECT * FROM facts WHERE workspace_id=? ORDER BY id", (ws,)).fetchall()
        out = []
        for r in rows:
            d = access.redact_fact(dict(r), user)
            d["active"] = claims._fact_active(r)
            out.append(d)
        return {"facts": out}
    finally:
        conn.close()


@app.get("/terms")
def get_terms(req: Request):
    conn = connect()
    try:
        _user(req, conn)
        return {"terms": [dict(t) for t in conn.execute("SELECT * FROM terms ORDER BY id").fetchall()]}
    finally:
        conn.close()


# ---- submissions & the check ---------------------------------------------------

# where content is published; drives routing and channel rules (e.g. social word limits)
CHANNELS = ("social", "web", "blog", "email", "sales")
# a long brochure is ~20,000 characters; far beyond that is a paste accident
MAX_DRAFT_CHARS = 100_000


class SubmitIn(BaseModel):
    title: str
    channel: str
    source_type: str
    content: str


@app.post("/submissions")
def submit(req: Request, body: SubmitIn):
    _require_same_origin(req)
    if not body.content.strip():
        raise HTTPException(422, "Write something to check: the draft is empty.")
    if len(body.content) > MAX_DRAFT_CHARS:
        raise HTTPException(422, f"This draft is too long to check at once ({len(body.content):,} characters; "
                                 f"the limit is {MAX_DRAFT_CHARS:,}). Split it into smaller pieces.")
    title = " ".join(body.title.split())[:240]
    if not title:
        raise HTTPException(422, "Give the draft a title.")
    source_type = body.source_type.strip()[:40] or "in-house"
    if body.channel not in CHANNELS:
        raise HTTPException(422, f"Channel must be one of: {', '.join(CHANNELS)}.")
    conn = connect()
    try:
        user = _user(req, conn)
        sid = gen_id("sub")
        conn.execute(
            "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
            "VALUES (?,?,?,?,?,?,'Draft',?)",
            (sid, _ws(conn), title, body.channel, source_type, user["email"], _now()),
        )
        audit(conn, user["email"], "submit_content", f"{sid}: {title}")
        result = run_check_for_submission(conn, sid, body.content, user["email"])
        resp = {"submission_id": sid, "revision_id": result["revision_id"], **{
            k: v for k, v in result.items() if k != "revision_id"}}
        conn.commit()
        return resp
    finally:
        conn.close()


def _disposition(kind: str, filename: str) -> str:
    """Content-Disposition that survives any file name: an ASCII fallback plus
    the exact UTF-8 name (RFC 5987)."""
    from urllib.parse import quote
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", filename) or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _revision_asset(rev: sqlite3.Row) -> Optional[Dict[str, Any]]:
    """The uploaded file behind a revision, so a re-check keeps it (and its
    page/line or image locations) instead of turning it into plain text."""
    keys = rev.keys()
    if "asset_id" not in keys or not rev["asset_id"]:
        return None
    try:
        locator_map = json.loads(rev["locator_map_json"] or "[]")
    except (TypeError, ValueError):
        locator_map = []
    return {"id": rev["asset_id"], "source_kind": rev["source_kind"] or "text", "locator_map": locator_map}


def run_check_for_submission(conn: sqlite3.Connection, sid: str, content: str,
                             actor: Optional[str] = None, reuse_ai_from: Optional[str] = None,
                             asset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rev_no = conn.execute("SELECT COALESCE(MAX(revision_no),0)+1 AS n FROM revisions WHERE submission_id=?", (sid,)).fetchone()["n"]
    rid = gen_id("rev")
    if asset:
        conn.execute(
            "INSERT INTO revisions (id, submission_id, content, revision_no, created_at, asset_id, source_kind, locator_map_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (rid, sid, content, rev_no, _now(), asset["id"], asset["source_kind"], json.dumps(asset["locator_map"])),
        )
    else:
        conn.execute(
            "INSERT INTO revisions (id, submission_id, content, revision_no, created_at, source_kind) VALUES (?,?,?,?,?,'text')",
            (rid, sid, content, rev_no, _now()),
        )
    conn.execute("UPDATE submissions SET status = CASE WHEN status='Draft' THEN 'Checked' ELSE status END WHERE id=?", (sid,))
    result = pipeline.run_check(conn, rid, actor, reuse_ai_from)
    result["revision_id"] = rid
    # `checked` is a product event, written in the same transaction as the run;
    # the checked response is never blocked on a slow receiver.
    ws_row = conn.execute("SELECT workspace_id, title, status FROM submissions WHERE id = ?", (sid,)).fetchone()
    if ws_row:
        latest_poc = conn.execute(
            "SELECT id FROM proof_of_compliance WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
        webhooks.emit(conn, ws_row["workspace_id"], "checked", {
            "submission_id": sid, "title": ws_row["title"], "status": ws_row["status"],
            "revision_id": rid, "revision_no": rev_no,
            "findings": len(result.get("findings", [])),
            "ai_pending": bool(result.get("ai_pending")),
            "poc_id": latest_poc["id"] if latest_poc else None,
        })
        try:
            webhooks.flush(conn, limit=2, timeout=2.5)
        except Exception:
            pass  # a receiver outage must never fail a check
    return result


@app.post("/submissions/upload")
async def upload_submission(req: Request, title: str, channel: str, source_type: str,
                            filename: str, alt_text: str = ""):
    """Upload a PDF/DOCX/PNG/JPEG as a new revision. The body is the raw file;
    metadata travels in query parameters, so the engine needs no multipart parser."""
    _require_same_origin(req)
    title = " ".join((title or "").split())
    if not title:
        raise HTTPException(422, "Give the upload a title.")
    if channel not in CHANNELS:
        raise HTTPException(422, f"Channel must be one of: {', '.join(CHANNELS)}.")
    data = await _read_limited_body(req, assets.MAX_PDF, "10 MB")

    def work():
        conn = connect()
        try:
            user = _user(req, conn)
            ws = _ws(conn)
            sid = gen_id("sub")
            conn.execute(
                "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
                "VALUES (?,?,?,?,?,?,'Draft',?)",
                (sid, ws, title[:240], channel, source_type[:40] or "in-house", user["email"], _now()),
            )
            try:
                asset = assets.create_asset(conn, ws, sid, filename, data, alt_text, user["email"])
            except assets.UploadError as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            except documents.DocumentError as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            except images.ImageError as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            audit(conn, user["email"], "upload_content", f"{sid}: {asset['filename']} ({asset['kind']})")
            result = run_check_for_submission(conn, sid, asset["extracted_text"], user["email"], asset=asset)
            conn.commit()
            return {"submission_id": sid, "revision_id": result["revision_id"], "asset": {
                k: asset[k] for k in ("id", "kind", "filename", "size_bytes", "width", "height", "page_count")},
                **{k: v for k, v in result.items() if k != "revision_id"}}
        finally:
            conn.close()

    # OCR and logo matching are CPU-bound: run them off the event loop
    return await run_in_threadpool(work)


@app.post("/submissions/{sid}/upload")
async def upload_new_version(req: Request, sid: str, filename: str, alt_text: Optional[str] = None):
    """A corrected file becomes the next revision of the same submission, so its
    history, decisions and review stay together. An image keeps its alt text
    unless a new one is given."""
    _require_same_origin(req)
    data = await _read_limited_body(req, assets.MAX_PDF, "10 MB")

    def work():
        conn = connect()
        try:
            user = _user(req, conn)
            sub = _visible_sub(conn, user, sid, "edit")
            latest = conn.execute(
                "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
            previous = assets.get_asset(conn, latest["asset_id"]) if latest and "asset_id" in latest.keys() \
                and latest["asset_id"] else None
            alt = alt_text if alt_text is not None else (previous or {}).get("alt_text")
            try:
                asset = assets.create_asset(conn, sub["workspace_id"], sid, filename, data, alt, user["email"])
            except (assets.UploadError, documents.DocumentError, images.ImageError) as exc:
                raise HTTPException(exc.status, str(exc)) from exc
            audit(conn, user["email"], "upload_new_version", f"{sid}: {asset['filename']} ({asset['kind']})")
            result = run_check_for_submission(conn, sid, asset["extracted_text"], user["email"], asset=asset)
            conn.commit()
            return {"submission_id": sid, "revision_id": result["revision_id"], "asset": {
                k: asset[k] for k in ("id", "kind", "filename", "size_bytes", "width", "height", "page_count")},
                **{k: v for k, v in result.items() if k != "revision_id"}}
        finally:
            conn.close()

    # OCR and logo matching are CPU-bound: run them off the event loop
    return await run_in_threadpool(work)


@app.get("/submissions")
def list_submissions(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        rows = conn.execute(
            "SELECT s.*, (SELECT content FROM revisions WHERE submission_id = s.id ORDER BY revision_no DESC LIMIT 1) "
            "content, (SELECT COUNT(*) FROM findings f WHERE f.revision_id = "
            "(SELECT id FROM revisions WHERE submission_id = s.id ORDER BY revision_no DESC LIMIT 1) "
            "AND f.status='open') open_findings, "
            "(SELECT signature FROM proof_of_compliance WHERE revision_id = (SELECT id FROM revisions "
            "WHERE submission_id = s.id ORDER BY revision_no DESC LIMIT 1)) poc_sig "
            "FROM submissions s ORDER BY s.created_at DESC").fetchall()
        visible = [dict(r) for r in rows if access.can_see_submission(user, r)]
        # the latest reviewer verdict, so a writer sees on their list what was decided and why
        for sub in visible:
            last = conn.execute(
                "SELECT a.action, a.reason, a.at, COALESCE(u.name, a.reviewer) AS by_name FROM approvals a "
                "LEFT JOIN users u ON u.email = a.reviewer WHERE a.submission_id = ? "
                "AND a.action IN ('approve', 'request_changes', 'exempt_approve') ORDER BY a.at DESC LIMIT 1",
                (sub["id"],)).fetchone()
            sub["last_review"] = dict(last) if last else None
        return {"submissions": visible}
    finally:
        conn.close()


@app.get("/submissions/{sid}")
def get_submission(req: Request, sid: str):
    conn = connect()
    try:
        user = _user(req, conn)
        sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
        if not sub or not access.can_see_submission(user, sub):
            raise HTTPException(404, "Submission not found")
        revs = [dict(r) for r in conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no", (sid,)).fetchall()]
        latest = revs[-1] if revs else None
        findings = [dict(f) for f in conn.execute(
            "SELECT * FROM findings WHERE revision_id = ? ORDER BY span_start", (latest["id"] if latest else "",)).fetchall()]
        for f in findings:
            f["citations"] = json.loads(f["citations_json"])
            del f["citations_json"]
            f["suggestion"] = json.loads(f["suggestion_json"]) if f["suggestion_json"] else None
            del f["suggestion_json"]
            f["provenance"] = json.loads(f["provenance_json"])
            del f["provenance_json"]
            f["locator"] = json.loads(f["locator_json"]) if f.get("locator_json") else None
            f["location_key"] = f.get("location_key") or None
            f.pop("locator_json", None)
            for c in f["citations"]:
                entity = {"fact": "fact", "rule": "rule", "pack": "rule", "term": "term"}.get(c["type"])
                if not entity:
                    continue
                ws_id = sub["workspace_id"]
                # show the version the finding was checked against; fall back to the
                # current row for findings recorded before versions were pinned
                row = (knowledge.snapshot_at(conn, ws_id, entity, str(c["id"]), c["version"]) if c.get("version")
                       else None) or knowledge.snapshot(conn, ws_id, entity, str(c["id"]))
                if not row:
                    continue
                c["current_version"] = knowledge.current_version(conn, ws_id, entity, str(c["id"]))
                if entity == "fact":
                    row = access.redact_fact(row, user)
                    c["excerpt"], c["owner"], c["valid_to"] = row["text"], row["owner"], row["valid_to"]
                    c["confidential"] = row.get("confidential", 0)
                elif entity == "term":
                    if row.get("preferred"):
                        c["excerpt"] = "approved term: " + row["preferred"]
                else:  # rule, or an India-pack rule
                    c["excerpt"] = row["statement"]
        # the whole trail: each resolve creates a new revision, so decisions sit on
        # earlier revisions; showing only the latest one's would always be empty
        decisions = [dict(d) for d in conn.execute(
            "SELECT d.*, u.name AS by_name FROM decisions d JOIN revisions r ON r.id = d.revision_id "
            "LEFT JOIN users u ON u.email = d.by_user WHERE r.submission_id = ? ORDER BY d.at", (sid,)).fetchall()]
        approvals = [dict(a) for a in conn.execute(
            "SELECT a.*, u.name AS reviewer_name FROM approvals a LEFT JOIN users u ON u.email = a.reviewer "
            "WHERE a.submission_id = ? ORDER BY a.at", (sid,)).fetchall()]
        asset = None
        if latest and latest.get("asset_id"):
            asset = assets.get_asset(conn, latest["asset_id"])
            if asset:
                asset = {k: asset.get(k) for k in ("id", "kind", "filename", "mime", "size_bytes",
                                                   "width", "height", "page_count", "alt_text", "sha256")}
        poc = conn.execute("SELECT id, created_at, content_kind, asset_id FROM proof_of_compliance "
                           "WHERE submission_id=? ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
        # latest check run on the latest revision, so the UI can say when AI checks are still pending
        check = conn.execute(
            "SELECT status, started_at, finished_at, ai_calls, discarded, knowledge_version, ai_reason, profile_json, "
            "vision_json FROM check_runs WHERE revision_id = ? ORDER BY started_at DESC LIMIT 1",
            (latest["id"] if latest else "",)).fetchone()
        if check:
            check = dict(check)
            try:  # what the content was understood to be (understand.profile); None on older runs
                check["profile"] = json.loads(check.pop("profile_json") or "null")
            except (TypeError, ValueError):
                check["profile"] = None
            try:  # what Canonry sees in an image (vision.py); None when no reading was made
                check["vision"] = json.loads(check.pop("vision_json") or "null")
            except (TypeError, ValueError):
                check["vision"] = None
        return {"submission": dict(sub), "revisions": revs, "latest_revision": latest,
                "findings": findings, "decisions": decisions, "approvals": approvals,
                "asset": asset, "poc": dict(poc) if poc else None,
                "check": dict(check) if check else None, "me": _public_user(user),
                "allowed": workflow.allowed(sub["status"]),
                "ai_allowance": quota.usage(conn, sub["workspace_id"], user["email"])}
    finally:
        conn.close()


class ResolveIn(BaseModel):
    revision_id: str
    finding_id: str
    action: str  # accept | edit | dispute
    replacement: Optional[str] = None
    reason: Optional[str] = None


RESOLVE_ACTIONS = {"accept": "accepted", "edit": "edited", "dispute": "disputed"}


@app.post("/submissions/{sid}/resolve")
def resolve_finding(req: Request, sid: str, body: ResolveIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        if body.action not in RESOLVE_ACTIONS:
            raise HTTPException(422, "Action must be accept, edit or dispute.")
        if body.action == "edit" and not (body.replacement or "").strip():
            raise HTTPException(422, "An edit needs the replacement text; use accept to take the suggested fix.")
        _lock_submission(conn, sid)  # a double click or a second tab waits, then sees the new revision
        _visible_sub(conn, user, sid, "edit")
        rev = conn.execute("SELECT * FROM revisions WHERE id=? AND submission_id=?", (body.revision_id, sid)).fetchone()
        f = conn.execute("SELECT * FROM findings WHERE id=? AND revision_id=?", (body.finding_id, body.revision_id)).fetchone()
        if not f or not rev:
            raise HTTPException(404, "That finding is not on this submission. Reload the page and try again.")
        # fixes apply to the latest revision only: an old tab must not undo newer fixes
        _require_latest_revision(conn, sid, body.revision_id)
        if f["status"] != "open":
            raise HTTPException(409, f"That finding is already {f['status']}. Reload the page to see the latest version.")
        content = rev["content"]
        source_kind = (rev["source_kind"] if "source_kind" in rev.keys() else None) or "text"
        asset_id = rev["asset_id"] if "asset_id" in rev.keys() else None
        # Uploaded documents are snapshots: the source file is fixed, so a text
        # edit would silently diverge from what would be published. Make the
        # creator upload a corrected file instead.
        if source_kind == "pdf" and body.action in ("accept", "edit"):
            raise HTTPException(409, "Canonry cannot edit a PDF. Fix this in the source document, export the PDF "
                                     "again and upload it, or dispute the finding.")
        suggestion = json.loads(f["suggestion_json"]) if f["suggestion_json"] not in (None, "", "null") else {}
        rev_map = json.loads(rev["locator_map_json"] or "[]") if "locator_map_json" in rev.keys() else []
        finding_region = (json.loads(f["locator_json"]) or {}).get("region") if f["locator_json"] else None
        in_picture = source_kind == "image" and (
            finding_region in (images.IMAGE_TEXT_REGION, vision.REGION) if finding_region
            else images.in_image_text(rev_map, f["span_start"]))
        if source_kind == "image" and in_picture and body.action != "dispute":
            raise HTTPException(409, "This text is part of the image. Change it in the design file and upload a "
                                     "corrected image, or dispute the finding.")
        if (source_kind == "image" and body.action == "accept" and finding_region == images.ALT_REGION
                and (suggestion or {}).get("operation") == "replace" and (suggestion or {}).get("replace")):
            # the suggested alt text (what Canonry sees in the image) is a one-click fix
            body.action, body.replacement = "edit", suggestion["replace"]
        if source_kind == "image" and body.action == "edit":
            alt = (body.replacement or "").strip()
            if not alt:
                raise HTTPException(422, "Write the alt text you want to use.")
            assets.update_alt_text(conn, asset_id, alt)
            conn.execute(
                "INSERT INTO decisions (id, revision_id, finding_id, action, replacement, reason, by_user, at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (gen_id("dec"), body.revision_id, body.finding_id, "edit", alt, body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE findings SET status='edited' WHERE id=?", (body.finding_id,))
            image_content, asset_row = assets.image_revision(assets.get_asset(conn, asset_id) or {"id": asset_id}, alt)
            result = run_check_for_submission(conn, sid, image_content, user["email"], asset=asset_row)
            audit(conn, user["email"], "finding_edit_alt", f"{body.finding_id}")
            conn.commit()
            return {"ok": True, "revision_id": result["revision_id"], "ai_pending": result["ai_pending"],
                    "ai_reason": result["ai_reason"]}
        if source_kind == "image" and body.action == "accept":
            raise HTTPException(409, "Image findings need a replacement file or a dispute; there is no safe one-click pixel fix.")
        if body.action == "accept":
            repl = (suggestion or {}).get("replace")
            op = (suggestion or {}).get("operation", "replace")
            if op == "rewrite" or (not repl and op != "remove"):
                # "rewrite" carries advice ("State the actual conditions..."), not copy:
                # pasting it into the draft would publish the advice
                raise HTTPException(409, "This finding has no one-click fix — edit it in your own words or dispute it.")
            new_content = apply_fix(content, f["span_start"], f["span_text"], repl or "")
            if new_content == content:
                raise HTTPException(409, "The flagged text no longer matches this revision — re-check and try again.")
            content = new_content
        elif body.action == "edit":
            new_content = apply_fix(content, f["span_start"], f["span_text"], body.replacement.strip())
            if new_content == content:
                raise HTTPException(409, "That edit leaves the text unchanged — write a different replacement or dispute the finding.")
            content = new_content
        elif not (body.reason or "").strip():
            raise HTTPException(400, "Disputes require a reason (rule applies? unclear? fact outdated? AI misread?)")
        conn.execute(
            "INSERT INTO decisions (id, revision_id, finding_id, action, replacement, reason, by_user, at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (gen_id("dec"), body.revision_id, body.finding_id, body.action, body.replacement, body.reason, user["email"], _now()),
        )
        conn.execute("UPDATE findings SET status=? WHERE id=?", (RESOLVE_ACTIONS[body.action], body.finding_id))
        revision_asset = _revision_asset(rev)  # a dispute keeps the uploaded file
        if source_kind == "docx" and body.action in ("accept", "edit"):
            revision_asset = _fixed_docx(conn, sid, asset_id, content, user["email"])
        # rules re-run now; the AI's findings carry over (Re-check runs the AI again)
        result = run_check_for_submission(conn, sid, content, user["email"], reuse_ai_from=body.revision_id,
                                          asset=revision_asset)
        audit(conn, user["email"], f"finding_{body.action}", f"{body.finding_id} reason={body.reason or ''}")
        conn.commit()
        return {"ok": True, "revision_id": result["revision_id"], "ai_pending": result["ai_pending"],
                "ai_reason": result["ai_reason"]}
    finally:
        conn.close()


def _fixed_docx(conn: sqlite3.Connection, sid: str, asset_id: Optional[str], content: str,
                actor: str) -> Dict[str, Any]:
    """Make the fix inside the Word file: a new version of the file whose own text
    is the fixed revision, so what is approved, stamped and downloaded is fixed too."""
    row = assets.get_asset(conn, asset_id) if asset_id else None
    raw = assets.asset_bytes(conn, asset_id) if asset_id else None
    if not row or raw is None:
        raise HTTPException(409, "The Word file behind this revision is missing; upload it again.")
    try:
        fixed = documents.docx_with_text(raw, content)
        asset = assets.create_asset(conn, row["workspace_id"], sid, row["filename"], fixed, None, actor)
    except (documents.DocumentError, assets.UploadError) as exc:
        raise HTTPException(getattr(exc, "status", 409), str(exc)) from exc
    if asset["extracted_text"] != content:
        raise HTTPException(409, "This fix could not be made inside the Word file. Edit the document and upload "
                                 "it again, or dispute the finding.")
    return asset


def apply_fix(content: str, start: Optional[int], span: Optional[str], replacement: str) -> str:
    """Replace exactly the flagged span (not every copy of it). A removal also
    tidies what it leaves behind: a dangling "and"/comma/dash, doubled spaces,
    a space before punctuation."""
    if not span:
        return content
    if start is None or content[start:start + len(span)] != span:
        start = content.find(span)
        if start < 0:
            return content
    # the paragraph that holds the span: tidying never reaches other paragraphs
    para_start = content.rfind("\n\n", 0, start)
    para_start = 0 if para_start < 0 else para_start + 2
    para_end = content.find("\n\n", start + len(span))
    para_end = len(content) if para_end < 0 else para_end
    para = content[para_start:start] + replacement + content[start + len(span):para_end]
    if not replacement:
        para = re.sub(r"(?:\s*(?:,|—|–|--|\band\b|\bor\b))+\s*(?=[.!?;,]|$)", "", para)
    para = re.sub(r"[ \t]{2,}", " ", para)
    para = re.sub(r"\s+([.!?;,])", r"\1", para)
    return (content[:para_start] + para.strip() + content[para_end:]).strip()


@app.post("/submissions/{sid}/recheck")
def recheck(req: Request, sid: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _lock_submission(conn, sid)
        _visible_sub(conn, user, sid, "edit")
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        result = run_check_for_submission(conn, sid, rev["content"], user["email"], asset=_revision_asset(rev))
        conn.commit()
        return result
    finally:
        conn.close()


class EditIn(BaseModel):
    content: str


@app.post("/submissions/{sid}/edit")
def edit_text(req: Request, sid: str, body: EditIn):
    """The writer changes the text of a draft (for example, what a reviewer asked for when sending it
    back). It becomes the next revision and is checked again; history and decisions stay together.
    Only while the draft is with its writer, never during review or after approval."""
    _require_same_origin(req)
    if not body.content.strip():
        raise HTTPException(422, "Write something to check: the draft is empty.")
    if len(body.content) > MAX_DRAFT_CHARS:
        raise HTTPException(422, f"This draft is too long to check at once ({len(body.content):,} characters; "
                                 f"the limit is {MAX_DRAFT_CHARS:,}). Split it into smaller pieces.")
    conn = connect()
    try:
        user = _user(req, conn)
        _lock_submission(conn, sid)
        _visible_sub(conn, user, sid, "edit")
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        if rev is None:
            raise HTTPException(404, "Submission not found")
        if _revision_asset(rev):
            raise HTTPException(409, "This draft is a file: change it in its source and use Upload new version.")
        if rev["content"] == body.content:
            raise HTTPException(422, "Nothing changed: edit the text, then save.")
        audit(conn, user["email"], "edit_text", f"{sid}: revision {rev['revision_no'] + 1}")
        result = run_check_for_submission(conn, sid, body.content, user["email"])
        conn.commit()
        return result
    finally:
        conn.close()


# ---- risk routing, review, approvals -----------------------------------------

def compute_risk(conn: sqlite3.Connection, sid: str) -> Dict[str, Any]:
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    rev = conn.execute(
        "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
    open_f = conn.execute(
        "SELECT tier, severity, category FROM findings WHERE revision_id=? AND status='open'",
        (rev["id"],)).fetchall()
    definite_high = any(f["tier"] == "definite" and f["severity"] == "high" for f in open_f)
    unsupported = any(f["category"] == "unsupported_claim" for f in open_f)
    public = sub["channel"] in ("social", "web", "blog")
    ai = sub["source_type"] == "ai-assisted"
    risky = (public and ai and (unsupported or definite_high or len(open_f) >= 3))
    if not open_f:
        # exemption policies auto-approve narrow, low-risk variants only
        policy = conn.execute(
            "SELECT name FROM exempt_policies WHERE workspace_id=? AND active=1", (sub["workspace_id"],)).fetchone()
        if policy and sub["channel"] == "email":
            return {"risk": "exempt", "router": policy["name"],
                    "note": "Auto-approved under exemption policy a brand owner wrote; logged, 10% spot-audited, revocable."}
        return {"risk": "low", "router": "one reviewer (fast track)",
                "note": "No open findings — fast track to one reviewer."}
    if risky or definite_high:
        return {"risk": "high", "router": "senior approver (regional legal lead)",
                "note": "Public channel + AI-assisted + contradicted/outdated or unsupported claims; concerns pre-highlighted for the senior approver."}
    return {"risk": "medium", "router": "one reviewer", "note": "Judgement calls only; one reviewer, not a bottleneck."}


class ReviewIn(BaseModel):
    action: str  # approve | request_changes | override | comment
    reason: Optional[str] = None
    finding_id: Optional[str] = None
    comment: Optional[str] = None


@app.post("/submissions/{sid}/submit-review")
def submit_review(req: Request, sid: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _lock_submission(conn, sid)  # a double click submits once
        _visible_sub(conn, user, sid, "submit")
        result = _send_to_review(conn, sid, user["email"])
        conn.commit()
        return result
    finally:
        conn.close()


def _send_to_review(conn, sid: str, actor: str) -> Dict[str, Any]:
    """Route a checked item into review (or the exemption lane). Caller commits."""
    risk = compute_risk(conn, sid)
    status = "Exempt-approved" if risk["risk"] == "exempt" else "In review"
    conn.execute("UPDATE submissions SET status=?, risk=?, router_note=? WHERE id=?",
                 (status, risk["risk"], risk["note"], sid))
    if risk["risk"] == "exempt":
        conn.execute(
            "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
            (gen_id("app"), sid, "exempt_approve", risk["note"], "exemption-policy:" + actor, _now()),
        )
    audit(conn, actor, "submit_review", f"{sid} risk={risk['risk']}")
    return {"status": status, **risk}


@app.post("/submissions/{sid}/review")
def review(req: Request, sid: str, body: ReviewIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/approvers decide")
        _lock_submission(conn, sid)  # a double click or a second tab decides once
        sub = _visible_sub(conn, user, sid)
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        open_high = conn.execute(
            "SELECT COUNT(*) c FROM findings WHERE revision_id=? AND status='open' AND severity='high'",
            (rev["id"],)).fetchone()["c"]
        why = workflow.blocked(sub["status"], body.action)
        if why:
            raise HTTPException(409, why)
        if body.action == "approve":
            if not DEMO_MODE and sub["created_by"].lower() == user["email"].lower():
                raise HTTPException(403, "A different reviewer must approve your work in production mode.")
            if open_high > 0:
                raise HTTPException(409, "High-severity findings must be resolved or explicitly overridden before approval — the reviewer decides, never the AI.")
            # roles are self-chosen, so the same person may draft and approve; allowed
            # (a solo demo must finish the loop) but never hidden: labelled and signed
            self_approved = sub["created_by"] == user["email"]
            note = body.comment or body.reason
            if self_approved:
                note = "[self-approved] " + (note or "approved by the same person who drafted it")
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "approve", note, user["email"], _now()),
            )
            asset = None
            asset_id = rev["asset_id"] if "asset_id" in rev.keys() else None
            if asset_id:
                row = assets.get_asset(conn, asset_id)
                raw = assets.asset_bytes(conn, asset_id)
                if row and raw is not None:
                    asset = {**row, "asset_id": row["id"], "bytes": raw}
            signed = signing.sign_approval(conn, sub["workspace_id"], sid, rev["id"], rev["content"], user["email"],
                                           user["role"], self_approved=self_approved, asset=asset,
                                           pack_versions=pack_versions(conn, sub["workspace_id"]))
            if asset:
                proof_row = conn.execute("SELECT public_key_fingerprint FROM proof_of_compliance WHERE id=?",
                                         (signed["poc_id"],)).fetchone()
                signed_record = {k: v for k, v in signed["record"].items()
                                 if k not in ("ledger_hash", "record_hash")}
                envelope = {
                    "record": signed_record, "signature": signed["signature"],
                    "public_key_fingerprint": proof_row["public_key_fingerprint"] if proof_row else None,
                    "verify_url": f"{PUBLIC_WEB_URL}/verify/{signed['poc_id']}",
                }
                try:
                    stamped = stamping.stamp_file(asset["bytes"], envelope, asset["kind"])
                    conn.execute("INSERT INTO proof_files (poc_id, bytes) VALUES (?,?)", (signed["poc_id"], stamped))
                    conn.execute("UPDATE proof_of_compliance SET stamped_sha256=? WHERE id=?",
                                 (stamping.sha256(stamped), signed["poc_id"]))
                    signed["stamped_sha256"] = stamping.sha256(stamped)
                except (ValueError, KeyError) as exc:
                    raise HTTPException(422, f"This file could not be stamped: {exc}") from exc
            conn.execute("UPDATE submissions SET status='Signed' WHERE id=?", (sid,))
            verify_url = f"{PUBLIC_WEB_URL}/verify/{signed['poc_id']}"
            # `approved` fires once the reviewer's decision exists; `signed` only
            # after the seal (and, for a file, the stamped copy) exists. A CMS must
            # wait for `signed` — approval alone is not publication authority.
            webhooks.emit(conn, sub["workspace_id"], "approved", {
                "submission_id": sid, "title": sub["title"], "status": "Approved",
                "revision_id": rev["id"], "poc_id": signed["poc_id"],
                "content_sha256": signed["record"]["content_sha256"],
                "content_kind": signed["record"]["content_kind"],
                "self_approved": self_approved,
            })
            webhooks.emit(conn, sub["workspace_id"], "signed", {
                "submission_id": sid, "title": sub["title"], "status": "Signed",
                "revision_id": rev["id"], "poc_id": signed["poc_id"],
                "verify_url": verify_url,
                "content_sha256": signed["record"]["content_sha256"],
                "content_kind": signed["record"]["content_kind"],
                "asset_id": signed["record"].get("asset_id"),
                "filename": signed["record"].get("filename"),
                "mime": signed["record"].get("mime"),
                "stamped_sha256": signed.get("stamped_sha256"),
                "self_approved": self_approved,
            })
            audit(conn, user["email"], "approve", f"{sid} signed {signed['poc_id']}" + (" (self-approved)" if self_approved else ""))
            conn.commit()
            try:
                webhooks.flush(conn, limit=4, timeout=2.5)
            except Exception:
                pass
            return {"status": "Signed", "poc_id": signed["poc_id"], "self_approved": self_approved,
                    "verify_url": verify_url}
        if body.action == "override":
            if not body.reason or body.reason.strip() == "" or not body.finding_id:
                raise HTTPException(400, "Overrides need the finding id and a reason")
            target = conn.execute(
                "SELECT id, status FROM findings WHERE id = ? AND revision_id = ?",
                (body.finding_id, rev["id"])).fetchone()
            if not target:
                raise HTTPException(404, "That finding is not on the current revision — re-check the item and try again.")
            if target["status"] != "open":
                raise HTTPException(409, f"That finding is already {target['status']}.")
            conn.execute(
                "INSERT INTO decisions (id, revision_id, finding_id, action, replacement, reason, by_user, at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (gen_id("dec"), rev["id"], body.finding_id, "override", None, body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE findings SET status='disputed' WHERE id=? AND revision_id=?", (body.finding_id, rev["id"]))
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM findings WHERE revision_id=? AND status='open'", (rev["id"],)).fetchone()["c"]
            status = sub["status"]  # an override settles one finding; the reviewer still decides the item
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "override", body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE submissions SET status=? WHERE id=?", (status, sid))
            audit(conn, user["email"], "override", f"{body.finding_id}: {body.reason}")
            conn.commit()
            return {"status": status, "remaining_open": remaining}
        if body.action == "request_changes":
            if not (body.comment or body.reason or "").strip():
                raise HTTPException(422, "Say what needs to change before requesting changes.")
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "request_changes", body.comment or body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE submissions SET status='Changes requested' WHERE id=?", (sid,))
            conn.commit()
            return {"status": "Changes requested"}
        # comment
        conn.execute(
            "INSERT INTO comments (id, revision_id, by_user, at, text) VALUES (?,?,?,?,?)",
            (gen_id("c"), rev["id"], user["email"], _now(), body.comment or ""),
        )
        conn.commit()
        return {"status": sub["status"]}
    finally:
        conn.close()


# ---- Proof of Compliance verify ----------------------------------------------

class VerifyIn(BaseModel):
    content: str = Field(max_length=200_000)


@app.get("/verify/{poc_id}")
def verify_poc(poc_id: str):
    """Public, no sign-in: is this seal genuine?"""
    conn = connect(service=True)
    try:
        return signing.verify(conn, poc_id)
    finally:
        conn.close()


@app.post("/verify/{poc_id}/file")
async def verify_published_file(req: Request, poc_id: str):
    """Public: upload the published file and check it against the signed original."""
    data = await _read_limited_body(req, 12 * 1024 * 1024, "12 MB")
    conn = connect(service=True)
    try:
        return signing.verify_file(conn, poc_id, data)
    finally:
        conn.close()


@app.get("/submissions/{sid}/proof-file")
def download_proof_file(req: Request, sid: str):
    """Signed-in download of the stamped approved file."""
    conn = connect()
    try:
        user = _user(req, conn)
        _visible_sub(conn, user, sid)
        row = conn.execute(
            "SELECT p.id, p.asset_id, a.filename, a.mime, f.bytes FROM proof_of_compliance p "
            "JOIN proof_files f ON f.poc_id = p.id LEFT JOIN assets a ON a.id = p.asset_id "
            "WHERE p.submission_id = ? ORDER BY p.created_at DESC LIMIT 1", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "This submission has no stamped file.")
        filename = row["filename"] or "canonry-approved-file"
        return Response(content=bytes(row["bytes"]), media_type=row["mime"] or "application/octet-stream",
                        headers={"Content-Disposition": _disposition("attachment", f"canonry-{filename}")})
    finally:
        conn.close()


@app.post("/verify/{poc_id}")
def verify_published(poc_id: str, body: VerifyIn):
    """Public, no sign-in: is this the exact text that was approved?"""
    conn = connect(service=True)
    try:
        return signing.verify(conn, poc_id, body.content)
    finally:
        conn.close()


# ---- public API v1 ------------------------------------------------------------

API_VERSION = "2026-10-30"


def _api_headers() -> Dict[str, str]:
    return {"X-Canon-API-Version": API_VERSION, "X-Canon-Contract-Version": contract.CONTRACT_VERSION}


def _api_finding(row) -> Dict[str, Any]:
    data = dict(row)
    data["citations"] = json.loads(data.pop("citations_json") or "[]")
    data["suggestion"] = json.loads(data.pop("suggestion_json") or "null")
    data["provenance"] = json.loads(data.pop("provenance_json") or "{}")
    data["locator"] = json.loads(data.pop("locator_json") or "null")
    # contract v2: one `span` object, not the three storage columns
    data["span"] = {"start": data.pop("span_start", None), "end": data.pop("span_end", None),
                    "text": data.pop("span_text", "")}
    return data


def _api_submission(conn, sub) -> Dict[str, Any]:
    sid = sub["id"]
    rev = conn.execute(
        "SELECT * FROM revisions WHERE submission_id = ? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
    findings = [_api_finding(r) for r in conn.execute(
        "SELECT * FROM findings WHERE revision_id = ? ORDER BY span_start", (rev["id"] if rev else "",)).fetchall()]
    approvals = [dict(r) for r in conn.execute(
        "SELECT id, action, reason, reviewer, at FROM approvals WHERE submission_id = ? ORDER BY at", (sid,)).fetchall()]
    poc = conn.execute(
        "SELECT id, content_sha256, content_kind, asset_id, stamped_sha256, created_at "
        "FROM proof_of_compliance WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
    asset = None
    if rev is not None and rev["asset_id"]:
        row = assets.get_asset(conn, rev["asset_id"])
        if row:
            asset = {k: row.get(k) for k in ("id", "kind", "filename", "mime", "size_bytes",
                                              "width", "height", "page_count", "alt_text", "sha256")}
    return {
        "id": sid, "title": sub["title"], "channel": sub["channel"],
        "source_type": sub["source_type"], "status": sub["status"], "risk": sub["risk"],
        "created_at": sub["created_at"],
        # `content` is the text that was checked (for a file, its extracted text);
        # once signed it is the approved text, whose SHA-256 is poc.content_sha256
        "latest_revision": {k: rev[k] for k in ("id", "revision_no", "created_at", "source_kind", "asset_id", "content")} if rev else None,
        "findings": findings,
        "approvals": approvals,
        "poc": ({"id": poc["id"], "content_sha256": poc["content_sha256"], "content_kind": poc["content_kind"],
                 "asset_id": poc["asset_id"], "stamped_sha256": poc["stamped_sha256"],
                 "verify_url": f"{PUBLIC_WEB_URL}/verify/{poc['id']}"} if poc else None),
        "asset": asset,
        "links": {"self": f"/api/v1/submissions/{sid}"},
        "contract_version": contract.CONTRACT_VERSION,
    }


class ApiCheckIn(BaseModel):
    title: str = Field(max_length=240)
    channel: str
    source_type: str = "in-house"
    content: str = Field(max_length=200_000)
    # true: after the check, route it straight into the review queue (a CMS
    # that holds a post until a reviewer signs it)
    submit_for_review: bool = False


@app.post("/api/v1/checks")
def api_check(req: Request, body: ApiCheckIn):
    """Check text from an external client. Idempotent when the caller sends an
    Idempotency-Key, so a retried request never creates a second submission."""
    conn = connect()
    try:
        key = api.authenticate(req, conn, "check")
        ws = key["workspace_id"]
        if body.channel not in CHANNELS:
            raise HTTPException(422, {"code": "bad_channel", "message": f"Channel must be one of: {', '.join(CHANNELS)}."})
        if not body.content.strip():
            raise HTTPException(422, {"code": "empty_content", "message": "The draft is empty."})
        if not body.title.strip():
            raise HTTPException(422, {"code": "missing_title", "message": "Give the draft a title."})
        endpoint = "POST /api/v1/checks"
        payload_hash = api.request_hash(body.model_dump())
        key_header = api.idempotency_key(req)
        cached = api.claim_idempotent(conn, ws, key_header, endpoint, payload_hash)
        if cached:
            return JSONResponse(cached["body"], status_code=cached["status"], headers=_api_headers())
        try:
            sid = gen_id("sub")
            conn.execute(
                "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
                "VALUES (?,?,?,?,?,?,'Draft',?)",
                (sid, ws, body.title, body.channel, body.source_type[:40] or "in-house",
                 "api:" + key["name"], _now()),
            )
            audit(conn, "api:" + key["name"], "api_check", f"{sid}: {body.title}")
            result = run_check_for_submission(conn, sid, body.content, None)
            status = "Checked"
            if body.submit_for_review:
                status = _send_to_review(conn, sid, "api:" + key["name"])["status"]
            response = {
                "submission_id": sid, "revision_id": result["revision_id"], "status": status,
                "contract_version": contract.CONTRACT_VERSION,
                "findings": result.get("findings", []), "discarded": result.get("discarded", 0),
                "ai_pending": result.get("ai_pending", False), "ai_reason": result.get("ai_reason"),
                "profile": result.get("profile"),
                "links": {"self": f"/api/v1/submissions/{sid}"},
            }
            # the answer is stored in the same transaction as the submission
            api.store_idempotent(conn, ws, key_header, endpoint, payload_hash, 200, response)
            conn.commit()
        except BaseException:
            api.release_idempotent(conn, ws, key_header, endpoint)
            raise
        return JSONResponse(response, headers=_api_headers())
    finally:
        conn.close()


@app.post("/api/v1/uploads")
async def api_upload(req: Request, title: str, channel: str, filename: str,
                     source_type: str = "in-house", alt_text: str = ""):
    """Upload a PDF/DOCX/PNG/JPEG via raw body (no multipart parser)."""
    data = await _read_limited_body(req, assets.MAX_PDF, "10 MB")

    def work():
        conn = connect()
        try:
            key = api.authenticate(req, conn, "check")
            ws = key["workspace_id"]
            if channel not in CHANNELS:
                raise HTTPException(422, {"code": "bad_channel", "message": f"Channel must be one of: {', '.join(CHANNELS)}."})
            endpoint = "POST /api/v1/uploads"
            payload_hash = api.request_hash({"title": title, "channel": channel, "filename": filename,
                                             "source_type": source_type, "alt_text": alt_text,
                                             "sha256": hashlib.sha256(data).hexdigest()})
            key_header = api.idempotency_key(req)
            cached = api.claim_idempotent(conn, ws, key_header, endpoint, payload_hash)
            if cached:
                return JSONResponse(cached["body"], status_code=cached["status"], headers=_api_headers())
            try:
                sid = gen_id("sub")
                conn.execute(
                    "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
                    "VALUES (?,?,?,?,?,?,'Draft',?)",
                    (sid, ws, " ".join(title.split())[:240], channel, source_type[:40] or "in-house",
                     "api:" + key["name"], _now()),
                )
                try:
                    asset = assets.create_asset(conn, ws, sid, filename, data, alt_text, "api:" + key["name"])
                except (assets.UploadError, documents.DocumentError, images.ImageError) as exc:
                    raise HTTPException(getattr(exc, "status", 422), {"code": "bad_upload", "message": str(exc)}) from exc
                audit(conn, "api:" + key["name"], "api_upload", f"{sid}: {asset['filename']}")
                result = run_check_for_submission(conn, sid, asset["extracted_text"], None, asset=asset)
                response = {
                    "submission_id": sid, "revision_id": result["revision_id"], "status": "Checked",
                    "contract_version": contract.CONTRACT_VERSION,
                    "asset": {k: asset[k] for k in ("id", "kind", "filename", "size_bytes", "width", "height", "page_count")},
                    "findings": result.get("findings", []), "ai_pending": result.get("ai_pending", False),
                    "links": {"self": f"/api/v1/submissions/{sid}", "file": f"/api/v1/assets/{asset['id']}"},
                }
                api.store_idempotent(conn, ws, key_header, endpoint, payload_hash, 200, response)
                conn.commit()
            except BaseException:
                api.release_idempotent(conn, ws, key_header, endpoint)
                raise
            return JSONResponse(response, headers=_api_headers())
        finally:
            conn.close()

    # OCR and logo matching are CPU-bound: run them off the event loop
    return await run_in_threadpool(work)


@app.get("/api/v1/submissions")
def api_list_submissions(req: Request, limit: int = 25):
    conn = connect()
    try:
        key = api.authenticate(req, conn, "read")
        rows = conn.execute(
            "SELECT * FROM submissions WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (key["workspace_id"], min(max(limit, 1), 100))).fetchall()
        return JSONResponse({"submissions": [_api_submission(conn, r) for r in rows]}, headers=_api_headers())
    finally:
        conn.close()


@app.get("/api/v1/submissions/{sid}")
def api_get_submission(req: Request, sid: str):
    conn = connect()
    try:
        key = api.authenticate(req, conn, "read")
        sub = conn.execute("SELECT * FROM submissions WHERE id = ? AND workspace_id = ?",
                           (sid, key["workspace_id"])).fetchone()
        if not sub:
            raise HTTPException(404, {"code": "not_found", "message": "Submission not found in this workspace."})
        return JSONResponse(_api_submission(conn, sub), headers=_api_headers())
    finally:
        conn.close()


@app.get("/api/v1/proofs/{poc_id}")
def api_proof(req: Request, poc_id: str):
    conn = connect(service=True)
    try:
        api_key = api.authenticate(req, conn, "read")
        row = conn.execute(
            "SELECT p.id FROM proof_of_compliance p JOIN submissions s ON s.id = p.submission_id "
            "WHERE p.id = ? AND s.workspace_id = ?", (poc_id, api_key["workspace_id"])).fetchone()
        if not row:
            raise HTTPException(404, {"code": "not_found", "message": "Proof not found in this workspace."})
        return JSONResponse(signing.verify(conn, poc_id), headers=_api_headers())
    finally:
        conn.close()


@app.get("/api/v1/assets/{asset_id}")
def api_asset(req: Request, asset_id: str):
    """The uploaded file behind a submission (the `links.file` of an upload)."""
    conn = connect()
    try:
        key = api.authenticate(req, conn, "read")
        row = assets.get_asset(conn, asset_id)
        sub = conn.execute("SELECT id FROM submissions WHERE id = ? AND workspace_id = ?",
                           (row["submission_id"], key["workspace_id"])).fetchone() if row else None
        raw = assets.asset_bytes(conn, asset_id) if sub else None
        if raw is None:
            raise HTTPException(404, {"code": "not_found", "message": "File not found in this workspace."})
        return Response(content=raw, media_type=row["mime"],
                        headers={**_api_headers(), "Content-Disposition": _disposition("attachment", row["filename"]),
                                 "Cache-Control": "private, no-store"})
    finally:
        conn.close()


@app.get("/api/v1/compliance/packs")
def api_compliance_packs(req: Request):
    conn = connect()
    try:
        key = api.authenticate(req, conn, "read")
        return JSONResponse(compliance.pack_overview(conn, key["workspace_id"]), headers=_api_headers())
    finally:
        conn.close()


@app.get("/api/v1/contract")
def api_contract():
    return JSONResponse({
        "contract": contract.CONTRACT_VERSION, "api_version": API_VERSION,
        "finding": {"span": "{start,end,text}", "locator": "{kind,page,line,paragraph,section,bbox,region,asset_id}",
                    "tier": "definite | likely | consider", "severity": "high | medium | low",
                    "citations": "[{type: fact|rule|pack|term, id, ref?, source?, url?, version?}]"},
        "events": list(webhooks.EVENTS),
    }, headers=_api_headers())


def _admin(user) -> None:
    if user["role"] != "admin":
        raise HTTPException(403, "Only a workspace administrator can manage API keys and webhooks.")


@app.get("/api-keys")
def api_keys_list(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        return {"keys": api.list_keys(conn, _ws(conn))}
    finally:
        conn.close()


class ApiKeyIn(BaseModel):
    name: str
    scopes: List[str] = ["check", "read"]


@app.post("/api-keys")
def api_keys_create(req: Request, body: ApiKeyIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        created = api.create_key(conn, _ws(conn), body.name, body.scopes, user["email"])
        audit(conn, user["email"], "api_key_create", created["id"])
        conn.commit()
        return created
    finally:
        conn.close()


@app.post("/api-keys/{key_id}/revoke")
def api_keys_revoke(req: Request, key_id: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        api.revoke_key(conn, _ws(conn), key_id)
        audit(conn, user["email"], "api_key_revoke", key_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/webhook-endpoints")
def webhook_endpoints_list(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        return {"endpoints": webhooks.list_endpoints(conn, _ws(conn))}
    finally:
        conn.close()


class WebhookIn(BaseModel):
    url: str
    events: List[str] = ["checked", "approved", "signed"]
    description: str = ""


@app.post("/webhook-endpoints")
def webhook_endpoints_create(req: Request, body: WebhookIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        try:
            created = webhooks.create_endpoint(conn, _ws(conn), body.url, body.events,
                                               body.description, user["email"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit(conn, user["email"], "webhook_create", created["id"])
        conn.commit()
        return created
    finally:
        conn.close()


@app.post("/webhook-endpoints/{endpoint_id}/rotate")
def webhook_endpoints_rotate(req: Request, endpoint_id: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        try:
            rotated = webhooks.rotate_secret(conn, _ws(conn), endpoint_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        audit(conn, user["email"], "webhook_rotate", endpoint_id)
        conn.commit()
        return rotated
    finally:
        conn.close()


@app.post("/webhook-endpoints/{endpoint_id}/disable")
def webhook_endpoints_disable(req: Request, endpoint_id: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        try:
            webhooks.disable_endpoint(conn, _ws(conn), endpoint_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        audit(conn, user["email"], "webhook_disable", endpoint_id)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/webhook-deliveries")
def webhook_deliveries_list(req: Request, limit: int = 50):
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        return {"deliveries": webhooks.list_deliveries(conn, _ws(conn), limit)}
    finally:
        conn.close()


@app.post("/webhook-deliveries/{delivery_id}/retry")
def webhook_delivery_retry(req: Request, delivery_id: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        try:
            return webhooks.retry_delivery(conn, _ws(conn), delivery_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    finally:
        conn.close()


@app.post("/webhooks/flush")
def webhooks_flush(req: Request):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _admin(user)
        result = webhooks.flush(conn, limit=20)
        conn.commit()
        return result
    finally:
        conn.close()


@app.get("/assets/{asset_id}")
def get_asset_file(req: Request, asset_id: str):
    conn = connect()
    try:
        user = _user(req, conn)
        row = assets.get_asset(conn, asset_id)
        if not row:
            raise HTTPException(404)
        if row["submission_id"]:
            sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (row["submission_id"],)).fetchone()
            if not sub or not access.can_see_submission(user, sub):
                raise HTTPException(404)
        raw = assets.asset_bytes(conn, asset_id)
        if raw is None:
            raise HTTPException(404)
        return Response(content=raw, media_type=row["mime"],
                        headers={"Content-Disposition": _disposition("inline", row["filename"]),
                                 "Cache-Control": "private, no-store"})
    finally:
        conn.close()


@app.get("/compliance/packs")
def compliance_packs(req: Request):
    conn = connect()
    try:
        _user(req, conn)
        return compliance.pack_overview(conn, _ws(conn))
    finally:
        conn.close()


class PackSwitchIn(BaseModel):
    active: bool


@app.post("/compliance/packs/{pack_id}")
def compliance_pack_switch(req: Request, pack_id: str, body: PackSwitchIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] != "admin":
            raise HTTPException(403, "Only a workspace administrator can switch compliance packs.")
        try:
            compliance.set_pack_active(conn, _ws(conn), pack_id, body.active, user["email"])
        except KeyError as exc:
            raise HTTPException(404, "That compliance pack is not installed.") from exc
        audit(conn, user["email"], "pack_enable" if body.active else "pack_disable", pack_id)
        conn.commit()
        return compliance.pack_overview(conn, _ws(conn))
    finally:
        conn.close()


# ---- insights, alerts, evaluation --------------------------------------------

@app.get("/insights")
def insights(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        scope, args = access.submission_scope(user)
        # findings / decisions joined to the submissions this user may see
        in_scope = ("JOIN revisions v ON v.id = {t}.revision_id JOIN submissions s ON s.id = v.submission_id "
                    f"WHERE {scope}")
        # each re-check re-reports unresolved issues on the new revision, so count
        # an issue once per submission (checker + category + flagged text)
        issues = ("(SELECT DISTINCT v.submission_id, f.checker, f.category, f.tier, f.span_text "
                  "FROM findings f JOIN revisions v ON v.id = f.revision_id) i "
                  f"JOIN submissions s ON s.id = i.submission_id WHERE {scope}")
        by_checker = {}
        for r in conn.execute(
                "SELECT i.checker, COUNT(*) c, SUM(CASE WHEN i.tier='definite' THEN 1 ELSE 0 END) definite "
                f"FROM {issues} GROUP BY i.checker", args).fetchall():
            by_checker[r["checker"]] = dict(r)
        decision_counts = conn.execute(
            f"SELECT d.action, COUNT(*) c FROM decisions d {in_scope.format(t='d')} GROUP BY d.action", args).fetchall()
        overrides = conn.execute(
            f"SELECT s.title, d.reason, d.at FROM decisions d {in_scope.format(t='d')} "
            "AND d.action IN ('dispute','override') ORDER BY d.at DESC LIMIT 20", args).fetchall()
        broken = conn.execute(
            f"SELECT i.category, COUNT(*) c FROM {issues} GROUP BY i.category ORDER BY c DESC",
            args).fetchall()
        unsupported = conn.execute(
            f"SELECT COUNT(*) c FROM {issues} AND i.category='unsupported_claim'", args).fetchone()["c"]
        statuses = conn.execute(
            f"SELECT s.status, COUNT(*) c FROM submissions s WHERE {scope} GROUP BY s.status", args).fetchall()
        vague = conn.execute("SELECT id, statement, vague_flag FROM rules WHERE vague_flag IS NOT NULL").fetchall()
        ai_calls = conn.execute(
            "SELECT task, provider, model, COUNT(*) c, SUM(ok) ok FROM ai_calls GROUP BY task, provider, model").fetchall()
        # clarity dashboard: an unsupported claim is a missing fact, not just a
        # finding. Group the exact phrases so an owner can add one fact and clear
        # every occurrence; this is a suggestion, never an auto-authored fact.
        missing = conn.execute(
            f"SELECT i.span_text, COUNT(DISTINCT i.submission_id) occurrences, "
            f"MIN(s.title) sample_title, MIN(i.submission_id) sample_id "
            f"FROM {issues} AND i.category='unsupported_claim' "
            "GROUP BY i.span_text ORDER BY occurrences DESC, i.span_text LIMIT 12", args).fetchall()
        # tier calibration: the share of each tier that a human disputed. A tier
        # whose disputes climb is drifting and should be re-calibrated before it
        # is trusted as "Definite".
        tier_rows = conn.execute(
            f"SELECT f.tier, COUNT(*) total, "
            "SUM(CASE WHEN f.status IN ('disputed') THEN 1 ELSE 0 END) disputed, "
            "SUM(CASE WHEN f.status IN ('accepted','edited') THEN 1 ELSE 0 END) accepted, "
            "SUM(CASE WHEN f.status='open' THEN 1 ELSE 0 END) open "
            "FROM findings f JOIN revisions v ON v.id = f.revision_id "
            f"JOIN submissions s ON s.id = v.submission_id WHERE {scope} GROUP BY f.tier", args).fetchall()
        calibration = []
        for row in tier_rows:
            total = int(row["total"] or 0)
            disputed = int(row["disputed"] or 0)
            rate = (disputed / total) if total else 0.0
            calibration.append({
                "tier": row["tier"], "total": total, "disputed": disputed,
                "accepted": int(row["accepted"] or 0), "open": int(row["open"] or 0),
                "dispute_rate": round(rate, 4),
                "needs_recalibration": row["tier"] == "definite" and total >= 20 and rate > 0.10,
            })
        return {
            "by_checker": by_checker, "decisions": {r["action"]: r["c"] for r in decision_counts},
            "dispute_overrides": [dict(d) for d in overrides],
            "categories": [dict(b) for b in broken],
            "unsupported_claims": unsupported,
            "statuses": [dict(s) for s in statuses],
            "possibly_unclear_rules": [dict(v) for v in vague],
            "ai_calls": [dict(a) for a in ai_calls],
            "missing_facts": [dict(m) for m in missing],
            "tier_calibration": calibration,
        }
    finally:
        conn.close()


@app.get("/alerts/expiry")
def expiry_alerts(req: Request):
    """Fact expiry + impact alerts (listed approved content that used the fact)."""
    conn = connect()
    try:
        user = _user(req, conn)
        scope, args = access.submission_scope(user)
        expired = conn.execute(
            "SELECT * FROM facts WHERE valid_to IS NOT NULL AND valid_to < ?", (date.today().isoformat(),)).fetchall()
        alerts = []
        for f in expired:
            used = conn.execute(
                "SELECT DISTINCT s.id, s.title, s.status FROM submissions s JOIN revisions v ON v.submission_id=s.id "
                "JOIN decisions d ON d.revision_id=v.id JOIN findings fnd ON fnd.id=d.finding_id "
                f"WHERE fnd.citations_json LIKE ? AND s.status IN ('Approved','Signed') AND {scope}",
                (f'%"{f["id"]}"%', *args),
            ).fetchall()
            alerts.append({
                "fact": access.redact_fact(dict(f), user), "active": claims._fact_active(f),
                "affected_approved_content": [dict(u) for u in used],
                "action": "Content cites expired fact; open re-review tasks."
            })
        return {"alerts": alerts}
    finally:
        conn.close()


@app.get("/alerts/claims-in-review")
def pending_jobs(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        scope, args = access.submission_scope(user)
        pend = conn.execute(
            "SELECT cr.id run_id, cr.revision_id, s.id submission_id, s.title, cr.started_at "
            "FROM check_runs cr JOIN revisions r ON r.id = cr.revision_id "
            "JOIN submissions s ON s.id = r.submission_id "
            "WHERE cr.status = 'ai_pending' AND r.revision_no = "
            f"(SELECT MAX(revision_no) FROM revisions WHERE submission_id = s.id) AND {scope} "
            "ORDER BY cr.started_at DESC", args).fetchall()
        return {"pending": [dict(p) for p in pend]}
    finally:
        conn.close()


@app.get("/health")
def health():
    """Liveness for the host's health check: the database answers."""
    conn = connect()
    try:
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "demo_mode": DEMO_MODE}
    finally:
        conn.close()


@app.get("/auth-mode")
def auth_mode():
    return JSONResponse(
        {"demo_mode": DEMO_MODE, "registration": "demo" if DEMO_MODE else "invitation-only"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/ai-status")
def ai_status():
    conn = connect()
    try:
        providers = gateway.provider_list()
        calls = conn.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 20").fetchall()
        return {
            "providers": providers,
            "prompt_versions": {"claims": gateway.PROMPT_VERSION, "tone": pipeline.TONE_PROMPT_VERSION},
            "data_policy": "Only needed excerpts go to the provider — never the whole knowledge base; confidential facts are excluded for free APIs.",
            "degradation": "With no model available rule-based findings still arrive and AI checks are marked pending.",
            "recent_calls": [dict(c) for c in calls],
        }
    finally:
        conn.close()
