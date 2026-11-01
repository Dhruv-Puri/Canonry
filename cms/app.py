"""Canonry demo publisher — a CMS that cannot publish without a seal.

The flow is deliberately one-way:

1. An editor writes a post here. The publisher sends it to Canonry's public API
   (`POST /api/v1/checks`, with an Idempotency-Key and `submit_for_review`), so it
   lands in the reviewer's queue. The post stays held.
2. A reviewer approves it in Canonry. Canonry signs it and sends a `signed`
   webhook, HMAC-signed with the endpoint secret.
3. The publisher checks the signature and timestamp, fetches the approved text
   through the API, checks that its SHA-256 equals the hash in the signed event,
   and only then publishes exactly that text with a link to verify the seal. A
   bad signature, an `approved` event alone or a hash that does not match leaves
   the post held.

Two ways to run it:

* **Inside the engine** (the live demo and `engine/run_local.py`): the engine
  mounts this app at `/cms`, issues its API key and webhook endpoint at boot and
  calls `configure()`. Nothing to deploy or set.
* **As its own service** (`cms/Dockerfile`): set CANONRY_ENGINE_URL,
  CANONRY_API_KEY and CANONRY_WEBHOOK_SECRET, and add this service's
  `/webhooks/canonry` URL as a webhook endpoint in Canonry.

The demo is open to anyone with the link; put it behind your own access
control before using it for real content.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

MAX_BODY = 20_000
MAX_SKEW_SECONDS = 300


class Config:
    engine_url = (os.environ.get("CANONRY_ENGINE_URL") or "http://127.0.0.1:8000").rstrip("/")
    api_key = (os.environ.get("CANONRY_API_KEY") or "").strip()
    webhook_secret: Callable[[], str] = staticmethod(lambda: (os.environ.get("CANONRY_WEBHOOK_SECRET") or "").strip())
    db_path = os.environ.get("CANONRY_CMS_DB") or os.path.join(os.path.dirname(__file__), "..", "db", "cms.db")
    canonry_url = (os.environ.get("CANONRY_WEB_URL") or "").rstrip("/")
    site_name = os.environ.get("CANONRY_CMS_NAME") or "The Quillmark Edit"
    transport: Optional[httpx.AsyncBaseTransport] = None  # in-process calls when mounted in the engine
    webhooks_ready = True
    note = ""


def configure(**settings: Any) -> None:
    """Used by the engine when it mounts this app: key, secret, database, links."""
    global _schema_ready
    for name, value in settings.items():
        if not hasattr(Config, name):
            raise AttributeError(name)
        setattr(Config, name, staticmethod(value) if name == "webhook_secret" else value)
    _schema_ready = False


app = FastAPI(title="Canonry demo publisher", version="1.1.0")
_schema_ready = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    global _schema_ready
    os.makedirs(os.path.dirname(os.path.abspath(Config.db_path)), exist_ok=True)
    conn = sqlite3.connect(Config.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    if not _schema_ready:  # a mounted app never receives its own startup event
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
        _schema_ready = True
    return conn


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def post_row(post_id: str):
    conn = connect()
    try:
        return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    finally:
        conn.close()


def update_post(post_id: str, **fields: Any) -> None:
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn = connect()
    try:
        conn.execute(f"UPDATE posts SET {assignments} WHERE id = ?", (*fields.values(), post_id))
        conn.commit()
    finally:
        conn.close()


def _engine() -> httpx.AsyncClient:
    if Config.transport is not None:
        return httpx.AsyncClient(transport=Config.transport, base_url="http://engine", timeout=120)
    return httpx.AsyncClient(base_url=Config.engine_url, timeout=120)


def _engine_error(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    message = detail.get("message") if isinstance(detail, dict) else detail
    return f"Canonry answered {resp.status_code}: {message or resp.text[:200]}"


async def engine_check(title: str, body: str, post_id: str) -> Dict[str, Any]:
    if not Config.api_key:
        raise RuntimeError("This publisher has no Canonry API key (set CANONRY_API_KEY).")
    async with _engine() as client:
        resp = await client.post(
            "/api/v1/checks",
            headers={"Authorization": f"Bearer {Config.api_key}", "Idempotency-Key": f"cms-{post_id}"},
            json={"title": title, "channel": "web", "source_type": "in-house", "content": body,
                  "submit_for_review": True})
    if resp.status_code >= 400:
        raise RuntimeError(_engine_error(resp))
    return resp.json()


async def approved_text(submission_id: str) -> str:
    async with _engine() as client:
        resp = await client.get(f"/api/v1/submissions/{submission_id}",
                                headers={"Authorization": f"Bearer {Config.api_key}"})
    if resp.status_code >= 400:
        raise RuntimeError(_engine_error(resp))
    return ((resp.json().get("latest_revision") or {}).get("content")) or ""


# ---- pages -------------------------------------------------------------------

def base_href(req: Request) -> str:
    """Relative path from this page to the publisher's root, so the links work
    at /, at /cms/ in the engine and at /engine/cms behind the web app's proxy."""
    root = (req.scope.get("root_path") or "").rstrip("/")
    path = req.url.path
    rest = path[len(root):] if root and path.startswith(root) else path
    if rest == "":
        return root.rsplit("/", 1)[-1] + "/"
    depth = rest.count("/") - 1
    return "../" * depth if depth > 0 else "./"


