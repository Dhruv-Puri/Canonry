"""AI gateway: fallback chain, honest call ledger, data policy (fresh test DB).

No network and no real keys: providers are faked with an in-process HTTP
transport, so this suite runs in CI and exercises the AI path end to end.

Run:  .venv/Scripts/python engine/tests/test_gateway.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

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


def _gemini_reply(body):
    system = (((body.get("systemInstruction") or {}).get("parts") or [{}])[0].get("text") or "")
    if "claim extractor" in system:
        out = {"claims": [{"claim": "Customers love our reliable dashboards"}]}
    elif "verify promotional claims" in system:
        out = {"claims": [{"claim": "Customers love our reliable dashboards", "verdict": "unsupported",
                           "fact_ids": ["F-999"], "explanation": "No approved fact backs this.", "fix": ""}]}
    else:
        out = {"tone_findings": [{"span": "You will regret waiting another day",
                                  "explanation": "Pushy; VOICE-3.2 asks for confident, never pushy.",
                                  "fix": "Start when you are ready"}]}
    return httpx.Response(200, json={"candidates": [{
        "content": {"parts": [{"text": json.dumps(out)}]}, "finishReason": "STOP"}]})


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    requests.append((request.url.host, request.content.decode("utf-8", "replace")))
    if request.url.host == "generativelanguage.googleapis.com":
        if gemini_mode["reply"] == "429":
            return httpx.Response(429, json={"error": {"message": "quota"}})
        if gemini_mode["reply"] == "fallback":
            if "gemini-3.5-flash-lite" in request.url.path:
                return _gemini_reply(body)
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        if gemini_mode["reply"] == "deep_fallback":
            if "gemini-3-flash-preview" in request.url.path:
                return _gemini_reply(body)
            if any(m in request.url.path for m in (
                    "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest")):
                return httpx.Response(429, json={"error": {"message": "daily quota"}})
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json={})  # 200 with no candidates
    return _openai_reply(body)


arjun = TestClient(engine.app, raise_server_exceptions=False)
arjun.post("/login", json={"email": "arjun@quillmark"})


def ledger():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT provider, task, ok, prompt_version, model FROM ai_calls ORDER BY id")]
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
gateway.reset_limits()
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

# --- a busy Gemini model falls through to another Gemini model -------------------
print("== gemini model fallback")
gateway.reset_limits()
gemini_mode["reply"] = "fallback"
requests.clear()
gateway.configure(env={"GEMINI_API_KEY": "test", "GROQ_API_KEY": "test"}, transport=httpx.MockTransport(handler))
before = len(ledger())
r, d = check("gemini 3.5 fallback")
new = ledger()[before:]
ok = [x for x in new if x["ok"] == 1]
expect(r["ai_pending"] is False and d["check"]["status"] == "done",
       f"the 3.5 fallback completed the check ({d['check']['status']})")
expect(len(ok) == 3 and all(x["provider"] == "gemini" for x in ok),
       f"three Gemini fallback calls succeeded ({[(x['provider'], x['task']) for x in ok]})")
expect(all(x["model"] == "gemini-3.5-flash-lite" for x in ok),
       f"the fallback model is logged ({[x['model'] for x in ok]})")
claim = next((f for f in d["findings"] if f["checker"] == "claims" and
              f["span_text"] == "Customers love our reliable dashboards"), None)
expect(claim is not None and claim["provenance"]["model"] == "gemini-3.5-flash-lite",
       "the finding names the fallback model")

# --- several models exhausted or busy: keep trying the remaining free quotas ---
print("== gemini deeper fallback")
gateway.reset_limits()
gemini_mode["reply"] = "deep_fallback"
requests.clear()
before = len(ledger())
r, d = check("gemini deeper fallback")
new = ledger()[before:]
ok = [x for x in new if x["ok"] == 1]
expect(r["ai_pending"] is False and d["check"]["status"] == "done",
       f"the check completed after three models were unavailable ({d['check']['status']})")
expect(len(ok) == 3 and all(x["model"] == "gemini-3-flash-preview" for x in ok),
       f"the next free model answered every call ({[x['model'] for x in ok]})")
expect({"gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"}
       <= {x["model"] for x in new if x["ok"] == 0},
       "the exhausted models are logged and skipped")
expect(gateway.Gemini().models() == [
    "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest",
    "gemini-3-flash-preview", "gemini-3.8-flash", "gemini-3.6-flash",
], f"the full free-tier chain is configured ({gateway.Gemini().models()})")

# --- 3. a 200 with no answer is a failure, not a success -------------------------
print("== empty answer")
gateway.reset_limits()
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

# --- which .env file is read: CANONRY_ENV_FILE ("" = none; the suites run that way) ---
import time  # noqa: E402

print("== resolving a finding re-checks without the AI")
gateway.reset_limits()
gateway.configure(env={"GROQ_API_KEY": "test"}, transport=httpx.MockTransport(handler))
arjun = TestClient(engine.app, raise_server_exceptions=False)
arjun.post("/login", json={"email": "maya@quillmark"})  # a fresh daily AI allowance
requests.clear()
r, d = check("resolve")
sid = r["submission_id"]
expect(r["ai_pending"] is False and requests, f"setup: the submit ran the AI checks ({r.get('ai_reason')})")
tone = next(f for f in d["findings"] if f["checker"] == "tone")
claim = next(f for f in d["findings"] if f["checker"] == "claims" and f["provenance"]["model"])
requests.clear()
started = time.monotonic()
res = arjun.post(f"/submissions/{sid}/resolve", json={
    "revision_id": d["latest_revision"]["id"], "finding_id": tone["id"], "action": "accept"})
took = time.monotonic() - started
after = arjun.get(f"/submissions/{sid}").json()
expect(res.status_code == 200 and requests == [], f"accepting a fix sends no AI request ({len(requests)})")
expect(took < 3.0, f"and answers at once ({took:.1f}s)")
expect("Start when you are ready" in after["latest_revision"]["content"], "the suggested fix is in the new revision")
kept = [f for f in after["findings"] if f["checker"] == "claims" and f["span_text"] == claim["span_text"]]
expect(len(kept) == 1 and kept[0]["provenance"]["model"] == claim["provenance"]["model"],
       "the AI claim finding carries over to the new revision")
expect(not any(f["checker"] == "tone" and f["status"] == "open" for f in after["findings"]),
       "the fixed tone finding does not come back")
expect(after["check"]["ai_reason"] is None and after["check"]["ai_calls"] == 0,
       "the carried run reads as AI-checked, with no new calls")
disp = arjun.post(f"/submissions/{sid}/resolve", json={
    "revision_id": after["latest_revision"]["id"], "finding_id": kept[0]["id"], "action": "dispute",
    "reason": "AI misread"})
final = arjun.get(f"/submissions/{sid}").json()
expect(disp.status_code == 200 and requests == [], "a dispute sends no AI request either")
expect(any(f["span_text"] == claim["span_text"] and f["status"] == "disputed" for f in final["findings"]),
       "the disputed AI finding stays decided")

print("== env file")
import tempfile  # noqa: E402
env_file = os.path.join(tempfile.mkdtemp(), "keys.env")
with open(env_file, "w", encoding="utf-8") as fh:
    fh.write("GROQ_API_KEY=from-file\n")
os.environ["CANONRY_ENV_FILE"] = env_file
gateway.configure(env=None, transport=None)
expect([p["provider"] for p in gateway.provider_list() if p["available"]] == ["groq"],
       "keys are read from the file CANONRY_ENV_FILE names")
os.environ["CANONRY_ENV_FILE"] = ""
gateway.configure(env=None, transport=None)
expect(not any(p["available"] for p in gateway.provider_list()), "CANONRY_ENV_FILE='' reads no .env at all")

gateway.configure(env={}, transport=None)
print()
if failures:
    print(f"{len(failures)} GATEWAY TEST(S) FAILED")
    raise SystemExit(1)
print("ALL GATEWAY TESTS PASSED")
