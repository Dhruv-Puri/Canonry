"""Regression tests for bugs found in the Round 2 review (fresh test DB).

Run:  .venv/Scripts/python engine/tests/test_regressions.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

# Print rupee signs and other non-ASCII output on any console encoding.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_regress.db")
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

# the launch post exactly as written in plan Section 1
PLAN_POST = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams "
             "and fully ISO 27001 certified. Plans start at just ₹999/month!")

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def make_client(email):
    c = TestClient(engine.app)
    assert c.post("/login", json={"email": email}).status_code == 200
    return c


def submit(client, content, channel="blog", source="in-house", title="t"):
    r = client.post("/submissions", json={"title": title, "channel": channel,
                                          "source_type": source, "content": content})
    return r


arjun = make_client("arjun@quillmark")
maya = make_client("maya@quillmark")

# --- 1. accepting every suggested fix leaves clean, grammatical copy -----------
r = submit(arjun, PLAN_POST, channel="social", source="ai-assisted").json()
sid = r["submission_id"]
for _ in range(10):
    d = arjun.get(f"/submissions/{sid}").json()
    fixable = [f for f in d["findings"] if f["status"] == "open" and f["suggestion"]
               and (f["suggestion"].get("replace") or f["suggestion"].get("operation") == "remove")]
    if not fixable:
        break
    arjun.post(f"/submissions/{sid}/resolve", json={
        "revision_id": d["latest_revision"]["id"], "finding_id": fixable[0]["id"], "action": "accept"})
d = arjun.get(f"/submissions/{sid}").json()
final = d["latest_revision"]["content"]
print("      final copy:", final)
expect(" ." not in final and "  " not in final and " ," not in final, "no dangling punctuation or double spaces")
expect("2,300+ teams" in final, "count fix keeps its noun ('2,300+ teams')")
expect("ISO" not in final and "#1" not in final and "999" not in final, "every wrong claim is gone")
expect("an analytics platform" in final, "superlative fix keeps the sentence readable")
still_open = [(f["category"], f["span_text"]) for f in d["findings"] if f["status"] == "open"]
expect(not any(f[0] == "banned_term" for f in still_open), f"engine's own fixes raise no new terminology findings {still_open}")
expect(not any(f["status"] == "open" and f["severity"] == "high" for f in d["findings"]), "no high-severity finding left")

# --- 2. a disputed finding stays disputed on the next revision ----------------
r = submit(arjun, "Quillmark Pulse is trusted by 5,000+ teams. Learn more: https://quillmark.co").json()
sid2 = r["submission_id"]
high = [f for f in r["findings"] if f["severity"] == "high"][0]
arjun.post(f"/submissions/{sid2}/resolve", json={"revision_id": r["revision_id"], "finding_id": high["id"],
                                                 "action": "dispute", "reason": "sales approved the new number"})
d = arjun.get(f"/submissions/{sid2}").json()
same = [f for f in d["findings"] if f["category"] == high["category"] and f["span_text"] == high["span"]["text"]]
expect(same and same[0]["status"] == "disputed", "dispute carries over to the re-checked revision")

# --- 3. reviewer override of one finding works and unblocks approval -----------
r = submit(arjun, "Quillmark Pulse is trusted by 5,000+ teams. Learn more: https://quillmark.co").json()
sid3 = r["submission_id"]
arjun.post(f"/submissions/{sid3}/submit-review")
fid = [f for f in r["findings"] if f["severity"] == "high"][0]["id"]
ov = maya.post(f"/submissions/{sid3}/review", json={"action": "override", "finding_id": fid, "reason": "fact outdated"})
expect(ov.status_code == 200, f"override with finding id accepted ({ov.status_code})")
ap = maya.post(f"/submissions/{sid3}/review", json={"action": "approve"})
expect(ap.status_code == 200, f"approve after override succeeds ({ap.status_code} {ap.text[:80]})")

# --- 4. a draft that was never submitted for review cannot be signed ----------
r = submit(arjun, "Quillmark Pulse helps team members see their data.").json()
ap = maya.post(f"/submissions/{r['submission_id']}/review", json={"action": "approve"})
expect(ap.status_code == 409, f"approving a never-submitted draft is refused ({ap.status_code})")

# --- 5. long social post does not crash; SOC-01 flagged ------------------------
big = ("Quillmark Pulse helps team members. " * 60).strip()
rr = submit(arjun, big, channel="social")
expect(rr.status_code == 200, f">200-word social post checks without error ({rr.status_code})")
if rr.status_code == 200:
    expect(any(c["id"] == "SOC-01" for f in rr.json()["findings"] for c in f["citations"]), "SOC-01 word limit flagged")

# --- 6. long-sentence readability finding survives the citation check ----------
LONG = ("Quillmark Pulse gives team members one place to see the numbers that matter across every "
        "product line region channel and campaign so that nobody has to wait for a report again today.")
rr = submit(arjun, LONG).json()
expect(any(f["category"] == "readability" for f in rr["findings"]), "long sentence flagged (VOICE-3.1)")

# --- 7. false alarms on ordinary words ----------------------------------------
CLEAN = "Our misleading-claims checklist covers the best practices for leading teams."
rr = submit(arjun, CLEAN).json()
expect(rr["findings"] == [], f"no superlative false alarms {[f['span']['text'] for f in rr['findings']]}")
rr = submit(arjun, "Quillmark Pulse is the leading analytics platform in India.").json()
expect(any(f["category"] == "unsupported_claim" for f in rr["findings"]), "a real superlative is still flagged")

# --- 8. no AI key: AI checks marked pending, never silently skipped ------------
expect(rr["ai_pending"] is True, "ai_pending is true when no provider is configured")
detail = arjun.get(f"/submissions/{rr['submission_id']}").json()
expect((detail.get("check") or {}).get("status") == "ai_pending",
       f"submission detail tells the UI the AI checks are pending ({detail.get('check')})")

# a connected provider that finds no implied claims is a finished check, not a pending one
import claims as _claims  # noqa: E402
import gateway as _gateway  # noqa: E402

_saved = (_gateway.any_available, _claims.ai_implicit_claims, _gateway.gateway_call)
_gateway.any_available = lambda: True
_claims.ai_implicit_claims = lambda text, budget, conn, **_: []
_gateway.gateway_call = lambda *a, **k: {"text": '{"tone_findings": []}', "model": "stub"}
try:
    rr = submit(arjun, "Quillmark Pulse helps team members see their numbers.").json()
    expect(rr.get("ai_pending") is False, f"empty AI answer is not 'pending' (ai_pending={rr.get('ai_pending')})")
    _gateway.gateway_call = lambda *a, **k: None  # provider listed, but the tone call fails
    rr = submit(arjun, "Quillmark Pulse helps team members see their numbers today.").json()
    expect(rr.get("ai_pending") is True, f"a failed tone call is 'pending' (ai_pending={rr.get('ai_pending')})")
finally:
    _gateway.any_available, _claims.ai_implicit_claims, _gateway.gateway_call = _saved

# --- 9. small endpoints ------------------------------------------------------
expect(maya.get("/alerts/claims-in-review").status_code == 200, "/alerts/claims-in-review answers")
expect(TestClient(engine.app).get("/health").json().get("ok") is True, "/health answers without sign-in")
# approve the cleaned launch post, which fixed a price claim citing X-101
arjun.post(f"/submissions/{sid}/submit-review")
maya.post(f"/submissions/{sid}/review", json={"action": "approve"})
alerts = {a["fact"]["id"]: a for a in maya.get("/alerts/expiry").json()["alerts"]}
expect(sid in [s["id"] for s in alerts["X-101"]["affected_approved_content"]],
       "expiry alert lists approved content that touched the superseded price fact")

# --- 10. MCP check_claim tool -------------------------------------------------
msgs = "\n".join(json.dumps(m) for m in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
     "params": {"name": "check_claim", "arguments": {"claim": "trusted by 5,000+ teams"}}},
]) + "\n"
env = dict(os.environ, CANONRY_DB_PATH=os.path.abspath(_db.DB_PATH), PYTHONIOENCODING="utf-8")
out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_server.py")],
                     input=msgs, capture_output=True, text=True, env=env, encoding="utf-8").stdout
lines = [json.loads(line) for line in out.splitlines() if line.strip()]
res = lines[-1]["result"] if lines else {"isError": True, "content": [{"text": "{}"}]}
verdict = json.loads(res["content"][0]["text"]).get("verdict")
expect(not res["isError"] and verdict == "contradicted", f"MCP check_claim works (verdict={verdict})")

# --- 11. signed content cannot be pushed back into review ---------------------
again = arjun.post(f"/submissions/{sid}/submit-review")
expect(again.status_code == 409, f"re-submitting signed content is refused ({again.status_code})")

# --- 12. found by the 2026-10-27 case matrix -----------------------------------
for content, label in (("", "empty"), ("   \n ", "whitespace-only")):
    r = submit(arjun, content)
    expect(r.status_code == 422, f"{label} draft refused ({r.status_code})")
r = submit(arjun, "Quillmark Pulse helps team members.", title="  ")
expect(r.status_code == 422, f"blank title refused ({r.status_code})")
r = submit(arjun, "Quillmark Pulse helps team members.", channel="fax")
expect(r.status_code == 422, f"unknown channel refused ({r.status_code})")

r = submit(arjun, "Quillmark Insights is great. Quillmark Insights is fast.").json()
starts = sorted(f["span"]["start"] for f in r["findings"] if f["category"] == "outdated_term")
expect(starts == [0, 29], f"a repeated outdated name is flagged at every place ({starts})")
r = submit(arjun, "Trusted by 5,000+ teams. Yes, trusted by 5,000+ teams.").json()
n = len([f for f in r["findings"] if f["category"] == "contradicted_claim"])
expect(n == 2, f"a repeated contradicted claim is flagged at every place ({n})")

sid5 = submit(arjun, "Quillmark Pulse helps team members see their numbers. Start your free trial at quillmark.co/pulse.").json()["submission_id"]
arjun.post(f"/submissions/{sid5}/submit-review")
r = maya.post(f"/submissions/{sid5}/review", json={"action": "request_changes"})
expect(r.status_code == 422, f"request changes without a reason refused ({r.status_code})")
r = maya.post(f"/submissions/{sid5}/review", json={"action": "request_changes", "reason": "Add the pricing link."})
expect(r.status_code == 200, f"request changes with a reason accepted ({r.status_code})")

print()
if failures:
    print(f"{len(failures)} REGRESSION TEST(S) FAILED")
    raise SystemExit(1)
print("ALL REGRESSION TESTS PASSED")
