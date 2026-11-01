"""Publishing gate: API keys, scopes, idempotency and signed webhooks.

What an integrator (or a judge with curl) would try: missing, wrong and
revoked keys; the wrong scope; bad JSON and oversized bodies; a retried request
with the same and with a different payload; webhook URLs that point inside the
network; signatures a receiver can check; retries on a failing receiver; secret
rotation; disabling an endpoint.

Run:  .venv/Scripts/python engine/tests/test_api.py
"""
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_db.use_test_database("canonry_api")
os.environ.pop("CANONRY_WEBHOOK_ALLOW_LOCAL", None)

from fastapi.testclient import TestClient  # noqa: E402

import main as engine  # noqa: E402
import webhooks  # noqa: E402
from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()
engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def login(email):
    c = TestClient(engine.app, raise_server_exceptions=False)
    assert c.post("/login", json={"email": email}).status_code == 200
    return c


def detail(r):
    try:
        d = r.json().get("detail")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {"message": d}


admin, reviewer, creator = login("karan@quillmark"), login("maya@quillmark"), login("arjun@quillmark")
anon = TestClient(engine.app, raise_server_exceptions=False)

# ---- keys: only an admin issues them; the raw key is shown once --------------
r = creator.post("/api-keys", json={"name": "nope"})
expect(r.status_code == 403, f"a creator cannot issue API keys ({r.status_code})")
r = admin.post("/api-keys", json={"name": "   "})
expect(r.status_code == 422, f"a key needs a name ({r.status_code})")
r = admin.post("/api-keys", json={"name": "Integration", "scopes": ["check", "read"]})
expect(r.status_code == 200 and r.json()["key"].startswith("ck_live_"), "admin creates a check+read key")
full_key = r.json()["key"]
full_id = r.json()["id"]
listed = admin.get("/api-keys").json()["keys"]
expect(all("key" not in k and "key_hash" not in k for k in listed), "the key list never contains the key or its hash")
read_key = admin.post("/api-keys", json={"name": "Reader", "scopes": ["read"]}).json()["key"]
check_key = admin.post("/api-keys", json={"name": "Checker", "scopes": ["check"]}).json()["key"]
odd = admin.post("/api-keys", json={"name": "Odd", "scopes": ["root", "delete"]}).json()
expect(odd["scopes"] == ["check", "read"], f"unknown scopes fall back to check+read ({odd['scopes']})")


def auth(key):
    return {"Authorization": f"Bearer {key}"}


GOOD = {"title": "API post", "channel": "web", "content": "Pulse 2.0 helps teams read their numbers."}

# ---- authentication and scopes ----------------------------------------------
r = anon.post("/api/v1/checks", json=GOOD)
expect(r.status_code == 401 and detail(r).get("code") == "missing_key", f"no key: 401 missing_key ({r.status_code})")
r = anon.post("/api/v1/checks", json=GOOD, headers={"Authorization": "Basic abc"})
expect(r.status_code == 401, f"wrong auth scheme: 401 ({r.status_code})")
r = anon.post("/api/v1/checks", json=GOOD, headers=auth("ck_live_" + "x" * 30))
expect(r.status_code == 401 and detail(r).get("code") == "invalid_key", f"unknown key: 401 invalid_key ({r.status_code})")
r = anon.post("/api/v1/checks", json=GOOD, headers=auth(full_key[:-1] + ("A" if full_key[-1] != "A" else "B")))
expect(r.status_code == 401, f"a key with the right prefix but wrong secret is refused ({r.status_code})")
r = anon.post("/api/v1/checks", json=GOOD, headers=auth(read_key))
expect(r.status_code == 403 and detail(r).get("code") == "insufficient_scope", f"read-only key cannot check ({r.status_code})")
r = anon.get("/api/v1/submissions", headers=auth(check_key))
expect(r.status_code == 403, f"check-only key cannot read ({r.status_code})")
r = anon.get("/api/v1/submissions", headers=auth(read_key))
expect(r.status_code == 200 and r.headers.get("x-canon-api-version"), "read key lists submissions with a version header")
r = anon.get("/api/v1/contract")
expect(r.status_code == 200 and r.json()["events"] == ["checked", "approved", "signed"], "contract is public and lists the events")
r = anon.get("/api/v1/submissions", headers=auth(read_key), params={"limit": "lots"})
expect(r.status_code == 422, f"a non-numeric limit is a 422, not a 500 ({r.status_code})")

