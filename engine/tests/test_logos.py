"""Logo use: found at any size, and judged against the brand rule (BRD-02:
never stretched, recoloured or placed over busy backgrounds; current version
only; clear space; minimum size). Every case is a generated image, so the
expected answer is known exactly.

Run:  .venv/Scripts/python engine/tests/test_logos.py
"""
import io
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_logos")

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import logos  # noqa: E402
import main  # noqa: E402
import ocr  # noqa: E402
from seed import seed  # noqa: E402

main.DEMO_MODE = True
main.COOKIE_SECURE = False
ocr.words = lambda img, timeout=40.0: []  # logo tests are about pixels; no text recognition needed
seed()

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
CURRENT = Image.open(os.path.join(ROOT, "brand", "quillmark_logo.png")).convert("RGBA")
RETIRED = Image.open(os.path.join(ROOT, "brand", "quillmark_logo_old.png")).convert("RGBA")
TEMPLATES = [logos.Template("cur", "Quillmark Pulse logo", "current", CURRENT, 0.14, 0.15),
             logos.Template("old", "Quillmark Insights logo (retired)", "deprecated", RETIRED, 0.14, 0.15)]

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def scene(logo=CURRENT, width=300, stretch=1.0, rotate=0, at=(80, 60), size=(1200, 630), busy_behind=False,
          crowded=False):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    if busy_behind:
        rng = np.random.default_rng(7)
        for _ in range(220):
            x, y = int(rng.integers(0, 500)), int(rng.integers(0, 260))
            d.line((x, y, x + int(rng.integers(-40, 40)), y + int(rng.integers(-40, 40))),
                   fill=tuple(int(v) for v in rng.integers(60, 230, 3)), width=2)
    h = round(width * logo.height / logo.width)
    art = logo.resize((round(width * stretch), h), Image.LANCZOS)
    if rotate:
        art = art.rotate(rotate, expand=True, resample=Image.BICUBIC)
    img.paste(art, at, art)
    if crowded:
        d.rectangle((at[0] + art.width + 4, at[1], at[0] + art.width + 120, at[1] + art.height), fill="#111827")
    return img


def recoloured(logo, src=(15, 118, 110), dst=(220, 38, 38)):
    arr = np.array(logo).astype(np.int32)
    near = np.linalg.norm(arr[:, :, :3] - np.array(src), axis=2) < 60
    arr[near, :3] = dst
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def jpeg(img, quality=70):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


# ---- finding the logo -----------------------------------------------------------
m = logos.find(scene(), TEMPLATES)
expect(m is not None and m.template.variant == "current", "the current logo is found")
expect(m is not None and abs(m.width - 300) < 8 and abs(m.aspect_change - 1) < 0.03 and abs(m.rotation) < 1.5,
       f"its size and shape are measured ({m and (round(m.width), round(m.aspect_change, 3), round(m.rotation, 1))})")
expect(m is not None and m.colour_delta < 12, f"its colours match the artwork (dE {m and round(m.colour_delta, 1)})")

m = logos.find(scene(width=70), TEMPLATES)
expect(m is not None and abs(m.width - 70) < 6, f"a 70 px logo is still found ({m and round(m.width)})")

m = logos.find(scene(stretch=1.5), TEMPLATES)
expect(m is not None and abs(m.aspect_change - 1.5) < 0.05, f"a logo stretched 50% wide is measured "
                                                             f"({m and round(m.aspect_change, 3)})")
m = logos.find(scene(stretch=0.7), TEMPLATES)
expect(m is not None and abs(m.aspect_change - 0.7) < 0.05, "a squashed logo is measured")
m = logos.find(scene(rotate=10), TEMPLATES)
expect(m is not None and abs(abs(m.rotation) - 10) < 1.5, f"a tilted logo is measured ({m and round(m.rotation, 1)})")

m = logos.find(scene(RETIRED), TEMPLATES)
expect(m is not None and m.template.variant != "current", "the retired logo is told apart from the current one")
m = logos.find(scene(recoloured(CURRENT)), TEMPLATES)
expect(m is not None and m.template.variant == "current" and m.colour_delta > 20,
       f"a current logo in the wrong colour is the current logo, recoloured "
       f"({m and (m.template.variant, round(m.colour_delta, 1))})")
m = logos.find(jpeg(scene()), TEMPLATES)
expect(m is not None and m.template.variant == "current" and m.colour_delta < 15,
       f"JPEG compression is not a recolour ({m and round(m.colour_delta, 1)})")

