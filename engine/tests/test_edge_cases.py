"""Edge-case tests for the 2026-10-27 hardening pass (fresh test DB).

Probes the API surface the normal suites leave alone: input validation on
login/resolve/override, the insights payload shape, number-format
normalisation, dashboard open-finding counts and sentence splitting.

Run:  .venv/Scripts/python engine/tests/test_edge_cases.py
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_edge.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import checkers  # noqa: E402
import claims  # noqa: E402
import main as engine  # noqa: E402

# Test clients use localhost HTTP with password-free demo login.
engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def make_client(email):
    c = TestClient(engine.app, raise_server_exceptions=False)
    r = c.post("/login", json={"email": email})
    assert r.status_code == 200, r.text
    return c


def submit(client, content, channel="web", source="in-house", title="edge"):
    return client.post("/submissions", json={"title": title, "channel": channel,
                                             "source_type": source, "content": content})


anon = TestClient(engine.app, raise_server_exceptions=False)

# --- 1. login validates the email address -------------------------------------
for bad, label in (("", "empty"), ("   ", "whitespace"), ("not-an-email", "no @"),
                   ("a@b", "one-letter domain"), ("x" * 300 + "@example.com", "over 254 chars")):
    r = anon.post("/login", json={"email": bad})
    expect(r.status_code == 422, f"login refuses {label} email ({r.status_code})")
    if r.status_code == 200:
        anon.post("/logout")

r = anon.post("/login", json={"email": "  Dev@Quillmark.COM  "})
expect(r.status_code == 200, f"a normal email signs in ({r.status_code})")
me = anon.get("/me").json()
expect(me.get("email") == "dev@quillmark.com", f"email is normalised ({me.get('email')})")
expect(me.get("name") == "Dev", f"a derived name is never blank ({me.get('name')!r})")

r2 = TestClient(engine.app, raise_server_exceptions=False).post("/login", json={"email": "ARJUN@QUILLMARK"})
expect(r2.status_code == 200 and r2.json().get("id") == "arjun",
       f"an existing persona signs in case-insensitively, no duplicate ({r2.text[:80]})")

arjun = make_client("arjun@quillmark")
maya = make_client("maya@quillmark")

# --- 2. resolve: unknown action is a validation error, not a crash -------------
r = submit(arjun, "Quillmark Insights is a fast analytics product.").json()
sid, rid = r["submission_id"], r["revision_id"]
fid = r["findings"][0]["id"]
resp = arjun.post(f"/submissions/{sid}/resolve",
                  json={"revision_id": rid, "finding_id": fid, "action": "banana"})
expect(resp.status_code == 422, f"unknown resolve action refused ({resp.status_code})")
detail = arjun.get(f"/submissions/{sid}").json()
expect(detail["decisions"] == [], "a refused action leaves no decision behind")
expect(len(detail["revisions"]) == 1, "a refused action forks no revision")

# --- 3. resolve: edit needs replacement text ----------------------------------
resp = arjun.post(f"/submissions/{sid}/resolve",
                  json={"revision_id": rid, "finding_id": fid, "action": "edit", "replacement": "  "})
expect(resp.status_code == 422, f"edit without replacement text refused ({resp.status_code})")

# --- 4. resolve: accept is refused when there is no automatic fix -------------
LONG = ("Quillmark Pulse gives team members one place to see the numbers that matter across every "
        "product line region channel and campaign so that nobody has to wait for a report again today.")
r = submit(arjun, LONG).json()
sid_no_fix = r["submission_id"]
f_no_fix = next(f for f in r["findings"] if f["category"] == "readability")
expect(f_no_fix["suggestion"] is None, "the long-sentence finding carries no automatic fix")
resp = arjun.post(f"/submissions/{sid_no_fix}/resolve",
                  json={"revision_id": r["revision_id"], "finding_id": f_no_fix["id"], "action": "accept"})
expect(resp.status_code == 409, f"accept with nothing to accept is refused ({resp.status_code})")

# --- 5. review override: the finding must exist on the current revision -------
r = submit(arjun, "Quillmark Pulse is trusted by 5,000+ teams. Learn more: https://quillmark.co").json()
sid_ov, rid_ov = r["submission_id"], r["revision_id"]
high = [f for f in r["findings"] if f["severity"] == "high"][0]
# fork a revision by accepting the high claim (content changes only before review)
arjun.post(f"/submissions/{sid_ov}/resolve",
           json={"revision_id": rid_ov, "finding_id": high["id"], "action": "accept"})
arjun.post(f"/submissions/{sid_ov}/submit-review")

approvals_before = len(arjun.get(f"/submissions/{sid_ov}").json()["approvals"])
resp = maya.post(f"/submissions/{sid_ov}/review",
                 json={"action": "override", "finding_id": "fnd_deadbeef", "reason": "test"})
expect(resp.status_code == 404, f"override of an unknown finding refused ({resp.status_code})")

# target the old revision's finding
resp = maya.post(f"/submissions/{sid_ov}/review",
                 json={"action": "override", "finding_id": high["id"], "reason": "fact outdated"})
expect(resp.status_code == 404, f"override of a stale-revision finding refused ({resp.status_code})")
approvals_after = len(arjun.get(f"/submissions/{sid_ov}").json()["approvals"])
expect(approvals_after == approvals_before,
       f"refused overrides write no approvals ({approvals_before} -> {approvals_after})")

# --- 6. insights: decisions is an action -> count map --------------------------
conn = connect()
expected = {row["action"]: row["c"] for row in conn.execute(
    "SELECT action, COUNT(*) c FROM decisions GROUP BY action").fetchall()}
ins = maya.get("/insights").json()
expect(bool(expected), "some decisions were recorded by now")
expect(ins.get("decisions") == expected,
       f"insights decisions is action->count ({ins.get('decisions')} vs {expected})")

# --- 7. number formats: 2300 and 2,300 are the same number ---------------------
facts = conn.execute("SELECT * FROM facts WHERE id = 'F-012'").fetchall()
v = claims.classify_match("count", "trusted by 2300+ teams", facts)
expect(v["verdict"] == "supported", f"a count without comma grouping matches its fact ({v['verdict']})")
r = submit(arjun, "Quillmark Pulse is trusted by 2300+ teams. Start your free trial at quillmark.co/pulse.").json()
wrong = [f for f in r["findings"] if f["category"] in ("contradicted_claim", "unsupported_claim")]
expect(not wrong, f"a correctly-formatted-only difference is not flagged {[f['span']['text'] for f in wrong]}")

# --- 8. dashboard open_findings counts the latest revision only ----------------
PLAN_POST = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams "
             "and fully ISO 27001 certified. Plans start at just ₹999/month!")
r = submit(arjun, PLAN_POST, channel="social", source="ai-assisted").json()
sid_plan = r["submission_id"]
d = arjun.get(f"/submissions/{sid_plan}").json()
fixable = next(f for f in d["findings"] if f["status"] == "open" and f["suggestion"]
               and (f["suggestion"].get("replace") or f["suggestion"].get("operation") == "remove"))
arjun.post(f"/submissions/{sid_plan}/resolve",
           json={"revision_id": d["latest_revision"]["id"], "finding_id": fixable["id"], "action": "accept"})
d = arjun.get(f"/submissions/{sid_plan}").json()
latest_open = len([f for f in d["findings"] if f["status"] == "open"])
row = next(s for s in arjun.get("/submissions").json()["submissions"] if s["id"] == sid_plan)
expect(row["open_findings"] == latest_open,
       f"dashboard ignores findings resolved on earlier revisions ({row['open_findings']} vs {latest_open})")

# --- 9. a decimal number does not split a sentence -----------------------------
ctx = checkers.Ctx(conn, "rev_edge", "blog", "in-house", 1)
DEC_FRACTION = ("Quillmark Pulse serves more than 4.2 crore customers across India and every regional team "
                "ships improvements every single week without waiting for long monthly reports anymore.")
read = [f for f in checkers.check_readability(ctx, DEC_FRACTION)
        if any(c["id"] == "VOICE-3.1" for c in f["citations"])]
expect(read and read[0]["span"]["text"].startswith("Quillmark"),
       f"a 26-word sentence with a decimal is seen whole ({[f['span']['text'][:40] for f in read]})")

# --- 10. rule change preview: a proposed edit shows what would newly break ----
r = submit(arjun, "Quillmark Pulse keeps every launch on brand. Learn more: https://quillmark.co/pulse").json()
sid_pv = r["submission_id"]
arjun.post(f"/submissions/{sid_pv}/submit-review")
app = maya.post(f"/submissions/{sid_pv}/review", json={"action": "approve"})
expect(app.status_code == 200, f"preview fixture approves ({app.status_code})")
pv = maya.post("/rules/BRD-01/preview-change", json={"dont_example": "launch"})
expect(pv.status_code == 200, f"rule preview answers ({pv.status_code})")
if pv.status_code == 200:
    body = pv.json()
    expect(body["impacted"]["before"] == 0, f"the stored rule touches nothing approved ({body['impacted']['before']})")
    expect(body["impacted"]["new_breakages"] == 1
           and body["new_breakages"][0]["submission_id"] == sid_pv,
           f"a proposed don't-example shows the newly-broken item {body['new_breakages']}")
    expect(body["proposed"]["statement"].startswith("Use the approved palette"),
           "preview echoes the proposed rule text")
pj = maya.post("/rules/BRD-01/preview-change", json={"dont_example": ""}).json()
expect(pj["impacted"]["after"] == 0 and pj["impacted"]["new_breakages"] == 0,
       "an empty don't-example breaks nothing")

# --- 11. the audit log hash chain verifies -------------------------------------
rows = connect().execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
prev, chain_ok = "GENESIS", bool(rows)
for row in rows:
    if row["prev_hash"] != prev:
        chain_ok = False
        break
    payload = f"{prev}|{row['at']}|{row['actor']}|{row['action']}|{row['detail']}"
    if hashlib.sha256(payload.encode()).hexdigest() != row["hash"]:
        chain_ok = False
        break
    prev = row["hash"]
expect(chain_ok, "audit log hash chain verifies end to end")

# --- 12. a tampered seal is not 'verified' -------------------------------------
r = submit(arjun, "Quillmark Pulse helps team members see their numbers. Learn more: https://quillmark.co").json()
arjun.post(f"/submissions/{r['submission_id']}/submit-review")
app = maya.post(f"/submissions/{r['submission_id']}/review", json={"action": "approve"})
expect(app.status_code == 200, f"clean copy approves ({app.status_code} {app.text[:80]})")
poc_id = app.json().get("poc_id")
ver = maya.get(f"/verify/{poc_id}").json()
expect(ver["status"] == "verified", f"the fresh seal verifies ({ver['status']})")
conn.execute("UPDATE proof_of_compliance SET record_json = replace(record_json, 'ProofOfCompliance/2', 'ProofOfCompliance/9') WHERE id = ?",
             (poc_id,))
conn.commit()
tampered = maya.get(f"/verify/{poc_id}").json()
expect(tampered["status"] == "unknown" and tampered["signature_valid"] is False,
       f"a tampered record fails verification ({tampered['status']}, valid={tampered['signature_valid']})")

print()
if failures:
    print(f"{len(failures)} EDGE-CASE TEST(S) FAILED")
    raise SystemExit(1)
print("ALL EDGE-CASE TESTS PASSED")
