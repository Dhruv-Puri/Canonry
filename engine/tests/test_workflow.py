"""Submission lifecycle: what each status allows (fresh test DB).

Content can change only while a draft is with its creator (Draft, Checked,
Changes requested). In review, the content the router assessed is the content
the reviewer decides on. Signed and exempt-approved content never changes.

Run:  .venv/Scripts/python engine/tests/test_workflow.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_workflow.db")
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
import workflow  # noqa: E402

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


arjun, maya = login("arjun@quillmark"), login("maya@quillmark")


def new(content, channel="blog"):
    sid = arjun.post("/submissions", json={"title": "wf", "channel": channel, "source_type": "in-house",
                                          "content": content}).json()["submission_id"]
    return sid


def detail(sid):
    return arjun.get(f"/submissions/{sid}").json()


def try_edits(sid):
    """Every way content can change; returns the status codes."""
    d = detail(sid)
    f = next((x for x in d["findings"] if x["status"] == "open"), None) or (d["findings"] or [None])[0]
    codes = [arjun.post(f"/submissions/{sid}/recheck").status_code]
    if f:
        codes.append(arjun.post(f"/submissions/{sid}/resolve", json={
            "revision_id": d["latest_revision"]["id"], "finding_id": f["id"],
            "action": "edit", "replacement": "loved by everyone"}).status_code)
    return codes


# --- the rules themselves ---------------------------------------------------------
print("== rules")
for status in ("Draft", "Checked", "Changes requested"):
    expect(workflow.blocked(status, "edit") is None, f"{status}: content can change")
    expect(workflow.blocked(status, "submit") is None, f"{status}: can be submitted")
for status in ("In review", "Signed", "Exempt-approved"):
    expect(workflow.blocked(status, "edit") is not None, f"{status}: content is locked")
    expect(workflow.blocked(status, "submit") is not None, f"{status}: cannot be resubmitted")
expect(workflow.blocked("In review", "approve") is None, "In review: can be approved")
expect(workflow.blocked("Checked", "approve") is not None, "Checked: cannot be approved")

# --- In review: locked ------------------------------------------------------------
print("== in review")
sid = new("Reports load 47% faster.")
arjun.post(f"/submissions/{sid}/submit-review")
revs = len(detail(sid)["revisions"])
codes = try_edits(sid)
expect(all(c == 409 for c in codes), f"no edits while in review ({codes})")
expect(len(detail(sid)["revisions"]) == revs, "no new revision was created")

# --- Changes requested: open again, and the router reassesses -----------------------
print("== changes requested")
maya.post(f"/submissions/{sid}/review", json={"action": "request_changes", "comment": "cite the source"})
d = detail(sid)
f = d["findings"][0]
r = arjun.post(f"/submissions/{sid}/resolve", json={"revision_id": d["latest_revision"]["id"], "finding_id": f["id"],
               "action": "edit", "replacement": "Reports load faster"})
expect(r.status_code == 200, f"creator can edit after changes are requested ({r.status_code})")
r = arjun.post(f"/submissions/{sid}/submit-review").json()
expect(r["risk"] == "low", f"resubmission is routed on the new content ({r['risk']})")

# --- Signed: frozen forever ---------------------------------------------------------
print("== signed")
ap = maya.post(f"/submissions/{sid}/review", json={"action": "approve"}).json()
expect(ap.get("status") == "Signed", f"approved and signed ({ap.get('status')})")
revs = len(detail(sid)["revisions"])
codes = try_edits(sid)
expect(all(c == 409 for c in codes), f"no edits after signing ({codes})")
expect(detail(sid)["allowed"] == {"edit": False, "submit": False, "approve": False, "request_changes": False,
                                  "override": False}, "the detail payload says nothing is allowed any more")
expect(len(detail(sid)["revisions"]) == revs and detail(sid)["submission"]["status"] == "Signed",
       "signed content and status unchanged")
expect(arjun.post(f"/submissions/{sid}/submit-review").status_code == 409, "a signed item cannot be resubmitted")
expect(maya.post(f"/submissions/{sid}/review", json={"action": "approve"}).status_code == 409,
       "a signed item cannot be approved twice")

# --- public verification: check the text that was actually published ---------------
print("== public verification")
public = TestClient(engine.app, raise_server_exceptions=False)  # no sign-in
signed_text = detail(sid)["latest_revision"]["content"]
seal = public.get(f"/verify/{ap['poc_id']}").json()
expect(seal["status"] == "verified" and seal["content_checked"] is False,
       f"the seal itself verifies without content ({seal['status']})")
expect("approved_by" not in seal["record"] and "arjun@" not in str(seal) and "maya@" not in str(seal),
       "the public answer carries no email address")
expect(seal["record"].get("approver_role") == "reviewer", "it says which role approved")
same = public.post(f"/verify/{ap['poc_id']}", json={"content": signed_text}).json()
expect(same["status"] == "verified" and same["content_checked"] is True, f"the published text verifies ({same['status']})")
spaced = public.post(f"/verify/{ap['poc_id']}", json={"content": "  " + signed_text.replace(" ", "\n ") + "\n"}).json()
expect(spaced["status"] == "verified" and "spacing" in (spaced.get("reason") or ""),
       f"copy-paste spacing differences still verify, with a note ({spaced['status']}, {spaced.get('reason')})")
changed = public.post(f"/verify/{ap['poc_id']}", json={"content": signed_text + " Now 50% off!"}).json()
expect(changed["status"] == "modified", f"edited text is reported as modified ({changed['status']})")
expect(public.post("/verify/poc_nope", json={"content": "x"}).json()["status"] == "unknown", "unknown seal id")
expect(public.post(f"/verify/{ap['poc_id']}", json={"content": "x" * 200_001}).status_code == 422,
       "oversized text is refused")

# --- Exempt-approved: frozen too ----------------------------------------------------
print("== exempt-approved")
sid = new("Quillmark Pulse helps teams read their data.", channel="email")
r = arjun.post(f"/submissions/{sid}/submit-review").json()
expect(r["status"] == "Exempt-approved", f"clean email digest is exempt-approved ({r['status']})")
codes = try_edits(sid)
expect(all(c == 409 for c in codes), f"no edits after exempt approval ({codes})")

print()
if failures:
    print(f"{len(failures)} WORKFLOW TEST(S) FAILED")
    raise SystemExit(1)
print("ALL WORKFLOW TESTS PASSED")
