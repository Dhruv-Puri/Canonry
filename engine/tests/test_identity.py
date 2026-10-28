"""Self-chosen identity (no login) and role-enforced access (fresh test DB).

Run:  .venv/Scripts/python engine/tests/test_identity.py
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

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

# Test clients use localhost HTTP. Production cookies remain Secure in the
# actual app; disable that attribute only in this isolated suite.
main.COOKIE_SECURE = False
# This suite explicitly exercises local persona behavior; let the client use the
# demo-mode self-join path without requiring a persisted environment setting.
main.DEMO_MODE = True

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

# ---- production-mode auth and single-use invitations --------------------------
main.DEMO_MODE = False
main.COOKIE_SECURE = False

# Bootstrap a production administrator with a deployment-configured password.
os.environ["CANONRY_BOOTSTRAP_ADMIN_EMAIL"] = "owner@example.com"
os.environ["CANONRY_BOOTSTRAP_ADMIN_PASSWORD"] = "a-long-deployment-password"
main._ensure_bootstrap_admin()
owner = TestClient(main.app)
login = owner.post("/login", json={"email": "owner@example.com", "password": "a-long-deployment-password"})
expect(login.status_code == 200 and owner.get("/me").json().get("role") == "admin", "production admin signs in with password")
expect(owner.post("/login", json={"email": "owner@example.com", "password": "wrong-password"}).status_code == 401,
       "production login rejects an incorrect password")
expect(owner.patch("/me", json={"role": "admin"}).status_code == 403, "production users cannot self-assign a role")
expect(owner.get("/workspace").json().get("me", {}).get("password_hash") is None, "workspace API does not expose password hashes")
invite = owner.post("/invitations", json={"email": "new.writer@example.com", "role": "reviewer"})
expect(invite.status_code == 200, f"admin can issue a role-bound invitation ({invite.status_code})")
token = invite.json().get("invitation", "")
info = owner.get(f"/invitations/{token}")
expect(info.status_code == 200 and info.json().get("role") == "reviewer", "invitation preview reveals its assigned role")
joined = TestClient(main.app)
joined_response = joined.post("/join", json={"name": "New Writer", "email": "new.writer@example.com", "password": "secure-password-123", "role": "admin", "invitation": token})
expect(joined_response.status_code == 200 and joined.get("/me").json().get("role") == "reviewer", "invite overrides any submitted role")
expect(owner.post("/join", json={"name": "No Invite", "email": "no.invite@example.com", "password": "secure-password-123", "role": "admin"}).status_code == 403,
       "production signup requires an invitation")
expect(TestClient(main.app).post("/join", json={"name": "Replay", "email": "new.writer@example.com", "password": "secure-password-123", "invitation": token}).status_code == 403,
       "used invitations cannot create another account")
expect(owner.post("/invitations", json={"email": "x@example.com", "role": "admin"}, headers={"Origin": "https://attacker.invalid"}).status_code == 403,
       "cross-origin state changes are blocked")

# Production rulebook uploads are previews first and remain inactive drafts.
md = b"# Voice\nUse short, active sentences for every customer-facing headline.\n- Avoid unsupported superiority claims in all public copy.\n"
preview = owner.post("/rules/import-document?filename=voice.md", content=md, headers={"Content-Type": "application/octet-stream"})
expect(preview.status_code == 200 and len(preview.json().get("proposals", [])) == 2,
       f"Markdown rulebook produces editable proposals ({preview.status_code})")
proposals = preview.json().get("proposals", [])
expect(all(p.get("status") == "draft" and p.get("category") == "Voice" for p in proposals),
       "import preview categorizes rule suggestions and marks them draft")
drafts = owner.post("/rules/import-drafts", json={"proposals": proposals})
expect(drafts.status_code == 200 and drafts.json().get("count") == 2
       and all(rule["status"] == "draft" for rule in drafts.json().get("created", [])),
       f"reviewed import saves inactive drafts ({drafts.status_code})")
docx_bytes = io.BytesIO()
with zipfile.ZipFile(docx_bytes, "w") as archive:
    archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Claims</w:t></w:r></w:p><w:p><w:r><w:t>Every product claim must match an approved and current fact.</w:t></w:r></w:p></w:body></w:document>')
preview_docx = owner.post("/rules/import-document?filename=claims.docx", content=docx_bytes.getvalue(), headers={"Content-Type": "application/octet-stream"})
expect(preview_docx.status_code == 200 and preview_docx.json().get("proposals", [{}])[0].get("category") == "Claims",
       f"valid DOCX paragraphs are extracted ({preview_docx.status_code})")
invalid_docx = owner.post("/rules/import-document?filename=not-a-doc.docx", content=b"not a zip", headers={"Content-Type": "application/octet-stream"})
expect(invalid_docx.status_code == 422, "malformed DOCX is rejected cleanly")
large = owner.post("/rules/import-document?filename=large.txt", content=b"x" * (5 * 1024 * 1024 + 1), headers={"Content-Type": "application/octet-stream"})
expect(large.status_code == 413, "oversized document rejected before parsing")
main.DEMO_MODE = True
main.COOKIE_SECURE = False
os.environ.pop("CANONRY_BOOTSTRAP_ADMIN_EMAIL", None)
os.environ.pop("CANONRY_BOOTSTRAP_ADMIN_PASSWORD", None)

# Demo persona tests use their normal no-password / role-picker path.
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
