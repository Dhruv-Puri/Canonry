"""Fixes to a Word upload are made inside the .docx itself, keeping its formatting,
and the approved, stamped file is the fixed one.

Run:  .venv/Scripts/python engine/tests/test_docx_fix.py
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db  # noqa: E402

_db.use_test_database("canonry_docx_fix")

from fastapi.testclient import TestClient  # noqa: E402
from lxml import etree  # noqa: E402

import documents  # noqa: E402
import main  # noqa: E402
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


def run(text, bold=False):
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r>'


def make_docx() -> bytes:
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' + run("Pulse for retail teams") + "</w:p>"
        "<w:p>" + run("Meet ") + run("Quillmark Insights", bold=True) + run(" 2.0, now on every plan.") + "</w:p>"
        "<w:tbl><w:tr><w:tc><w:p>" + run("Teams: ") + run("Quillmark Insights users") + "</w:p></w:tc></w:tr></w:tbl>"
        "<w:p>" + run("Trusted by 5,000+ teams across India.") + "</w:p>"
        "<w:p>" + run("Questions? Write to hello@quillmark.co.") + "</w:p>"
    )
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
                   'officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", f'<w:styles xmlns:w="{W}"/>')
    return out.getvalue()


def paragraphs(data):
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    return root


ORIGINAL = make_docx()
text = documents.extract("brochure.docx", ORIGINAL).text

# ---- the editor on its own ------------------------------------------------------
edited = documents.docx_with_text(ORIGINAL, text.replace("Quillmark Insights 2.0", "Quillmark Pulse 2.0", 1))
expect(documents.extract("b.docx", edited).text == text.replace("Quillmark Insights 2.0", "Quillmark Pulse 2.0", 1),
       "the edited file reads back as exactly the fixed text")
root = paragraphs(edited)
bold_runs = ["".join(t.text or "" for t in r.iter(f"{{{W}}}t")) for r in root.iter(f"{{{W}}}r")
             if r.find(f"{{{W}}}rPr/{{{W}}}b") is not None]
expect(bold_runs == ["Quillmark Pulse"], f"the fixed words keep their bold run ({bold_runs})")
expect(root.find(f".//{{{W}}}pStyle").get(f"{{{W}}}val") == "Heading1", "the heading keeps its style")
expect(zipfile.ZipFile(io.BytesIO(edited)).read("word/styles.xml") ==
       zipfile.ZipFile(io.BytesIO(ORIGINAL)).read("word/styles.xml"), "the other parts of the file are untouched")
expect(b"ns0:" not in zipfile.ZipFile(io.BytesIO(edited)).read("word/document.xml"),
       "Word's namespace prefixes are kept (Word refuses ns0: documents)")
edited = documents.docx_with_text(ORIGINAL, text.replace("Quillmark Insights users", "Quillmark Pulse users"))
expect("Quillmark Pulse users" in documents.extract("b.docx", edited).text, "a table cell can be fixed")
try:
    documents.docx_with_text(ORIGINAL, text + "\n\nA paragraph that is not in the file.")
    expect(False, "a change of paragraph count is refused")
except documents.DocumentError:
    expect(True, "a change of paragraph count is refused (it would not map onto the file)")

# ---- through the product ----------------------------------------------------------
client = TestClient(main.app)
client.__enter__()
client.post("/login", json={"email": "arjun@quillmark"})
r = client.post("/submissions/upload?title=Brochure&channel=web&source_type=in-house&filename=brochure.docx",
                content=ORIGINAL, headers={"content-type": "application/octet-stream"})
expect(r.status_code == 200, f"the Word file uploads ({r.status_code})")
sid = r.json()["submission_id"]
d = client.get(f"/submissions/{sid}").json()
first_asset = d["latest_revision"]["asset_id"]
old_name = next((f for f in d["findings"] if f["category"] == "outdated_term"), None)
expect(old_name is not None and old_name["suggestion"], "the old product name is found, with a fix")
r = client.post(f"/submissions/{sid}/resolve", json={"finding_id": old_name["id"], "action": "accept",
                                                        "revision_id": d["latest_revision"]["id"]})
expect(r.status_code == 200, f"the fix is accepted in Canonry ({r.status_code} {r.text[:100]})")
d = client.get(f"/submissions/{sid}").json()
rev = d["latest_revision"]
expect(rev["source_kind"] == "docx" and rev["asset_id"] and rev["asset_id"] != first_asset,
       "the fixed revision is a new version of the Word file")
f = client.get(f"/assets/{rev['asset_id']}")
fixed_text = documents.extract("b.docx", f.content).text
expect(f.status_code == 200 and fixed_text == rev["content"], "the file's own text is the revision's text")
expect("Quillmark Insights" not in fixed_text.split("\n\n")[1], "and the fix is inside the file")
expect(all((x.get("locator") or {}).get("paragraph") for x in d["findings"] if x["span_text"]),
       "findings on the fixed version still point to their paragraph")

target = next((x for x in d["findings"] if x["category"] == "outdated_term"), None)
if target:
    r = client.post(f"/submissions/{sid}/resolve", json={
        "finding_id": target["id"], "action": "edit", "revision_id": rev["id"], "replacement": "Quillmark Pulse"})
    expect(r.status_code == 200, f"an edit in your own words also lands in the file ({r.status_code})")
d = client.get(f"/submissions/{sid}").json()
spanned = next(x for x in d["findings"] if x["span_text"])
r = client.post(f"/submissions/{sid}/resolve", json={
    "finding_id": spanned["id"], "action": "edit", "revision_id": d["latest_revision"]["id"],
    "replacement": "one\n\ntwo"})
expect(r.status_code == 409, f"an edit that adds a paragraph is refused ({r.status_code} {r.text[:80]})")
d = client.get(f"/submissions/{sid}").json()
expect(d["latest_revision"]["asset_id"] and d["latest_revision"]["source_kind"] == "docx",
       "and the refused edit leaves the file as it was")

# ---- approve: the stamped file is the fixed one -----------------------------------------
d = client.get(f"/submissions/{sid}").json()
for x in d["findings"]:
    if x["status"] == "open":
        client.post(f"/submissions/{sid}/resolve", json={"finding_id": x["id"], "action": "dispute",
                                                            "revision_id": d["latest_revision"]["id"],
                                                            "reason": "test"})
r = client.post(f"/submissions/{sid}/submit-review")
expect(r.status_code == 200, f"sent for review ({r.status_code} {r.text[:80]})")
client.post("/login", json={"email": "karan@quillmark"})
r = client.post(f"/submissions/{sid}/review", json={"action": "approve", "comment": "ok"})
expect(r.status_code == 200, f"approved ({r.status_code} {r.text[:120]})")
f = client.get(f"/submissions/{sid}/proof-file")
expect(f.status_code == 200 and "Quillmark Insights 2.0" not in documents.extract("b.docx", f.content).text,
       "the stamped, approved file carries the fix")
import stamping  # noqa: E402

envelope = stamping.extract_record(f.content)
expect(envelope is not None and envelope["record"].get("submission_id") == sid,
       "and its proof travels inside the Word file")
poc_id = client.get(f"/submissions/{sid}").json()["poc"]["id"]
v = client.post(f"/verify/{poc_id}/file", content=f.content, headers={"content-type": "application/octet-stream"})
expect(v.status_code == 200 and v.json().get("status") == "verified",
       f"the stamped Word file verifies on the public page ({v.status_code} {v.text[:120]})")
tampered = documents.docx_with_text(f.content, documents.extract("b.docx", f.content).text.replace(
    "hello@quillmark.co", "sales@quillmark.co"))
v = client.post(f"/verify/{poc_id}/file", content=tampered, headers={"content-type": "application/octet-stream"})
expect(v.json().get("status") == "modified" and "changed" in v.json().get("reason", ""), f"and a changed copy that keeps the seal is reported as changed ({v.json().get('status')})")
from PIL import Image  # noqa: E402

other = io.BytesIO()
Image.new("RGB", (40, 40), "#dc2626").save(other, format="PNG")
forged = stamping.stamp_file(other.getvalue(), envelope, "png")
v = client.post(f"/verify/{poc_id}/file", content=forged, headers={"content-type": "application/octet-stream"})
expect(v.json().get("status") == "modified",
       f"a real seal copied onto a different file does not verify ({v.json().get('status')})")

client.__exit__(None, None, None)
print()
if failures:
    print(f"{len(failures)} FAILED")
    sys.exit(1)
print("ALL WORD FIX CHECKS PASSED")
