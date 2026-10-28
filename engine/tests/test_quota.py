"""Daily AI allowance: per person and per workspace (fresh test DB, faked providers).

Free API keys run out without warning, so AI-assisted checks are rationed: each
person gets a few per day (default 5) and the workspace has a daily cap (default
50). Out of tries, a check still runs every rule-based checker and says exactly
why the AI part was skipped. Failed provider attempts never use up a try.

Run:  .venv/Scripts/python engine/tests/test_quota.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_quota.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db import init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import gateway  # noqa: E402
import main as engine  # noqa: E402
import quota  # noqa: E402

engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


provider = {"mode": "ok"}


def handler(request: httpx.Request) -> httpx.Response:
    if provider["mode"] == "down":
        return httpx.Response(503, json={"error": "unavailable"})
    body = json.loads(request.content or b"{}")
    system = body["messages"][0]["content"]
    out = {"claims": []} if "claim" in system else {"tone_findings": []}
    return httpx.Response(200, json={"model": body["model"],
                                     "choices": [{"message": {"content": json.dumps(out)}}]})


def login(email):
    c = TestClient(engine.app, raise_server_exceptions=False)
    assert c.post("/login", json={"email": email}).status_code == 200
    return c


n = {"i": 0}


def check(client):
    """Submit a fresh draft; return (submit response, detail payload)."""
    n["i"] += 1
    r = client.post("/submissions", json={"title": f"q{n['i']}", "channel": "blog", "source_type": "in-house",
                                          "content": f"Quillmark Pulse helps teams read their data, note {n['i']}."}).json()
    return r, client.get(f"/submissions/{r['submission_id']}").json()


# --- defaults ----------------------------------------------------------------------
print("== defaults")
for k in ("CANONRY_AI_DAILY_PER_USER", "CANONRY_AI_DAILY_PER_WORKSPACE"):
    os.environ.pop(k, None)
expect(quota.limits() == {"per_user": 5, "per_workspace": 50}, f"5 per person, 50 per workspace ({quota.limits()})")
os.environ["CANONRY_AI_DAILY_PER_USER"] = "not-a-number"
try:
    quota.limits(); refused = False
except RuntimeError as e:
    refused = "CANONRY_AI_DAILY_PER_USER" in str(e)
expect(refused, "a malformed limit is refused with a clear message")

# small limits keep the test short: 2 per person, 3 for the workspace
os.environ["CANONRY_AI_DAILY_PER_USER"] = "2"
os.environ["CANONRY_AI_DAILY_PER_WORKSPACE"] = "3"
arjun, maya, karan = login("arjun@quillmark"), login("maya@quillmark"), login("karan@quillmark")

# --- no provider: nothing is counted --------------------------------------------------
print("== no provider")
gateway.configure(env={}, transport=httpx.MockTransport(handler))
r, d = check(arjun)
expect(d["check"]["ai_reason"] == "no_provider", f"reason no_provider ({d['check']['ai_reason']})")
expect(d["ai_allowance"]["used"] == 0, "nothing counted without a provider")

# --- per-person allowance ---------------------------------------------------------------
print("== per person")
gateway.configure(env={"GROQ_API_KEY": "test"}, transport=httpx.MockTransport(handler))
for i in (1, 2):
    r, d = check(arjun)
    expect(r["ai_pending"] is False and d["check"]["ai_reason"] is None, f"try {i}: AI checks ran")
expect(d["ai_allowance"] == {**d["ai_allowance"], "used": 2, "limit": 2}, f"2 of 2 used ({d['ai_allowance']})")
r, d = check(arjun)
expect(r["ai_pending"] is True and d["check"]["ai_reason"] == "user_quota",
       f"try 3: refused with user_quota ({d['check']['ai_reason']})")
expect(d["check"]["ai_calls"] == 0, "no AI call was made once out of tries")
expect(d["ai_allowance"]["used"] == 2, "a refused check does not count")
rr = arjun.post("/submissions", json={"title": "rules", "channel": "web", "source_type": "in-house",
                                     "content": "Trusted by 9,000+ teams."}).json()
expect(any(f["checker"] == "claims" for f in rr["findings"]), "rule-based findings still arrive when out of tries")
expect(rr.get("ai_reason") == "user_quota", "the submit response says why AI was skipped")
expect(d["ai_allowance"]["resets_at"].endswith("T00:00:00+00:00"), "the allowance resets at 00:00 UTC")

# --- failed provider attempts never cost a try ---------------------------------------
print("== provider down")
provider["mode"] = "down"
r, d = check(maya)
expect(d["check"]["ai_reason"] == "provider_unavailable", f"reason provider_unavailable ({d['check']['ai_reason']})")
expect(d["ai_allowance"]["used"] == 0, "a failed provider attempt does not use a try")
provider["mode"] = "ok"
gateway.reset_limits()  # the cooldown after the 503 has expired

# --- workspace cap (3): arjun used 2, maya's first makes 3 ---------------------------
print("== workspace cap")
r, d = check(maya)
expect(d["check"]["ai_reason"] is None and d["ai_allowance"]["workspace_used"] == 3, "maya's try uses the last workspace slot")
r, d = check(karan)
expect(d["check"]["ai_reason"] == "workspace_quota", f"admin is not exempt: workspace_quota ({d['check']['ai_reason']})")

# --- a new day resets every allowance --------------------------------------------------
print("== next day")
conn = _db.connect()
conn.execute("UPDATE check_runs SET started_at = '2000-01-01T12:00:00+00:00'")  # everything so far was "yesterday"
conn.commit()
conn.close()
r, d = check(arjun)
expect(d["check"]["ai_reason"] is None and d["ai_allowance"]["used"] == 1, "a new day starts a fresh allowance")

gateway.configure(env={}, transport=None)
for k in ("CANONRY_AI_DAILY_PER_USER", "CANONRY_AI_DAILY_PER_WORKSPACE"):
    os.environ.pop(k, None)
print()
if failures:
    print(f"{len(failures)} QUOTA TEST(S) FAILED")
    raise SystemExit(1)
print("ALL QUOTA TESTS PASSED")
