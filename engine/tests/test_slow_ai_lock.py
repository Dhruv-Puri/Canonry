"""A slow AI check must not lock everyone else out of the database.

SQLite has one write lock for the whole file. A check used to hold it from the
moment its revision was saved until the AI answered (up to a minute live), so
any other person's write (a sign-in, a fix, an approval) waited 5 s and failed
with "database is locked".

Run:  .venv/Scripts/python engine/tests/test_slow_ai_lock.py
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

os.environ["CANONRY_AI_DAILY_PER_USER"] = "1000"
os.environ["CANONRY_AI_DAILY_PER_WORKSPACE"] = "1000"

import db as _db  # noqa: E402

_db.use_test_database("canonry_slow_ai_lock")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import gateway  # noqa: E402
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


SLOW = 7.0


def slow_handler(request: httpx.Request) -> httpx.Response:
    time.sleep(SLOW)  # a free model taking its time
    body = json.loads(request.content or b"{}")
    return httpx.Response(200, json={"model": body.get("model", "m"), "choices": [
        {"message": {"content": json.dumps({"claims": [], "tone_findings": []})}}]})


gateway.configure(env={"GROQ_API_KEY": "test"}, transport=httpx.MockTransport(slow_handler))

a = TestClient(main.app, raise_server_exceptions=False)
a.__enter__()
a.post("/login", json={"email": "arjun@quillmark"})
b = TestClient(main.app, raise_server_exceptions=False)

result = {}


def slow_check():
    result["a"] = a.post("/submissions", json={"title": "slow", "channel": "social", "source_type": "ai-assisted",
                                               "content": "Customers love our reliable dashboards."})


t = threading.Thread(target=slow_check)
t.start()
time.sleep(1.5)  # the slow check is now waiting on the AI
started = time.perf_counter()
r = b.post("/join", json={"name": "Guest", "role": "creator"})
took = time.perf_counter() - started
expect(r.status_code == 200, f"another person can sign in while a check waits on the AI ({r.status_code} {r.text[:80]})")
expect(took < 3.0, f"without waiting for that check ({took:.1f}s)")
time.sleep(SLOW)  # now ~SLOW+1.5 s in: the first AI call is logged, the second is under way
started = time.perf_counter()
c = TestClient(main.app, raise_server_exceptions=False)  # a third visitor; a sign-in never calls the AI
r = c.post("/join", json={"name": "Guest", "role": "reviewer"})
took = time.perf_counter() - started
expect(r.status_code == 200 and took < 3.0,
       f"a write during the check's later AI calls does not wait either ({r.status_code}, {took:.1f}s)")
r = b.post("/submissions", json={"title": "rules only", "channel": "social", "source_type": "in-house",
                                 "content": "Meet Quillmark Insights 2.0."})
expect(r.status_code == 200, f"and submit their own draft ({r.status_code} {r.text[:80]})")
t.join(timeout=120)
expect(result.get("a") is not None and result["a"].status_code == 200,
       f"the slow check still finishes ({result.get('a') and result['a'].status_code})")

gateway.configure(env={}, transport=None)
a.__exit__(None, None, None)
print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("SLOW AI DOES NOT LOCK OTHERS OUT")