# ---- not a logo ------------------------------------------------------------------
demo = Image.open(os.path.join(ROOT, "demo", "social_launch.png")).convert("RGB")
expect(logos.find(demo.crop((0, 330, 1080, 1080)), TEMPLATES) is None,
       "a headline in the logo's typeface is not a logo")
rng = np.random.default_rng(3)
photo = Image.fromarray(rng.integers(0, 255, (630, 1200, 3), dtype=np.uint8), "RGB")
expect(logos.find(photo, TEMPLATES) is None, "noise is not a logo")
expect(logos.find(Image.new("RGB", (800, 400), "#312e81"), TEMPLATES) is None, "a flat banner is not a logo")

# ---- the findings, through the real upload -----------------------------------------
client = TestClient(main.app)
client.__enter__()
client.post("/login", json={"email": "arjun@quillmark"})


def logo_findings(img, alt="Quillmark Pulse launch banner"):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = client.post(f"/submissions/upload?title=Logo&channel=social&source_type=in-house&filename=l.png"
                    f"&alt_text={alt}", content=buf.getvalue(), headers={"content-type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    d = client.get(f"/submissions/{r.json()['submission_id']}").json()
    return {f["category"]: f for f in d["findings"] if f["category"].startswith("logo_")}


got = logo_findings(scene())
expect(not got, f"a correct logo has no logo findings ({list(got)})")
got = logo_findings(scene(stretch=1.5))
expect("logo_distorted" in got and re.search(r"stretched (4[6-9]|5[0-4])% wider", got["logo_distorted"]["explanation"]),
       f"a stretched logo is flagged with how much ({list(got)})")
expect("logo_distorted" in got and got["logo_distorted"]["citations"][0]["id"] == "BRD-02",
       "citing the Quillmark logo rule BRD-02")
expect("logo_distorted" in got and got["logo_distorted"]["locator"].get("bbox"), "and boxed on the image")
got = logo_findings(scene(rotate=10))
expect("logo_distorted" in got and "tilt" in got["logo_distorted"]["explanation"].lower(), "a tilted logo is flagged")
got = logo_findings(scene(recoloured(CURRENT)))
expect("logo_recoloured" in got and "logo_outdated" not in got, f"a recoloured logo is flagged as such ({list(got)})")
got = logo_findings(scene(RETIRED))
expect("logo_outdated" in got, "the retired logo is flagged")
got = logo_findings(scene(busy_behind=True))
expect("logo_busy_background" in got, f"a logo on a busy background is flagged ({list(got)})")
got = logo_findings(scene(crowded=True))
expect("logo_clear_space" in got and "logo_busy_background" not in got,
       f"content inside the clear space is flagged ({list(got)})")
got = logo_findings(scene(width=70))
expect("logo_too_small" in got, f"a logo below the minimum size is flagged ({list(got)})")
got = logo_findings(demo)
expect("logo_outdated" in got, "the demo graphic's retired logo is flagged")

# ---- the logo's own words are not "text in the image" --------------------------
ocr.words = lambda img, timeout=40.0: [
    {"text": "PULSE", "key": (1, 1, 1), "box": (180, 120, 60, 14)},      # the logo's subtitle
    {"text": "r", "key": (2, 1, 1), "box": (100, 80, 8, 10)},           # noise inside the icon
    {"text": "Analytics", "key": (3, 1, 1), "box": (80, 300, 200, 40)},  # real copy
    {"text": "you", "key": (3, 1, 1), "box": (290, 300, 80, 40)},
    {"text": "trust", "key": (3, 1, 1), "box": (380, 300, 110, 40)}]
img = scene()
ImageDraw.Draw(img).text((80, 300), "Analytics you trust", fill="#111827")
buf = io.BytesIO()
img.save(buf, format="PNG")
r = client.post("/submissions/upload?title=Logo&channel=social&source_type=in-house&filename=l.png"
                "&alt_text=Quillmark%20Pulse%20banner", content=buf.getvalue(),
                headers={"content-type": "application/octet-stream"})
content = client.get(f"/submissions/{r.json()['submission_id']}").json()["latest_revision"]["content"]
expect("PULSE" not in content and "\nr" not in content and "Analytics you trust" in content,
       f"words inside the logo, and one-letter noise, are left out of the image text ({content!r})")
ocr.words = lambda img, timeout=40.0: []

client.__exit__(None, None, None)
print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL LOGO CHECKS PASSED")
