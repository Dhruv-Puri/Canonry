"""Round 3 documents: extraction, page/line locators, image checks, stamping.

Run:  .venv/Scripts/python engine/tests/test_documents.py
"""
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: never reach a real AI provider)

import db as _db

_db.use_test_database("canonry_documents")

import documents  # noqa: E402
import images  # noqa: E402
import stamping  # noqa: E402
from checkers import Ctx  # noqa: E402
from db import connect  # noqa: E402
from seed import seed  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def make_docx() -> bytes:
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Launch plan</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Meet Quillmark Insights 2.0, trusted by 5,000+ teams.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Plans start at just ₹999/month.</w:t></w:r></w:p>'
        '</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", body)
    return buf.getvalue()


ws = seed()
conn = connect()
try:
    # ---- PDF: real page and line, not a character offset alone ----
    demo_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "demo")
    pdf = open(os.path.join(demo_dir, "quillmark_pulse_onepager.pdf"), "rb").read()
    pdf_doc = documents.extract("one-pager.pdf", pdf)
    expect(pdf_doc.page_count == 2, f"PDF page count ({pdf_doc.page_count})")
    expect(len(pdf_doc.locator_map) == 2, "one locator block per text page")
    idx = pdf_doc.text.find("5,000+")
    expect(idx >= 0, "PDF text layer contains the planted count")
    loc = documents.locate(pdf_doc.locator_map, idx, idx + 6, "pdf", "ast_demo")
    expect(bool(loc and loc.get("page") == 1 and loc.get("line")), f"PDF locator names page and line ({loc})")
    expect(documents.describe(loc).startswith("page 1"), "PDF locator has a readable label")

    # ---- DOCX: section and paragraph, page only when the file declares one ----
    docx = make_docx()
    docx_doc = documents.extract("launch.docx", docx)
    expect(docx_doc.source_kind == "docx" and len(docx_doc.locator_map) == 3, "DOCX paragraphs are extracted in order")
    idx = docx_doc.text.find("₹999")
    dloc = documents.locate(docx_doc.locator_map, idx, idx + 5, "docx", "ast_docx")
    expect(bool(dloc and dloc.get("paragraph") == 3 and dloc.get("section") == "Launch plan"),
           f"DOCX locator names section and paragraph ({dloc})")
    expect(not dloc.get("page"), "DOCX does not invent a page number without a page break")

    # ---- images: visual checks against the seeded brand kit ----
    img_path = os.path.join(demo_dir, "social_launch.png")
    raw = open(img_path, "rb").read()
    info = images.inspect(raw)
    expect(info.width > 0 and info.height > 0 and info.dhash, "image inspector returns dimensions and a dHash")
    ctx = Ctx(conn, "rev_doc_test", "social", "in-house", 0, ws=ws)
    found = images.check_image(ctx, raw, "", "ast_social", "social_launch.png")
    categories = {f["category"] for f in found}
    expect("logo_outdated" in categories, f"retired logo is found ({sorted(categories)})")
    expect("missing_alt_text" in categories, "missing alt text is found")
    expect(all(f["locator"].get("kind") == "image" for f in found), "every image finding carries an image locator")
    expect(any(f["locator"].get("bbox") for f in found), "visual findings carry a bounding box")

    # ---- stamping round-trips all three formats without touching pixels ----
    envelope = {"record": {"kind": "ProofOfCompliance/3", "content_sha256": "a" * 64},
                "signature": "b" * 128, "public_key_fingerprint": "fp", "verify_url": "https://example/verify/poc_x"}
    jpeg_buf = io.BytesIO()
    images._open(raw).convert("RGB").save(jpeg_buf, format="JPEG", quality=88)
    for name, data, kind in (("pdf", pdf, "pdf"), ("png", raw, "png"), ("jpeg", jpeg_buf.getvalue(), "jpeg")):
        stamped = stamping.stamp_file(data, envelope, kind)
        expect(stamped != data, f"{name}: stamping changes the bytes")
        recovered = stamping.extract_record(stamped)
        expect(bool(recovered and recovered.get("record") == envelope["record"]), f"{name}: embedded record round-trips")
        expect(stamping.sha256(stamped) != stamping.sha256(data), f"{name}: stamped copy has its own hash")
    print()
finally:
    conn.close()

if failures:
    print(f"{len(failures)} DOCUMENT CHECK(S) FAILED")
    sys.exit(1)
print("ALL DOCUMENT CHECKS PASSED")
