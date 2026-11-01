"""Uploaded files: validation, extraction, storage and the brand kit.

Files live in the database (`asset_data`), not on the host disk, so a Render
restart cannot orphan an approval. The same code path works for SQLite (BLOB)
and Postgres (BYTEA).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from typing import Any, Dict, Optional, Tuple

import documents
import images
import ocr
from db import _now

MAX_PDF = 10 * 1024 * 1024
MAX_DOCX = 5 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
KIND_BY_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/png": "png",
    "image/jpeg": "jpeg",
}


class UploadError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def clean_filename(name: str) -> str:
    name = os.path.basename((name or "").strip()) if name else ""
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", name).strip(" .")
    if not name:
        raise UploadError("Give the uploaded file a name.")
    if len(name) > 200:
        raise UploadError("The file name is too long (limit 200 characters).")
    return name


def detect_kind(filename: str, data: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if data.startswith(b"%PDF-"):
        if suffix and suffix != "pdf":
            raise UploadError("The file contents are PDF but the extension is not .pdf.")
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if suffix and suffix not in ("png",):
            raise UploadError("The file contents are PNG but the extension is not .png.")
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        if suffix and suffix not in ("jpg", "jpeg"):
            raise UploadError("The file contents are JPEG but the extension is not .jpg/.jpeg.")
        return "jpeg"
    if data[:2] == b"PK" and b"[Content_Types].xml" in data[:8192]:
        if suffix and suffix != "docx":
            raise UploadError("The file contents are DOCX but the extension is not .docx.")
        return "docx"
    raise UploadError("Choose a PDF, Word (.docx), PNG or JPEG file.", 415)


def validate_size(kind: str, data: bytes) -> None:
    limit = {"pdf": MAX_PDF, "docx": MAX_DOCX, "png": MAX_IMAGE, "jpeg": MAX_IMAGE}.get(kind, MAX_IMAGE)
    if len(data) > limit:
        raise UploadError(f"This file is larger than the {limit // (1024 * 1024)} MB limit.", 413)
    if not data:
        raise UploadError("The uploaded file is empty.")


def inspect_image(data: bytes) -> images.ImageInfo:
    return images.inspect(data)


def create_asset(conn, workspace_id: str, submission_id: Optional[str], filename: str,
                 data: bytes, alt_text: Optional[str], created_by: Optional[str]) -> Dict[str, Any]:
    filename = clean_filename(filename)
    kind = detect_kind(filename, data)
    validate_size(kind, data)
    digest = hashlib.sha256(data).hexdigest()
    width = height = pages = None
    dhash = None
    palette_json = None
    metadata: Dict[str, Any] = {}
    if kind in ("png", "jpeg"):
        info = inspect_image(data)
        width, height, dhash = info.width, info.height, info.dhash
        palette_json = json.dumps(info.palette)
        read = ocr.read_bytes(data)
        metadata = {"graphic": info.graphic, "format": info.fmt,
                    "ocr": read if read is not None else {"unavailable": True, "lines": []}}
        extracted_text, locator_map = images.image_text(alt_text, read)
        source_kind = "image"
    else:
        extracted = documents.extract(filename, data)
        extracted_text = extracted.text
        source_kind = extracted.source_kind
        pages = extracted.page_count
        locator_map = extracted.locator_map
        metadata = extracted.metadata
    asset_id = "ast_" + secrets.token_hex(8)
    mime = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "png": "image/png",
        "jpeg": "image/jpeg",
    }[kind]
    conn.execute(
        "INSERT INTO assets (id, workspace_id, submission_id, kind, filename, mime, size_bytes, sha256, "
        "width, height, page_count, alt_text, dhash, palette_json, metadata_json, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (asset_id, workspace_id, submission_id, kind, filename, mime, len(data), digest,
         width, height, pages, (alt_text or "").strip() or None, dhash, palette_json,
         json.dumps(metadata), created_by, _now()),
    )
    conn.execute("INSERT INTO asset_data (asset_id, bytes) VALUES (?,?)", (asset_id, data))
    return {
        "id": asset_id, "workspace_id": workspace_id, "submission_id": submission_id,
        "kind": kind, "filename": filename, "mime": mime, "size_bytes": len(data),
        "sha256": digest, "width": width, "height": height, "page_count": pages,
        "alt_text": (alt_text or "").strip() or None, "dhash": dhash,
        "extracted_text": extracted_text, "source_kind": source_kind,
        "locator_map": locator_map, "metadata": metadata,
    }


def get_asset(conn, asset_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def asset_bytes(conn, asset_id: str) -> Optional[bytes]:
    row = conn.execute("SELECT bytes FROM asset_data WHERE asset_id = ?", (asset_id,)).fetchone()
    return bytes(row["bytes"]) if row else None


def image_ocr(asset_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The words read from an image at upload (None for documents or old uploads)."""
    try:
        meta = json.loads((asset_row or {}).get("metadata_json") or "{}")
    except (TypeError, ValueError):
        return None
    read = meta.get("ocr")
    return None if not read or read.get("unavailable") else read


