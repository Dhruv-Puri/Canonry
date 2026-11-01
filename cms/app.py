"""Canonry demo CMS — an external publisher that cannot publish without a seal.

The flow is deliberately one-way:

1. An editor submits a post here. The CMS asks Canonry's public API to check it
   and stores the returned submission id. The post stays `pending`.
2. A reviewer approves it in Canonry. Canonry signs it and sends a `signed`
   webhook, HMAC-signed with the endpoint secret.
3. This service verifies the signature and timestamp, compares the signed
   content hash with the post it holds, and only then publishes. A changed post,
   a missing event, a bad signature or an `approved` event alone leaves it held.

It is a separate Render service on purpose: the publisher is a different trust
domain, so "review is optional" is no longer true for anything that goes through
it. The demo is intentionally open; put it behind your own access control before
using it for real content.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

ENGINE_URL = (os.environ.get("CANONRY_ENGINE_URL") or "http://127.0.0.1:8000").rstrip("/")
API_KEY = (os.environ.get("CANONRY_API_KEY") or "").strip()
WEBHOOK_SECRET = (os.environ.get("CANONRY_WEBHOOK_SECRET") or "").strip()
DB_PATH = os.environ.get("CANONRY_CMS_DB") or os.path.join(os.path.dirname(__file__), "..", "db", "cms.db")
PUBLIC_URL = (os.environ.get("CANONRY_CMS_PUBLIC_URL") or "http://localhost:8100").rstrip("/")
SITE_NAME = os.environ.get("CANONRY_CMS_NAME") or "The Quillmark Edit"
MAX_BODY = 200_000
MAX_SKEW_SECONDS = 300

app = FastAPI(title="Canonry demo CMS", version="1.0.0")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema() -> None:
    conn = connect()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
          submission_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
          reason TEXT, poc_id TEXT, verify_url TEXT, content_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
          id TEXT PRIMARY KEY, event TEXT, received_at TEXT NOT NULL,
          outcome TEXT, detail TEXT
        );
        """)
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def startup() -> None:
    init_schema()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def post_row(post_id: str):
    conn = connect()
    try:
        return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    finally:
        conn.close()


