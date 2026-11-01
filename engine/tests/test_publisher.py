"""Demo publisher mounted in the engine: the publishing gate end to end.

A real server on a free port (the webhook travels over HTTP, signed, exactly
as on the live demo): a post written in the publisher is checked by Canonry
and lands in the review queue; it stays held until a reviewer approves; the
signed webhook publishes it with its seal. Then the receiver on its own: bad
signatures, stale timestamps, `approved` alone, replays, text edited in review.

Run:  .venv/Scripts/python engine/tests/test_publisher.py
"""
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time

# OpenCV's OpenCL teardown can abort the interpreter on Windows after a server
# thread used it, turning a pass into a failing exit code; the checks need no GPU
os.environ.setdefault("OPENCV_OPENCL_DEVICE", "disabled")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_db.use_test_database("canonry_publisher")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
os.environ["CANONRY_PUBLIC_ENGINE_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["CANONRY_WEBHOOK_ALLOW_LOCAL"] = "true"
os.environ["CANONRY_PUBLISHER_DEMO"] = "true"
os.environ["CANONRY_WEBHOOK_RETRY_SECONDS"] = "1"
for p in (os.path.join(os.path.dirname(_db.DB_PATH), "cms.db"),):
    if os.path.exists(p):
        os.remove(p)

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import main as engine  # noqa: E402

engine.DEMO_MODE = True
engine.COOKIE_SECURE = False

failures = []


def post_body(post_id):
    # what the published page shows: the stored post text
    with engine.app.state.publisher.connect() as c:
        return c.execute("SELECT body FROM posts WHERE id = ?", (post_id,)).fetchone()["body"]


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


server = uvicorn.Server(uvicorn.Config(engine.app, host="127.0.0.1", port=PORT, log_level="warning"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
deadline = time.time() + 30
while not server.started and time.time() < deadline:
    time.sleep(0.1)
expect(server.started, "engine with the publisher starts")
BASE = f"http://127.0.0.1:{PORT}"

try:
    web = httpx.Client(base_url=BASE, timeout=60)
    r = web.get("/cms")
    expect(r.status_code == 200 and 'action="cms/posts"' in r.text, f"/cms serves the desk with links that work without a trailing slash ({r.status_code})")
    r = web.get("/cms/")
    expect(r.status_code == 200 and 'action="./posts"' in r.text, "/cms/ serves the desk too")
    expect("not connected" not in r.text and "cannot send" not in r.text, "the publisher is connected (key and webhook endpoint issued at boot)")
    health = web.get("/cms/healthz").json()
    expect(health["api_key"] and health["webhook_secret"] and health["in_process"], f"publisher health ({health})")

    body = "Pulse 2.0 helps teams read their numbers.\r\nIt is ready for your next review."
    form = {"title": "Gate test", "body": body}
    r = web.post("/cms/posts", data=form)
    expect(r.status_code == 303 and r.headers["location"].startswith("./p/post_"),
           f"sending a post redirects to it (Post/Redirect/Get) ({r.status_code} {r.headers.get('location')})")
    post_id = r.headers["location"].split("/")[-1]
    again = web.post("/cms/posts", data=form)
    expect(again.headers.get("location") == r.headers["location"], "sending the same form twice opens the same post")

    post = web.get(f"/cms/posts/{post_id}").json()
    expect(post["status"] == "in_review" and post["submission_id"], f"Canonry checked it and put it in review ({post['status']})")
    expect(post["content_sha256"] == hashlib.sha256(body.replace("\r\n", "\n").encode()).hexdigest(),
           "the publisher holds the text with plain line ends")
    page = web.get(f"/cms/p/{post_id}")
    expect(page.status_code == 200 and "NOT PUBLISHED" in page.text and 'http-equiv="refresh"' in page.text,
           "the held post says it is not published and refreshes itself")

    reviewer = httpx.Client(base_url=BASE, timeout=60)
    assert reviewer.post("/login", json={"email": "maya@quillmark"}).status_code == 200
    sid = post["submission_id"]
    detail = reviewer.get(f"/submissions/{sid}").json()
    expect(detail["submission"]["status"] == "In review", "the reviewer sees it waiting in the queue")
    expect(web.get(f"/cms/posts/{post_id}").json()["status"] != "published", "nothing is published before approval")
    rev_findings = detail.get("findings") or []
    for f in rev_findings:
        if f.get("status") == "open" and f.get("severity") == "high":
            reviewer.post(f"/submissions/{sid}/review", json={"action": "override", "finding_id": f["id"],
                                                               "reason": "test override"})
    r = reviewer.post(f"/submissions/{sid}/review", json={"action": "approve", "comment": "ok"})
    expect(r.status_code == 200 and r.json()["status"] == "Signed", f"reviewer approves and Canonry signs ({r.status_code} {r.text[:120]})")
    poc = r.json().get("poc_id")

    deadline = time.time() + 10
    while time.time() < deadline and web.get(f"/cms/posts/{post_id}").json()["status"] != "published":
        time.sleep(0.3)
    post = web.get(f"/cms/posts/{post_id}").json()
    expect(post["status"] == "published" and post["poc_id"] == poc, f"the signed webhook publishes the post ({post['status']}, {post['reason']})")
    expect(post["verify_url"] and post["verify_url"].endswith(f"/verify/{poc}"), f"the published post links to its seal ({post['verify_url']})")
    page = web.get(f"/cms/p/{post_id}")
    expect("verify this exact text" in page.text and "refresh" not in page.text, "the published page shows the seal")
    v = httpx.post(f"{BASE}/verify/{poc}", json={"content": post_body(post_id)})
    expect(v.status_code == 200 and v.json().get("status") == "verified" and "reason" not in v.json(),
           f"the published text verifies exactly against the seal ({v.status_code} {str(v.json())[:120]})")
    desk = web.get("/cms/").text
    expect("published" in desk and "Seal" in desk, "the desk's webhook log shows the signed delivery")
finally:
    server.should_exit = True
    thread.join(timeout=10)

# ---- the receiver on its own -------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402

cms = engine.app.state.publisher
SECRET = "whsec_test_secret_value_123456"
APPROVED = {"text": "Edited in review."}


def fake_engine(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"latest_revision": {"content": APPROVED["text"]}})


cms.configure(webhook_secret=lambda: SECRET, transport=httpx.MockTransport(fake_engine))
client = TestClient(cms.app, raise_server_exceptions=False)
with cms.connect() as c:
    c.execute("INSERT INTO posts (id, title, body, submission_id, status, content_sha256, created_at, updated_at) "
              "VALUES ('post_unit', 'Unit', 'Original text.', 'sub_unit', 'in_review', ?, 'x', 'x')",
              (hashlib.sha256(b"Original text.").hexdigest(),))
    c.commit()


def send(event, data, secret=SECRET, ts=None, delivery=None):
    payload = {"id": delivery or f"whd_{time.time_ns()}", "event": event, "data": data}
    raw = json.dumps(payload).encode()
    ts = str(int(time.time()) if ts is None else ts)
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/canonry", content=raw, headers={
        "X-Canonry-Timestamp": ts, "X-Canonry-Signature": sig, "X-Canonry-Event": event,
        "X-Canonry-Delivery": payload["id"], "Content-Type": "application/json"})


