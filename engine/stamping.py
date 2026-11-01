"""Stamp a Proof of Compliance into an approved file's metadata.

PDF: a DocInfo key plus a `canonry-proof.json` attachment (pypdf rewrite).
PNG: an iTXt chunk inserted before IEND (IDAT pixels untouched).
JPEG: an APP1 segment inserted after SOI (compressed scan data untouched).

The embedded object is `{record, signature, public_key_fingerprint, verify_url}`.
The signed record covers the original uploaded bytes; the engine stores the
stamped copy's own hash separately (see signing.verify_file).
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
from typing import Any, Dict, Optional

MAGIC = b"CanonryProof"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _json_bytes(envelope: Dict[str, Any]) -> bytes:
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---- PDF ---------------------------------------------------------------------

def _stamp_pdf(data: bytes, envelope: Dict[str, Any]) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    meta = {str(k): str(v) for k, v in (reader.metadata or {}).items() if v is not None}
    meta["/CanonryProof"] = json.dumps({k: envelope[k] for k in ("verify_url", "public_key_fingerprint") if k in envelope})
    meta["/Producer"] = "Canonry Proof of Compliance"
    writer.add_metadata(meta)
    writer.add_attachment("canonry-proof.json", _json_bytes(envelope))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _extract_pdf(data: bytes) -> Optional[Dict[str, Any]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return None
    try:
        for _name, entries in (reader.attachments or {}).items():
            for entry in entries:
                try:
                    obj = json.loads(bytes(entry).decode("utf-8"))
                    if isinstance(obj, dict) and obj.get("record"):
                        return obj
                except Exception:
                    continue
    except Exception:
        pass
    meta = reader.metadata or {}
    raw = meta.get("/CanonryProof")
    if raw:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("record"):
                return obj
        except Exception:
            pass
    return None


# ---- PNG ---------------------------------------------------------------------

def _png_chunks(data: bytes):
    if not data.startswith(PNG_SIG):
        return
    pos = len(PNG_SIG)
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        start = pos
        pos += 8
        body = data[pos:pos + length]
        pos += length
        crc = data[pos:pos + 4]
        pos += 4
        yield start, ctype, body, crc
        if ctype == b"IEND":
            return


def _itxt(keyword: str, text: str) -> bytes:
    # keyword\0 compression-flag\0 compression-method\0 language\0 translated-keyword\0 text
    payload = keyword.encode("utf-8") + b"\x00" + b"\x00\x00" + b"\x00" + b"\x00" + text.encode("utf-8")
    return struct.pack(">I", len(payload)) + b"iTXt" + payload + struct.pack(">I", zlib.crc32(b"iTXt" + payload) & 0xFFFFFFFF)


def _stamp_png(data: bytes, envelope: Dict[str, Any]) -> bytes:
    insert_at = len(data)
    for start, ctype, _body, _crc in _png_chunks(data):
        if ctype == b"IEND":
            insert_at = start
            break
    return data[:insert_at] + _itxt("CanonryProof", _json_bytes(envelope).decode("utf-8")) + data[insert_at:]


def _extract_png(data: bytes) -> Optional[Dict[str, Any]]:
    for _start, ctype, body, _crc in _png_chunks(data):
        if ctype != b"iTXt" or not body.startswith(MAGIC + b"\x00"):
            continue
        try:
            parts = body.split(b"\x00", 5)
            text = parts[5].decode("utf-8") if len(parts) >= 6 else ""
            obj = json.loads(text)
            if isinstance(obj, dict) and obj.get("record"):
                return obj
        except Exception:
            continue
    return None


# ---- JPEG --------------------------------------------------------------------

def _jpeg_segments(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        return
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        yield pos, marker, length
        if marker == 0xDA:  # start of scan: compressed data follows
            return
        pos += 2 + length


def _strip_jpeg_proof(data: bytes) -> bytes:
    out = bytearray(data[:2])
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            out.extend(data[pos:])
            break
        marker = data[pos + 1]
        if marker == 0xDA:  # keep the scan and everything after it untouched
            out.extend(data[pos:])
            break
        if marker == 0xD9:
            out.extend(data[pos:pos + 2])
            break
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            out.extend(data[pos:pos + 2])
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        body = data[pos + 4:pos + 2 + length]
        if not (marker == 0xE1 and body.startswith(MAGIC + b"\x00")):
            out.extend(data[pos:pos + 2 + length])
        pos += 2 + length
    return bytes(out)


def _stamp_jpeg(data: bytes, envelope: Dict[str, Any]) -> bytes:
    payload = MAGIC + b"\x00" + _json_bytes(envelope)
    if len(payload) > 65000:
        raise ValueError("Proof metadata is too large for a JPEG APP1 segment.")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    clean = _strip_jpeg_proof(data)
    return clean[:2] + segment + clean[2:]


def _extract_jpeg(data: bytes) -> Optional[Dict[str, Any]]:
    for pos, marker, length in _jpeg_segments(data):
        if marker != 0xE1:
            continue
        body = data[pos + 4:pos + 2 + length]
        if not body.startswith(MAGIC + b"\x00"):
            continue
        try:
            obj = json.loads(body[len(MAGIC) + 1:].decode("utf-8"))
            if isinstance(obj, dict) and obj.get("record"):
                return obj
        except Exception:
            continue
    return None


# ---- public helpers ----------------------------------------------------------

def kind_of(data: bytes) -> Optional[str]:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(PNG_SIG):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    return None


def stamp_file(data: bytes, envelope: Dict[str, Any], kind: Optional[str] = None) -> bytes:
    kind = kind or kind_of(data)
    if kind == "pdf":
        return _stamp_pdf(data, envelope)
    if kind == "png":
        return _stamp_png(data, envelope)
    if kind == "jpeg":
        return _stamp_jpeg(data, envelope)
    raise ValueError("Only PDF, PNG and JPEG files can carry a Proof of Compliance stamp.")


def extract_record(data: bytes) -> Optional[Dict[str, Any]]:
    kind = kind_of(data)
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "png":
        return _extract_png(data)
    if kind == "jpeg":
        return _extract_jpeg(data)
    return None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
