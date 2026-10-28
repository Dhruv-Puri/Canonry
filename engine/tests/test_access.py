"""Role scoping on every read endpoint (fresh test DB).

An agency partner sees only the submissions it created, on every screen, and
nobody below reviewer sees the text of a confidential fact, wherever it shows up.

Run:  .venv/Scripts/python engine/tests/test_access.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_access.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import access  # noqa: E402
import main as engine  # noqa: E402

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


arjun, maya, riya = login("arjun@quillmark"), login("maya@quillmark"), login("riya@agency")

# arjun's work: one disputed finding, one approved item that cites CLM-01
s = arjun.post("/submissions", json={"title": "ARJUN-PRIVATE launch", "channel": "social",
               "source_type": "in-house", "content": "India's #1 analytics platform."}).json()
det = arjun.get(f"/submissions/{s['submission_id']}").json()
arjun.post(f"/submissions/{s['submission_id']}/resolve", json={
    "revision_id": det["latest_revision"]["id"], "finding_id": det["findings"][0]["id"],
    "action": "dispute", "reason": "ARJUN-REASON"})
a = arjun.post("/submissions", json={"title": "ARJUN-APPROVED note", "channel": "blog",
               "source_type": "in-house", "content": "Reports load 47% faster."}).json()
arjun.post(f"/submissions/{a['submission_id']}/submit-review")
ap = maya.post(f"/submissions/{a['submission_id']}/review", json={"action": "approve"})
expect(ap.status_code == 200, f"setup: arjun's note approved ({ap.status_code})")
conn = connect()
v = conn.execute("SELECT version FROM rules WHERE id='CLM-01'").fetchone()[0]
r = maya.put("/kb/rules/CLM-01", json={"statement": "Every figure in public content must trace to an approved fact.",
                                        "expected_version": v, "reason": "wording"})
expect(r.status_code == 200, f"setup: CLM-01 edited so the approval is stale ({r.status_code})")
conn.execute("UPDATE facts SET valid_to='2020-01-01' WHERE id='CONF-03'")  # an expired confidential fact
conn.commit()

# riya's own work
mine = riya.post("/submissions", json={"title": "RIYA-OWN draft", "channel": "web",
                 "source_type": "agency", "content": "Trusted by 9,000+ teams."}).json()

print("== insights")
ins = riya.get("/insights")
body = ins.text
expect(ins.status_code == 200, "agency can open insights")
expect("ARJUN-PRIVATE" not in body and "ARJUN-REASON" not in body, "no other creator's titles or dispute reasons")
data = ins.json()
expect(sum(s["c"] for s in data["statuses"]) == 1, f"status counts cover only riya's own item ({data['statuses']})")
own = conn.execute("SELECT COUNT(*) FROM findings f JOIN revisions r ON r.id=f.revision_id "
                   "WHERE r.submission_id=?", (mine["submission_id"],)).fetchone()[0]
expect(sum(c["c"] for c in data["by_checker"].values()) == own,
       f"finding counts cover only riya's own findings ({own})")
full = maya.get("/insights").text
expect("ARJUN-PRIVATE" in full and "ARJUN-REASON" in full, "a reviewer still sees the whole workspace")

# re-checking a draft re-reports the same issue on every revision; insights count it once
before = riya.get("/insights").json()
for _ in range(2):
    riya.post(f"/submissions/{mine['submission_id']}/recheck")
after = riya.get("/insights").json()
expect(after["by_checker"] == before["by_checker"] and after["categories"] == before["categories"],
       "an issue repeated across revisions counts once")

print("== expiry alerts")
for who, client in (("agency", riya), ("creator", arjun)):
    body = client.get("/alerts/expiry").text
    expect("Logo churn 2.1%" not in body, f"{who} never sees confidential fact text")
    expect(access.CONFIDENTIAL_PLACEHOLDER in body, f"{who} sees the placeholder instead")
expect("Logo churn 2.1%" in maya.get("/alerts/expiry").text, "a reviewer sees the confidential fact")
expect("ARJUN" not in riya.get("/alerts/expiry").text, "agency sees no other creator's affected content")

print("== AI-pending list")
pend = riya.get("/alerts/claims-in-review").json()["pending"]
expect(all(p["submission_id"] == mine["submission_id"] for p in pend), f"only riya's own runs listed ({len(pend)})")
expect(any(p["title"].startswith("ARJUN") for p in maya.get("/alerts/claims-in-review").json()["pending"]),
       "a reviewer sees everyone's pending runs")

print("== stale approvals")
expect(len(maya.get("/kb/stale-approvals").json()["items"]) >= 1, "a reviewer sees the stale approval")
expect(riya.get("/kb/stale-approvals").json()["items"] == [], "agency sees no other creator's approvals")

print("== rule-change preview")
pv = riya.post("/rules/CLM-01/preview-change", json={"dont_example": "faster"})
expect(pv.status_code == 403, f"only rule editors preview rule changes ({pv.status_code})")
expect(maya.post("/rules/CLM-01/preview-change", json={"dont_example": "faster"}).status_code == 200,
       "a reviewer can preview")
conn.close()

print()
if failures:
    print(f"{len(failures)} ACCESS TEST(S) FAILED")
    raise SystemExit(1)
print("ALL ACCESS TESTS PASSED")
