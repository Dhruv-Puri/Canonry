"""Document extraction and locators (PDF pages/lines, DOCX paragraphs).

PDFs have real pages and a text layer, so a finding can say "page 2, line 7".
DOCX layout is renderer-dependent; we report the section and paragraph, plus a
page only when the file carries explicit page breaks. Scanned PDFs are rejected
rather than silently analysed with OCR.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree


class DocumentError(ValueError):
    """A readable, user-facing document problem."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Extracted:
    text: str
    source_kind: str
    page_count: Optional[int] = None
    locator_map: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _pdf(data: bytes) -> Extracted:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise DocumentError("PDF support is not installed on this engine.", 503) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError("This file is not a readable PDF.") from exc
    if reader.is_encrypted:
        raise DocumentError("This PDF is password-protected. Upload an unlocked copy.")
    if len(reader.pages) > 20:
        raise DocumentError("PDFs are limited to 20 pages.")
    chunks: List[str] = []
    locator_map: List[Dict[str, Any]] = []
    offset = 0
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            page_text = page.extract_text() or ""
        page_text = page_text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not page_text.strip():
            continue
        start = offset
        lines: List[Dict[str, int]] = []
        line_start = offset
        for line_no, line in enumerate(page_text.split("\n"), start=1):
            lines.append({"start": line_start, "end": line_start + len(line), "line": line_no})
            line_start += len(line) + 1
        chunks.append(page_text)
        locator_map.append({"page": page_no, "start": start, "end": start + len(page_text), "lines": lines})
        offset += len(page_text) + 2  # "\n\n" between pages
    text = "\n\n".join(chunks)
    if not text.strip():
        raise DocumentError("This PDF has no selectable text: it was scanned, or printed to PDF as shapes. "
                            "Upload the original file (Word, or a PDF exported from it), or paste the text.")
    if len(text) > 200_000:
        raise DocumentError("The extracted text is too long (limit 200,000 characters).")
    return Extracted(text=text, source_kind="pdf", page_count=len(reader.pages),
                     locator_map=locator_map, metadata={"pages": len(reader.pages)})


