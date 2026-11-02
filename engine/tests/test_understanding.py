"""Understand first, then check (team lead, 2 Nov 2026).

"The logic only checks the rules without understanding the context behind the
message; first it must identify what kind of content it is, and understand
the meaning behind it before acting." Plus three bugs from the live walkthrough:
fixes that contradict each other (A2), two cards for the same words (B2), and
an explanation naming one rule while citing another (B4).

Covered here: the content profile (format, kind, intent, summary) for a
promotional social post, an internal note, a press release, a policy, a PDF and
an image; checks gated by the profile; negated, attributed and quoted claims;
duplicate merging; conflict-safe fixes (accept every fix in turn: nothing that
was fixed comes back); citation integrity with a faked AI answer.

Run:  .venv/Scripts/python engine/tests/test_understanding.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

os.environ["CANONRY_AI_DAILY_PER_USER"] = "1000"
os.environ["CANONRY_AI_DAILY_PER_WORKSPACE"] = "1000"

import db as _db  # noqa: E402

_db.use_test_database("canonry_understanding")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import gateway  # noqa: E402
import main as engine  # noqa: E402
import ocr  # noqa: E402
import understand  # noqa: E402
from db import connect, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()
engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


SAMPLE = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully "
          "ISO 27001 certified. Plans start at just ₹999/month!")
NAMES = ["Quillmark Pulse", "Quillmark Insights", "Quillmark Analytics"]

# ---- 1. the profile, without any AI --------------------------------------------
p = understand.profile(SAMPLE, "social", "text", None, names=NAMES)
expect(p["format"] == "text" and p["kind"] == "social_post" and p["intent"] == "promotional",
       f"the launch post is a promotional social post ({p['format']}, {p['kind']}, {p['intent']})")
expect(p["audience"] == "customers" and p["language"] == "en" and not p["has_cta"],
       f"for customers, in English, with no call to action ({p['audience']}, {p['language']}, {p['has_cta']})")
expect(p["product"] == ["Quillmark Insights"], f"it names the product it talks about ({p['product']})")
expect([c["type"] for c in p["claims"]] == ["ranking", "customer count", "certification", "price"],
       f"it lists the four factual claims ({[c['type'] for c in p['claims']]})")
expect(p["summary"] == "A promotional social post for Quillmark Insights that makes 4 factual claims: a ranking, "
                       "a customer count, a certification and a price.", f"plain one-line summary ({p['summary']})")
expect("pricing" in p["topics"] and "customers" in p["topics"], f"topics are found ({p['topics']})")

NOTE = ("Internal note for the marketing team, do not publish. Friday's post offers a free trial and plans at "
        "₹1,299/month. Hurry and review the draft before Thursday!! Priya owns the pricing slide.")
p = understand.profile(NOTE, "social", "text", None, names=NAMES)
expect(p["kind"] == "internal_note" and p["intent"] == "internal" and p["audience"] == "internal",
       f"an internal note is internal, whatever channel it was filed under ({p['kind']}, {p['intent']})")
expect(p["summary"].startswith("An internal note or brief"), f"its summary says so ({p['summary']})")

PRESS = ("FOR IMMEDIATE RELEASE\nBENGALURU, 2 November 2026 — Quillmark Analytics today announced Quillmark Pulse "
         "2.0, which checks every claim against approved facts.\nAbout Quillmark Analytics\nQuillmark Analytics "
         "was founded in 2019.\nMedia contact: press@quillmark.co")
p = understand.profile(PRESS, "web", "text", None, names=NAMES)
expect(p["kind"] == "press_release", f"a press release is recognised ({p['kind']})")

POLICY = ("Privacy Policy\n1. Scope. This policy explains how Quillmark Analytics processes personal data. "
          "2. Retention. We shall retain account data for the term of the contract and delete it within 30 days "
          "of termination, unless the law requires otherwise. 3. Grievance officer: privacy@quillmark.co.")
p = understand.profile(POLICY, "web", "text", None, names=NAMES)
expect(p["kind"] == "policy" and p["intent"] == "informational", f"a policy is informational ({p['kind']}, {p['intent']})")

expect(understand.profile("Pulse one-pager", "web", "pdf", None)["format"] == "pdf", "a PDF upload is a PDF")
expect(understand.profile("Pulse plan", "web", "docx", None)["format"] == "word", "a .docx upload is a Word document")
expect(understand.profile("Launch banner\n\nTrusted by 2,300+ teams", "social", "image", {"image_words": 1})["format"]
       == "image_with_words", "an image with words read from it is an image with words")
expect(understand.profile("Launch banner", "social", "image", {"image_words": 0})["format"]
       == "image_without_words", "an image with only alt text is an image without words")
hindi = understand.profile("क्विलमार्क पल्स आपकी टीम के लिए सबसे अच्छा एनालिटिक्स प्लेटफॉर्म है", "social")
expect(hindi["language"] == "other" and hindi["language_note"], "copy not in English is noted, plainly")

# ---- 2. claims read in context ----------------------------------------------------
NEG = "We never claim to be India's #1 analytics platform; 2,300+ teams decide for themselves."
ctx = understand.claim_context(NEG, NEG.index("India's"), NEG.index("analytics") + 9)
expect(ctx and ctx["kind"] == "negated", f"a denied claim is recognised ({ctx})")
ATTR = "Competitors say they are the best analytics platform. Quillmark Pulse shows its working."
ctx = understand.claim_context(ATTR, ATTR.index("the best"), ATTR.index("the best") + 8)
expect(ctx and ctx["kind"] == "attributed", f"someone else's claim is recognised ({ctx})")
QUOTE = 'A reviewer wrote: "Quillmark Pulse is the best analytics tool in India."'
ctx = understand.claim_context(QUOTE, QUOTE.index("the best"), QUOTE.index("the best") + 8)
expect(ctx and ctx["kind"] == "quoted", f"a quoted claim is recognised ({ctx})")
expect(understand.claim_context(SAMPLE, SAMPLE.index("India's"), SAMPLE.index("India's") + 20) is None,
       "an ordinary claim is ours")

# ---- the API, with a faked AI provider ----------------------------------------------
AI = {"on": False, "calls": [], "extract": None, "verify": None, "tone": None}
DEFAULT = {
    "extract": {"claims": [{"claim": "India's #1 analytics platform"}],
                "profile": {"kind": "ad", "intent": "promotional",
                            "summary": "A launch ad for the analytics product with four claims."}},
    "verify": {"claims": [{"claim": "India's #1 analytics platform", "verdict": "unsupported", "fact_ids": [],
                           "explanation": "No approved fact supports the ranking (CLM-02).",
                           "fix": "India's top analytics platform"}]},
    "tone": {"tone_findings": [
        {"span": "Plans start at just ₹999/month!", "explanation": "Pushy price line (VOICE-3.2).",
         "fix": "Plans start at ₹999 per month."},
        {"span": "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully "
                 "ISO 27001 certified.",
         "explanation": "Exceeds the 20-word limit set by VOICE-3.1.",
         "fix": "Meet Quillmark Insights 2.0. India's top analytics platform, trusted by 5,000+ teams, "
                "ISO 27001 certified."}]},
}


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    system = body["messages"][0]["content"]
    task = "extract" if "claim extractor" in system else "verify" if "verify promotional claims" in system else "tone"
    AI["calls"].append(task)
    out = AI[task] if AI[task] is not None else DEFAULT[task]
    return httpx.Response(200, json={"model": body["model"], "choices": [
        {"message": {"content": out if isinstance(out, str) else json.dumps(out)}}]})


def ai(on: bool):
    AI["on"] = on
    gateway.configure(env={"GROQ_API_KEY": "test"} if on else {}, transport=httpx.MockTransport(handler))


client = TestClient(engine.app, raise_server_exceptions=False)
expect(client.post("/login", json={"email": "arjun@quillmark"}).status_code == 200, "creator signs in")


def submit(content, channel="social"):
    r = client.post("/submissions", json={"title": "t", "channel": channel, "source_type": "in-house",
                                          "content": content})
    assert r.status_code == 200, r.text
    return r.json()


def detail(sid):
    return client.get(f"/submissions/{sid}").json()


def overlap(a, b):
    return a["span_start"] < b["span_end"] and b["span_start"] < a["span_end"]


FAMILY = {"unsupported_claim": "claim", "contradicted_claim": "claim", "outdated_claim": "claim",
          "unsubstantiated_claim": "claim", "misleading_claim": "claim"}

# ---- 3. the profile is stored with the check and returned ---------------------------------
ai(False)
res = submit(SAMPLE)
d = detail(res["submission_id"])
prof = (d.get("check") or {}).get("profile") or {}
expect(prof.get("kind") == "social_post" and prof.get("summary", "").startswith("A promotional social post"),
       f"GET /submissions/{{id}} returns check.profile ({prof.get('summary')})")
expect(res.get("profile", {}).get("kind") == "social_post", "the check response carries the profile too")
conn = connect()
row = conn.execute("SELECT profile_json FROM check_runs WHERE revision_id = ?", (res["revision_id"],)).fetchone()
conn.close()
expect(row and json.loads(row["profile_json"])["kind"] == "social_post", "the profile is stored with the check run")
cats = [f["category"] for f in d["findings"]]
expect("missing_cta" in cats, "a promotional social post with a price and no call to action is still flagged")

# ---- 4. checks gated by the profile ---------------------------------------------------------
d = detail(submit(NOTE)["submission_id"])
cats = [(f["checker"], f["category"]) for f in d["findings"]]
expect(not any(c == "missing_cta" for _, c in cats), f"no call-to-action finding on an internal note ({cats})")
expect(not any(ch == "compliance" for ch, _ in cats), f"the India pack is silent on an internal note ({cats})")
expect(not any(ch == "tone" for ch, _ in cats), f"no hard-sell or exclamation finding on an internal note ({cats})")
decisions = {c["check"]: c for c in d["check"]["profile"]["checks"]}
expect(not decisions["messaging.cta"]["applies"] and "internal" in decisions["messaging.cta"]["why"],
       "the profile says, in words, why the CTA check was skipped")

# the same words without the internal marker are a promotional post: the checks run
d = detail(submit(NOTE.replace("Internal note for the marketing team, do not publish. ", ""))["submission_id"])
cats = [(f["checker"], f["category"]) for f in d["findings"]]
expect(any(c == "missing_cta" for _, c in cats) and any(ch == "tone" for ch, _ in cats),
       f"the same copy as a public post gets the CTA and tone checks ({cats})")
cta = next(f for f in d["findings"] if f["category"] == "missing_cta")
expect("social post" in (cta["provenance"].get("profile") or ""), "the finding records the profile decision behind it")

LONG = " ".join(["Quillmark Pulse helps team members read their numbers every week."] * 22)
social = detail(submit(LONG, "social")["submission_id"])
blog = detail(submit(LONG, "blog")["submission_id"])
social_len = [f for f in social["findings"] if "Social posts are limited" in f["explanation"]]
blog_len = [f for f in blog["findings"] if "Social posts are limited" in f["explanation"]]
expect(len(social_len) == 1 and not blog_len, "the social-post length limit applies only to social posts")

# ---- 5. negation and quotation ----------------------------------------------------------------
d = detail(submit(NEG, "web")["submission_id"])
expect(not any("#1" in (f["span_text"] or "") for f in d["findings"]),
       f"'we never claim to be #1' is not flagged as our claim ({[f['span_text'] for f in d['findings']]})")
d = detail(submit(ATTR, "web")["submission_id"])
expect(not any("best" in (f["span_text"] or "") for f in d["findings"]),
       "'competitors say they are the best' is not flagged as our claim")
d = detail(submit(QUOTE, "web")["submission_id"])
quoted = [f for f in d["findings"] if "best" in (f["span_text"] or "")]
expect(quoted and all(f["tier"] == "consider" and "quotation marks" in f["explanation"] for f in quoted),
       f"a quoted claim is lowered to Consider and says why ({[(f['tier'], f['explanation'][:60]) for f in quoted]})")
expect(d["check"]["profile"]["claims"] and d["check"]["profile"]["claims"][0]["ours"],
       "a quoted claim still counts as a claim the post makes")
neg_prof = understand.profile(NEG, "web")
expect(not neg_prof["claims"][0]["ours"] and "not treated as yours" in neg_prof["summary"],
       f"the summary separates denied claims ({neg_prof['summary']})")

# ---- 6. duplicate findings merge (B2) ------------------------------------------------------------
ai(True)
AI["calls"].clear()
res = submit(SAMPLE)
expect(AI["calls"] == ["extract", "verify", "tone"], f"no extra AI call for the profile ({AI['calls']})")
d = detail(res["submission_id"])
fs = d["findings"]
for i, a in enumerate(fs):
    for b in fs[i + 1:]:
        if not a["span_text"] or not b["span_text"] or not overlap(a, b):
            continue
        fa, fb = FAMILY.get(a["category"], a["category"]), FAMILY.get(b["category"], b["category"])
        expect(fa != fb, f"one card per issue on the same words: {a['category']} {a['span_text']!r} / "
                         f"{b['category']} {b['span_text']!r}")
ranking = [f for f in fs if f["category"] == "unsupported_claim" and "#1" in f["span_text"]]
by = [x["checker"] for x in (ranking[0]["provenance"].get("found_by") or [])] if ranking else []
# rule + AI, and since the India pack learned leadership claims (ASCI cases), the pack too: still one card
expect(len(ranking) == 1 and by.count("claims") == 2 and set(by) <= {"claims", "compliance"},
       f"the rule, the AI and the India pack ranking findings became one card ({by})")
price_tone = [f for f in fs if f["category"] == "tone" and "999" in f["span_text"]]
expect(len(price_tone) == 1, f"'just ₹999' and 'Plans start at just ₹999/month!' are one tone card ({len(price_tone)})")
expect(any(f["category"] == "outdated_term" for f in fs) and any(f["category"] == "contradicted_claim" for f in fs),
       "different issues on the same sentence stay separate (outdated name, contradicted count)")
prof = d["check"]["profile"]
expect(prof["decided_by"] == "rules+ai" and prof["summary"].startswith("A launch ad"),
       f"the AI's reading refines the summary ({prof.get('summary')})")

# ---- 7. citation integrity (B4) -----------------------------------------------------------------
conn = connect()
rule_ids = {r["id"] for r in conn.execute("SELECT id FROM rules WHERE status = 'approved'").fetchall()}
conn.close()
for f in fs:
    named = set(re.findall(r"\b[A-Z][A-Z0-9]{1,7}-\d+(?:\.\d+)*\b", f["explanation"])) & rule_ids
    cited = {c["id"] for c in f["citations"]}
    expect(named <= cited, f"{f['category']} {f['span_text'][:30]!r}: every rule named is cited ({named - cited})")
long_tone = next((f for f in fs if f["category"] == "tone" and f["span_text"].startswith("Meet")), None)
expect(long_tone and {"VOICE-3.1", "VOICE-3.2"} <= {c["id"] for c in long_tone["citations"]},
       "'Exceeds the 20-word limit set by VOICE-3.1' now cites VOICE-3.1")

AI["tone"] = {"tone_findings": [{"span": "Plans start at ₹1,299/month", "explanation": "Too flat (VOICE-9.9).",
                                 "fix": "Plans start at ₹1,299/month"}]}
d = detail(submit("Quillmark Pulse is ready for your team. Plans start at ₹1,299/month. Start a trial at "
                  "quillmark.co.")["submission_id"])
bad = [f for f in d["findings"] if "VOICE-9.9" in f["explanation"]]
expect(not bad, "an explanation never names a rule that does not exist")
AI["tone"] = None

# ---- 8. conflict-safe fixes (A2) ------------------------------------------------------------------
d = detail(res["submission_id"])
fs = d["findings"]
tone = next(f for f in fs if f["category"] == "tone" and "999" in f["span_text"])
expect(tone["suggestion"] and "999" not in tone["suggestion"]["replace"] and "1,299" in tone["suggestion"]["replace"],
       f"the tone fix uses the approved price, never the old one ({tone['suggestion']})")
price = next(f for f in fs if f["category"] == "outdated_claim" and "999" in f["span_text"])
expect("just" not in (price["suggestion"] or {}).get("replace", "just"),
       f"the price fix does not keep the hard-sell word ({price['suggestion']})")
expect(long_tone and not (long_tone["suggestion"] or {}).get("replace")
       and "Fix in your own words" in long_tone["explanation"],
       "an AI rewrite that would still make a flagged claim loses its one-click fix and says why")

AI["tone"] = {"tone_findings": [{"span": "so do not wait any longer", "explanation": "Pushy (VOICE-3.2).",
                                 "fix": "starting at ₹999/month"}]}
d = detail(submit("Plans start at ₹1,299/month, so do not wait any longer. Start a trial at quillmark.co.")
           ["submission_id"])
t = next((f for f in d["findings"] if f["checker"] == "tone" and "wait" in f["span_text"]), None)
expect(t is not None and "999" not in json.dumps(t["suggestion"]),
       f"an AI tone rewrite never brings back a flagged price ({t and t['suggestion']})")
AI["tone"] = None


def issue_keys(findings):
    return {(FAMILY.get(f["category"], f["category"]), f["span_text"]) for f in findings if f["status"] == "open"}


sid = res["submission_id"]
resolved, reappeared, accepted = set(), [], 0
for _ in range(15):
    cur = detail(sid)
    before = issue_keys(cur["findings"])
    nxt = next((f for f in cur["findings"] if f["status"] == "open" and (
        (f["suggestion"] or {}).get("operation") == "replace" and (f["suggestion"] or {}).get("replace")
        or (f["suggestion"] or {}).get("operation") == "remove")), None)
    if not nxt:
        break
    r = client.post(f"/submissions/{sid}/resolve", json={"revision_id": cur["latest_revision"]["id"],
                                                         "finding_id": nxt["id"], "action": "accept"})
    expect(r.status_code == 200, f"accept {nxt['category']} {nxt['span_text']!r} ({r.status_code})")
    accepted += 1
    after = issue_keys(detail(sid)["findings"])
    reappeared += sorted(after & resolved)
    resolved |= before - after
final = detail(sid)
expect(accepted >= 4 and not reappeared, f"accepting every fix in turn never brings a fixed issue back "
                                         f"({accepted} accepted; back: {reappeared})")
text = final["latest_revision"]["content"]
expect("999" not in text and "5,000" not in text and "#1" not in text and "Insights" not in text,
       f"after every fix the copy holds no flagged value ({text!r})")

# a compliance finding's advice is not copy: accepting it is refused, never pasted in
ai(False)
d = detail(submit("Get a free trial at just ₹1,299 per month.", "web")["submission_id"])
comp = next((f for f in d["findings"] if f["checker"] == "compliance"), None)
if comp is not None:
    r = client.post(f"/submissions/{d['submission']['id']}/resolve", json={
        "revision_id": d["latest_revision"]["id"], "finding_id": comp["id"], "action": "accept"})
    expect(r.status_code == 409, f"accepting advice text is refused ({r.status_code})")
    expect(detail(d["submission"]["id"])["latest_revision"]["content"] == "Get a free trial at just ₹1,299 per month.",
           "the copy is unchanged")
else:
    expect(False, "the free-trial line raises an India pack finding")

# ---- 9. uploads: PDF and image formats reach the profile -------------------------------------------
demo_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "demo")
pdf = open(os.path.join(demo_dir, "quillmark_pulse_onepager.pdf"), "rb").read()
r = client.post("/submissions/upload?title=One-pager&channel=web&source_type=in-house&filename=one-pager.pdf",
                content=pdf, headers={"content-type": "application/octet-stream"})
expect(r.status_code == 200, f"PDF uploads ({r.status_code})")
if r.status_code == 200:
    prof = detail(r.json()["submission_id"])["check"]["profile"]
    expect(prof["format"] == "pdf" and "PDF" in prof["summary"], f"a PDF upload is profiled as a PDF ({prof['summary']})")

try:
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (600, 300), "#312e81").save(buf, format="PNG")
    png = buf.getvalue()
    real_words = ocr.words
    ocr.words = lambda img, timeout=40.0: [
        {"text": t, "key": (1, 1, 1), "box": (40 + i * 120, 100, 110, 40)}
        for i, t in enumerate(["Trusted", "by", "2,300+", "teams"])]
    r = client.post("/submissions/upload?title=Banner&channel=social&source_type=in-house&filename=b.png"
                    "&alt_text=Launch banner for Pulse", content=png,
                    headers={"content-type": "application/octet-stream"})
    ocr.words = real_words
    expect(r.status_code == 200, f"image uploads ({r.status_code})")
    if r.status_code == 200:
        prof = detail(r.json()["submission_id"])["check"]["profile"]
        expect(prof["format"] == "image_with_words",
               f"an image upload with words read from it is profiled as such ({prof['format']})")
except ImportError:
    expect(False, "Pillow is installed")

gateway.configure(env=None, transport=None)
print()
print(f"{len(failures)} failure(s)" if failures else "all understanding checks passed")
sys.exit(1 if failures else 0)