# ---- bad input ---------------------------------------------------------------
r = anon.post("/api/v1/checks", content=b"{not json", headers={**auth(full_key), "Content-Type": "application/json"})
expect(r.status_code == 422, f"malformed JSON: 422 ({r.status_code})")
r = anon.post("/api/v1/checks", json={**GOOD, "channel": "billboard"}, headers=auth(full_key))
expect(r.status_code == 422 and detail(r).get("code") == "bad_channel", f"unknown channel: 422 bad_channel ({r.status_code})")
r = anon.post("/api/v1/checks", json={**GOOD, "content": "   "}, headers=auth(full_key))
expect(r.status_code == 422 and detail(r).get("code") == "empty_content", f"empty content: 422 ({r.status_code})")
r = anon.post("/api/v1/checks", json={**GOOD, "title": " "}, headers=auth(full_key))
expect(r.status_code == 422, f"blank title: 422 ({r.status_code})")
r = anon.post("/api/v1/checks", json={"title": "x", "channel": "web"}, headers=auth(full_key))
expect(r.status_code == 422, f"missing content field: 422 ({r.status_code})")
r = anon.post("/api/v1/checks", json={**GOOD, "content": "a" * 200_001}, headers=auth(full_key))
expect(r.status_code == 422, f"content over 200,000 characters: 422 ({r.status_code})")
huge = b'{"title":"x","channel":"web","content":"' + b"a" * (3 * 1024 * 1024) + b'"}'
r = anon.post("/api/v1/checks", content=huge, headers={**auth(full_key), "Content-Type": "application/json"})
expect(r.status_code == 413, f"a 3 MB JSON body is refused before parsing: 413 ({r.status_code})")
with connect() as c:
    before = c.execute("SELECT COUNT(*) n FROM submissions").fetchone()["n"]

# ---- idempotency ---------------------------------------------------------------
idem = {**auth(full_key), "Idempotency-Key": "order-0001"}
r1 = anon.post("/api/v1/checks", json=GOOD, headers=idem)
r2 = anon.post("/api/v1/checks", json=GOOD, headers=idem)
expect(r1.status_code == 200 and r2.status_code == 200, "a retried request succeeds")
expect(r1.json()["submission_id"] == r2.json()["submission_id"], "the same Idempotency-Key replays the first answer")
r3 = anon.post("/api/v1/checks", json={**GOOD, "content": "Different copy."}, headers=idem)
expect(r3.status_code == 409 and detail(r3).get("code") == "idempotency_conflict",
       f"same key, different payload: 409 ({r3.status_code})")
r = anon.post("/api/v1/checks", json=GOOD, headers={**auth(full_key), "Idempotency-Key": "short"})
expect(r.status_code == 422, f"an Idempotency-Key under 8 characters is refused ({r.status_code})")
with connect() as c:
    after = c.execute("SELECT COUNT(*) n FROM submissions").fetchone()["n"]
expect(after == before + 1, f"one submission for the replayed request ({after - before})")

# two clients retrying at the same moment must not create two submissions or a 500
results = []


def fire():
    c = TestClient(engine.app, raise_server_exceptions=False)
    results.append(c.post("/api/v1/checks", json={**GOOD, "title": "race"},
                          headers={**auth(full_key), "Idempotency-Key": "race-0001"}))


