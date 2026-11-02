"""Round 3 publishing gate: the public REST API does its job and a receiver can
only trust a signed webhook.

Covers the documented "done when" for improvement 2: an external client gets its
content checked over the API, an `approved` event alone does not publish, and
the `signed` event matches the exact copy the receiver holds (and a mismatch is
held back).

Run:  .venv/Scripts/python engine/tests/test_api_gate.py
"""
import hashlib
import hmac
import http.server
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: never reach a real AI provider)

import db as _db

_db.use_test_database("canonry_api_gate")

import api  # noqa: E402
import main as engine  # noqa: E402
import webhooks  # noqa: E402
from db import connect  # noqa: E402
from seed import seed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


ws = seed()
engine.DEMO_MODE = True
engine.COOKIE_SECURE = False
os.environ["CANONRY_WEBHOOK_ALLOW_LOCAL"] = "true"

conn = connect()
key = api.create_key(conn, ws, "publish-gate", ["check", "read"], "test")["key"]
check_only = api.create_key(conn, ws, "publish-only-check", ["check"], "test")["key"]
conn.commit()
conn.close()

CLEAN_POST = ("Meet Quillmark Pulse 2.0, an analytics platform trusted by 2,300+ teams. "
              "Plans start at 1,299 per month. Start a free trial at quillmark.co/pulse.")

# ---- a loopback receiver, standing in for the demo CMS -----------------------

received = []


class Receiver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        received.append({
            "path": self.path,
            "event": self.headers.get("X-Canonry-Event") or "",
            "delivery": self.headers.get("X-Canonry-Delivery") or "",
            "timestamp": self.headers.get("X-Canonry-Timestamp") or "",
            "signature": self.headers.get("X-Canonry-Signature") or "",
            "body_raw": raw,
        })
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
RECEIVER_URL = f"http://127.0.0.1:{port}/hooks"

