"""Canonry analysis engine — FastAPI web/API (doc Section 9.3).

Background job queue for the event build = FastAPI background tasks; the flow
is small documents, so checks run inline but through the same job-table seam
(check_runs row) that a Redis queue adapter replaces later.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import claims
import gateway
import pipeline
import signing
from checkers import Ctx
from db import (
    _now, audit, connect, create_session, gen_id, get_knowledge_version,
    init_schema, resolve_session,
)
from seed import seed

app = FastAPI(title="Canonry engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    init_schema()
    seed()


def _user(req: Request, conn: sqlite3.Connection):
    token = req.cookies.get("canonry_session") or req.headers.get("x-canon-session")
    user = resolve_session(conn, token)
    if not user:
        raise HTTPException(401, "Sign in required")
    return user


def _ws(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
    return row["id"]


# ---- auth -------------------------------------------------------------------

class LoginIn(BaseModel):
    email: str


@app.post("/login")
def login(body: LoginIn):
    conn = connect()
    try:
        email = body.email.strip().lower()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            uid = gen_id("usr")
            conn.execute(
                "INSERT INTO users (id, workspace_id, email, name, role, created_at) VALUES (?,?,?,?,?,?)",
                (uid, _ws(conn), email, email.split("@")[0].title(), "creator", _now()),
            )
        else:
            uid = user["id"]
        token = create_session(conn, uid)
        resp = JSONResponse({"ok": True, "user_id": uid})
        resp.set_cookie("canonry_session", token, httponly=True, samesite="lax")
        conn.commit()
        return resp
    finally:
        conn.close()


@app.get("/me")
def me(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        return dict(user)
    finally:
        conn.close()


@app.get("/workspace")
def workspace(req: Request):
    conn = connect()
    try:
        user = _user(req, conn)
        ws = _ws(conn)
        users = [dict(u) for u in conn.execute("SELECT id, name, email, role FROM users").fetchall()]
        rules = conn.execute("SELECT COUNT(*) c FROM rules WHERE status='approved'").fetchone()["c"]
        facts = conn.execute("SELECT COUNT(*) c FROM facts WHERE confidential=0").fetchone()["c"]
        terms = conn.execute("SELECT COUNT(*) c FROM terms").fetchone()["c"]
        vague = [dict(r) for r in conn.execute(
            "SELECT id, statement, vague_flag FROM rules WHERE vague_flag IS NOT NULL").fetchall()]
        return {
            "workspace": ws, "rules": rules, "facts": facts, "terms": terms,
            "users": users, "vague_rules": vague,
            "knowledge_version": get_knowledge_version(conn),
            "me": dict(user),
        }
    finally:
        conn.close()


# ---- knowledge base ----------------------------------------------------------

def lint_rule(stmt: str, do: Optional[str], dont: Optional[str], existing: List[str]) -> Optional[str]:
    cheap = not stmt.strip()
    short = len(stmt.strip()) < 25
    no_examples = not (do or dont)
    words = [w.lower() for w in stmt.split()]
    lack = any(w in words for w in ("bold", "fresh", "engaging", "nice")) and no_examples
    contradictory = stmt.count(" and ") > 0 and (("formal" in words and "fresh" in words) or ("always" in words and "never" in words))
    duplicate = stmt[:40] in existing
    if contradictory:
        return "vague_contradictory"
    if duplicate:
        return "vague_duplicate"
    if short or no_examples or lack or cheap:
        return "vague_no_examples"
    return None


@app.post("/rules/import")
def rules_import(req: Request, body: Dict[str, Any]):
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/owners import guidelines")
        ws = req.state.ws = _ws(conn)
        lines = (body.get("csv") or "").strip().splitlines()
        if not lines:
            raise HTTPException(400, "Paste CSV with header: id,category,statement,do_example,dont_example,severity")
        header = [h.strip() for h in lines[0].split(",")]
        existing = [r["statement"][:40] for r in conn.execute(
            "SELECT statement FROM rules WHERE workspace_id=?", (ws,)).fetchall()]
        added, flagged = 0, []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            r = dict(zip(header, parts + [None] * (len(header) - len(parts))))
            rid = r.get("id") or gen_id("r")
            stmt = r.get("statement") or ""
            if not stmt:
                continue
            vague = lint_rule(stmt, r.get("do_example"), r.get("dont_example"), existing)
            status = "flagged" if vague else "approved"
            conn.execute(
                "INSERT OR REPLACE INTO rules (id, workspace_id, category, statement, do_example, "
                "dont_example, severity, status, vague_flag, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, ws, r.get("category", "General"), stmt, r.get("do_example"),
                 r.get("dont_example"), r.get("severity", "medium"), status, vague, _now()),
            )
            added += 1
            if vague:
                flagged.append({"id": rid, "statement": stmt, "flag": vague,
                                "rewrite_suggestion": rewrite_suggestion(stmt, vague)})
        audit(conn, user["email"], "import_rules", f"imported {added} rules, {len(flagged)} flagged")
        conn.commit()
        return {"added": added, "flagged": flagged}
    finally:
        conn.close()


def rewrite_suggestion(stmt: str, flag: str) -> str:
    if flag == "vague_contradictory":
        return "Split the rule: one requirement per rule, then approve each separately."
    if flag == "vague_duplicate":
        return "Merge with the existing rule on this topic; keep one canonical statement."
    return "Make it checkable: state one requirement plus one do and one don't example."


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


@app.patch("/rules/{rule_id}")
def update_rule(req: Request, rule_id: str, body: Dict[str, Any]):
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Reviewers edit guidelines; others may suggest")
        ws = _ws(conn)
        vague = lint_rule(body.get("statement", ""), body.get("do_example"), body.get("dont_example"), [])
        conn.execute(
            "UPDATE rules SET statement=?, do_example=?, dont_example=?, status=?, vague_flag=? "
            "WHERE id=? AND workspace_id=?",
            (body.get("statement"), body.get("do_example"), body.get("dont_example"),
             "flagged" if vague else "approved", vague, rule_id, ws),
        )
        audit(conn, user["email"], "edit_rule", f"{rule_id}")
        conn.commit()
        return {"ok": True, "flag": vague}
    finally:
        conn.close()


@app.post("/rules/{rule_id}/preview-change")
def preview_rule_change(req: Request, rule_id: str, body: Dict[str, Any]):
    """Rule tests & change preview (doc 5.4): which examples and past approved
    content would fail if this edit goes live."""
    conn = connect()
    try:
        _user(req, conn)
        ws = _ws(conn)
        rule = conn.execute("SELECT * FROM rules WHERE id=? AND workspace_id=?", (rule_id, ws)).fetchone()
        if not rule:
            raise HTTPException(404, "Rule not found")
        impacts: List[Dict[str, Any]] = []
        dont = rule["dont_example"] or ""
        do = rule["do_example"] or ""
        # words the *dont- example* shares with approved content
        banned_tokens = [w for w in dont.replace(",", " ").split() if len(w) > 4]
        approved = conn.execute(
            "SELECT s.id, s.title, v.content FROM submissions s JOIN revisions v ON v.submission_id = s.id "
            "WHERE s.workspace_id=? AND s.status IN ('Approved','Signed') ORDER BY v.revision_no DESC",
            (ws,),
        ).fetchall()
        seen = set()
        for a in approved:
            for tok in banned_tokens:
                if tok and tok in a["content"] and a["id"] not in seen:
                    seen.add(a["id"])
                    impacts.append({"submission_id": a["id"], "title": a["title"],
                                    "because": f"contains \"{tok}\" (from the don't-example)"})
                    break
        return {"rule": rule_id, "new_examples_would_be_tests": bool(do or dont),
                "impacted_approved_content": impacts, "impacted_count": len(impacts)}
    finally:
        conn.close()


@app.get("/facts")
def get_facts(req: Request, hashes: Optional[str] = None):
    conn = connect()
    try:
        user = _user(req, conn)
        ws = _ws(conn)
        confidential_ok = user["role"] in ("reviewer", "admin", "creator")
        rows = conn.execute("SELECT * FROM facts WHERE workspace_id=? ORDER BY id", (ws,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d["confidential"] and not confidential_ok:
                d["text"] = "[Confidential] cited excerpt only"
            d["active"] = claims._fact_active(r)
            out.append(d)
        return {"facts": out}
    finally:
        conn.close()


class FactIn(BaseModel):
    text: str
    category: str
    owner: str = "Marketing Ops"
    source: str = ""
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidential: int = 0


@app.post("/facts")
def add_fact(req: Request, body: FactIn):
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/owners add facts")
        fid = body.text.lower().startswith("legacy") and None or None
        fid = gen_id("F-")
        conn.execute(
            "INSERT INTO facts (id, workspace_id, text, category, owner, source, valid_from, valid_to, "
            "confidential, superseded, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?)",
            (fid, _ws(conn), body.text, body.category, body.owner, body.source,
             body.valid_from, body.valid_to, body.confidential, _now()),
        )
        audit(conn, user["email"], "add_fact", f"{fid}: {body.text[:60]}")
        conn.commit()
        return {"id": fid}
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

class SubmitIn(BaseModel):
    title: str
    channel: str
    source_type: str
    content: str


@app.post("/submissions")
def submit(req: Request, body: SubmitIn):
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
        result = run_check_for_submission(conn, sid, body.content, user["role"])
        resp = {"submission_id": sid, "revision_id": result["revision_id"], **{
            k: v for k, v in result.items() if k != "revision_id"}}
        conn.commit()
        return resp
    finally:
        conn.close()


def run_check_for_submission(conn: sqlite3.Connection, sid: str, content: str, role: str) -> Dict[str, Any]:
    rev_no = conn.execute("SELECT COALESCE(MAX(revision_no),0)+1 AS n FROM revisions WHERE submission_id=?", (sid,)).fetchone()["n"]
    rid = gen_id("rev")
    conn.execute(
        "INSERT INTO revisions (id, submission_id, content, revision_no, created_at) VALUES (?,?,?,?,?)",
        (rid, sid, content, rev_no, _now()),
    )
    conn.execute("UPDATE submissions SET status = CASE WHEN status='Draft' THEN 'Checked' ELSE status END WHERE id=?", (sid,))
    result = pipeline.run_check(conn, rid, role)
    result["revision_id"] = rid
    return result


@app.get("/submissions")
def list_submissions(req: Request):
    conn = connect()
    try:
        _user(req, conn)
        rows = conn.execute(
            "SELECT s.*, (SELECT content FROM revisions WHERE submission_id = s.id ORDER BY revision_no DESC LIMIT 1) "
            "content, (SELECT COUNT(*) FROM findings f WHERE f.revision_id IN "
            "(SELECT id FROM revisions WHERE submission_id = s.id) AND f.status='open') open_findings, "
            "(SELECT signature FROM proof_of_compliance WHERE revision_id = (SELECT id FROM revisions "
            "WHERE submission_id = s.id ORDER BY revision_no DESC LIMIT 1)) poc_sig "
            "FROM submissions s ORDER BY s.created_at DESC").fetchall()
        return {"submissions": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/submissions/{sid}")
def get_submission(req: Request, sid: str):
    conn = connect()
    try:
        user = _user(req, conn)
        sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
        if not sub:
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
                if c["type"] == "fact":
                    row = conn.execute("SELECT text, owner, valid_to, confidential FROM facts WHERE id=?", (c["id"],)).fetchone()
                    if row:
                        c["excerpt"] = row["text"]
                        c["owner"] = row["owner"]
                        c["valid_to"] = row["valid_to"]
                elif c["type"] == "term":
                    row = conn.execute(
                        "SELECT preferred FROM terms WHERE id=? AND workspace_id=?", (c["id"], sub["workspace_id"])
                    ).fetchone()
                    if row and row["preferred"]:
                        c["excerpt"] = "approved term: " + row["preferred"]
                elif c["type"] == "rule":
                    row = conn.execute("SELECT statement FROM rules WHERE id=? AND workspace_id=?", (c["id"], sub["workspace_id"])).fetchone()
                    if row:
                        c["excerpt"] = row["statement"]
        decisions = [dict(d) for d in conn.execute(
            "SELECT * FROM decisions WHERE revision_id=? ORDER BY at", (latest["id"] if latest else "",)).fetchall()]
        approvals = [dict(a) for a in conn.execute(
            "SELECT * FROM approvals WHERE submission_id=? ORDER BY at", (sid,)).fetchall()]
        poc = conn.execute("SELECT id, created_at FROM proof_of_compliance WHERE submission_id=? ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
        return {"submission": dict(sub), "revisions": revs, "latest_revision": latest,
                "findings": findings, "decisions": decisions, "approvals": approvals,
                "poc": dict(poc) if poc else None, "me": dict(user)}
    finally:
        conn.close()


class ResolveIn(BaseModel):
    revision_id: str
    finding_id: str
    action: str  # accept | edit | dispute
    replacement: Optional[str] = None
    reason: Optional[str] = None


@app.post("/submissions/{sid}/resolve")
def resolve_finding(req: Request, sid: str, body: ResolveIn):
    conn = connect()
    try:
        user = _user(req, conn)
        f = conn.execute("SELECT * FROM findings WHERE id=? AND revision_id=?", (body.finding_id, body.revision_id)).fetchone()
        if not f:
            raise HTTPException(404, "Finding not found")
        rev = conn.execute("SELECT * FROM revisions WHERE id=?", (body.revision_id,)).fetchone()
        content = rev["content"]
        suggestion = json.loads(f["suggestion_json"]) if f["suggestion_json"] not in (None, "", "null") else {}
        if body.action == "accept":
            repl = (suggestion or {}).get("replace")
            op = (suggestion or {}).get("operation", "replace")
            if not repl and op == "remove":
                if f["span_text"] and f["span_text"] in content:
                    content = content.replace(f["span_text"], "").replace("  ", " ")
            elif repl and f["span_text"] and f["span_text"] in content:
                content = content.replace(f["span_text"], repl)
        elif body.action == "edit" and body.replacement:
            if f["span_text"] and f["span_text"] in content:
                content = content.replace(f["span_text"], body.replacement)
        elif body.action == "dispute" and not body.reason:
            raise HTTPException(400, "Disputes require a reason (rule applies? unclear? fact outdated? AI misread?)")
        conn.execute(
            "INSERT INTO decisions (id, revision_id, finding_id, action, replacement, reason, by_user, at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (gen_id("dec"), body.revision_id, body.finding_id, body.action, body.replacement, body.reason, user["email"], _now()),
        )
        conn.execute("UPDATE findings SET status=? WHERE id=?",
                     ({"accept": "accepted", "edit": "edited", "dispute": "disputed"}[body.action], body.finding_id))
        result = run_check_for_submission(conn, sid, content, user["role"])
        audit(conn, user["email"], f"finding_{body.action}", f"{body.finding_id} reason={body.reason or ''}")
        conn.commit()
        return {"ok": True, "revision_id": result["revision_id"], "ai_pending": result["ai_pending"]}
    finally:
        conn.close()


@app.post("/submissions/{sid}/recheck")
def recheck(req: Request, sid: str):
    conn = connect()
    try:
        user = _user(req, conn)
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        result = run_check_for_submission(conn, sid, rev["content"], user["role"])
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
        return {"risk": "high", "router": "regional legal lead (Karan in the demo)",
                "note": "Public channel + AI-assisted + contradicted/outdated or unsupported claims; concerns pre-highlighted, SLA timer starts."}
    return {"risk": "medium", "router": "one reviewer", "note": "Judgement calls only; one reviewer, not a bottleneck."}


class ReviewIn(BaseModel):
    action: str  # approve | request_changes | override | comment
    reason: Optional[str] = None
    finding_id: Optional[str] = None
    comment: Optional[str] = None


@app.post("/submissions/{sid}/submit-review")
def submit_review(req: Request, sid: str):
    conn = connect()
    try:
        user = _user(req, conn)
        sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if not sub:
            raise HTTPException(404)
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
    conn = connect()
    try:
        user = _user(req, conn)
        if user["role"] not in ("reviewer", "admin"):
            raise HTTPException(403, "Only reviewers/approvers decide")
        sub = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if not sub:
            raise HTTPException(404)
        rev = conn.execute(
            "SELECT * FROM revisions WHERE submission_id=? ORDER BY revision_no DESC LIMIT 1", (sid,)).fetchone()
        open_high = conn.execute(
            "SELECT COUNT(*) c FROM findings WHERE revision_id=? AND status='open' AND severity='high'",
            (rev["id"],)).fetchone()["c"]
        if body.action == "approve":
            if open_high > 0:
                raise HTTPException(409, "High-severity findings must be resolved or explicitly overridden before approval — the reviewer decides, never the AI.")
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "approve", body.comment, user["email"], _now()),
            )
            signed = signing.sign_approval(conn, sub["workspace_id"], sid, rev["id"], rev["content"], user["email"], user["role"])
            conn.execute("UPDATE submissions SET status='Signed' WHERE id=?", (sid,))
            audit(conn, user["email"], "approve", f"{sid} signed {signed['poc_id']}")
            conn.commit()
            return {"status": "Signed", "poc_id": signed["poc_id"]}
        if body.action == "override":
            if not body.reason or body.finding_id is None:
                raise HTTPException(400, "Overrides need the finding id and a reason")
            conn.execute(
                "INSERT INTO decisions (id, revision_id, finding_id, action, replacement, reason, by_user, at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (gen_id("dec"), rev["id"], body.finding_id, "override", None, body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE findings SET status='disputed' WHERE id=?", (body.finding_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM findings WHERE revision_id=? AND status='open'", (rev["id"],)).fetchone()["c"]
            status = "Changes requested" if remaining else sub["status"]
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "override", body.reason, user["email"], _now()),
            )
            conn.execute("UPDATE submissions SET status=? WHERE id=?", (status, sid))
            audit(conn, user["email"], "override", f"{body.finding_id}: {body.reason}")
            conn.commit()
            return {"status": status, "remaining_open": remaining}
        if body.action == "request_changes":
            conn.execute(
                "INSERT INTO approvals (id, submission_id, action, reason, reviewer, at) VALUES (?,?,?,?,?,?)",
                (gen_id("app"), sid, "request_changes", body.comment, user["email"], _now()),
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


class OverrideIn(BaseModel):
    finding_id: str
    reason: str


# ---- Proof of Compliance verify ----------------------------------------------

@app.get("/verify/{poc_id}")
def verify_poc(poc_id: str):
    conn = connect()
    try:
        return signing.verify(conn, poc_id, None)
    finally:
        conn.close()


# ---- insights, alerts, evaluation --------------------------------------------

@app.get("/insights")
def insights(req: Request):
    conn = connect()
    try:
        _user(req, conn)
        by_checker = {}
        for r in conn.execute(
                "SELECT checker, COUNT(*) c, SUM(CASE WHEN tier='definite' THEN 1 ELSE 0 END) definite FROM findings GROUP BY checker").fetchall():
            by_checker[r["checker"]] = dict(r)
        decisions = conn.execute("SELECT action, COUNT(*) c FROM decisions GROUP BY action").fetchall()
        overrides = conn.execute(
            "SELECT s.title, d.reason, d.at FROM decisions d JOIN revisions v ON v.id=d.revision_id "
            "JOIN submissions s ON s.id=v.submission_id WHERE d.action IN ('dispute','override') ORDER BY d.at DESC LIMIT 20").fetchall()
        broken = conn.execute(
            "SELECT findings.category, COUNT(*) c FROM findings GROUP BY category ORDER BY c DESC").fetchall()
        unsupported = conn.execute(
            "SELECT COUNT(*) c FROM findings WHERE category='unsupported_claim'").fetchone()["c"]
        statuses = conn.execute("SELECT status, COUNT(*) c FROM submissions GROUP BY status").fetchall()
        vague = conn.execute("SELECT id, statement, vague_flag FROM rules WHERE vague_flag IS NOT NULL").fetchall()
        ai_calls = conn.execute(
            "SELECT task, provider, model, COUNT(*) c, SUM(ok) ok FROM ai_calls GROUP BY task, provider, model").fetchall()
        return {
            "by_checker": by_checker, "decisions": dict(decisions[0]) if decisions else {},
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
        _user(req, conn)
        today = date.today()
        expired = conn.execute(
            "SELECT * FROM facts WHERE valid_to IS NOT NULL AND valid_to < ?", (today,)).fetchall()
        alerts = []
        for f in expired:
            used = conn.execute(
                "SELECT DISTINCT s.id, s.title, s.status FROM submissions s JOIN revisions v ON v.submission_id=s.id "
                "JOIN decisions d ON d.revision_id=v.id JOIN findings fnd ON fnd.id=d.finding_id "
                "WHERE fnd.citations_json LIKE ? AND s.status IN ('Approved','Signed')",
                (f'"{f["id"]}"%',),
            ).fetchall()
            alerts.append({
                "fact": dict(f), "active": claims._fact_active(f),
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
        _user(req, conn)
        pend = conn.execute(
            "SELECT r.id rid, s.id, r.started_at FROM revisions r JOIN submissions s on s.id=r.submission_id LIMIT 0").fetchall()
        return {"pending": [dict(p) for p in pend]}
    finally:
        conn.close()


@app.get("/ai-status")
def ai_status():
    conn = connect()
    try:
        providers = gateway.provider_list()
        calls = conn.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 20").fetchall()
        return {
            "providers": providers,
            "prompt_versions": {"claims": gateway.PROMPT_VERSION, "tone": pipeline.TONE_SYSTEM[:4] + "...tone@1"},
            "data_policy": "Only needed excerpts go to the provider — never the whole knowledge base; confidential facts are excluded for free APIs.",
            "degradation": "With no model available rule-based findings still arrive and AI checks are marked pending.",
            "recent_calls": [dict(c) for c in calls],
        }
    finally:
        conn.close()
