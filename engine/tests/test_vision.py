"""Image understanding: one vision call per checked image, findings that cite rules.

A fake Gemini answers through httpx.MockTransport; no real AI is reached. The
OCR is mocked, so the suite needs no Tesseract. Every vision finding cites a
workspace rule (or an India-pack clause), is never above "likely", and the
check is exactly the old one when the vision call fails or is skipped.

Run:  .venv/Scripts/python engine/tests/test_vision.py
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

os.environ["CANONRY_AI_DAILY_PER_USER"] = "1000"
os.environ["CANONRY_AI_DAILY_PER_WORKSPACE"] = "1000"

import db as _db  # noqa: E402

_db.use_test_database("canonry_vision")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import compliance  # noqa: E402
import gateway  # noqa: E402
import main  # noqa: E402
import ocr  # noqa: E402
from db import connect  # noqa: E402
from seed import seed  # noqa: E402

main.DEMO_MODE = True
main.COOKIE_SECURE = False
seed()

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def png() -> bytes:
    img = Image.new("RGB", (640, 360), "#0E7C7B")
    ImageDraw.Draw(img).rectangle((60, 60, 580, 300), fill="#F4EDE5")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def words(*lines):
    out = []
    for n, line in enumerate(lines):
        for i, t in enumerate(line.split()):
            out.append({"text": t, "key": (n + 1, 1, 1), "box": (70 + i * 150, 80 + n * 80, 140, 50)})
    return lambda img, timeout=40.0: [dict(w) for w in out]


ocr.words = words()  # nothing readable unless a case says so

VISION = {
    "description": "A teal launch banner with a dashboard screenshot.",
    "alt_text": "Quillmark Pulse dashboard on a teal launch banner.",
    "brands": [], "products": [], "people": {"present": False, "endorsement": False},
    "claims": [], "fits_text": {"fits": True, "why": ""},
}
state = {"vision": VISION, "vision_calls": 0, "seen_images": 0, "facts_sent": False}


def answer(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    parts = [p for c in body.get("contents", []) for p in c.get("parts", [])]
    if any("inline_data" in p for p in parts):
        state["vision_calls"] += 1
        state["seen_images"] += sum(1 for p in parts if "inline_data" in p)
        sent = " ".join(p.get("text", "") for p in parts)
        if "F-0" in sent or "X-10" in sent:
            state["facts_sent"] = True
        v = state["vision"]
        if v == "timeout":
            raise httpx.ReadTimeout("stalled", request=request)
        return answer(v if isinstance(v, str) else json.dumps(v))
    return answer('{"claims": [], "tone_findings": []}')


AI_ENV = {"GEMINI_API_KEY": "test", "CANONRY_GEMINI_FALLBACK_MODELS": "off", "CANONRY_GEMINI_RPM": "0",
          "CANONRY_GEMINI_COOLDOWN_SECONDS": "0"}


def ai_on():
    gateway.configure(env=AI_ENV, transport=httpx.MockTransport(handler))
    gateway.reset_limits()


def ai_off():
    gateway.configure(env={}, transport=None)


client = TestClient(main.app)
client.__enter__()
expect(client.post("/login", json={"email": "arjun@quillmark"}).status_code == 200, "creator signs in")


def upload(alt="Pulse launch banner", title="Pulse launch"):
    r = client.post(f"/submissions/upload?title={title}&channel=social&source_type=in-house&filename=banner.png"
                    f"&alt_text={alt}", content=png(), headers={"content-type": "application/octet-stream"})
    expect(r.status_code == 200, f"image upload is checked ({r.status_code} {r.text[:120]})")
    return client.get(f"/submissions/{r.json()['submission_id']}").json()


def shape(d):
    return sorted((f["checker"], f["category"], f["tier"], f["explanation"]) for f in d["findings"])


def seen_by_vision(d):
    return [f for f in d["findings"] if (f.get("locator") or {}).get("region") == "what the image shows"]


def uncited(d):
    return [f for f in d["findings"] if not f["citations"]]


# ---- baseline: the old image findings ---------------------------------------
ai_off()
base = upload()
expect(base["check"].get("vision") is None, "no provider: nothing is said about what the image shows")
expect(base["check"]["ai_reason"] == "no_provider", "and the AI part is recorded as skipped")
BASE_SHAPE = shape(base)

# ---- a plain answer is stored and shown ---------------------------------------
ai_on()
d = upload()
v = d["check"].get("vision") or {}
expect(v.get("description") == VISION["description"], f"the reading is stored with the check ({v})")
expect(state["seen_images"] >= 1, "the image travels to Gemini as an inline part")
expect(not state["facts_sent"], "no knowledge-base fact is sent with the image")
expect(shape(d) == BASE_SHAPE, "an image that shows nothing wrong adds no finding")

# ---- competitor brand ----------------------------------------------------------
state["vision"] = dict(VISION, brands=[{"name": "Tableau", "kind": "competitor", "logo": True}])
d = upload()
comp = [f for f in seen_by_vision(d) if f["category"] == "comparative_advertising"]
expect(len(comp) == 1 and any(c["type"] == "pack" and c.get("id") == "asci_4_comparative"
                              for c in comp[0]["citations"]),
       f"a competitor's brand cites the comparative-advertising clause ({[f['citations'] for f in comp]})")
expect(comp and comp[0]["tier"] in ("likely", "consider") and "Tableau" in comp[0]["explanation"],
       "at most Should fix, naming what was seen")
expect(not uncited(d), "every finding cites something")
conn = connect()
compliance.set_pack_active(conn, "ws_quillmark", "in_advertising", False, "test")
conn.commit()
conn.close()
d = upload()
comp = seen_by_vision(d)
expect(not any(f["category"] == "comparative_advertising" for f in comp), "pack off: no clause is cited")
expect(all(f["citations"] and all(c["type"] == "rule" for c in f["citations"]) for f in comp)
       and any(c["id"] == "BASE-09" for f in comp for c in f["citations"]),
       f"pack off: the brand logo rule is cited instead ({[f['citations'] for f in comp]})")
expect(not uncited(d), "still no finding without a citation")
conn = connect()
compliance.set_pack_active(conn, "ws_quillmark", "in_advertising", True, "test")
conn.commit()
conn.close()

# ---- retired product name seen only by vision --------------------------------------
state["vision"] = dict(VISION, products=["Quillmark Insights"])
d = upload()
old = [f for f in seen_by_vision(d) if f["checker"] == "terminology"]
expect(len(old) == 1 and old[0]["tier"] == "likely", f"the retired name is flagged at Should fix ({old})")
expect(old and any(c["id"] == "TERM-04" for c in old[0]["citations"]), "citing the naming rule")

# ---- the same retired name found by OCR and by vision: one card -------------------------
ocr.words = words("Quillmark Insights 2.0")
d = upload()
cards = [f for f in d["findings"] if f["checker"] == "terminology"
         and ("Quillmark Insights" in (f["span_text"] or "") or "Quillmark Insights" in f["explanation"])]
expect(len(cards) == 1, f"one card when OCR and vision both see it ({[(f['span_text'], f['tier']) for f in cards]})")
expect(cards and len((cards[0]["provenance"] or {}).get("found_by") or []) == 2, "found by both checks")
ocr.words = words()

# ---- a claim in the imagery ------------------------------------------------------------
state["vision"] = dict(VISION, claims=["India's #1 analytics platform"])
d = upload()
claim = [f for f in seen_by_vision(d) if f["category"].endswith("_claim")]
expect(claim and any(c["id"] == "CLM-02" for f in claim for c in f["citations"]),
       f"a superlative shown as imagery is checked like text ({[(f['category'], f['citations']) for f in claim]})")
expect(claim and all(f["tier"] != "definite" for f in claim), "never Definite")
expect(len(claim) == 1, f"the claim and the India-pack reading are one card ({len(claim)})")

# ---- picture contradicts its caption ------------------------------------------------------
state["vision"] = dict(VISION, fits_text={"fits": False, "why": "The caption says a dashboard; the picture shows a beach."})
d = upload()
mis = [f for f in seen_by_vision(d) if f["category"] == "image_text_mismatch"]
expect(len(mis) == 1 and mis[0]["tier"] == "consider" and "beach" in mis[0]["explanation"],
       f"a picture that contradicts its caption is Worth a look, with the reason ({mis})")
expect(mis and mis[0]["citations"], "and cites a rule")

# ---- alt text: the suggested description is the one-click fix ------------------------------
state["vision"] = VISION
d = upload(alt="")
miss = next((f for f in d["findings"] if f["category"] == "missing_alt_text"), None)
expect(miss and (miss["suggestion"] or {}).get("replace") == VISION["alt_text"]
       and miss["suggestion"].get("operation") == "replace",
       f"missing alt text offers the description Canonry sees ({miss and miss['suggestion']})")
r = client.post(f"/submissions/{d['submission']['id']}/resolve",
                json={"finding_id": miss["id"], "revision_id": d["latest_revision"]["id"], "action": "accept"})
expect(r.status_code == 200, f"accepting it works ({r.status_code} {r.text[:120]})")
d = client.get(f"/submissions/{d['submission']['id']}").json()
expect(d["asset"]["alt_text"] == VISION["alt_text"], "the image now has that alt text")
expect(not any(f["category"] == "missing_alt_text" for f in d["findings"]), "and the finding is gone")

# ---- malformed answers never break a check ----------------------------------------------
for label, bad in [
    ("a list of strings", '["Tableau", "India\'s #1"]'), ("null", "null"), ("a number", "42"),
    ("prose", "I see a teal banner with a dashboard."),
    ("fields of the wrong type", {"description": 7, "brands": "Tableau", "claims": [None, 3, {"x": 1}],
                                  "products": None, "fits_text": "no", "alt_text": ["x"], "people": "yes"}),
    ("items of the wrong type", {"brands": [None, 3, "Tableau", {"name": None}], "claims": "India's #1"}),
]:
    state["vision"] = bad
    r = client.post("/submissions/upload?title=Pulse&channel=social&source_type=in-house&filename=b.png"
                    "&alt_text=Pulse launch banner", content=png(), headers={"content-type": "application/octet-stream"})
    ok = r.status_code == 200
    d = client.get(f"/submissions/{r.json()['submission_id']}").json() if ok else {}
    expect(ok and not uncited(d) and all(f["tier"] != "definite" for f in seen_by_vision(d)),
           f"vision answer as {label}: a normal check ({r.status_code})")

# ---- timeout or skipped: exactly the old findings ---------------------------------------
state["vision"] = "timeout"
d = upload()
expect(shape(d) == BASE_SHAPE, "a vision call that times out leaves exactly the old image findings")
expect(d["check"].get("vision") is None and d["check"]["ai_reason"] == "provider_unavailable",
       f"and the skipped AI part is recorded ({d['check']['ai_reason']})")

# ---- quota: a vision call counts like any AI call ------------------------------------------
state["vision"] = VISION
used = client.get(f"/submissions/{base['submission']['id']}").json()["ai_allowance"]["used"]
calls = state["vision_calls"]
d = upload()
expect(d["ai_allowance"]["used"] == used + 1 and d["check"]["ai_calls"] >= 1, "a check with a vision call uses one try")
conn = connect()
logged = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE task = 'image_vision' AND ok = 1").fetchone()[0]
conn.close()
expect(logged >= 1, "the vision call is in the AI call ledger")
os.environ["CANONRY_AI_DAILY_PER_USER"] = str(used + 1)
calls = state["vision_calls"]
d = upload()
expect(state["vision_calls"] == calls, "out of tries: no vision call is made")
expect(d["check"]["ai_reason"] == "user_quota" and shape(d) == BASE_SHAPE,
       "and the check is exactly the old one, with the reason recorded")
os.environ["CANONRY_AI_DAILY_PER_USER"] = "1000"

ai_off()
client.__exit__(None, None, None)
print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