with TestClient(engine.app) as client:
    # ---- authentication and scopes --------------------------------------------
    r = client.post("/api/v1/checks", json={"title": "x", "channel": "web", "content": CLEAN_POST})
    expect(r.status_code == 401, f"no API key is an authentication failure ({r.status_code})")
    r = client.post("/api/v1/checks", headers={"Authorization": "Bearer ck_live_not_a_real_key_0000000000"},
                    json={"title": "x", "channel": "web", "content": CLEAN_POST})
    expect(r.status_code == 401, f"an invalid key is rejected ({r.status_code})")
    r = client.get("/api/v1/compliance/packs", headers={"Authorization": f"Bearer {check_only}"})
    expect(r.status_code == 403, f"a check-scoped key cannot read ({r.status_code})")
    detail = (r.json().get("detail") or {}) if isinstance(r.json().get("detail"), dict) else {}
    expect(detail.get("code") == "insufficient_scope", f"the 403 names the missing scope ({detail})")

    # ---- endpoint registration (admin; the secret is shown once) ---------------
    admin = TestClient(engine.app)
    r = admin.post("/join", json={"name": "Rhea Adminer", "email": "rhea@quillmark", "role": "admin"})
    expect(r.status_code == 200, f"join as admin ({r.status_code})")
    r = admin.post("/webhook-endpoints",
                   json={"url": RECEIVER_URL, "events": ["checked", "approved", "signed"]})
    expect(r.status_code == 200, f"webhook endpoint registered ({r.status_code}) {r.text[:120]}")
    endpoint = r.json()
    secret = endpoint["secret"]

    # ---- idempotent checks ------------------------------------------------------
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": "gate-0001"}
    payload = {"title": "Clean launch post", "channel": "web", "content": CLEAN_POST}
    r1 = client.post("/api/v1/checks", headers={**headers, "Origin": "http://localhost:3000"}, json=payload)
    expect(r1.status_code == 200, f"API check succeeds ({r1.status_code}) {r1.text[:140]}")
    first = r1.json()
    r2 = client.post("/api/v1/checks", headers=headers, json=payload)
    expect(r2.status_code == 200 and r2.json()["submission_id"] == first["submission_id"],
           "the same Idempotency-Key replays the first response")
    expect(first.get("contract_version") == "finding@2", f"response carries the contract version ({first.get('contract_version')})")

    # ---- the checked webhook reaches the receiver, properly signed --------------
    checked = [r for r in received if r["event"] == "checked" and first["submission_id"] in r["body_raw"].decode()]
    expect(bool(checked), f"checked event delivered ({len(checked)} of {len(received)} received; "
                          f"{[r['event'] for r in received]})")
    if checked:
        hit = checked[0]
        mac = hmac.new(secret.encode(), hit["timestamp"].encode() + b"." + hit["body_raw"],
                       hashlib.sha256).hexdigest()
        expect(hit["signature"] == "sha256=" + mac, "the receiver can verify the HMAC signature")
        data = json.loads(hit["body_raw"])["data"]
        expect(data["findings"] == len(first["findings"]), "the checked event reports the finding count")

    # hold the copy the way the demo CMS does, keyed by submission id
    held_hash = hashlib.sha256(CLEAN_POST.encode()).hexdigest()

    def cms_verdict(event: str, data: dict) -> str:
        """The demo CMS's one-way rule, expressed once here for proof."""
        if event == "checked":
            return "held"  # being checked never publishes
        if event == "approved":
            return "held"  # approval alone is not publication authority
        if event == "signed":
            if data.get("content_kind") != "text":
                return "held"
            if not hmac.compare_digest(str(data.get("content_sha256") or ""), held_hash):
                return "held"  # hash mismatch: the copy changed after approval
            if not (data.get("poc_id") and data.get("verify_url")):
                return "held"
            return "published"
        return "held"

    # ---- the real review leg: a reviewer signs, the receiver gets `signed` -----
    creator = TestClient(engine.app)
    expect(creator.post("/join", json={"name": "Cloe Creator", "email": "cloe@quillmark",
                                       "role": "creator"}).status_code == 200, "join creator")
    reviewer = TestClient(engine.app)
    # maya@quillmark is a seeded reviewer persona; /join would refuse her
    expect(reviewer.post("/login", json={"email": "maya@quillmark"}).status_code == 200, "login reviewer")
    r = creator.post("/submissions", json={"title": "Clean launch post", "channel": "web",
                                           "source_type": "in-house", "content": CLEAN_POST})
    expect(r.status_code == 200, f"creator submits ({r.status_code})")
    sid2 = r.json()["submission_id"]
    r = creator.post(f"/submissions/{sid2}/submit-review")
    expect(r.status_code == 200, f"submit for review ({r.status_code})")
    r = reviewer.post(f"/submissions/{sid2}/review", json={"action": "approve"})
    expect(r.status_code == 200, f"reviewer approves and signs ({r.status_code}) {r.text[:120]}")

    signed_events = [json.loads(r["body_raw"]) for r in received if r["event"] == "signed"
                     and sid2 in r["body_raw"].decode()]
    approved_events = [json.loads(r["body_raw"]) for r in received if r["event"] == "approved"]
    expect(bool(signed_events) and bool(approved_events),
           f"both the approved and signed events arrive ({[r['event'] for r in received]})")

    if signed_events:
        data = signed_events[0]["data"]
        expect(cms_verdict("approved", data) == "held", "a CMS must not publish on approval alone")
        expect(cms_verdict("signed", data) == "published", "the signed event publishes the exact copy")
        expect(data["content_sha256"] == held_hash, "the signed hash matches the held copy")
        expect(data["verify_url"].startswith("http") and data["poc_id"],
               f"verify URL + poc id present ({data.get('verify_url')})")

    # a mismatched copy is provably held: simulate the publisher storing other text
    stored_other = hashlib.sha256((CLEAN_POST + " changed").encode()).hexdigest()
    tampered = json.loads(json.dumps(signed_events[0])) if signed_events else None
    if tampered:
        tampered["data"]["content_sha256"] = stored_other
        expect(cms_verdict("signed", tampered["data"]) == "held", "a hash mismatch is held, never published")

    # ---- an unreachable receiver retries, honestly -----------------------------
    r = admin.post("/webhook-endpoints",
                   json={"url": "http://127.0.0.1:9/hooks", "events": ["checked"]})
    expect(r.status_code == 200, f"an unreachable loopback receiver can be registered ({r.status_code})")
    endpoint_id = r.json()["id"]
    client.post("/api/v1/checks", headers={**headers, "Idempotency-Key": "gate-0002"},
                json={"title": "Retry probe", "channel": "web", "content": CLEAN_POST})
    conn = connect()
    row = conn.execute(
        "SELECT event, status, attempts FROM webhook_deliveries WHERE endpoint_id = ? "
        "ORDER BY created_at DESC LIMIT 1", (endpoint_id,)).fetchone()
    conn.close()
    expect(bool(row) and row["event"] == "checked" and row["status"] == "pending" and row["attempts"] >= 1,
           f"a failed delivery stays in the outbox for retry ({row and dict(row)})")
    print()

server.shutdown()  # graceful: from the main thread, against the serving thread
server.server_close()

if failures:
    print(f"{len(failures)} API GATE CHECK(S) FAILED")
    sys.exit(1)
print("ALL API GATE CHECKS PASSED")
