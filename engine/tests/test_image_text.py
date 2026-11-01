"""Text inside images is read, checked like any copy, and located on the image.

The OCR is mocked for the deterministic checks (so CI needs no Tesseract) and
real for the last block, which skips cleanly when Tesseract is not installed.

Run:  .venv/Scripts/python engine/tests/test_image_text.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db  # noqa: E402

_db.use_test_database("canonry_image_text")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import images  # noqa: E402
import main  # noqa: E402
import ocr  # noqa: E402
from seed import seed  # noqa: E402

main.DEMO_MODE = True
main.COOKIE_SECURE = False
seed()

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def social_png() -> bytes:
    """Brand indigo, a white claim, and a grey line too faint to read (about 1.6:1)."""
    img = Image.new("RGB", (1200, 630), "#312e81")
    d = ImageDraw.Draw(img)
    d.text((70, 110), "India's #1 analytics platform", font=_font(64), fill="#ffffff")
    d.text((70, 230), "Trusted by 5,000+ teams", font=_font(44), fill="#4b4a8a")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# words as Tesseract reports them for social_png(): (block, paragraph, line) and box
MOCK_WORDS = [
    {"text": t, "key": (1, 1, 1), "box": (70 + i * 160, 110, 150, 60)}
    for i, t in enumerate(["India's", "#1", "analytics", "platform"])
] + [
    {"text": t, "key": (2, 1, 1), "box": (70 + i * 130, 230, 120, 42)}
    for i, t in enumerate(["Trusted", "by", "5,000+", "teams"])
]

real_words = ocr.words
ocr.words = lambda img, timeout=40.0: [dict(w) for w in MOCK_WORDS]

# ---- composing the checked text -------------------------------------------
text, lmap = images.image_text("Launch banner for Pulse", {"lines": [
    {"text": "India's #1 analytics platform", "bbox": [70, 110, 630, 60], "ratio": 12.0, "needs": 3.0},
    {"text": "Trusted by 5,000+ teams", "bbox": [70, 230, 510, 42], "ratio": 1.6, "needs": 3.0}]})
expect(text == "Launch banner for Pulse\n\nIndia's #1 analytics platform\nTrusted by 5,000+ teams",
       "checked text is the alt text, then each line read from the image")
second = [b for b in lmap if b["region"] == "text in image"][1]
expect(text[second["start"]:second["end"]] == "Trusted by 5,000+ teams" and second["bbox"] == [70, 230, 510, 42],
       "each image line knows its characters and its box")
loc = images.locate(lmap, text.index("5,000+"), text.index("5,000+") + 6, "ast_x")
expect(loc and loc["region"] == "text in image" and loc["bbox"] == [70, 230, 510, 42] and loc["line"] == 2,
       f"a finding in image text points at that line's box ({loc})")
loc = images.locate(lmap, 0, 6, "ast_x")
expect(loc and loc["region"] == "alt text", "a finding in the alt text points at the alt text")
text0, lmap0 = images.image_text("", None)
expect(text0 == "" and lmap0 == [], "no alt text and no OCR: nothing to check as text")

client = TestClient(main.app)
client.__enter__()
r = client.post("/login", json={"email": "arjun@quillmark"})
expect(r.status_code == 200, f"creator signs in ({r.status_code})")


def upload(data, alt="Launch banner for Pulse 2.0", name="social.png"):
    return client.post(f"/submissions/upload?title=Social&channel=social&source_type=in-house&filename={name}"
                       f"&alt_text={alt}", content=data, headers={"content-type": "application/octet-stream"})


def detail(sid):
    return client.get(f"/submissions/{sid}").json()


# ---- an image's own words are checked --------------------------------------
r = upload(social_png())
expect(r.status_code == 200, f"image upload is checked ({r.status_code} {r.text[:120]})")
sid = r.json()["submission_id"]
d = detail(sid)
rev = d["latest_revision"]
expect("Trusted by 5,000+ teams" in rev["content"], "the words in the image are part of the checked text")
in_image = [f for f in d["findings"] if (f.get("locator") or {}).get("region") == "text in image"]
claim = next((f for f in in_image if "5,000+" in (f["span_text"] or "")), None)
expect(claim is not None and claim["checker"] == "claims",
       f"the team-count claim inside the image is caught ({[(f['checker'], f['span_text']) for f in in_image]})")
expect(claim is not None and claim["locator"].get("bbox") == [70, 230, 510, 42],
       "and the finding carries the box of that line on the image")
low = [f for f in d["findings"] if f["category"] == "low_text_contrast"]
expect(len(low) == 1 and "Trusted by 5,000+ teams" in low[0]["explanation"],
       f"the faint line is flagged for contrast ({[f['explanation'][:70] for f in low]})")
expect(low and low[0]["locator"].get("bbox") == [70, 230, 510, 42], "on that line's box")
expect(not any("India's" in f["explanation"] for f in low), "the white headline passes contrast")

# ---- fixing: image words need a new file, alt text can be edited here -----
r = client.post(f"/submissions/{sid}/resolve", json={"finding_id": claim["id"], "revision_id": rev["id"],
                                                        "action": "edit", "replacement": "Trusted by 2,300+ teams"})
expect(r.status_code == 409 and "image" in r.text.lower(),
       f"text inside the image cannot be edited in Canonry ({r.status_code} {r.text[:90]})")
r = client.post(f"/submissions/{sid}/resolve", json={"finding_id": claim["id"], "revision_id": rev["id"],
                                                        "action": "accept"})
expect(r.status_code == 409, "nor accepted as a one-click fix")
alt_finding = next((f for f in d["findings"] if (f.get("locator") or {}).get("region") == "alt text"), None)

r = upload(social_png(), alt="Image of a banner")
sid2 = r.json()["submission_id"]
d2 = detail(sid2)
weak = next((f for f in d2["findings"] if f["category"] == "alt_text_quality"), None)
expect(weak is not None, "weak alt text is still flagged")
r = client.post(f"/submissions/{sid2}/resolve", json={
    "finding_id": weak["id"], "revision_id": d2["latest_revision"]["id"], "action": "edit",
    "replacement": "Pulse 2.0 launch banner on Quillmark Indigo"})
expect(r.status_code == 200, f"alt text can be edited ({r.status_code} {r.text[:90]})")
d2 = detail(sid2)
expect(d2["latest_revision"]["content"].startswith("Pulse 2.0 launch banner on Quillmark Indigo\n\n")
       and "Trusted by 5,000+ teams" in d2["latest_revision"]["content"],
       "the new revision keeps the image's words after an alt-text edit")
expect(any(f["checker"] == "claims" and "5,000+" in (f["span_text"] or "") for f in d2["findings"]),
       "so the claim in the image is still caught")

# ---- re-check keeps the file ------------------------------------------------
r = client.post(f"/submissions/{sid}/recheck")
expect(r.status_code == 200, f"re-check runs ({r.status_code})")
d = detail(sid)
expect(d["latest_revision"].get("asset_id") and d["latest_revision"].get("source_kind") == "image",
       "re-checking an uploaded image keeps the image (it used to become plain text)")
expect(any(f["category"] == "low_text_contrast" for f in d["findings"]),
       "and the image checks still run after a re-check")

# ---- without OCR the upload still works ---------------------------------------
ocr.words = lambda img, timeout=40.0: None
r = upload(social_png(), alt="Pulse 2.0 launch banner")
expect(r.status_code == 200, "an image uploads when text recognition is unavailable")
d = detail(r.json()["submission_id"])
expect(d["latest_revision"]["content"] == "Pulse 2.0 launch banner", "only the alt text is checked as text")
expect(not any(f["tier"] == "definite" for f in d["findings"] if f["category"] == "low_text_contrast"),
       "and any contrast estimate without the text is never Definite")
ocr.words = real_words

# ---- real Tesseract (skipped when it is not installed) ------------------------
if ocr.available():
    read = ocr.read(Image.open(io.BytesIO(social_png())))
    lines = [ln["text"] for ln in read["lines"]]
    expect(any("India's #1 analytics platform" in t for t in lines), f"real OCR reads the headline ({lines})")
    faint = next((ln for ln in read["lines"] if "Trusted by" in ln["text"]), None)
    expect(faint is not None, "real OCR reads the faint line too (the line a contrast check is for)")
    expect(faint is not None and faint["ratio"] is not None and faint["ratio"] < faint["needs"],
           f"and measures it below WCAG ({faint and faint['ratio']})")
    head = next((ln for ln in read["lines"] if "India" in ln["text"]), None)
    expect(head is not None and head["ratio"] and head["ratio"] >= head["needs"], "the white headline passes")
else:
    print("skip: Tesseract is not installed, real-OCR checks skipped")

client.__exit__(None, None, None)
print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL IMAGE TEXT CHECKS PASSED")
