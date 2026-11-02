"""The knowledge base grows from real use: a claim that keeps coming back unsupported is suggested
on Insights; once a reviewer adds it as an approved fact, the same claim is checked against it
instead of flagged.

Run:  .venv/Scripts/python engine/tests/test_suggested_facts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_suggested_facts")

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
CLAIM = "Quillmark Pulse cuts reporting time by 37% for finance teams."


def unsupported(sid):
    d = writer.get(f"/submissions/{sid}").json()
    return [f for f in d["findings"] if f["category"] == "unsupported_claim" and "37%" in (f.get("span_text") or "")]


ids = []
for title in ("Finance launch post", "Finance newsletter"):
    r = writer.post("/submissions", json={"title": title, "channel": "web", "source_type": "in-house", "content": CLAIM})
    expect(r.status_code == 200, f"draft checked ({r.status_code})")
    ids.append(r.json()["submission_id"])
expect(all(unsupported(i) for i in ids), "a claim with no approved fact is flagged as unsupported")

ins = reviewer.get("/insights").json()
suggested = [m for m in ins.get("missing_facts", []) if "37%" in m["span_text"]]
expect(suggested and suggested[0]["occurrences"] == 2,
       f"Insights suggests it, counted once per submission ({suggested})")

r = reviewer.post("/kb/facts", json={"text": "Quillmark Pulse cuts reporting time by 37% for finance teams "
                                              "(2026 customer study, 41 finance teams).",
                                      "category": "product", "owner": "Maya", "source": "2026 customer study",
                                      "valid_from": "2026-01-01", "reason": "suggested on Insights"})
expect(r.status_code == 200, f"reviewer adds it as an approved fact ({r.status_code} {r.text[:160]})")

r = writer.post("/submissions", json={"title": "Finance follow-up", "channel": "web", "source_type": "in-house",
                                      "content": CLAIM})
sid = r.json()["submission_id"]
expect(not unsupported(sid), "the same claim in a new draft is now backed by the fact, not flagged")
d = writer.get(f"/submissions/{sid}").json()
cited = [c for f in d["findings"] for c in f.get("citations", []) if c.get("type") == "fact"]
ins = reviewer.get("/insights").json()

r = writer.post("/submissions", json={"title": "Wrong number", "channel": "web", "source_type": "in-house",
                                      "content": "Quillmark Pulse cuts reporting time by 45% for finance teams."})
d = writer.get(f"/submissions/{r.json()['submission_id']}").json()
expect(any("45%" in (f.get("span_text") or "") for f in d["findings"]),
       "a different number is still caught: the fact backs 37%, not 45%")

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("THE KNOWLEDGE BASE GROWS FROM USE")