def update_post(post_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn = connect()
    try:
        conn.execute(f"UPDATE posts SET {assignments} WHERE id = ?", (*fields.values(), post_id))
        conn.commit()
    finally:
        conn.close()


def engine_check(title: str, body: str, post_id: str) -> Dict[str, Any]:
    if not API_KEY:
        raise RuntimeError("CANONRY_API_KEY is not set on the CMS service.")
    headers = {"Authorization": f"Bearer {API_KEY}", "Idempotency-Key": f"cms-{post_id}"}
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{ENGINE_URL}/api/v1/checks", headers=headers,
                           json={"title": title, "channel": "web", "source_type": "in-house",
                                 "content": body})
    if resp.status_code >= 400:
        raise RuntimeError(f"Engine returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


# ---- public site -------------------------------------------------------------

def layout(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · {html.escape(SITE_NAME)}</title>
<style>
  :root {{ --ink:#101828; --teal:#0E7C7B; --sand:#F4EDE5; --muted:#667085; --line:#E4E7EC; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#FBFAF7; color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  header, main, footer {{ max-width:760px; margin:0 auto; padding:0 24px; }}
  header {{ padding-top:38px; padding-bottom:26px; display:flex; align-items:center; gap:12px; }}
  .mark {{ width:34px;height:34px;border:2px solid var(--teal);border-radius:50%;display:grid;place-items:center;color:var(--teal);font-weight:700; }}
  a {{ color:var(--teal); }}
  h1 {{ font-family:Georgia,serif; font-size:clamp(2rem,5vw,3.2rem); line-height:1.08; margin:8px 0 10px; letter-spacing:-.025em; }}
  .meta {{ color:var(--muted); font-size:13px; }}
  article {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:clamp(22px,4vw,40px); box-shadow:0 14px 40px rgba(16,24,40,.05); }}
  .seal {{ display:flex; gap:14px; align-items:flex-start; background:#F0FDF9; border:1px solid #99F6E4; border-radius:12px; padding:14px 16px; margin-top:24px; font-size:13px; }}
  .seal strong {{ color:#065F46; }}
  form {{ display:grid; gap:12px; margin-top:24px; }}
  label {{ font-weight:600; font-size:14px; }}
  input, textarea {{ width:100%; padding:12px 14px; border:1px solid var(--line); border-radius:10px; font:inherit; background:#fff; }}
  textarea {{ min-height:170px; resize:vertical; }}
  button {{ justify-self:start; background:var(--teal); color:white; border:0; border-radius:999px; padding:11px 20px; font:inherit; cursor:pointer; }}
  table {{ width:100%; border-collapse:collapse; margin-top:22px; font-size:14px; }}
  th, td {{ text-align:left; padding:11px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
  .pill {{ display:inline-block; border-radius:999px; padding:2px 9px; background:var(--sand); font-size:12px; }}
  .published {{ background:#D1FAE5; color:#065F46; }}
  .held {{ background:#FEF3C7; color:#92400E; }}
  footer {{ color:var(--muted); font-size:12px; padding:34px 24px 50px; }}
</style></head><body>
<header><span class="mark">C</span><strong>{html.escape(SITE_NAME)}</strong><span class="meta" style="margin-left:auto">published through Canonry</span></header>
<main>{content}</main>
<footer>Demo publisher · a post goes live only on a signed approval whose content hash matches the copy held here.</footer>
</body></html>"""


def _post_row(p) -> str:
    reason = f"<div class='meta'>{html.escape(p['reason'])}</div>" if p["reason"] else ""
    pill = "published" if p["status"] == "published" else "held"
    return (
        f"<tr><td><a href='/p/{html.escape(p['id'])}'>{html.escape(p['title'])}</a>"
        f"<div class='meta'>{html.escape(p['id'])}</div></td>"
        f"<td><span class='pill {pill}'>{html.escape(p['status'])}</span>{reason}</td>"
        f"<td>{html.escape(p['updated_at'][:19].replace('T', ' '))}</td></tr>"
    )


@app.get("/", response_class=HTMLResponse)
def home():
    conn = connect()
    try:
        posts = conn.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT 50").fetchall()
    finally:
        conn.close()
    rows = "".join(_post_row(p) for p in posts) or (
        "<tr><td colspan='3'>No posts yet. Write the first one below.</td></tr>")
    content = f"""
    <article>
      <div class="meta">THE EDITORIAL DESK</div>
      <h1>Publish only what passed.</h1>
      <p>Write a post. It goes to Canonry for checking; it can only appear here after a reviewer signs it and Canonry sends a <code>signed</code> webhook whose content hash matches this exact text.</p>
      <form method="post" action="/posts">
        <label for="title">Headline</label>
        <input id="title" name="title" maxlength="240" required placeholder="Launch note">
        <label for="body">Post</label>
        <textarea id="body" name="body" maxlength="{MAX_BODY}" required placeholder="Paste the copy that should be published."></textarea>
        <button type="submit">Send to Canonry</button>
      </form>
    </article>
    <article style="margin-top:22px">
      <div class="meta">THE QUEUE</div>
      <table><thead><tr><th>Post</th><th>State</th><th>Updated</th></tr></thead><tbody>{rows}</tbody></table>
    </article>"""
    return HTMLResponse(layout("Editorial desk", content))


@app.post("/posts")
async def create_post(req: Request):
    form = await req.form()
    title = " ".join(str(form.get("title") or "").split())[:240]
    body = str(form.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(422, "A headline and a post are required.")
    if len(body) > MAX_BODY:
        raise HTTPException(413, "That post is too long.")
    post_id = "post_" + hashlib.sha256(f"{title}\x00{body}\x00{time.time_ns()}".encode()).hexdigest()[:12]
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO posts (id, title, body, status, content_sha256, created_at, updated_at) "
            "VALUES (?,?,?,'pending',?,?,?)",
            (post_id, title, body, sha256_text(body), now(), now()))
        conn.commit()
    finally:
        conn.close()
    try:
        checked = engine_check(title, body, post_id)
        update_post(post_id, submission_id=checked.get("submission_id"), status="checked",
                    reason=f"{len(checked.get('findings', []))} finding(s) returned by Canonry")
    except Exception as exc:
        update_post(post_id, status="engine_error", reason=str(exc)[:400])
    return HTMLResponse(layout("Sent to Canonry", f"""
      <article><div class="meta">SENT TO CANONRY</div><h1>Held for review.</h1>
      <p><strong>{html.escape(title)}</strong> is stored here. It is not public. When a reviewer signs it in Canonry, the sealed webhook releases it.</p>
      <p><a href="/">Back to the desk</a> · <a href="/p/{post_id}">Open the held draft</a></p></article>"""), status_code=303)


@app.get("/p/{post_id}", response_class=HTMLResponse)
def view_post(post_id: str):
    post = post_row(post_id)
    if not post:
        raise HTTPException(404, "No such post.")
    if post["status"] != "published":
        return HTMLResponse(layout("Held", f"""
        <article><div class="meta">HELD · {html.escape(post['status'])}</div>
        <h1>{html.escape(post['title'])}</h1>
        <p>This post is not published. {html.escape(post['reason'] or 'It is waiting for a signed approval.')}</p>
        <p><a href="/">Back to the desk</a></p></article>"""), status_code=403)
    seal = ""
    if post["verify_url"]:
        seal = (f"<div class='seal'><span>✓</span><div><strong>Proof of Compliance</strong><br>"
                f"Seal <code>{html.escape(post['poc_id'] or '')}</code> · "
                f"<a href='{html.escape(post['verify_url'])}'>verify this exact text</a><br>"
                f"<span class='meta'>Signed approval {html.escape(post['poc_id'] or '')}; the seal covers the text below.</span></div></div>")
    return HTMLResponse(layout(post["title"], f"""
      <article><div class="meta">PUBLISHED · {html.escape((post['published_at'] or '')[:19].replace('T', ' '))}</div>
      <h1>{html.escape(post['title'])}</h1>
      <div style="white-space:pre-wrap; font-family:Georgia,serif; font-size:1.1rem">{html.escape(post['body'])}</div>
      {seal}</article>"""))


@app.get("/posts/{post_id}")
def post_json(post_id: str):
    post = post_row(post_id)
    if not post:
        raise HTTPException(404, "No such post.")
    return {k: post[k] for k in ("id", "title", "status", "submission_id", "poc_id", "verify_url",
                                  "reason", "content_sha256", "created_at", "updated_at", "published_at")}


@app.get("/healthz")
def health():
    conn = connect()
    try:
        count = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()["c"]
    finally:
        conn.close()
    return {"ok": True, "posts": count, "engine": ENGINE_URL, "api_key": bool(API_KEY),
            "webhook_secret": bool(WEBHOOK_SECRET), "signature_window_seconds": MAX_SKEW_SECONDS}


# ---- Canonry webhook ---------------------------------------------------------

@app.post("/webhooks/canonry")
async def canonry_webhook(req: Request):
    raw = await req.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Webhook payload too large.")
    if not WEBHOOK_SECRET:
        raise HTTPException(503, "CANONRY_WEBHOOK_SECRET is not configured.")
    timestamp = req.headers.get("x-canonry-timestamp") or ""
    signature = req.headers.get("x-canonry-signature") or ""
    try:
        age = abs(int(time.time()) - int(timestamp))
    except ValueError:
        raise HTTPException(401, "Missing or malformed signature timestamp.")
    if age > MAX_SKEW_SECONDS:
        raise HTTPException(401, "Signature timestamp is outside the five-minute window.")
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode("utf-8"),
                                    timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Bad HMAC signature.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Payload is not JSON.")
    delivery_id = req.headers.get("x-canonry-delivery") or payload.get("id") or ""
    event = req.headers.get("x-canonry-event") or payload.get("event") or ""
    data = payload.get("data") or {}
    if not delivery_id or event not in ("checked", "approved", "signed"):
        raise HTTPException(422, "Unknown event or missing delivery id.")
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM webhook_deliveries WHERE id = ?", (delivery_id,)).fetchone():
            return {"ok": True, "duplicate": True}
        post = conn.execute("SELECT * FROM posts WHERE submission_id = ?", (data.get("submission_id"),)).fetchone()
        outcome, detail = "ignored", "No post matches this submission."
        if post and event == "checked":
            conn.execute("UPDATE posts SET status='checked', reason=?, updated_at=? WHERE id=?",
                         (f"{data.get('findings', 0)} finding(s) returned by Canonry", now(), post["id"]))
            outcome, detail = "held", "Checked; waiting for review."
        elif post and event == "approved":
            conn.execute("UPDATE posts SET status='approved_waiting', reason='Approved; waiting for the signed seal', updated_at=? WHERE id=?",
                         (now(), post["id"]))
            outcome, detail = "held", "Approved is not enough; the signed event is required."
        elif post and event == "signed":
            if data.get("content_kind") != "text":
                conn.execute("UPDATE posts SET status='held', reason=?, updated_at=? WHERE id=?",
                             ("This publisher handles text posts; the approved item is a file.", now(), post["id"]))
                outcome, detail = "held", "file content is not publishable here"
            elif not hmac.compare_digest(str(data.get("content_sha256") or ""), post["content_sha256"]):
                conn.execute("UPDATE posts SET status='held_hash_mismatch', reason=?, updated_at=? WHERE id=?",
                             ("The signed hash does not match the copy held here. Edit or re-check the post.", now(), post["id"]))
                outcome, detail = "held", "content hash mismatch"
            elif not data.get("poc_id") or not data.get("verify_url"):
                conn.execute("UPDATE posts SET status='held', reason=?, updated_at=? WHERE id=?",
                             ("The signed event did not include a seal id and verify URL.", now(), post["id"]))
                outcome, detail = "held", "incomplete signed event"
            else:
                conn.execute(
                    "UPDATE posts SET status='published', reason=NULL, poc_id=?, verify_url=?, "
                    "published_at=?, updated_at=? WHERE id=?",
                    (data["poc_id"], data["verify_url"], now(), now(), post["id"]))
                outcome, detail = "published", f"Seal {data['poc_id']} verified."
        conn.execute(
            "INSERT INTO webhook_deliveries (id, event, received_at, outcome, detail) VALUES (?,?,?,?,?)",
            (delivery_id, event, now(), outcome, detail))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "event": event, "outcome": outcome, "detail": detail}
