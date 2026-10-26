"""Self-chosen identity (no login) and role-enforced access (fresh test DB).

Run:  .venv/Scripts/python engine/test_identity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_identity.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import main  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def person(name, role):
    c = TestClient(main.app)
    r = c.post("/join", json={"name": name, "role": role})
    return c, r


RULE_EDIT = {"category": "Brand", "statement": "Use the approved palette: Ink, Teal and Paper only.",
             "severity": "low", "status": "approved", "reason": "tidy wording"}

# ---- Task 1: join, switch role, logout ----------------------------------------
priya, r = person("  Priya Raman ", "creator")
me = priya.get("/me").json()
expect(r.status_code == 200 and me.get("name") == "Priya Raman" and me.get("role") == "creator",
       f"join creates the person ({r.status_code} {me})")

for bad in ("A", "x" * 41, "   "):
    expect(person(bad, "creator")[1].status_code == 422, f"join validates name ({bad[:6]!r})")
expect(person("Kabir", "boss")[1].status_code == 422, "join validates role")

twin, _ = person("Priya Raman", "creator")
expect(twin.get("/me").json()["id"] != me["id"], "same name, different people")

ver = priya.get("/rules").json()["rules"]
ver = next(x for x in ver if x["id"] == "BRD-01")["version"]
r = priya.put("/kb/rules/BRD-01", json={**RULE_EDIT, "expected_version": ver})
expect(r.status_code == 403, f"a creator cannot edit the KB ({r.status_code})")
r = priya.patch("/me", json={"role": "reviewer"})
r2 = priya.put("/kb/rules/BRD-01", json={**RULE_EDIT, "expected_version": ver})
expect(r.status_code == 200 and r2.status_code == 200, f"role switch takes effect immediately ({r.status_code}, {r2.status_code})")
conn = connect()
row = conn.execute("SELECT detail FROM audit_log WHERE action='profile_change' ORDER BY seq DESC LIMIT 1").fetchone()
conn.close()
expect(row is not None and "creator -> reviewer" in row["detail"], f"role switch is audited ({row and row['detail']})")
r = priya.patch("/me", json={"name": "Priya R."})
expect(r.status_code == 200 and priya.get("/me").json()["name"] == "Priya R.", "rename keeps the same person")

leaver, _ = person("Dev Shah", "agency")
leaver.post("/logout")
expect(leaver.get("/me").status_code == 401, "logout ends the session")

# ---- Task 2: role-enforced visibility -----------------------------------------
import access  # noqa: E402

creator, _ = person("Meera Iyer", "creator")
reviewer, _ = person("Tom Okafor", "reviewer")
agency, _ = person("Sana from Northwind", "agency")
agency2, _ = person("Leo from Brightside", "agency")

conf_c = next(f for f in creator.get("/facts").json()["facts"] if f["id"] == "CONF-02")
conf_r = next(f for f in reviewer.get("/facts").json()["facts"] if f["id"] == "CONF-02")
expect(conf_c["text"] == access.CONFIDENTIAL_PLACEHOLDER, f"creator sees confidential facts redacted ({conf_c['text']})")
expect("4.2 crore" in conf_r["text"], "reviewer sees confidential text")

h = creator.get("/kb/facts/CONF-02/history").json()["versions"]
expect(h and all(v["snapshot"]["text"] == access.CONFIDENTIAL_PLACEHOLDER for v in h),
       "KB history redacts confidential snapshots for creators")


def sub(c, content):
    return c.post("/submissions", json={"title": "t", "channel": "web", "source_type": "in-house", "content": content}).json()


own = sub(agency, "Quillmark Pulse helps team members see their numbers.")["submission_id"]
other = sub(agency2, "Quillmark Pulse helps team members plan their week.")["submission_id"]
ids = [s["id"] for s in agency.get("/submissions").json()["submissions"]]
expect(own in ids and other not in ids, f"agency lists only own submissions ({len(ids)} listed)")
expect(agency.get(f"/submissions/{other}").status_code == 404, "agency cannot open others' submissions")
expect(other in [s["id"] for s in creator.get("/submissions").json()["submissions"]], "in-house creators still see team work")
codes = [agency.post(f"/submissions/{other}/recheck").status_code,
         agency.post(f"/submissions/{other}/submit-review").status_code,
         agency.post(f"/submissions/{other}/resolve", json={"revision_id": "x", "finding_id": "x", "action": "accept"}).status_code]
expect(codes == [404, 404, 404], f"agency cannot act on others' submissions ({codes})")

# ---- Task 2b: confidential-leak check -------------------------------------------
leak = sub(creator, "Big news: our MRR is 4.2 crore as of Sep 2026. Quillmark Pulse keeps growing.")
lf = [f for f in leak["findings"] if f["category"] == "confidential_leak"]
expect(lf and lf[0]["tier"] == "definite" and any(c["id"] == "CONF-02" for c in lf[0]["citations"]),
       f"a leaked figure is a definite confidential finding ({[(f['category'], f['tier']) for f in leak['findings']]})")
det = creator.get(f"/submissions/{leak['submission_id']}").json()
cit = [c for f in det["findings"] for c in f["citations"] if c["id"] == "CONF-02"]
expect(cit and cit[0]["excerpt"] == access.CONFIDENTIAL_PLACEHOLDER, "citations to confidential facts are redacted for creators")
det_r = reviewer.get(f"/submissions/{leak['submission_id']}").json()
cit_r = [c for f in det_r["findings"] for c in f["citations"] if c["id"] == "CONF-02"]
expect(cit_r and "4.2 crore" in cit_r[0]["excerpt"], "reviewers see the confidential citation text")

phrase = sub(creator, "Logo churn was something we tackled this quarter.")
pf = [f for f in phrase["findings"] if f["category"] == "confidential_leak"]
expect(pf and pf[0]["tier"] == "likely", f"a leaked phrase is a likely confidential finding ({[(f['category'], f['tier']) for f in phrase['findings']]})")

for text in ("Quillmark Pulse helps team members see their numbers. Start your free trial at quillmark.co/pulse.",
             "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully ISO 27001 "
             "certified. Plans start at just ₹999/month!",
             "Version 4.2 of the mobile app ships on Friday."):
    cats = [f["category"] for f in sub(creator, text)["findings"]]
    expect("confidential_leak" not in cats, f"ordinary copy raises no confidential finding ({text[:30]}…)")

# ---- Task 3: names in payloads, labelled self-approval ---------------------------
CLEAN = "Quillmark Pulse helps team members see their numbers. Start your free trial at quillmark.co/pulse."
solo, _ = person("Aarav Mehta", "creator")
s1 = sub(solo, CLEAN)["submission_id"]
solo.post(f"/submissions/{s1}/submit-review")
solo.patch("/me", json={"role": "reviewer"})
ap = solo.post(f"/submissions/{s1}/review", json={"action": "approve", "reason": "looks right"}).json()
det = solo.get(f"/submissions/{s1}").json()
rec = solo.get(f"/verify/{ap.get('poc_id')}").json().get("record", {}) if ap.get("poc_id") else {}
expect(ap.get("self_approved") is True and rec.get("self_approved") is True
       and det["approvals"][-1]["reason"].startswith("[self-approved]"),
       f"self-approval is labelled in the PoC ({ap.get('self_approved')}, {rec.get('self_approved')}, {det['approvals'][-1]['reason']})")

s2 = sub(creator, CLEAN + " ")["submission_id"]
creator.post(f"/submissions/{s2}/submit-review")
ap2 = reviewer.post(f"/submissions/{s2}/review", json={"action": "approve"}).json()
expect(ap2.get("self_approved") is False, f"approval by someone else is not self-approved ({ap2.get('self_approved')})")
det2 = reviewer.get(f"/submissions/{s2}").json()
expect(det2["approvals"][-1].get("reviewer_name") == "Tom Okafor", f"approvals carry names ({det2['approvals'][-1].get('reviewer_name')})")

s3 = sub(creator, "Our employees love Quillmark Insights.")
fid = s3["findings"][0]["id"]
creator.post(f"/submissions/{s3['submission_id']}/resolve",
             json={"revision_id": s3["revision_id"], "finding_id": fid, "action": "dispute", "reason": "brand name is quoted"})
det3 = creator.get(f"/submissions/{s3['submission_id']}").json()
expect(det3["decisions"] and det3["decisions"][-1].get("by_name") == "Meera Iyer",
       f"decisions carry names ({det3['decisions'] and det3['decisions'][-1].get('by_name')})")

h = reviewer.get("/kb/rules/BRD-01/history").json()["versions"]
expect(h[0].get("by_name") == "Priya R." and h[-1].get("by_name") is None,
       f"KB history carries names ({[v.get('by_name') for v in h]})")

print()
if failures:
    print(f"{len(failures)} IDENTITY TEST(S) FAILED")
    sys.exit(1)
print("ALL IDENTITY TESTS PASSED")