threads = [threading.Thread(target=fire) for _ in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
codes = sorted(r.status_code for r in results)
expect(all(code in (200, 409) for code in codes), f"concurrent retries never 500 ({codes})")
with connect() as c:
    races = c.execute("SELECT COUNT(*) n FROM submissions WHERE title = 'race'").fetchone()["n"]
expect(races == 1, f"concurrent retries with one key create one submission ({races})")

# a retry that arrives while the first request is still running gets a clear 409
import api as api_mod  # noqa: E402

with connect() as c:
    ws_id = c.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
    payload = {**GOOD, "title": "slow", "source_type": "in-house"}
    api_mod.claim_idempotent(c, ws_id, "slow-0001", "POST /api/v1/checks", api_mod.request_hash(payload))
r = anon.post("/api/v1/checks", json=payload, headers={**auth(full_key), "Idempotency-Key": "slow-0001"})
expect(r.status_code == 409 and detail(r).get("code") == "idempotency_in_progress",
       f"a retry during the first request: 409 in progress ({r.status_code} {detail(r).get('code')})")

# ---- revoke --------------------------------------------------------------------
r = admin.post(f"/api-keys/{full_id}/revoke")
expect(r.status_code == 200, "admin revokes a key")
r = anon.get("/api/v1/submissions", headers=auth(full_key))
expect(r.status_code == 401, f"a revoked key stops working at once ({r.status_code})")
r = admin.post("/api-keys/key_nope/revoke")
expect(r.status_code == 404, f"revoking an unknown key: 404 ({r.status_code})")
api_key = admin.post("/api-keys", json={"name": "Second", "scopes": ["check", "read"]}).json()["key"]

# ---- every link in a response works --------------------------------------------
from PIL import Image  # noqa: E402
import io  # noqa: E402

buf = io.BytesIO()
Image.new("RGB", (64, 64), (14, 124, 123)).save(buf, "PNG")
r = anon.post("/api/v1/uploads", params={"title": "Banner", "channel": "social", "filename": "b.png",
                                         "alt_text": "Teal square for the launch banner"},
              content=buf.getvalue(), headers={**auth(api_key), "Content-Type": "image/png"})
expect(r.status_code == 200, f"API upload works ({r.status_code} {r.text[:120]})")
if r.status_code == 200:
    link = r.json()["links"]["file"]
    got = anon.get(link, headers=auth(api_key))
    expect(got.status_code == 200 and got.content == buf.getvalue(), f"the upload's file link serves the file ({link} {got.status_code})")
    expect(anon.get(link).status_code == 401, "the file link needs a key")

# ---- webhook URLs: nothing inside the network --------------------------------
_real_getaddrinfo = socket.getaddrinfo
FAKE_DNS = {"hooks.example.test": "93.184.216.34", "rebind.example.test": "93.184.216.34",
            "internal.example.test": "10.1.2.3"}


def fake_getaddrinfo(host, port, *args, **kwargs):
    if host in FAKE_DNS:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (FAKE_DNS[host], port))]
    if host.endswith(".test"):
        raise socket.gaierror("no such host")
    return _real_getaddrinfo(host, port, *args, **kwargs)


webhooks.socket.getaddrinfo = fake_getaddrinfo
bad_urls = [
    "http://localhost:9000/hook", "https://localhost/hook", "https://127.0.0.1/hook", "https://127.0.0.2/hook",
    "https://10.0.0.1/hook", "https://192.168.1.10/hook", "https://172.16.0.5/hook",
    "https://169.254.169.254/latest/meta-data", "https://[::1]/hook", "https://[::ffff:127.0.0.1]/hook",
    "https://0.0.0.0/hook", "https://100.64.0.1/hook", "https://224.0.0.1/hook", "https://2130706433/hook",
    "https://internal.example.test/hook", "https://nowhere.example.test/hook",
    "ftp://example.com/hook", "file:///etc/passwd", "javascript:alert(1)", "gopher://example.com/",
    "https://user:pw@hooks.example.test/hook", "http://hooks.example.test/hook", "", "not a url",
]
for url in bad_urls:
    r = admin.post("/webhook-endpoints", json={"url": url, "events": ["signed"]})
    expect(r.status_code == 422 and isinstance(r.json().get("detail"), str),
           f"refused webhook URL {url!r} ({r.status_code}: {str(r.json().get('detail'))[:70]})")
r = admin.post("/webhook-endpoints", json={"url": "https://hooks.example.test/hook", "events": ["nonsense"]})
expect(r.status_code == 422, f"an endpoint needs a known event ({r.status_code})")
r = reviewer.post("/webhook-endpoints", json={"url": "https://hooks.example.test/hook"})
expect(r.status_code == 403, f"only an admin adds endpoints ({r.status_code})")
r = admin.post("/webhook-endpoints", json={"url": "https://hooks.example.test/hook", "events": ["signed"]})
expect(r.status_code == 200 and r.json()["secret"].startswith("whsec_"), "a public HTTPS endpoint is accepted")
public_hook = r.json()["id"]
admin.post(f"/webhook-endpoints/{public_hook}/disable")

