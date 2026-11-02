"""Text inside images: what it says, where it is, and whether people can read it.

Tesseract (a CLI, installed in the Docker image) reads the words. It reads a
prepared copy of the image: each pixel's colour distance from its local
background, so faint grey-on-indigo text, the text a contrast check exists for,
comes out as solid black. Contrast is then measured on the ORIGINAL pixels of
each line. Without Tesseract every function returns None and the image checks
that do not need text still run.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

OCR_MAX_SIDE = 2000      # larger images are read at this size; boxes are scaled back
MIN_CONFIDENCE = 55      # Tesseract word confidence (0-100) below which a word is noise
BACKGROUND_WINDOW = 51   # median-blur window that estimates the local background
FULL_INK_DELTA = 20.0    # Lab distance from the background drawn as solid black
LARGE_TEXT_PX = 32       # cap height treated as WCAG "large text" (3:1 instead of 4.5:1)


def tesseract_path() -> Optional[str]:
    path = os.environ.get("CANONRY_TESSERACT") or shutil.which("tesseract")
    if not path and os.name == "nt":
        guess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        path = guess if os.path.exists(guess) else None
    return path


def available() -> bool:
    return tesseract_path() is not None


def _prepared(img: Image.Image) -> Tuple[bytes, float]:
    """PNG bytes Tesseract reads best, and the factor that maps its boxes back."""
    import cv2
    import numpy as np

    rgb = img if img.mode == "RGB" else img.convert("RGB")  # no full-size copy of an RGB image
    scale = min(1.0, OCR_MAX_SIDE / max(rgb.width, rgb.height))
    if scale < 1.0:
        rgb = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))))
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    window = BACKGROUND_WINDOW if min(bgr.shape[:2]) > BACKGROUND_WINDOW * 2 else 5
    background = cv2.medianBlur(bgr, window)
    # the same distance as np.linalg.norm(lab - lab_bg), computed in strips of rows so a large image
    # never holds two full-size float colour copies at once (per-pixel, so the result is identical)
    distance = np.empty(bgr.shape[:2], dtype=np.float32)
    for top in range(0, bgr.shape[0], 256):
        rows = slice(top, top + 256)
        lab = cv2.cvtColor(bgr[rows], cv2.COLOR_BGR2LAB).astype(np.float32)
        lab -= cv2.cvtColor(background[rows], cv2.COLOR_BGR2LAB).astype(np.float32)
        np.square(lab, out=lab)
        distance[rows] = np.sqrt(lab.sum(axis=2))
    del background
    ink = 255 - np.clip(distance * 255.0 / FULL_INK_DELTA, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", ink)
    if not ok:
        raise ValueError("could not encode the OCR image")
    return buf.tobytes(), scale


def words(img: Image.Image, timeout: float = 40.0) -> Optional[List[Dict[str, Any]]]:
    """Words with their boxes (original-image pixels); None when OCR is unavailable."""
    exe = tesseract_path()
    if not exe:
        return None
    try:
        data, scale = _prepared(img)
        proc = subprocess.run([exe, "stdin", "stdout", "--psm", "11", "tsv"], input=data,
                              capture_output=True, timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf < MIN_CONFIDENCE:
            continue
        left, top, width, height = (int(int(v) / scale) for v in cols[6:10])
        out.append({"text": cols[11].strip(), "key": (int(cols[2]), int(cols[3]), int(cols[4])),
                    "box": (left, top, width, height)})
    return out


def _word_contrast(img: Image.Image, box: Tuple[int, int, int, int]) -> Optional[float]:
    """Contrast between a word's two main colours (its ink and its background)."""
    left, top, width, height = box
    if width < 3 or height < 3:
        return None
    pad = max(2, height // 4)
    import numpy as np

    # crop first: converting the whole image for every word held a full copy per word in memory
    crop = img.crop((max(0, left - pad), max(0, top - pad),
                     min(img.width, left + width + pad), min(img.height, top + height + pad))).convert("RGB")
    colours = crop.getcolors(crop.width * crop.height) or []
    if len(colours) < 2:
        return None
    background = max(colours)[1]  # the most common colour around the word
    px = np.asarray(crop, dtype=np.float64).reshape(-1, 3) / 255.0
    lin = np.where(px <= 0.04045, px / 12.92, ((px + 0.055) / 1.055) ** 2.4)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    bg = _luminance(background)
    ratio = (np.maximum(lum, bg) + 0.05) / (np.minimum(lum, bg) + 0.05)
    ink = ratio[ratio > 1.1]
    if ink.size < 6:
        return None
    # the solid strokes, not the anti-aliased edges that blend into the background
    return float(np.percentile(ink, 90))


def _luminance(rgb) -> float:
    def lin(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def read(img: Image.Image, found: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Lines of text in reading order, each with its box and contrast:
    {"lines": [{"text", "bbox": [x, y, w, h], "ratio", "needs"}]}. None = OCR unavailable.
    `found` lets tests supply the words instead of running Tesseract."""
    found = words(img) if found is None else found
    if found is None:
        return None
    grouped: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
    for w in found:
        grouped.setdefault(tuple(w["key"]), []).append(w)
    lines = []
    for key in sorted(grouped, key=lambda k: (min(w["box"][1] for w in grouped[k]), k)):
        ws = sorted(grouped[key], key=lambda w: w["box"][0])
        text = " ".join(w["text"] for w in ws)
        x0 = min(w["box"][0] for w in ws)
        y0 = min(w["box"][1] for w in ws)
        x1 = max(w["box"][0] + w["box"][2] for w in ws)
        y1 = max(w["box"][1] + w["box"][3] for w in ws)
        ratios = [r for w in ws if (r := _word_contrast(img, tuple(w["box"]))) is not None]
        ratio = round(sorted(ratios)[len(ratios) // 2], 2) if ratios else None  # the line's typical word
        needs = 3.0 if max(w["box"][3] for w in ws) >= LARGE_TEXT_PX else 4.5
        lines.append({"text": text, "bbox": [x0, y0, x1 - x0, y1 - y0], "ratio": ratio, "needs": needs})
    return {"lines": lines}


def read_bytes(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001 - an unreadable image is reported by the image checks
        return None
    return read(img)
