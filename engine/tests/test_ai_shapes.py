"""Malformed AI answers never break a check (live bug, 1 Nov 2026).

Free models change the shape of their JSON from one call to the next: a list of
strings instead of objects, null instead of a list, a number where text was
asked for. The engine used to trust the shape, raise, and answer the whole
submission with "Internal Server Error". Every case below must give a normal
check: the rule findings, and the AI part either used or marked as skipped.

Run:  .venv/Scripts/python engine/tests/test_ai_shapes.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

os.environ["CANONRY_AI_DAILY_PER_USER"] = "1000"
os.environ["CANONRY_AI_DAILY_PER_WORKSPACE"] = "1000"

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_ai_shapes.db")
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

engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


CONTENT = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams. "
           "Customers love our reliable dashboards. You will regret waiting another day!")
CLAIM = "Customers love our reliable dashboards"
GOOD = {
    "extract": {"claims": [{"claim": CLAIM}]},
    "verify": {"claims": [{"claim": CLAIM, "verdict": "unsupported", "fact_ids": [], "explanation": "No fact.",
                           "fix": ""}]},
    "tone": {"tone_findings": [{"span": "You will regret waiting another day", "explanation": "Pushy.",
                                "fix": "Start when you are ready"}]},
}
reply = {}


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    system = body["messages"][0]["content"]
    task = "extract" if "claim extractor" in system else "verify" if "verify promotional claims" in system else "tone"
    out = reply.get(task, GOOD[task])
    text = out if isinstance(out, str) else json.dumps(out)
    return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": text}}]})


gateway.configure(env={"GROQ_API_KEY": "test"}, transport=httpx.MockTransport(handler))
client = TestClient(engine.app, raise_server_exceptions=False)
client.post("/login", json={"email": "arjun@quillmark"})

CASES = [
    ("extractor returns a list of strings", {"extract": {"claims": [CLAIM]}}),
    ("extractor returns a top-level list", {"extract": [{"claim": CLAIM}]}),
    ("extractor returns claims: null", {"extract": {"claims": None}}),
    ("extractor returns a number as the claim", {"extract": {"claims": [{"claim": 5}]}}),
    ("verifier returns a list of strings", {"verify": {"claims": [CLAIM]}}),
    ("verifier returns a top-level list", {"verify": [{"claim": CLAIM, "verdict": "unsupported"}]}),
    ("verifier returns a number as the claim", {"verify": {"claims": [{"claim": 42, "verdict": "unsupported"}]}}),
    ("verifier returns objects as fact ids", {"verify": {"claims": [{"claim": CLAIM, "verdict": "contradicted",
                                                                       "fact_ids": [{"id": "F-012"}]}]}}),
    ("verifier returns fact_ids as one string", {"verify": {"claims": [{"claim": CLAIM, "verdict": "unsupported",
                                                                         "fact_ids": "F-012"}]}}),
    ("verifier returns an unknown verdict word", {"verify": {"claims": [{"claim": CLAIM, "verdict": "Maybe?!"}]}}),
    ("verifier returns a non-text explanation and fix", {"verify": {"claims": [{
        "claim": CLAIM, "verdict": "unsupported", "explanation": {"why": "x"}, "fix": ["a", "b"]}]}}),
    ("tone returns a top-level list", {"tone": [{"span": "You will regret waiting another day"}]}),
    ("tone returns tone_findings: null", {"tone": {"tone_findings": None}}),
    ("tone returns a list of strings", {"tone": {"tone_findings": ["pushy"]}}),
    ("tone returns a number as the span", {"tone": {"tone_findings": [{"span": 123}]}}),
    ("tone returns a non-text fix and explanation", {"tone": {"tone_findings": [{
        "span": "You will regret waiting another day", "explanation": ["pushy"], "fix": {"text": "x"}}]}}),
    ("every task answers plain prose", {"extract": "Sure! Here are the claims.", "verify": "I think so.",
                                        "tone": "Looks fine."}),
    ("every task answers an empty object", {"extract": {}, "verify": {}, "tone": {}}),
]

for name, case in CASES:
    reply.clear()
    reply.update(case)
    r = client.post("/submissions", json={"title": name, "channel": "social", "source_type": "ai-assisted",
                                          "content": CONTENT})
    ok = r.status_code == 200
    detail = ""
    if ok:
        d = client.get(f"/submissions/{r.json()['submission_id']}").json()
        rule_findings = [f for f in d["findings"] if f["checker"] == "terminology"]
        ok = bool(rule_findings)
        detail = f"{len(d['findings'])} findings, ai_reason={d['check']['ai_reason']}"
    expect(ok, f"{name}: {r.status_code} {detail or r.text[:80]}")

reply.clear()
r = client.post("/submissions", json={"title": "good", "channel": "social", "source_type": "ai-assisted",
                                      "content": CONTENT})
d = client.get(f"/submissions/{r.json()['submission_id']}").json()
expect(any(f["checker"] == "tone" for f in d["findings"]) and
       any(f["checker"] == "claims" and f["span_text"] == CLAIM for f in d["findings"]),
       "well-formed answers still produce AI findings")

import claims  # noqa: E402

real = claims.ai_verify_claims


def broken(*args, **kwargs):
    raise ValueError("an answer shape nobody anticipated")


claims.ai_verify_claims = broken
r = client.post("/submissions", json={"title": "safety net", "channel": "social", "source_type": "ai-assisted",
                                      "content": CONTENT})
d = client.get(f"/submissions/{r.json()['submission_id']}").json() if r.status_code == 200 else {}
expect(r.status_code == 200 and any(f["checker"] == "terminology" for f in d.get("findings", [])),
       f"an unexpected error in the AI part still returns the rule findings ({r.status_code})")
expect(d.get("check", {}).get("ai_reason") == "provider_unavailable",
       "and says the AI part was skipped, so Re-check can retry it")
claims.ai_verify_claims = real

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("all AI-shape checks passed")