# DNS rebinding: a host that was public at creation and points inside later is
# not contacted at delivery time
r = admin.post("/webhook-endpoints", json={"url": "https://rebind.example.test/hook", "events": ["checked"]})
rebind_id = r.json()["id"]
sent = []


class RecordingClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **k):
        sent.append(url)
        raise ConnectionError("recorded only")


real_client = webhooks.httpx.Client
webhooks.httpx.Client = RecordingClient
FAKE_DNS["rebind.example.test"] = "127.0.0.1"
anon.post("/api/v1/checks", json={**GOOD, "title": "rebind"}, headers=auth(api_key))
webhooks.httpx.Client = real_client
expect(not sent, f"a host that now resolves to loopback is not contacted ({sent})")
with connect() as c:
    row = c.execute("SELECT status, last_error FROM webhook_deliveries WHERE endpoint_id = ?", (rebind_id,)).fetchone()
expect(row is not None and "address" in (row["last_error"] or ""), f"the delivery records why it was not sent ({dict(row) if row else None})")
admin.post(f"/webhook-endpoints/{rebind_id}/disable")
webhooks.socket.getaddrinfo = _real_getaddrinfo

# ---- a real receiver: signatures, retries, rotation, disable ----------------
received = []
plan = {"status": [500]}  # first answer 500, then 200


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        received.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body,
                         "path": self.path})
        status = plan["status"].pop(0) if plan["status"] else 200
        if status == 302:
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()
            return
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
threading.Thread(target=server.serve_forever, daemon=True).start()
hook_url = f"http://127.0.0.1:{server.server_address[1]}/canonry"

r = admin.post("/webhook-endpoints", json={"url": hook_url, "events": ["checked", "signed"]})
expect(r.status_code == 422 and "CANONRY_WEBHOOK_ALLOW_LOCAL" in r.json()["detail"],
       "a loopback receiver needs the explicit local-development switch")
os.environ["CANONRY_WEBHOOK_ALLOW_LOCAL"] = "true"
r = admin.post("/webhook-endpoints", json={"url": hook_url, "events": ["checked", "signed"]})
expect(r.status_code == 200, "local development may use a loopback receiver")
hook = r.json()
secret = hook["secret"]


def verify(item, secret):
    ts = item["headers"].get("x-canonry-timestamp", "")
    expected = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + item["body"], hashlib.sha256).hexdigest()
    return hmac.compare_digest(item["headers"].get("x-canonry-signature", ""), expected)


r = anon.post("/api/v1/checks", json={**GOOD, "title": "hooked"}, headers=auth(api_key))
expect(r.status_code == 200, "a check succeeds even while the receiver fails")
expect(len(received) == 1, f"the checked event was attempted at once ({len(received)})")
with connect() as c:
    d = c.execute("SELECT * FROM webhook_deliveries WHERE endpoint_id = ? ORDER BY created_at DESC",
                  (hook["id"],)).fetchone()
expect(d["status"] == "pending" and d["attempts"] == 1 and d["last_status"] == 500,
       f"a 500 leaves the delivery pending for a retry ({d['status']}, {d['attempts']}, {d['last_status']})")
delay = (datetime.fromisoformat(d["next_attempt_at"]) - datetime.now(timezone.utc)).total_seconds()
expect(20 < delay <= 31, f"first retry is scheduled about 30 s later ({delay:.0f} s)")
item = received[0]
expect(verify(item, secret), "a receiver can verify the HMAC signature over timestamp.body")
expect(not verify({**item, "body": item["body"] + b" "}, secret), "a changed body fails verification")
payload = json.loads(item["body"])
expect(payload["event"] == "checked" and item["headers"]["x-canonry-event"] == "checked"
       and item["headers"]["x-canonry-delivery"] == payload["id"], "event and delivery id are in headers and body")

