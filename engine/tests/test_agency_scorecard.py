"""The agency scorecard: how an agency's own work fares against the client's rules.

First-time right (approved without being sent back), drafts sent back, issues on the first check,
and the client rules its drafts trip most. Only agency partners have one, and it counts only their
own work, never another team's.

Run:  .venv/Scripts/python engine/tests/test_agency_scorecard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_agency_scorecard")

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


agency, reviewer, writer = login("riya@agency"), login("maya@quillmark"), login("arjun@quillmark")

card = agency.get("/agency/scorecard")
expect(card.status_code == 200 and card.json()["submissions"] == 0, f"a new agency starts with an empty scorecard ({card.text[:120]})")
expect(writer.get("/agency/scorecard").status_code == 403, "a creator has no agency scorecard")
expect(reviewer.get("/agency/scorecard").status_code == 403, "a reviewer has no agency scorecard")


def submit(client, title, content):
    sid = client.post("/submissions", json={"title": title, "channel": "social", "source_type": "agency",
                                            "content": content}).json()["submission_id"]
    assert client.post(f"/submissions/{sid}/submit-review").status_code == 200
    return sid


# one draft approved straight away; one sent back first, then approved
clean = submit(agency, "Clean post", "Quillmark Pulse helps teams read their data. Start your free trial at quillmark.co/pulse.")
r = reviewer.post(f"/submissions/{clean}/review", json={"action": "approve"})
expect(r.status_code == 200, f"the clean post is approved ({r.status_code} {r.text[:120]})")

risky = submit(agency, "Launch post", "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams.")
r = reviewer.post(f"/submissions/{risky}/review", json={"action": "request_changes", "reason": "Use the approved figures."})
expect(r.status_code == 200, "the launch post is sent back")
r = agency.post(f"/submissions/{risky}/edit", json={"content": "Meet Quillmark Pulse 2.0, trusted by 2,300+ teams. Start your free trial at quillmark.co/pulse."})
expect(r.status_code == 200, f"the agency fixes it ({r.status_code})")
agency.post(f"/submissions/{risky}/submit-review")
r = reviewer.post(f"/submissions/{risky}/review", json={"action": "approve", "reason": "Fixed."})
expect(r.status_code == 200, f"and it is approved on the second try ({r.status_code} {r.text[:120]})")

# another team's draft must not count
submit(writer, "In-house post", "Meet Quillmark Insights 2.0 — India's #1 analytics platform.")

s = agency.get("/agency/scorecard").json()
expect(s["submissions"] == 2, f"only the agency's own two drafts count ({s['submissions']})")
expect(s["approved"] == 2 and s["first_time_right"] == 1 and s["sent_back"] == 1,
       f"one of two approved first time, one sent back ({s})")
expect(s["avg_first_check_issues"] is not None and s["avg_first_check_issues"] > 0,
       f"issues on the first check are averaged ({s['avg_first_check_issues']})")
expect(s["top_rules"] and all(r["statement"] for r in s["top_rules"]),
       f"the client rules tripped most come with their wording ({s['top_rules'][:2]})")

if failures:
    print(f"{len(failures)} AGENCY SCORECARD CHECK(S) FAILED")
    sys.exit(1)
print("ALL AGENCY SCORECARD CHECKS PASSED")