def image_revision(asset_row: Dict[str, Any], alt_text: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Checked text and asset dict for a new revision of an image (after an alt-text
    edit): the image's words stay in, so they are still checked."""
    text, locator_map = images.image_text(alt_text, image_ocr(asset_row))
    return text, dict(asset_row, source_kind="image", locator_map=locator_map)


def update_alt_text(conn, asset_id: str, alt_text: str) -> None:
    conn.execute("UPDATE assets SET alt_text = ? WHERE id = ?", ((alt_text or "").strip() or None, asset_id))


def brand_kit(conn, workspace_id: str) -> Dict[str, Any]:
    return {
        "logos": [dict(r) for r in conn.execute(
            "SELECT id, name, variant, width, height, min_width_ratio, clear_space_ratio, active "
            "FROM brand_logos WHERE workspace_id = ? ORDER BY variant, name", (workspace_id,)).fetchall()],
        "colours": [dict(r) for r in conn.execute(
            "SELECT id, name, hex, role, delta_e, active FROM brand_colours WHERE workspace_id = ? "
            "ORDER BY role, name", (workspace_id,)).fetchall()],
    }


def seed_brand_kit(conn, workspace_id: str, data_dir: str) -> int:
    """Seed the demo brand kit once. Logo PNGs and the palette are tiny files."""
    if conn.execute("SELECT 1 FROM brand_colours WHERE workspace_id = ? LIMIT 1", (workspace_id,)).fetchone():
        return 0
    created = 0
    colours = [
        ("Quillmark teal", "#0E7C7B", "primary", 10.0),
        ("Quillmark ink", "#101828", "neutral", 10.0),
        ("Quillmark sand", "#F4EDE5", "neutral", 12.0),
    ]
    for i, (name, value, role, tol) in enumerate(colours, start=1):
        conn.execute(
            "INSERT INTO brand_colours (id, workspace_id, name, hex, role, delta_e, active, created_at) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (f"bc_{i}", workspace_id, name, value, role, tol, _now()),
        )
        created += 1
    for name, variant, filename, width_ratio, clear in (
        ("Quillmark Pulse logo", "current", "quillmark_logo.png", 0.14, 0.15),
        ("Quillmark Insights logo (retired)", "deprecated", "quillmark_logo_old.png", 0.14, 0.15),
    ):
        path = os.path.join(data_dir, "brand", filename)
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        info = images.inspect(raw)
        asset = create_asset(conn, workspace_id, None, filename, raw, None, "system")
        conn.execute(
            "INSERT INTO brand_logos (id, workspace_id, name, variant, asset_id, dhash, width, height, "
            "min_width_ratio, clear_space_ratio, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
            (f"bl_{variant}", workspace_id, name, variant, asset["id"], info.dhash,
             info.width, info.height, width_ratio, clear, _now()),
        )
        created += 1
    return created