# the outbox retries a due delivery without any new product event: the running
# engine's background loop picks it up
os.environ["CANONRY_WEBHOOK_RETRY_SECONDS"] = "0.3"
with TestClient(engine.app):
    with connect() as c:
        c.execute("UPDATE webhook_deliveries SET next_attempt_at = ? WHERE id = ?",
                  ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), d["id"]))
        c.commit()
    deadline = time.time() + 8
    while time.time() < deadline and len(received) < 2:
        time.sleep(0.2)
with connect() as c:
    d2 = c.execute("SELECT status, attempts FROM webhook_deliveries WHERE id = ?", (d["id"],)).fetchone()
expect(d2["status"] == "delivered" and d2["attempts"] == 2, f"the due retry is delivered by the background flusher ({dict(d2)})")
expect(received[-1]["headers"]["x-canonry-delivery"] == d["id"], "the retry re-sends the same delivery id")

# a redirect is a failure, never followed
plan["status"] = [302]
anon.post("/api/v1/checks", json={**GOOD, "title": "redirect"}, headers=auth(api_key))
with connect() as c:
    d3 = c.execute("SELECT * FROM webhook_deliveries WHERE endpoint_id = ? ORDER BY created_at DESC",
                   (hook["id"],)).fetchone()
expect(d3["status"] == "pending" and d3["last_status"] == 302, f"a redirect is not followed ({d3['last_status']})")
expect(all(not it["path"].startswith("/latest") for it in received), "the redirect target was never contacted")

# retries stop after MAX_ATTEMPTS and the delivery is marked failed
with connect() as c:
    c.execute("UPDATE webhook_deliveries SET attempts = ?, next_attempt_at = ? WHERE id = ?",
              (webhooks.MAX_ATTEMPTS - 1, (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), d3["id"]))
    c.commit()
    plan["status"] = [503]
    webhooks.deliver(c, d3["id"])
    d4 = c.execute("SELECT status, attempts, next_attempt_at FROM webhook_deliveries WHERE id = ?", (d3["id"],)).fetchone()
expect(d4["status"] == "failed" and d4["attempts"] == webhooks.MAX_ATTEMPTS and d4["next_attempt_at"] is None,
       f"after {webhooks.MAX_ATTEMPTS} attempts the delivery fails for good ({dict(d4)})")
r = admin.post(f"/webhook-deliveries/{d3['id']}/retry")
expect(r.status_code == 200 and r.json()["status"] == "delivered", f"an admin can retry a failed delivery by hand ({r.json()})")

# rotation: the old secret stops verifying at once
r = admin.post(f"/webhook-endpoints/{hook['id']}/rotate")
expect(r.status_code == 200 and r.json()["secret"] != secret, "rotate returns a new secret")
new_secret = r.json()["secret"]
anon.post("/api/v1/checks", json={**GOOD, "title": "rotated"}, headers=auth(api_key))
expect(verify(received[-1], new_secret) and not verify(received[-1], secret), "after rotation only the new secret verifies")
expect(admin.post("/webhook-endpoints/wh_nope/rotate").status_code == 404, "rotating an unknown endpoint: 404")
expect(creator.post(f"/webhook-endpoints/{hook['id']}/rotate").status_code == 403, "only an admin rotates")
listed = admin.get("/webhook-endpoints").json()["endpoints"]
expect(all("secret" not in e and "secret_salt" not in e for e in listed), "the endpoint list never shows a secret")

# disable: nothing more is queued or sent
r = admin.post(f"/webhook-endpoints/{hook['id']}/disable")
expect(r.status_code == 200, "admin disables an endpoint")
n = len(received)
anon.post("/api/v1/checks", json={**GOOD, "title": "after disable"}, headers=auth(api_key))
expect(len(received) == n, "a disabled endpoint receives nothing")
with connect() as c:
    audits = {r["action"] for r in c.execute("SELECT action FROM audit_log").fetchall()}
expect({"webhook_rotate", "webhook_disable"} <= audits, f"rotate and disable are in the audit trail ({sorted(a for a in audits if 'webhook' in a)})")

server.shutdown()
print()
if failures:
    print(f"{len(failures)} API CHECK(S) FAILED")
    sys.exit(1)
print("ALL API CHECKS PASSED")
