"""Engine end-to-end smoke test (fastapi TestClient, in-folder test DB).

Run:  .venv/Scripts/python engine/tests/test_engine.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_TEST_DB = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_test.db")
_db.DB_PATH = _TEST_DB
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from db import init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import main as engine  # noqa: E402

# Test clients use localhost HTTP with password-free demo login.
engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

LAUNCH_POST = (
    "Meet Quillmark Insights 2.0 -- India's #1 analytics platform, trusted by "
    "5,000+ teams and fully ISO 27001 certified. Plans start at just 999/month!"
)

CUSTOMER = "fastapi.testclient placeholder"


def make_client(email):
    c = TestClient(engine.app)
    r = c.post("/login", json={"email": email})
    assert r.status_code == 200, r.text
    return c


def expect(cond, msg):
    if not cond:
        print("FAIL:", msg)
        raise SystemExit(1)
    print("ok:", msg)


arjun = make_client("arjun@quillmark")
maya = make_client("maya@quillmark")

r = arjun.post("/submissions", json={
    "title": "Launch post - Pulse 2.0", "channel": "social",
    "source_type": "ai-assisted", "content": LAUNCH_POST,
})
expect(r.status_code == 200, "submit + first check ran")
first = r.json()
f0 = first["findings"]
cats = {f["category"] for f in f0}
expect("outdated_term" in cats, "outdated product name flagged (Quillmark Insights)")
expect("contradicted_claim" in cats, "customer count contradicted against fact")
expect("outdated_claim" in cats, "certification/price outdated flagged")
expect("unsupported_claim" in cats, "superlative unsupported (Likely)")
print("first-check categories:", sorted(cats), "| discarded:", first["discarded"],
      "| ai_pending:", first["ai_pending"])

tiers = {f["tier"] for f in f0}
expect(tiers <= {"definite", "likely", "consider"} and "definite" in tiers, "tiers assigned")


# citation contract (Improvement 3): every shown finding has a valid citation
rev0 = first["revision_id"]
import claims as _claims
from db import connect as _connect

conn = _connect()
wsid = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
expect(all(_claims.citation_check(conn, wsid, f, LAUNCH_POST) for f in f0),
       "no finding without a real, active citation")

# Resolve: accept every suggested fix, revision by revision (creator decision)
pending = [f["id"] for f in f0]
tried: set = set()
for _ in range(12):
    d = arjun.get(f"/submissions/{first['submission_id']}").json()
    open_f = [f for f in d["findings"] if f["status"] == "open"]
    if not open_f:
        break
    open_f.sort(key=lambda f: -len(f["span_text"] or ""))  # longest spans first
    f = open_f[0]
    print(f"  resolve#{_}: {f['category']} | span={f['span_text']!r} | sugg={f['suggestion']} | present={f['span_text'] in d['latest_revision']['content']}")
    sig = (f["category"], f["span_text"])
    if sig in tried or f["span_text"] not in d["latest_revision"]["content"]:
        print("  stopping: repeated or unresolvable finding")
        break
    tried.add(sig)
    sugg = f["suggestion"] or {}
    span = f["span_text"]
    if sugg.get("replace") or sugg.get("operation") == "remove":
        arjun.post(f"/submissions/{first['submission_id']}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"], "action": "accept"})
    elif f["category"] in ("missing_disclaimer", "missing_cta"):
        # fix in the creator's own words: end with a CTA/link (rule MSG-03)
        arjun.post(f"/submissions/{first['submission_id']}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"], "action": "edit",
            "replacement": (span.rstrip("!").rstrip() + ". Sign up: https://quillmark.co/launch")})
    elif f["category"] == "banned_term" and span.lower() == "trusted by":
        # swap the banned phrase for the approved alternative
        arjun.post(f"/submissions/{first['submission_id']}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"], "action": "edit",
            "replacement": "used by"})
    elif f["category"] == "tone" and span.lower().startswith("just "):
        # drop the pushy "just" (VOICE-3.2)
        arjun.post(f"/submissions/{first['submission_id']}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"], "action": "edit",
            "replacement": span[5:]})
    else:
        arjun.post(f"/submissions/{first['submission_id']}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"], "action": "dispute",
            "reason": "rule doesn't apply"})

r2 = arjun.get(f"/submissions/{first['submission_id']}")
latest = r2.json()["latest_revision"]
print("revision 2 content:", latest["content"])
expect("Quillmark Pulse" in latest["content"] and "1,299" in latest["content"],
       "fixes applied into a new revision")


owner = maya
r3 = owner.post(f"/submissions/{first['submission_id']}/submit-review")
expect(r3.status_code == 200, "submit for review")
print("routing:", r3.json().get("risk"), "-", r3.json().get("note"))
expect(r3.json().get("risk") == "low", "risk Low after fixes -> fast track")


r4 = maya.post(f"/submissions/{first['submission_id']}/review", json={
    "action": "approve", "comment": "Pre-checked, low risk. Approved."})
expect(r4.status_code == 200 and r4.json().get("status") == "Signed", "reviewer approved -> Signed")
poc_id = r4.json()["poc_id"]

r5 = arjun.get(f"/verify/{poc_id}")
expect(r5.json()["status"] == "verified", "Proof of Compliance: Verified")
print("poc record:", json.dumps(r5.json()["record"], indent=2)[:0] or r5.json()["status"])

# over-trust guard: high-severity cannot be approved silently
r_bad = arjun.post("/submissions", json={
    "title": "Unfixed copy", "channel": "social", "source_type": "ai-assisted", "content": LAUNCH_POST})
sid2 = r_bad.json()["submission_id"]
maya.post(f"/submissions/{sid2}/submit-review")
r6 = maya.post(f"/submissions/{sid2}/review", json={"action": "approve"})
expect(r6.status_code == 409, "high-severity findings block approval without resolution")

# Verified Claim Memory: re-running the same claims is instant, stored verdicts
me = arjun.post("/submissions", json={
    "title": "Repeat check (VCM)", "channel": "social", "source_type": "ai-assisted", "content": LAUNCH_POST})
mem = conn.execute("SELECT COUNT(*) c FROM claim_memory").fetchone()["c"]
expect(mem >= 2, f"claim memory populated ({mem} verdicts stored)")


r = engine.app  # keep module referenced
print("\nALL ENGINE TESTS PASSED")
