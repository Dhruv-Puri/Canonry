"""Large images are checked without exhausting the free server's memory, with the same answers.

Measured 2 Nov 2026: a 4096 px upload needed ~380 MB above idle (3000 px: ~300 MB) on an engine
that has 512 MB in all; running out restarts the free server and wipes the demo for everyone.
Now the logo search runs on a working copy of at most 2000 px with its positions scaled back,
text recognition prepares its image in strips, an image is decoded once per upload, and RGB
images are no longer copied (4096 px: ~160 MB; 3000 px: ~130 MB). This test pins the answers:
the same logo verdicts and box at 4000 px as at 1000 px, and one pixel job at a time.

Run:  .venv/Scripts/python engine/tests/test_large_images.py
"""
import os
import sys
import threading
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

from PIL import Image  # noqa: E402

import images  # noqa: E402
import logos  # noqa: E402
import ocr  # noqa: E402

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


def scene(scale, logo=RETIRED):
    """The same design at 1000 x 750 times `scale`: the logo 25% of the width, at (8%, 8%)."""
    w, h = 1000 * scale, 750 * scale
    img = Image.new("RGB", (w, h), "white")
    lw = w // 4
    art = logo.resize((lw, round(lw * logo.height / logo.width)), Image.LANCZOS)
    img.paste(art, (w * 8 // 100, h * 8 // 100), art)
    return img


small, big = scene(1), scene(4)                       # 1000 px and 4000 px wide
m_small, m_big = images._find_logo(small, TEMPLATES), images._find_logo(big, TEMPLATES)
expect(m_small is not None and m_big is not None, "the logo is found at 1000 px and at 4000 px")
if m_small and m_big:
    expect(m_small.template.variant == m_big.template.variant == "deprecated",
           "both see the retired version")
    expect(abs(m_big.width / big.width - m_small.width / small.width) < 0.02,
           f"the logo's share of the width is the same ({m_small.width / small.width:.3f} vs "
           f"{m_big.width / big.width:.3f}), so size verdicts do not change")
    sx, sy, sw, sh = m_small.bbox
    bx, by, bw, bh = m_big.bbox
    expect(abs(bx - sx * 4) <= 24 and abs(by - sy * 4) <= 24 and abs(bw - sw * 4) <= 32,
           f"the box is in the uploaded image's own pixels ({m_big.bbox} vs 4 x {m_small.bbox})")
    expect(abs(m_big.aspect_change - m_small.aspect_change) < 0.05 and abs(m_big.rotation - m_small.rotation) < 2,
           "distortion and rotation verdicts are the same")

# the OCR preparation never holds two full-size float colour copies (numpy memory is traced)
tracemalloc.start()
ocr._prepared(scene(4))
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
expect(peak < 120e6, f"preparing a 4000 px image for text recognition stays small ({peak / 1e6:.0f} MB)")

# one pixel job at a time
order = []


def job(name):
    with images.PIXEL_WORK:
        order.append(name + ":start")
        threading.Event().wait(0.05)
        order.append(name + ":end")


threads = [threading.Thread(target=job, args=(n,)) for n in ("a", "b")]
for t in threads:
    t.start()
for t in threads:
    t.join()
expect(order[0][2:] == "start" and order[1][2:] == "end" and order[1][0] == order[0][0],
       f"two uploads never do pixel work at the same time ({order})")

print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("LARGE IMAGES ARE SAFE")