def layout(title: str, content: str, refresh: bool = False) -> str:
    meta = '<meta http-equiv="refresh" content="6">' if refresh else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{html.escape(title)} · {html.escape(Config.site_name)}</title>
<style>
  :root {{ --ink:#101828; --teal:#0E7C7B; --sand:#F4EDE5; --muted:#5d6676; --line:#E4E7EC; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#FBFAF7; color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  header, main, footer {{ max-width:760px; margin:0 auto; padding:0 18px; }}
  header {{ padding-top:30px; padding-bottom:22px; display:flex; flex-wrap:wrap; align-items:center; gap:12px; }}
  .mark {{ width:34px;height:34px;border:2px solid var(--teal);border-radius:50%;display:grid;place-items:center;color:var(--teal);font-weight:700; }}
  a {{ color:var(--teal); }}
  h1 {{ font-family:Georgia,serif; font-size:clamp(1.8rem,5vw,3rem); line-height:1.1; margin:8px 0 10px; letter-spacing:-.02em; overflow-wrap:anywhere; }}
  .meta {{ color:var(--muted); font-size:13px; overflow-wrap:anywhere; }}
  article {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:clamp(18px,4vw,36px); box-shadow:0 14px 40px rgba(16,24,40,.05); margin-bottom:20px; }}
  .seal {{ display:flex; gap:14px; align-items:flex-start; background:#F0FDF9; border:1px solid #99F6E4; border-radius:12px; padding:14px 16px; margin-top:24px; font-size:14px; overflow-wrap:anywhere; }}
  .seal strong {{ color:#065F46; }}
  .note {{ background:#FEF3C7; border:1px solid #FCD34D; border-radius:12px; padding:12px 14px; font-size:14px; }}
  form {{ display:grid; gap:10px; margin-top:20px; }}
  label {{ font-weight:600; font-size:14px; }}
  input, textarea {{ width:100%; padding:12px 14px; border:1px solid #D0D5DD; border-radius:10px; font:inherit; background:#fff; }}
  textarea {{ min-height:150px; resize:vertical; }}
  button {{ justify-self:start; background:var(--teal); color:white; border:0; border-radius:999px; padding:11px 20px; font:inherit; cursor:pointer; }}
  button:disabled {{ opacity:.6; cursor:progress; }}
  ol {{ padding-left:20px; }} li {{ margin:4px 0; }}
  table {{ width:100%; border-collapse:collapse; margin-top:16px; font-size:14px; }}
  th, td {{ text-align:left; padding:10px 6px; border-bottom:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }}
  .pill {{ display:inline-block; border-radius:999px; padding:2px 9px; background:var(--sand); font-size:12px; white-space:nowrap; }}
  .published {{ background:#D1FAE5; color:#065F46; }}
  .held {{ background:#FEF3C7; color:#92400E; }}
  footer {{ color:var(--muted); font-size:12px; padding:20px 18px 44px; }}
</style></head><body>
<header><span class="mark">C</span><strong>{html.escape(Config.site_name)}</strong><span class="meta" style="margin-left:auto">demo publisher · published through Canonry</span></header>
<main>{content}</main>
<footer>A post goes live only on a signed approval from Canonry whose content hash matches the text published here.</footer>
</body></html>"""


STATE_TEXT = {
    "pending": "Sending to Canonry…",
    "in_review": "In Canonry's review queue",
    "checked": "Checked by Canonry",
    "approved_waiting": "Approved; waiting for the signed seal",
    "held_hash_mismatch": "Held: the signed text does not match",
    "held": "Held",
    "engine_error": "Not sent: Canonry could not be reached",
    "published": "Published",
}


def _canonry_link(path: str, label: str) -> str:
    if not Config.canonry_url:
        return html.escape(label)
    return f"<a href='{html.escape(Config.canonry_url + path)}'>{html.escape(label)}</a>"


def _post_row(p, base: str) -> str:
    reason = f"<div class='meta'>{html.escape(p['reason'])}</div>" if p["reason"] else ""
    pill = "published" if p["status"] == "published" else "held"
    return (
        f"<tr><td><a href='{base}p/{html.escape(p['id'])}'>{html.escape(p['title'])}</a></td>"
        f"<td><span class='pill {pill}'>{html.escape(STATE_TEXT.get(p['status'], p['status']))}</span>{reason}</td>"
        f"<td class='meta'>{html.escape(p['updated_at'][:16].replace('T', ' '))} UTC</td></tr>"
    )


def render_home(base: str) -> HTMLResponse:
    conn = connect()
    try:
        posts = conn.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT 30").fetchall()
        hooks = conn.execute("SELECT * FROM webhook_deliveries ORDER BY received_at DESC LIMIT 8").fetchall()
    finally:
        conn.close()
    rows = "".join(_post_row(p, base) for p in posts) or (
        "<tr><td colspan='3' class='meta'>No posts yet. Write the first one above.</td></tr>")
    hook_rows = "".join(
        f"<tr><td><code>{html.escape(h['event'] or '')}</code></td><td>{html.escape(h['outcome'] or '')}"
        f"<div class='meta'>{html.escape(h['detail'] or '')}</div></td>"
        f"<td class='meta'>{html.escape(h['received_at'][:19].replace('T', ' '))} UTC</td></tr>" for h in hooks
    ) or "<tr><td colspan='3' class='meta'>No webhooks received yet.</td></tr>"
    warning = ""
    if not Config.api_key or not Config.webhooks_ready:
        warning = (f"<p class='note'>{html.escape(Config.note or 'This publisher is not connected to Canonry yet.')}</p>")
    content = f"""
    <article>
      <div class="meta">THE EDITORIAL DESK</div>
      <h1>Publish only what passed.</h1>
      {warning}
      <ol>
        <li>Write a post below and press <strong>Send to Canonry</strong>. Canonry checks it and puts it in the review queue.</li>
        <li>In {_canonry_link('/review', 'Canonry')}, continue as <strong>Reviewer</strong>, open the post in the review queue, resolve or override any high-severity finding, and <strong>Approve</strong>.</li>
        <li>Canonry signs the approval and sends a signed webhook. This page publishes the approved text, with a link to verify the seal.</li>
      </ol>
      <form method="post" action="{base}posts" onsubmit="this.querySelector('button').disabled=true">
        <label for="title">Headline</label>
        <input id="title" name="title" maxlength="240" required placeholder="Pulse 2.0 is here">
        <label for="body">Post</label>
        <textarea id="body" name="body" maxlength="{MAX_BODY}" required placeholder="Paste the copy that should be published."></textarea>
        <button type="submit">Send to Canonry</button>
      </form>
    </article>
    <article>
      <div class="meta">POSTS</div>
      <table><thead><tr><th>Post</th><th>State</th><th>Updated</th></tr></thead><tbody>{rows}</tbody></table>
    </article>
    <article>
      <div class="meta">WEBHOOKS RECEIVED (signature checked)</div>
      <table><thead><tr><th>Event</th><th>Outcome</th><th>Received</th></tr></thead><tbody>{hook_rows}</tbody></table>
    </article>"""
    return HTMLResponse(layout("Editorial desk", content))


@app.get("/", response_class=HTMLResponse)
def home(req: Request):
    return render_home(base_href(req))


def _form_error(base: str, message: str, status: int) -> HTMLResponse:
    return HTMLResponse(layout("Not sent", f"""
      <article><div class="meta">NOT SENT</div><h1>Check the post.</h1>
      <p>{html.escape(message)}</p><p><a href="{base}">Back to the desk</a></p></article>"""), status_code=status)


@app.post("/posts")
async def create_post(req: Request):
    base = base_href(req)
    raw = await req.body()
    if len(raw) > MAX_BODY * 12:  # generous for percent-encoded text
        return _form_error(base, f"That post is longer than {MAX_BODY:,} characters.", 413)
    # a plain urlencoded form; no multipart parser needed
    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", errors="replace")).items()}
    title = " ".join(str(form.get("title") or "").split())[:240]
    # browsers send CRLF line ends; store the text as Canonry will hash it
    body = str(form.get("body") or "").replace("\r\n", "\n").strip()
    if not title or not body:
        return _form_error(base, "A headline and a post are both needed.", 422)
    if len(body) > MAX_BODY:
        return _form_error(base, f"That post is longer than {MAX_BODY:,} characters.", 413)
    digest = sha256_text(body)
    conn = connect()
    try:
        # a double click or a re-sent form within a minute is the same post
        recent = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        same = conn.execute("SELECT id FROM posts WHERE title = ? AND content_sha256 = ? AND created_at > ?",
                            (title, digest, recent)).fetchone()
        if same:
            return RedirectResponse(f"{base}p/{same['id']}", status_code=303)
        post_id = "post_" + hashlib.sha256(f"{title}\x00{body}\x00{time.time_ns()}".encode()).hexdigest()[:12]
        conn.execute(
            "INSERT INTO posts (id, title, body, status, content_sha256, created_at, updated_at) "
            "VALUES (?,?,?,'pending',?,?,?)", (post_id, title, body, digest, now(), now()))
        conn.commit()
    finally:
        conn.close()
    try:
        checked = await engine_check(title, body, post_id)
        n = len(checked.get("findings", []))
        status = "in_review" if checked.get("status") == "In review" else "checked"
        update_post(post_id, submission_id=checked.get("submission_id"), status=status,
                    reason=f"Canonry returned {n} finding{'s' if n != 1 else ''}; waiting for a reviewer's signed approval.")
    except Exception as exc:  # noqa: BLE001 - shown to the editor, never a 500
        update_post(post_id, status="engine_error", reason=str(exc)[:400])
    # Post/Redirect/Get: a refresh shows the post instead of sending it again
    return RedirectResponse(f"{base}p/{post_id}", status_code=303)


@app.get("/p/{post_id}", response_class=HTMLResponse)
def view_post(req: Request, post_id: str):
    base = base_href(req)
    post = post_row(post_id)
    if not post:
        return HTMLResponse(layout("Not found", f"<article><h1>No such post.</h1><p><a href='{base}'>Back to the desk</a></p></article>"),
                            status_code=404)
    if post["status"] != "published":
        waiting = post["status"] in ("pending", "in_review", "checked", "approved_waiting")
        return HTMLResponse(layout("Held", f"""
        <article><div class="meta">NOT PUBLISHED · {html.escape(STATE_TEXT.get(post['status'], post['status']))}</div>
        <h1>{html.escape(post['title'])}</h1>
        <p>{html.escape(post['reason'] or 'It is waiting for a signed approval.')}</p>
        <p class="meta">{'This page refreshes itself; it publishes as soon as the signed webhook arrives. ' if waiting else ''}
        Next: {_canonry_link('/review', 'open the review queue in Canonry')} as Reviewer and approve it.</p>
        <p><a href="{base}">Back to the desk</a></p></article>""", refresh=waiting))
    seal = ""
    if post["verify_url"]:
        seal = (f"<div class='seal'><span aria-hidden='true'>✓</span><div><strong>Proof of Compliance</strong><br>"
                f"Seal <code>{html.escape(post['poc_id'] or '')}</code> · "
                f"<a href='{html.escape(post['verify_url'])}'>verify this exact text</a><br>"
                f"<span class='meta'>The text above is the approved text: its SHA-256 matches the signed seal.</span></div></div>")
    return HTMLResponse(layout(post["title"], f"""
      <article><div class="meta">PUBLISHED · {html.escape((post['published_at'] or '')[:16].replace('T', ' '))} UTC</div>
      <h1>{html.escape(post['title'])}</h1>
      <div style="white-space:pre-wrap; font-family:Georgia,serif; font-size:1.1rem; overflow-wrap:anywhere">{html.escape(post['body'])}</div>
      {seal}<p><a href="{base}">Back to the desk</a></p></article>"""))


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
    return {"ok": True, "posts": count, "in_process": Config.transport is not None,
            "api_key": bool(Config.api_key), "webhook_secret": bool(Config.webhook_secret()),
            "signature_window_seconds": MAX_SKEW_SECONDS}


# ---- Canonry webhook ---------------------------------------------------------

@app.post("/webhooks/canonry")
async def canonry_webhook(req: Request):
    raw = await req.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Webhook payload too large.")
    secret = Config.webhook_secret()
    if not secret:
        raise HTTPException(503, "No webhook secret is configured (CANONRY_WEBHOOK_SECRET).")
    timestamp = req.headers.get("x-canonry-timestamp") or ""
    signature = req.headers.get("x-canonry-signature") or ""
    try:
        age = abs(int(time.time()) - int(timestamp))
    except ValueError:
        raise HTTPException(401, "Missing or malformed signature timestamp.")
    if age > MAX_SKEW_SECONDS:
        raise HTTPException(401, "Signature timestamp is outside the five-minute window.")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), timestamp.encode() + b"." + raw,
                                    hashlib.sha256).hexdigest()
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
    finally:
        conn.close()
    outcome, detail, changes = "ignored", "No post here matches this submission.", {}
    if post and post["status"] == "published":
        outcome, detail = "ignored", "Already published."
    elif post and event == "checked":
        outcome, detail = "held", "Checked; waiting for review."
    elif post and event == "approved":
        changes = {"status": "approved_waiting", "reason": "Approved; waiting for the signed seal."}
        outcome, detail = "held", "Approved is not enough; the signed event is required."
    elif post and event == "signed":
        signed_hash = str(data.get("content_sha256") or "")
        text = post["body"]
        if data.get("content_kind") != "text":
            changes = {"status": "held", "reason": "This publisher handles text posts; the approved item is a file."}
            outcome, detail = "held", "file content is not publishable here"
        elif not data.get("poc_id") or not data.get("verify_url"):
            changes = {"status": "held", "reason": "The signed event did not include a seal id and verify URL."}
            outcome, detail = "held", "incomplete signed event"
        else:
            if not hmac.compare_digest(signed_hash, post["content_sha256"]):
                # edited during review: publish the approved text, but only if it
                # is exactly what was signed
                try:
                    text = await approved_text(str(data.get("submission_id")))
                except Exception as exc:  # noqa: BLE001
                    text, detail = "", f"could not fetch the approved text: {exc}"
            if text and hmac.compare_digest(sha256_text(text), signed_hash):
                edited = text != post["body"]
                changes = {"status": "published", "reason": None, "poc_id": data["poc_id"],
                           "verify_url": data["verify_url"], "published_at": now(), "body": text,
                           "content_sha256": signed_hash}
                outcome = "published"
                detail = f"Seal {data['poc_id']} matches" + (" the text as edited in review." if edited else " this text.")
            else:
                changes = {"status": "held_hash_mismatch",
                           "reason": "The signed text does not match the text held here, so it was not published."}
                outcome, detail = "held", detail if not text else "content hash mismatch"
    conn = connect()
    try:
        if changes:
            changes["updated_at"] = now()
            conn.execute(f"UPDATE posts SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                         (*changes.values(), post["id"]))
        conn.execute(
            "INSERT OR IGNORE INTO webhook_deliveries (id, event, received_at, outcome, detail) VALUES (?,?,?,?,?)",
            (delivery_id, event, now(), outcome, detail))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "event": event, "outcome": outcome, "detail": detail}
