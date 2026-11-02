"""A writer can see what a reviewer decided and act on it.

Before 3 Nov 2026 a creator could not tell from their list whether a draft was approved or sent
back, and could not change the text of a sent-back draft at all (only accept or reword flagged
phrases), so a reviewer comment such as "add the trial link" could not be done.

Run:  .venv/Scripts/python engine/tests/test_creator_work.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_creator_work")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from seed import seed  # noqa: E402

main.DEMO_MODE = True
main.COOKIE_SECURE = False
seed()

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def login(email):
    c = TestClient(main.app, raise_server_exceptions=False)
    c.__enter__()
    assert c.post("/login", json={"email": email}).status_code == 200
    return c


writer, reviewer = login("arjun@quillmark"), login("maya@quillmark")
TEXT = "Quillmark Pulse 2.0 is here. Plans start at ₹1,299/month."
sid = writer.post("/submissions", json={"title": "Edit me", "channel": "web", "source_type": "in-house",
                                         "content": TEXT}).json()["submission_id"]


def listed():
    return next(s for s in writer.get("/submissions").json()["submissions"] if s["id"] == sid)


expect(listed()["last_review"] is None, "a new draft has no verdict yet")

# a role switch answers with the same user record as /me (My work matches drafts by email)
guest = TestClient(main.app, raise_server_exceptions=False)
guest.__enter__()
joined = guest.post("/join", json={"name": "Guest", "role": "creator"}).json()
switched = guest.patch("/me", json={"role": "reviewer"}).json()
expect(switched.get("email") == joined["email"] and switched.get("role") == "reviewer",
       f"switching role keeps and returns the same email ({switched})")

r = writer.post(f"/submissions/{sid}/edit", json={"content": TEXT + " Start your free trial at quillmark.co/pulse."})
expect(r.status_code == 200, f"the writer can change the text of their draft ({r.status_code} {r.text[:120]})")
d = writer.get(f"/submissions/{sid}").json()
expect(len(d["revisions"]) == 2 and "quillmark.co/pulse" in d["revisions"][-1]["content"],
       "the edit is the next revision, checked again")
expect(writer.post(f"/submissions/{sid}/edit", json={"content": "   "}).status_code == 422, "an empty edit is refused")
expect(writer.post(f"/submissions/{sid}/edit", json={"content": d["revisions"][-1]["content"]}).status_code == 422,
       "an edit that changes nothing is refused")

assert writer.post(f"/submissions/{sid}/submit-review").status_code == 200
expect(writer.post(f"/submissions/{sid}/edit", json={"content": "Changed during review."}).status_code == 409,
       "the text cannot change while a reviewer has it")

r = reviewer.post(f"/submissions/{sid}/review", json={"action": "request_changes", "comment": "Name the plan too."})
expect(r.status_code == 200, f"the reviewer sends it back ({r.status_code})")
last = listed()["last_review"]
expect(last and last["action"] == "request_changes" and last["reason"] == "Name the plan too."
       and "Maya" in (last["by_name"] or ""), f"the writer's list shows who sent it back and why ({last})")

r = writer.post(f"/submissions/{sid}/edit", json={"content": TEXT.replace("Plans", "Pro plans")})
expect(r.status_code == 200, "the writer makes the requested change")
expect(listed()["status"] == "Changes requested", "it stays with the writer until they send it again")
assert writer.post(f"/submissions/{sid}/submit-review").status_code == 200
r = reviewer.post(f"/submissions/{sid}/review", json={"action": "approve", "reason": "Looks good."})
expect(r.status_code == 200, f"the reviewer approves ({r.status_code} {r.text[:100]})")
last = listed()["last_review"]
expect(last and last["action"] == "approve", f"the writer's list shows it was approved ({last})")
expect(writer.post(f"/submissions/{sid}/edit", json={"content": "After approval."}).status_code == 409,
       "approved text cannot be changed")

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("WRITERS SEE AND ACT ON VERDICTS")
