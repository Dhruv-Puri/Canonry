"""A long draft is checked in seconds, not minutes.

Live, 2 Nov 2026: a 51,000-character draft (one sentence repeated 1,000 times) took over two
minutes on the free server, past Vercel's 120 s proxy limit, so the visitor saw an error. Several
steps re-scanned the whole text for every claim or compared every finding with every other.
Before the fix it took 11 s in this test; after, about 1 s. The 5 s limit leaves room for slower machines.

Run:  .venv/Scripts/python engine/tests/test_long_draft.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_long_draft")

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


client = TestClient(main.app)
client.__enter__()
client.post("/login", json={"email": "arjun@quillmark"})
text = "Quillmark Pulse is India's #1 analytics platform. " * 1000
started = time.perf_counter()
r = client.post("/submissions", json={"title": "long", "channel": "social", "source_type": "in-house", "content": text})
took = time.perf_counter() - started
expect(r.status_code == 200, f"a {len(text):,}-character draft is checked ({r.status_code})")
expect(took < 5, f"in seconds, not minutes ({took:.1f}s; 11s here before the fix, over 120s live)")
findings = r.json().get("findings", [])
expect(any("#1" in (f.get("span") or {}).get("text", "") for f in findings), "and the claim is still flagged")
client.__exit__(None, None, None)

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("LONG DRAFTS ARE FAST")
