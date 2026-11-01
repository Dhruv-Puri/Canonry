"""Two tabs, double clicks and odd input on the core journey (fresh test DB).

A judge can open the same draft in two tabs, double-click Accept or Approve,
or paste a very long title. None of that may lose a fix, fork the history or
sign twice.

Run:  .venv/Scripts/python engine/tests/test_reliability.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_reliability.db")
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
LAUNCH = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully "
          "ISO 27001 certified. Plans start at just ₹999/month!")


def new(content=LAUNCH, title="rel", source="in-house"):
    r = arjun.post("/submissions", json={"title": title, "channel": "social", "source_type": source,
                                        "content": content})
    assert r.status_code == 200, r.text
    return r.json()["submission_id"]


def detail(sid, who=None):
    return (who or arjun).get(f"/submissions/{sid}").json()


def fixable(d):
    return [f for f in d["findings"] if f["status"] == "open" and (f.get("suggestion") or {}).get("replace")]


def resolve(sid, rev_id, fid, action="accept", **kw):
    return arjun.post(f"/submissions/{sid}/resolve", json={"revision_id": rev_id, "finding_id": fid,
                                                           "action": action, **kw})


def together(fn, n=2):
    """Run fn n times at once (a double click, or two tabs pressing together)."""
    out, start = [None] * n, threading.Barrier(n)

    def run(i):
        start.wait()
        out[i] = fn()
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


# --- a second tab acting on an old revision must not throw away newer fixes -------------
print("== stale tab")
sid = new()
d = detail(sid)
rev1, fs = d["latest_revision"]["id"], fixable(d)
expect(len(fs) >= 2, f"the launch post has at least two one-click fixes ({len(fs)})")
r = resolve(sid, rev1, fs[0]["id"])
expect(r.status_code == 200, "tab A accepts the first fix")
after_a = detail(sid)["latest_revision"]["content"]
r = resolve(sid, rev1, fs[1]["id"])  # tab B still shows revision 1
expect(r.status_code == 409, f"tab B, still on the old revision, is told to reload ({r.status_code})")
expect("reload" in r.json().get("detail", "").lower(), f"the message says to reload ({r.json().get('detail')})")
expect(detail(sid)["latest_revision"]["content"] == after_a, "tab A's fix is still in the latest revision")
r = resolve(sid, rev1, fs[1]["id"], action="dispute", reason="old tab")
expect(r.status_code == 409, f"a dispute from the old revision is refused too ({r.status_code})")

# --- double click on Accept: one new revision, not two -----------------------------------
print("== double accept")
sid = new()
d = detail(sid)
rev1, f = d["latest_revision"]["id"], fixable(d)[0]
codes = sorted(r.status_code for r in together(lambda: resolve(sid, rev1, f["id"])))
expect(codes == [200, 409], f"one accept wins, the other is refused ({codes})")
expect(len(detail(sid)["revisions"]) == 2, f"exactly one new revision ({len(detail(sid)['revisions'])})")

# --- double click on Submit and on Approve: one seal -------------------------------------
print("== double submit and approve")
sid = new("Quillmark Pulse helps teams read their data. Start a free trial at quillmark.co/pulse.")
codes = sorted(r.status_code for r in together(lambda: arjun.post(f"/submissions/{sid}/submit-review")))
expect(codes == [200, 409], f"one submit wins ({codes})")
codes = sorted(r.status_code for r in together(
    lambda: maya.post(f"/submissions/{sid}/review", json={"action": "approve", "reason": "ok"})))
expect(codes == [200, 409], f"one approval wins ({codes})")
d = detail(sid, maya)
approvals = [a for a in d["approvals"] if a["action"] == "approve"]
expect(len(approvals) == 1, f"one approval in the trail ({len(approvals)})")
conn = _db.connect()
pocs = conn.execute("SELECT COUNT(*) c FROM proof_of_compliance WHERE submission_id=?", (sid,)).fetchone()["c"]
conn.close()
expect(pocs == 1, f"one Proof of Compliance ({pocs})")

# --- request changes and approve pressed together in two reviewer tabs --------------------
print("== approve vs request changes")
sid = new("Quillmark Pulse helps teams read their data. Start a free trial at quillmark.co/pulse.")
arjun.post(f"/submissions/{sid}/submit-review")
rs = together(lambda: maya.post(f"/submissions/{sid}/review", json={"action": "approve"}))
rs += [maya.post(f"/submissions/{sid}/review", json={"action": "request_changes", "comment": "late tab"})]
expect(rs[-1].status_code == 409, f"a decision after signing is refused ({rs[-1].status_code})")
expect(detail(sid, maya)["submission"]["status"] == "Signed", "the item stays signed")

# --- odd input -----------------------------------------------------------------------------
print("== odd input")
sid = new(title="T" * 5000)
title = detail(sid)["submission"]["title"]
expect(len(title) <= 240, f"a 5,000-character title is cut to 240 ({len(title)})")
sid = new(title="  Spaced   title  ")
expect(detail(sid)["submission"]["title"] == "Spaced title", "titles are tidied like file uploads")
r = arjun.post("/submissions", json={"title": "x", "channel": "social", "source_type": "s" * 500, "content": "Hi"})
expect(r.status_code == 200 and len(detail(r.json()["submission_id"])["submission"]["source_type"]) <= 40,
       "an over-long source is cut, as for uploads")
for label, text in [("emoji", "🚀 Quillmark Pulse 2.0 is #1 💯"), ("Hindi", "क्विलमार्क पल्स ₹999/माह"),
                    ("RTL", "منصة Quillmark Pulse الأفضل"), ("HTML", "<script>alert(1)</script> Quillmark Pulse")]:
    r = arjun.post("/submissions", json={"title": label, "channel": "social", "source_type": "in-house",
                                        "content": text})
    expect(r.status_code == 200, f"{label} text is checked ({r.status_code})")
    if r.status_code == 200:
        got = detail(r.json()["submission_id"])["latest_revision"]["content"]
        expect(got == text, f"{label} text is stored exactly as written")
r = arjun.post("/submissions", json={"title": "big", "channel": "blog", "source_type": "in-house",
                                    "content": "Quillmark Pulse helps teams. " * 2000})
expect(r.status_code == 200, f"a 58,000-character draft is checked ({r.status_code})")
r = arjun.post("/submissions", json={"title": "huge", "channel": "blog", "source_type": "in-house",
                                    "content": "x" * 300_000})
expect(r.status_code == 422 and "long" in r.json()["detail"].lower(),
       f"a 300,000-character draft is refused in plain words ({r.status_code} {r.text[:80]})")

print()
if failures:
    print(f"{len(failures)} RELIABILITY TEST(S) FAILED")
    raise SystemExit(1)
print("ALL RELIABILITY TESTS PASSED")