def status():
    with cms.connect() as c:
        return dict(c.execute("SELECT * FROM posts WHERE id = 'post_unit'").fetchone())


signed = {"submission_id": "sub_unit", "content_kind": "text", "poc_id": "poc_1",
          "verify_url": "https://example.test/verify/poc_1",
          "content_sha256": hashlib.sha256(b"Something else.").hexdigest()}
expect(send("signed", signed, secret="whsec_wrong_secret_00000000").status_code == 401, "a wrong signature is refused")
expect(send("signed", signed, ts=int(time.time()) - 600).status_code == 401, "a ten-minute-old timestamp is refused")
r = client.post("/webhooks/canonry", content=b"{}", headers={"X-Canonry-Timestamp": str(int(time.time()))})
expect(r.status_code == 401, "no signature: refused")
send("approved", {"submission_id": "sub_unit"})
expect(status()["status"] == "approved_waiting", "`approved` alone does not publish")
r = send("signed", signed)
expect(r.json()["outcome"] == "held" and status()["status"] == "held_hash_mismatch",
       "a signed hash that matches neither the post nor the approved text: held")
APPROVED["text"] = "Something else."
r = send("signed", signed, delivery="whd_once")
expect(r.json()["outcome"] == "published" and status()["body"] == "Something else.",
       "text edited in review: the approved text is published, after its hash matched the seal")
r = send("signed", signed, delivery="whd_once")
expect(r.json().get("duplicate") is True, "a replayed delivery id is ignored")
r = client.post("/posts", content=b"title=&body=", headers={"Content-Type": "application/x-www-form-urlencoded"})
expect(r.status_code == 422 and "headline" in r.text, "an empty form gets a plain message, not a 500")

print()
print(f"{len(failures)} PUBLISHER CHECK(S) FAILED" if failures else "ALL PUBLISHER CHECKS PASSED")
sys.exit(1 if failures else 0)
