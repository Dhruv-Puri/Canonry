"""Canonry analysis engine — FastAPI web/API (doc Section 9.3).

Background job queue for the event build = FastAPI background tasks; the flow
is small documents, so checks run inline but through the same job-table seam
(check_runs row) that a Redis queue adapter replaces later.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import hashlib
import secrets
import sqlite3
import zipfile
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import access
import claims
import gateway
import knowledge
import pipeline
import policy
import signing
import workflow
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
INVITE_TTL_HOURS = 72

app = FastAPI(title="Canonry engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=sorted(APP_ORIGINS), allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "Authorization", "X-Canon-Session"])


@app.middleware("http")
async def no_store_sensitive_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/me", "/workspace", "/invitations", "/rules", "/facts", "/terms", "/submissions", "/insights", "/alerts")):
        response.headers["Cache-Control"] = "private, no-store"
    if request.url.path in ("/login", "/join") and response.status_code < 400:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def _startup() -> None:
    init_schema()
    if not DEMO_MODE:
        _ensure_production_workspace()
        _ensure_bootstrap_admin()
    else:
        seed()
        _seed_demo_submission()


def _ensure_production_workspace() -> None:
    """Create an empty workspace for a fresh production install, never demo data."""
    conn = connect()
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
        # the workspace's own rulebook is imported)
        policy.ensure_bindings(conn, _ws(conn))
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
    conn = connect()
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
        conn.commit()
    finally:
        conn.close()


def _ensure_bootstrap_admin() -> None:
    email = os.environ.get("CANONRY_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("CANONRY_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        raise RuntimeError("Set CANONRY_BOOTSTRAP_ADMIN_EMAIL to a valid initial administrator address.")
    if len(password) < 12:
        raise RuntimeError("Set CANONRY_BOOTSTRAP_ADMIN_PASSWORD to at least 12 characters.")
    conn = connect()
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


def _user(req: Request, conn: sqlite3.Connection):
    token = req.cookies.get("canonry_session") or req.headers.get("x-canon-session")
    user = resolve_session(conn, token)
    if not user:
        raise HTTPException(401, "Sign in required")
    return user


def _ws(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
    return row["id"]


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
    conn = connect()
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
    resp.set_cookie("canonry_session", token, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", max_age=24 * 60 * 60, path="/")


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
    conn = connect()
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
        return {"id": user["id"], "name": name, "role": role}
    finally:
        conn.close()


@app.post("/logout")
def logout(req: Request):
    _require_same_origin(req)
    token = req.cookies.get("canonry_session") or req.headers.get("x-canon-session")
    conn = connect()
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


async def _read_limited_body(req: Request, limit: int) -> bytes:
    length = req.headers.get("content-length")
    if length:
        try:
            if int(length) > limit:
                raise HTTPException(413, "Document exceeds the 5 MB import limit.")
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length header.") from exc
    chunks = []
    total = 0
    async for chunk in req.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "Document exceeds the 5 MB import limit.")
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
    if not body.title.strip():
        raise HTTPException(422, "Give the draft a title.")
    if body.channel not in CHANNELS:
        raise HTTPException(422, f"Channel must be one of: {', '.join(CHANNELS)}.")
    conn = connect()
    try:
        user = _user(req, conn)
        sid = gen_id("sub")
        conn.execute(
            "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
            "VALUES (?,?,?,?,?,?,'Draft',?)",
            (sid, _ws(conn), body.title, body.channel, body.source_type, user["email"], _now()),
        )
        audit(conn, user["email"], "submit_content", f"{sid}: {body.title}")
        result = run_check_for_submission(conn, sid, body.content)
        resp = {"submission_id": sid, "revision_id": result["revision_id"], **{
            k: v for k, v in result.items() if k != "revision_id"}}
        conn.commit()
        return resp
    finally:
        conn.close()


def run_check_for_submission(conn: sqlite3.Connection, sid: str, content: str) -> Dict[str, Any]:
    rev_no = conn.execute("SELECT COALESCE(MAX(revision_no),0)+1 AS n FROM revisions WHERE submission_id=?", (sid,)).fetchone()["n"]
    rid = gen_id("rev")
    conn.execute(
        "INSERT INTO revisions (id, submission_id, content, revision_no, created_at) VALUES (?,?,?,?,?)",
        (rid, sid, content, rev_no, _now()),
    )
    conn.execute("UPDATE submissions SET status = CASE WHEN status='Draft' THEN 'Checked' ELSE status END WHERE id=?", (sid,))
    result = pipeline.run_check(conn, rid)
    result["revision_id"] = rid
    return result


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
        return {"submissions": [dict(r) for r in rows if access.can_see_submission(user, r)]}
    finally:
        conn.close()


@app.get("/submissions/{sid}")
def get_submission(req: Request, sid: str):
    conn = connect()
    try:
        user = _user(req, conn)
        sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
        if not sub or not access.can_see_submission(user, sub):
            raise HTTPException(404)
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
        poc = conn.execute("SELECT id, created_at FROM proof_of_compliance WHERE submission_id=? ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
        # latest check run on the latest revision, so the UI can say when AI checks are still pending
        check = conn.execute(
            "SELECT status, started_at, finished_at, ai_calls, discarded, knowledge_version FROM check_runs "
            "WHERE revision_id = ? ORDER BY started_at DESC LIMIT 1", (latest["id"] if latest else "",)).fetchone()
        return {"submission": dict(sub), "revisions": revs, "latest_revision": latest,
                "findings": findings, "decisions": decisions, "approvals": approvals,
                "poc": dict(poc) if poc else None, "check": dict(check) if check else None, "me": _public_user(user),
                "allowed": workflow.allowed(sub["status"])}
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
        _visible_sub(conn, user, sid, "edit")
        f = conn.execute("SELECT * FROM findings WHERE id=? AND revision_id=?", (body.finding_id, body.revision_id)).fetchone()
        if not f:
            raise HTTPException(404, "Finding not found")
        rev = conn.execute("SELECT * FROM revisions WHERE id=?", (body.revision_id,)).fetchone()
        content = rev["content"]
        suggestion = json.loads(f["suggestion_json"]) if f["suggestion_json"] not in (None, "", "null") else {}
        if body.action == "accept":
            repl = (suggestion or {}).get("replace")
            op = (suggestion or {}).get("operation", "replace")
            if not repl and op != "remove":
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
        result = run_check_for_submission(conn, sid, content)
        audit(conn, user["email"], f"finding_{body.action}", f"{body.finding_id} reason={body.reason or ''}")
        conn.commit()
        return {"ok": True, "revision_id": result["revision_id"], "ai_pending": result["ai_pending"]}
    finally:
        conn.close()


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
    content = content[:start] + replacement + content[start + len(span):]
    if not replacement:
        content = re.sub(r"(?:\s*(?:,|—|–|--|\band\b|\bor\b))+\s*(?=[.!?;,]|$)", "", content)
    content = re.sub(r"[ 	]{2,}", " ", content)
    content = re.sub(r"\s+([.!?;,])", r"\1", content)
    return content.strip()


@app.post("/submissions/{sid}/recheck")
def recheck(req: Request, sid: str):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        _visible_sub(conn, user, sid, "edit")
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        result = run_check_for_submission(conn, sid, rev["content"])
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
        _visible_sub(conn, user, sid, "submit")
        risk = compute_risk(conn, sid)
        status = "Exempt-approved" if risk["risk"] == "exempt" else "In review"
        conn.execute("UPDATE submissions SET status=?, risk=?, router_note=? WHERE id=?",
                     (status, risk["risk"], risk["note"], sid))
        if risk["risk"] == "exempt":
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "exempt_approve", risk["note"], "exemption-policy:" + user["email"], _now()),
            )
        audit(conn, user["email"], "submit_review", f"{sid} risk={risk['risk']}")
        conn.commit()
        return {"status": status, **risk}
    finally:
        conn.close()


@app.post("/submissions/{sid}/review")
def review(req: Request, sid: str, body: ReviewIn):
    _require_same_origin(req)
    conn = connect()
    try:
        user = _user(req, conn)
        sub = _visible_sub(conn, user, sid)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/approvers decide")
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
            signed = signing.sign_approval(conn, sub["workspace_id"], sid, rev["id"], rev["content"], user["email"],
                                           user["role"], self_approved=self_approved)
            conn.execute("UPDATE submissions SET status='Signed' WHERE id=?", (sid,))
            audit(conn, user["email"], "approve", f"{sid} signed {signed['poc_id']}" + (" (self-approved)" if self_approved else ""))
            conn.commit()
            return {"status": "Signed", "poc_id": signed["poc_id"], "self_approved": self_approved}
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
    conn = connect()
    try:
        return signing.verify(conn, poc_id)
    finally:
        conn.close()


@app.post("/verify/{poc_id}")
def verify_published(poc_id: str, body: VerifyIn):
    """Public, no sign-in: is this the exact text that was approved?"""
    conn = connect()
    try:
        return signing.verify(conn, poc_id, body.content)
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
        return {
            "by_checker": by_checker, "decisions": {r["action"]: r["c"] for r in decision_counts},
            "dispute_overrides": [dict(d) for d in overrides],
            "categories": [dict(b) for b in broken],
            "unsupported_claims": unsupported,
            "statuses": [dict(s) for s in statuses],
            "possibly_unclear_rules": [dict(v) for v in vague],
            "ai_calls": [dict(a) for a in ai_calls],
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