def _docx_paragraphs(data: bytes) -> List[Dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 15 * 1024 * 1024:
                raise DocumentError("DOCX document text exceeds the 15 MB extraction limit.", 413)
            if info.file_size > 0 and info.file_size / max(info.compress_size, 1) > 100:
                raise DocumentError("This DOCX has an unsafe compression ratio.", 413)
            xml = archive.read(info)
        root = ElementTree.fromstring(xml)
    except DocumentError:
        raise
    except (KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DocumentError("This file is not a readable DOCX document.") from exc
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = root.find("w:body", ns)
    if body is None:
        raise DocumentError("This DOCX has no document body.")
    paragraphs: List[Dict[str, Any]] = []
    section = ""
    page = 1
    saw_break = False
    # Iterate body children so tables and explicit page breaks are preserved in order.
    for node in body:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "p":
            texts: List[str] = []
            for p in [node] + node.findall(".//w:p", ns):
                if p is not node and p in paragraphs:
                    continue
                for t in p.findall(".//w:t", ns):
                    texts.append(t.text or "")
            text = "".join(texts).strip()
            style = node.find("./w:pPr/w:pStyle", ns)
            style_name = ""
            if style is not None:
                style_name = style.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
            if re.match(r"(?i)(heading|title)", style_name or "") and text:
                section = text[:120]
            if text:
                paragraphs.append({"text": text, "style": style_name, "section": section,
                                   "page": page if saw_break else None})
            if node.findall(".//w:br[@w:type='page']", ns) or node.findall(".//w:lastRenderedPageBreak", ns):
                page += 1
                saw_break = True
        elif tag == "tbl":
            for p in node.findall(".//w:p", ns):
                text = "".join(t.text or "" for t in p.findall(".//w:t", ns)).strip()
                if text:
                    paragraphs.append({"text": text, "style": "Table", "section": section,
                                       "page": page if saw_break else None})
    return paragraphs


MAX_DOCX_INFLATED = 60 * 1024 * 1024   # every part of the package together, uncompressed
MAX_DOCX_RATIO = 100                   # a part that inflates more than this is a zip bomb


def check_package(data: bytes) -> None:
    """Refuse a .docx that would exhaust memory when fixed or stamped later, or
    that lacks the parts every Word file has."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = {i.filename for i in infos}
            total = 0
            for info in infos:
                total += info.file_size
                if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > MAX_DOCX_RATIO:
                    raise DocumentError("This Word file has an unsafe compression ratio.", 413)
            if total > MAX_DOCX_INFLATED:
                raise DocumentError("This Word file is too large once unpacked (over 60 MB).", 413)
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentError("This is not a complete Word document. Save it again from Word and retry.")
            ElementTree.fromstring(archive.read("[Content_Types].xml"))
    except DocumentError:
        raise
    except (zipfile.BadZipFile, RuntimeError, ElementTree.ParseError, KeyError) as exc:
        raise DocumentError("This file is not a readable DOCX document.") from exc


def _docx(data: bytes) -> Extracted:
    check_package(data)
    paragraphs = _docx_paragraphs(data)
    if not paragraphs:
        raise DocumentError("This DOCX contains no readable paragraphs.")
    chunks: List[str] = []
    locator_map: List[Dict[str, Any]] = []
    offset = 0
    for index, para in enumerate(paragraphs, start=1):
        text = para["text"]
        chunks.append(text)
        locator_map.append({
            "paragraph": index, "section": para.get("section") or None,
            "page": para.get("page"), "start": offset, "end": offset + len(text),
            "lines": [{"start": offset, "end": offset + len(text), "line": 1}],
        })
        offset += len(text) + 2
    text = "\n\n".join(chunks)
    if len(text) > 200_000:
        raise DocumentError("The extracted text is too long (limit 200,000 characters).")
    return Extracted(text=text, source_kind="docx", page_count=None,
                     locator_map=locator_map, metadata={"paragraphs": len(paragraphs)})


def extract(filename: str, data: bytes) -> Extracted:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf" or data[:5] == b"%PDF-":
        return _pdf(data)
    if suffix == "docx" or (data[:2] == b"PK" and b"[Content_Types].xml" in data[:4096]):
        return _docx(data)
    raise DocumentError("Choose a PDF (.pdf) or Word (.docx) document.", 415)


def locate(locator_map: List[Dict[str, Any]], start: int, end: int,
           kind: str = "pdf", asset_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Map a character range in the extracted text to page/line or paragraph."""
    if not locator_map:
        return None
    block = None
    for candidate in locator_map:
        if candidate["start"] <= start <= candidate["end"]:
            block = candidate
            break
    if block is None:
        return None
    line = 1
    for candidate in block.get("lines") or []:
        if candidate["start"] <= start <= candidate["end"]:
            line = candidate["line"]
            break
    loc: Dict[str, Any] = {"kind": kind, "asset_id": asset_id,
                           "char_start": start - block["start"],
                           "char_end": max(start - block["start"], end - block["start"])}
    if kind == "pdf":
        loc["page"] = block.get("page")
        loc["line"] = line
    else:
        loc["paragraph"] = block.get("paragraph")
        loc["section"] = block.get("section")
        if block.get("page"):
            loc["page"] = block.get("page")
        loc["line"] = line
    return loc


def describe(locator: Optional[Dict[str, Any]]) -> str:
    if not locator:
        return ""
    kind = locator.get("kind")
    if kind == "image":
        region = (locator.get("region") or "region").replace("_", " ")
        return f"image · {region}"
    if kind == "pdf":
        page, line = locator.get("page"), locator.get("line")
        return f"page {page}" + (f" · line {line}" if line else "")
    if kind == "docx":
        bits = []
        if locator.get("section"):
            bits.append(str(locator["section"])[:32])
        bits.append(f"paragraph {locator.get('paragraph')}")
        if locator.get("page"):
            bits.append(f"page {locator['page']}")
        return " · ".join(bits)
    return ""


# ---- fixing a Word file in place ---------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _paragraph_runs(body) -> List[Tuple[List[Any], bool]]:
    """The w:t nodes behind each extracted paragraph, in exactly the order
    _docx_paragraphs reads them, and whether that paragraph can be edited
    (a paragraph holding a text box repeats the box's words, so it cannot)."""
    out: List[Tuple[List[Any], bool]] = []
    for node in body:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "p":
            nested = node.findall(f".//{_W}p")
            nodes: List[Any] = list(node.iter(f"{_W}t"))
            for p in nested:
                nodes += list(p.iter(f"{_W}t"))
            if "".join(t.text or "" for t in nodes).strip():
                out.append((nodes, not nested))
        elif tag == "tbl":
            for p in node.iter(f"{_W}p"):
                nodes = list(p.iter(f"{_W}t"))
                if "".join(t.text or "" for t in nodes).strip():
                    out.append((nodes, not p.findall(f".//{_W}p")))
    return out


def _replace_in_runs(nodes: List[Any], new_text: str) -> None:
    """Change the paragraph's words to new_text by editing only the characters
    that differ, inside the runs that hold them: formatting around a fix stays."""
    full = "".join(t.text or "" for t in nodes)
    lead = len(full) - len(full.lstrip())
    old = full.strip()
    p = 0
    while p < min(len(old), len(new_text)) and old[p] == new_text[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new_text)) - p and old[len(old) - 1 - s] == new_text[len(new_text) - 1 - s]:
        s += 1
    start, end = lead + p, lead + len(old) - s
    insert = new_text[p:len(new_text) - s]
    at = 0
    placed = False
    for t in nodes:
        text = t.text or ""
        lo, hi = at, at + len(text)
        at = hi
        if hi < start or lo > end or (hi == start and start != end) or (lo == end and start != end and placed):
            continue
        a, b = max(start, lo) - lo, min(end, hi) - lo
        if not placed:
            t.text = text[:a] + insert + text[b:]
            placed = True
        else:
            t.text = text[:a] + text[b:]
        t.set(_XML_SPACE, "preserve")
    if not placed and nodes:
        nodes[-1].text = (nodes[-1].text or "") + insert
        nodes[-1].set(_XML_SPACE, "preserve")


def docx_with_text(data: bytes, content: str) -> bytes:
    """The original .docx with its paragraphs changed to read `content` (the
    fixed revision). Paragraph count must not change; text boxes are not edited."""
    from lxml import etree

    check_package(data)
    try:
        return _docx_with_text(etree, data, content)
    except DocumentError:
        raise
    except (etree.XMLSyntaxError, KeyError, zipfile.BadZipFile, ValueError) as exc:
        raise DocumentError("This Word file could not be edited. Fix it in Word and upload it again.", 409) from exc


def _docx_with_text(etree, data: bytes, content: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = etree.fromstring(xml, parser)
        body = root.find(f"{_W}body")
        if body is None:
            raise DocumentError("This DOCX has no document body.")
        paragraphs = _paragraph_runs(body)
        new = content.split("\n\n")
        if len(new) != len(paragraphs):
            raise DocumentError("This change adds or removes a paragraph, which cannot be made inside the Word "
                                "file. Edit the document and upload it again.", 409)
        for (nodes, editable), wanted in zip(paragraphs, new):
            current = "".join(t.text or "" for t in nodes).strip()
            if current == wanted.strip():
                continue
            if not editable:
                raise DocumentError("This text is in a text box, which Canonry cannot edit. Fix it in Word and "
                                    "upload the document again.", 409)
            _replace_in_runs(nodes, wanted.strip())
        fixed = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in archive.infolist():
                dst.writestr(info, fixed if info.filename == "word/document.xml" else archive.read(info))
    return out.getvalue()
