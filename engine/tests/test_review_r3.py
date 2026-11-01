"""Findings of the Round 3 code review: each stays fixed.

Run:  .venv/Scripts/python engine/tests/test_review_r3.py
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_review_r3")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import images  # noqa: E402
import main  # noqa: E402
import ocr  # noqa: E402
import stamping  # noqa: E402
from seed import seed  # noqa: E402

main.DEMO_MODE = True
main.COOKIE_SECURE = False
seed()

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def docx(paragraphs, extra=None, content_types=True):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if content_types:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        else:
            z.writestr("notes/[Content_Types].xml.txt", "not the real part")
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                        f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return out.getvalue()


client = TestClient(main.app, raise_server_exceptions=False)
client.__enter__()


def login(email):
    client.post("/login", json={"email": email})


def upload(data, name="b.docx", alt=""):
    return client.post(f"/submissions/upload?title=T&channel=web&source_type=in-house&filename={name}"
                       f"&alt_text={alt}", content=data, headers={"content-type": "application/octet-stream"})


def approve(sid):
    login("arjun@quillmark")
    d = client.get(f"/submissions/{sid}").json()
    for f in d["findings"]:
        if f["status"] == "open":
            client.post(f"/submissions/{sid}/resolve", json={"finding_id": f["id"], "action": "dispute",
                                                                "revision_id": d["latest_revision"]["id"],
                                                                "reason": "test"})
            d = client.get(f"/submissions/{sid}").json()
    client.post(f"/submissions/{sid}/submit-review")
    login("karan@quillmark")
    return client.post(f"/submissions/{sid}/review", json={"action": "approve", "comment": "ok"})


login("arjun@quillmark")

# 1. a hostile embedded proof must not crash the public verify endpoint
r = upload(docx(["Analytics your team can trust."]))
sid = r.json()["submission_id"]
r = approve(sid)
poc = r.json().get("poc_id")
forged = stamping.stamp_file(docx(["Something else."]), {"record": {"a": 1}, "signature": 123}, "docx")
v = client.post(f"/verify/{poc}/file", content=forged, headers={"content-type": "application/octet-stream"})
expect(v.status_code == 200 and v.json().get("status") != "verified",
       f"a proof with a non-text signature is rejected, not a server error ({v.status_code})")
for bad in ({"record": "x", "signature": "ab"}, {"record": {"a": 1}, "signature": "zz"}, {"record": None}):
    forged = stamping.stamp_file(docx(["Other."]), bad, "docx")
    v = client.post(f"/verify/{poc}/file", content=forged, headers={"content-type": "application/octet-stream"})
    expect(v.status_code == 200, f"malformed proof {bad} answers 200 ({v.status_code})")

# 2. a zip bomb is refused at upload, before any fix or approval reads it
login("arjun@quillmark")
bomb = docx(["Analytics."], extra={"word/media/blob.bin": b"\0" * (80 * 1024 * 1024)})
r = upload(bomb)
expect(r.status_code == 413, f"a Word file that inflates to 80 MB is refused ({r.status_code} {len(bomb)} bytes)")

# 3. a Word file whose package parts are broken: refused at upload, or approvable
r = upload(docx(["Analytics."], content_types=False))
expect(r.status_code in (415, 422), f"a .docx without [Content_Types].xml is refused at upload ({r.status_code})")
r = upload(docx(["Analytics your team can trust."], extra={"docProps/custom.xml": "<Properties><broken"}))
expect(r.status_code == 200, "a .docx with broken custom properties uploads")
r = approve(r.json()["submission_id"])
expect(r.status_code == 200, f"and can still be approved and stamped ({r.status_code} {r.text[:100]})")

# 4. missing alt text on an image that has words can be fixed
login("arjun@quillmark")
ocr.words = lambda img, timeout=40.0: [{"text": t, "key": (1, 1, 1), "box": (60 + i * 140, 80, 130, 40)}
                                       for i, t in enumerate(["Analytics", "you", "trust"])]
buf = io.BytesIO()
img = Image.new("RGB", (800, 300), "white")
ImageDraw.Draw(img).text((60, 80), "Analytics you trust", fill="#111827")
img.save(buf, format="PNG")
r = upload(buf.getvalue(), name="i.png")
d = client.get(f"/submissions/{r.json()['submission_id']}").json()
missing = next((f for f in d["findings"] if f["category"] == "missing_alt_text"), None)
expect(missing is not None, "an image without alt text is flagged")
r = client.post(f"/submissions/{d['submission']['id']}/resolve", json={
    "finding_id": missing["id"], "revision_id": d["latest_revision"]["id"], "action": "edit",
    "replacement": "Banner reading Analytics you trust"})
expect(r.status_code == 200, f"and the alt text can be added in Canonry ({r.status_code} {r.text[:90]})")

# 6. a huge logo file is reduced before matching
big = Image.new("RGBA", (4000, 1000), (0, 0, 0, 0))
ImageDraw.Draw(big).rectangle((0, 0, 900, 900), fill=(15, 118, 110, 255))
small = images.template_art(big)
expect(max(small.size) <= 1000, f"logo artwork is matched at a bounded size ({small.size})")

# 8, 9. a removal at the start of a paragraph; tidying stays inside the edited paragraph
text = "Two  spaces here.\n\nVery good results."
out = main.apply_fix(text, text.index("Very"), "Very", "")
expect(out == "Two  spaces here.\n\ngood results.",
       f"removing a word at a paragraph start leaves no stray space, other paragraphs untouched ({out!r})")
text = "Two  spaces here .\n\nOld name ships today."
out = main.apply_fix(text, text.index("Old name"), "Old name", "New name")
expect(out.split("\n\n")[0] == "Two  spaces here .", f"other paragraphs are not tidied ({out!r})")

# 11. a non-Latin-1 file name downloads
login("arjun@quillmark")
r = upload(docx(["Analytics your team can trust."]), name="brochure™.docx")
asset = client.get(f"/submissions/{r.json()['submission_id']}").json()["latest_revision"]["asset_id"]
g = client.get(f"/assets/{asset}")
expect(g.status_code == 200, f"a file named brochure™.docx downloads ({g.status_code})")

client.__exit__(None, None, None)
print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL REVIEW FIXES HOLD")
