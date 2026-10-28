"""AI gateway: fallback chain, honest call ledger, data policy (fresh test DB).

No network and no real keys: providers are faked with an in-process HTTP
transport, so this suite runs in CI and exercises the AI path end to end.

Run:  .venv/Scripts/python engine/tests/test_gateway.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_gateway.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import gateway  # noqa: E402
import main as engine  # noqa: E402

engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


CONTENT = "Customers love our reliable dashboards. You will regret waiting another day."
requests = []          # every request body the fake providers received
gemini_mode = {"reply": "429"}


def _openai_reply(body):
    system = body["messages"][0]["content"]
    if "claim extractor" in system:
        out = {"claims": [{"claim": "Customers love our reliable dashboards"}]}
    elif "verify promotional claims" in system:
        out = {"claims": [{"claim": "Customers love our reliable dashboards", "verdict": "unsupported",
                           "fact_ids": ["F-999"], "explanation": "No approved fact backs this.", "fix": ""}]}
    else:
        out = {"tone_findings": [{"span": "You will regret waiting another day",
                                  "explanation": "Pushy; VOICE-3.2 asks for confident, never pushy.",
                                  "fix": "Start when you are ready"}]}
    return httpx.Response(200, json={"model": body["model"],
                                     "choices": [{"message": {"content": json.dumps(out)}}]})


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    requests.append((request.url.host, request.content.decode("utf-8", "replace")))
    if request.url.host == "generativelanguage.googleapis.com":
        if gemini_mode["reply"] == "429":
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json={})  # 200 with no candidates
    return _openai_reply(body)


arjun = TestClient(engine.app, raise_server_exceptions=False)
arjun.post("/login", json={"email": "arjun@quillmark"})


def ledger():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT provider, task, ok, prompt_version FROM ai_calls ORDER BY id")]
    finally:
        conn.close()


def check(title):
    r = arjun.post("/submissions", json={"title": title, "channel": "blog", "source_type": "in-house",
                                          "content": CONTENT}).json()
    return r, arjun.get(f"/submissions/{r['submission_id']}").json()


# --- 1. no provider: nothing is called, AI checks are pending ---------------------
print("== no provider")
gateway.configure(env={}, transport=httpx.MockTransport(handler))
expect(not any(p["available"] for p in gateway.provider_list()), "no provider is available without keys")
r, d = check("no keys")
expect(r["ai_pending"] is True and d["check"]["status"] == "ai_pending", "the run is marked ai_pending")
expect(requests == [] and ledger() == [], "nothing was sent and nothing logged")

# --- 2. Gemini rate-limited -> Groq answers; the ledger tells the truth ----------
print("== fallback")
gateway.configure(env={"GEMINI_API_KEY": "test", "GROQ_API_KEY": "test"}, transport=httpx.MockTransport(handler))
r, d = check("fallback")
expect(r["ai_pending"] is False and d["check"]["status"] == "done", f"AI checks ran ({d['check']['status']})")
rows = ledger()
expect(any(x["provider"] == "gemini" and x["ok"] == 0 for x in rows), "the rate-limited Gemini call is logged as failed")
ok = [x for x in rows if x["ok"] == 1]
expect(len(ok) == 3 and all(x["provider"] == "groq" for x in ok),
       f"three successful Groq calls: extract, verify, tone ({[(x['provider'], x['task']) for x in ok]})")
expect(r["ai_calls"] == 3, f"the run counts successful calls only ({r['ai_calls']})")
expect({x["prompt_version"] for x in ok if x["task"] == "tone_check"} == {"tone@1"},
       "the tone call is logged with the tone prompt version")
ai_claim = next((f for f in d["findings"] if f["checker"] == "claims" and
                 f["span_text"] == "Customers love our reliable dashboards"), None)
expect(ai_claim is not None and ai_claim["category"] == "unsupported_claim", "the implicit claim became a finding")
expect(ai_claim and [c["id"] for c in ai_claim["citations"]] == ["CLM-01"],
       "an invented fact id is dropped; the claim cites the statistic rule instead")
tone = next((f for f in d["findings"] if f["checker"] == "tone" and f["span_text"].startswith("You will regret")), None)
expect(tone is not None and tone["citations"][0]["id"] == "VOICE-3.2", "the AI tone finding cites the bound voice rule")
expect(tone and tone["provenance"]["model"], "AI findings say which model produced them")

print("== data policy")
sent = " ".join(b for _, b in requests)
conn = connect()
secret = [r["text"] for r in conn.execute("SELECT text FROM facts WHERE confidential = 1")]
conn.close()
expect(secret and not any(t in sent for t in secret), "no confidential fact text was sent to any provider")

# --- 3. a 200 with no answer is a failure, not a success -------------------------
print("== empty answer")
gemini_mode["reply"] = "empty"
before = len(ledger())
r, d = check("empty gemini")
new = ledger()[before:]
expect(any(x["provider"] == "gemini" and x["ok"] == 0 for x in new), "an empty Gemini reply is logged as failed")
expect(r["ai_pending"] is False, "and the chain still falls through to Groq")

# --- 4. local Ollama, no key ------------------------------------------------------
print("== local model")
requests.clear()
gateway.configure(env={"OLLAMA_URL": "http://ollama.test:11434"}, transport=httpx.MockTransport(handler))
expect([p["provider"] for p in gateway.provider_list() if p["available"]] == ["ollama"], "Ollama is available")
r, d = check("ollama")
expect(r["ai_pending"] is False and {h for h, _ in requests} == {"ollama.test"}, "checks ran on the local model")

gateway.configure(env={}, transport=None)
print()
if failures:
    print(f"{len(failures)} GATEWAY TEST(S) FAILED")
    raise SystemExit(1)
print("ALL GATEWAY TESTS PASSED")
