"""Deterministic image checks: logo use, brand palette, WCAG contrast, alt text.

No OCR and no model downloads. The checks target the flat, designed images a
social or web team actually publishes; photographs are recognised and the
palette/contrast checks stay quiet rather than guessing. Every finding cites a
workspace rule, and contrast is a judgement tier, never a blocking "definite".
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageOps, ImageStat

from db import gen_id

Image.MAX_IMAGE_PIXELS = 40_000_000
ANALYSIS_MAX = 512
NEUTRAL_SPREAD = 28


class ImageError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class ImageInfo:
    width: int
    height: int
    fmt: str
    palette: List[Tuple[str, float]]
    graphic: bool
    dhash: str


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ImageError("This file is not a readable PNG or JPEG image.") from exc
    if img.width > 4096 or img.height > 4096:
        raise ImageError("Images are limited to 4096 × 4096 pixels.", 413)
    if img.width < 32 or img.height < 32:
        raise ImageError("This image is too small to check (minimum 32 × 32).")
    return img


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, img).convert("RGB")
    return img.convert("RGB")


def dhash(img: Image.Image, size: int = 8) -> str:
    img = _flatten(img).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(img.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 999


def _hex(rgb: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(c))):02X}" for c in rgb[:3])


def _rgb(value: str) -> Tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(rgb: Sequence[int]) -> float:
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(int(x)) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: Sequence[int], b: Sequence[int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _lab(rgb: Sequence[int]) -> Tuple[float, float, float]:
    def lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(int(x)) for x in rgb[:3])
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.00000
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e_2000(a: Sequence[int], b: Sequence[int]) -> float:
    """CIEDE2000, the colour difference a designer would recognise."""
    l1, a1, b1 = _lab(a)
    l2, a2, b2 = _lab(b)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7))) if cbar else 0
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1, cp2 = math.hypot(ap1, b1), math.hypot(ap2, b2)
    hp1 = math.degrees(math.atan2(b1, ap1)) % 360 if cp1 else 0
    hp2 = math.degrees(math.atan2(b2, ap2)) % 360 if cp2 else 0
    dl, dc = l2 - l1, cp2 - cp1
    if cp1 * cp2 == 0:
        dh = 0
    elif abs(hp2 - hp1) <= 180:
        dh = hp2 - hp1
    elif hp2 <= hp1:
        dh = hp2 - hp1 + 360
    else:
        dh = hp2 - hp1 - 360
    dH = 2 * math.sqrt(cp1 * cp2) * math.sin(math.radians(dh / 2))
    lbar, cbarp = (l1 + l2) / 2, (cp1 + cp2) / 2
    if cp1 * cp2 == 0:
        hbar = hp1 + hp2
    elif abs(hp1 - hp2) <= 180:
        hbar = (hp1 + hp2) / 2
    elif hp1 + hp2 < 360:
        hbar = (hp1 + hp2 + 360) / 2
    else:
        hbar = (hp1 + hp2 - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbar - 30)) + 0.24 * math.cos(math.radians(2 * hbar))
         + 0.32 * math.cos(math.radians(3 * hbar + 6)) - 0.20 * math.cos(math.radians(4 * hbar - 63)))
    sl = 1 + (0.015 * (lbar - 50) ** 2) / math.sqrt(20 + (lbar - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -2 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25 ** 7)) * math.sin(
        math.radians(60 * math.exp(-(((hbar - 275) / 25) ** 2)))
    ) if cbarp else 0
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh))


def palette(img: Image.Image, colors: int = 16) -> List[Tuple[str, float]]:
    small = _flatten(img).resize((min(256, img.width), min(256, img.height)))
    q = small.quantize(colors=colors)
    counts = q.getcolors(maxcolors=colors * 4) or []
    total = sum(c for c, _ in counts) or 1
    out = []
    for count, idx in sorted(counts, reverse=True):
        rgb = q.getpalette()[idx * 3:idx * 3 + 3]
        if len(rgb) == 3:
            out.append((_hex(rgb), count / total))
    return out


def inspect(data: bytes) -> ImageInfo:
    img = _open(data)
    fmt = (img.format or "PNG").lower()
    pal = palette(img)
    # Photographs have many colours; designed graphics have a small palette.
    color_count = len(_flatten(img).resize((160, 160)).getcolors(maxcolors=4096) or [])
    top_coverage = sum(share for _hex_value, share in pal[:8])
    return ImageInfo(width=img.width, height=img.height, fmt=fmt, palette=pal,
                     graphic=color_count <= 256 or top_coverage >= 0.90, dhash=dhash(img))


def _finding(ctx, checker: str, category: str, rule: str, tier: str, severity: str,
             explanation: str, title: str, locator: Dict[str, Any], bbox=None,
             suggestion: Optional[Dict[str, Any]] = None, span_text: str = "") -> Dict[str, Any]:
    span = {"start": 0, "end": len(span_text), "text": span_text}
    loc = dict(locator)
    if bbox:
        loc["bbox"] = tuple(int(v) for v in bbox)
    return {
        "id": gen_id("fnd"), "revision_id": ctx.revision_id, "checker": checker,
        "category": category, "span": span, "tier": tier, "severity": severity,
        "citations": [{"type": "rule", "id": rule}], "explanation": explanation,
        "suggestion": suggestion, "title": title,
        "provenance": {"model": None, "prompt_version": "image@1", "knowledge_version": ctx.kv},
        "locator": loc,
        "location_key": f"{checker}|{category}|{loc.get('region') or 'region'}:{','.join(map(str, loc.get('bbox') or []))}",
    }


def _logo_templates(ctx) -> List[Dict[str, Any]]:
    rows = ctx.conn.execute(
        "SELECT l.*, d.bytes FROM brand_logos l LEFT JOIN asset_data d ON d.asset_id = l.asset_id "
        "WHERE l.workspace_id = ? AND l.active = 1", (ctx.ws,)).fetchall()
    out = []
    for row in rows:
        raw = row["bytes"]
        if not raw:
            continue
        try:
            img = _flatten(_open(bytes(raw)))
        except ImageError:
            continue
        out.append({"id": row["id"], "name": row["name"], "variant": row["variant"],
                    "dhash": row["dhash"] or dhash(img), "width": row["width"] or img.width,
                    "height": row["height"] or img.height,
                    "min_width_ratio": row["min_width_ratio"] or 0.12,
                    "clear_space_ratio": row["clear_space_ratio"] or 0.15,
                    "image": img})
    return out


def _corr(a: Image.Image, b: Image.Image, size=(48, 24)) -> float:
    """Mean per-channel Pearson correlation: discriminative enough to reject text
    that happens to share a coarse dHash with a wordmark."""
    a = _flatten(a).resize(size)
    b = _flatten(b).resize(size)
    pa, pb = list(a.getdata()), list(b.getdata())
    scores = []
    for channel in range(3):
        va = [p[channel] for p in pa]
        vb = [p[channel] for p in pb]
        ma, mb = sum(va) / len(va), sum(vb) / len(vb)
        da = [v - ma for v in va]
        db = [v - mb for v in vb]
        denom = math.sqrt(sum(v * v for v in da) * sum(v * v for v in db))
        scores.append(sum(x * y for x, y in zip(da, db)) / denom if denom else 0.0)
    return sum(scores) / 3


def _rms(a: Image.Image, b: Image.Image) -> float:
    """Fast per-pixel colour RMS (Pillow's C core), the logo match score."""
    a = _flatten(a).resize((64, 32))
    b = _flatten(b).resize((64, 32))
    diff = ImageChops.difference(a, b)
    rms = ImageStat.Stat(diff).rms
    return sum(rms) / 3


def _logo_match(img: Image.Image, templates: List[Dict[str, Any]]):
    """Coarse colour-template scan at several logo widths, then a fine refinement.
    Returns (template, bbox, distance, rms); lower rms is a closer visual match."""
    base = _flatten(img)
    scale = min(1.0, 256 / max(base.width, base.height))
    small = base.resize((max(1, int(base.width * scale)), max(1, int(base.height * scale)))) if scale < 1 else base
    coarse = []
    for tpl in templates:
        aspect = (tpl["width"] / tpl["height"]) if tpl["height"] else 1.0
        for ratio in (0.10, 0.14, 0.18, 0.22, 0.26, 0.28, 0.30, 0.34, 0.38):
            cw = int(small.width * ratio)
            ch = max(8, int(cw / max(aspect, 0.1)))
            if cw < 12 or ch < 8 or cw >= small.width or ch >= small.height:
                continue
            step = max(6, small.width // 32)
            for y in range(0, small.height - ch + 1, step):
                for x in range(0, small.width - cw + 1, step):
                    score = _rms(small.crop((x, y, x + cw, y + ch)), tpl["image"])
                    coarse.append((score, tpl, (x, y, cw, ch)))
    coarse.sort(key=lambda c: c[0])
    best = None
    for score0, tpl, (x, y, cw, ch) in coarse[:12]:
        for dx in (-6, -4, -2, 0, 2, 4, 6):
            for dy in (-6, -4, -2, 0, 2, 4, 6):
                xx, yy = max(0, x + dx), max(0, y + dy)
                if xx + cw > small.width or yy + ch > small.height:
                    continue
                score = _rms(small.crop((xx, yy, xx + cw, yy + ch)), tpl["image"])
                if best is None or score < best[0]:
                    best = (score, tpl, (xx, yy, cw, ch))
    if best and best[0] <= 42:
        score, tpl, (x, y, cw, ch) = best
        if scale < 1:
            x, y, cw, ch = (int(x / scale), int(y / scale), int(cw / scale), int(ch / scale))
        return tpl, (x, y, cw, ch), int(score), score
    return None


def _alt_findings(ctx, alt: Optional[str], rule: str, asset_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    text = (alt or "").strip()
    loc = {"kind": "image", "asset_id": asset_id, "region": "alt text"}
    if not text:
        out.append(_finding(
            ctx, "accessibility", "missing_alt_text", rule, "definite", "medium",
            "This image is published without alt text. Add one sentence describing what a person who cannot see it needs to know.",
            "Missing alt text", loc,
            suggestion={"replace": "Describe the image's message in one sentence.", "operation": "rewrite"},
        ))
        return out
    problems = []
    if len(text) < 8:
        problems.append("is shorter than 8 characters")
    if len(text) > 125:
        problems.append("is longer than 125 characters")
    if re.match(r"(?i)^(image|picture|photo|screenshot)\s+(of|showing)\b", text) or re.match(r"(?i)^(image|picture|photo)\b", text):
        problems.append("starts with 'image of' instead of describing the message")
    words = re.findall(r"[A-Za-z]{3,}", text.lower())
    if words and max(words.count(w) for w in set(words)) > 3:
        problems.append("repeats the same word as keyword stuffing")
    if re.search(r"(?i)\b\.(png|jpe?g|gif)\b", text):
        problems.append("is just a filename")
    if problems:
        out.append(_finding(
            ctx, "accessibility", "alt_text_quality", rule, "likely", "low",
            "Alt text " + "; ".join(problems) + ". Describe the message, not the file.",
            "Alt text needs work", dict(loc, region="alt text"),
            suggestion={"replace": text[:125], "operation": "rewrite"}, span_text=text,
        ))
    return out


def check_image(ctx, data: bytes, alt_text: Optional[str], asset_id: str,
                filename: str = "") -> List[Dict[str, Any]]:
    """Return image/accessibility findings. Any rule that is unbound switches its check off."""
    img = _open(data)
    flat = _flatten(img)
    info = inspect(data)
    out: List[Dict[str, Any]] = []
    logo_rule = ctx.rule("brand.logo")
    colour_rule = ctx.rule("brand.colour")
    contrast_rule = ctx.rule("accessibility.contrast")
    alt_rule = ctx.rule("accessibility.alt_text")

    templates = _logo_templates(ctx) if logo_rule else []
    if templates:
        match = _logo_match(flat, templates)
        if match:
            tpl, bbox, dist, score = match
            x, y, w, h = bbox
            loc = {"kind": "image", "asset_id": asset_id, "region": "logo"}
            if tpl["variant"] != "current":
                out.append(_finding(
                    ctx, "image", "logo_outdated", logo_rule, "definite", "high",
                    f"This looks like the retired logo \"{tpl['name']}\". Use the current approved logo.",
                    "Old logo variant", loc, bbox=bbox,
                    suggestion={"replace": "Replace with the current logo from the brand kit.", "operation": "upload"},
                ))
            else:
                if w / max(flat.width, 1) < (tpl["min_width_ratio"] or 0.12):
                    out.append(_finding(
                        ctx, "image", "logo_too_small", logo_rule, "likely", "medium",
                        f"The logo is {w / flat.width:.0%} of the image width; the brand kit asks for at least "
                        f"{(tpl['min_width_ratio'] or 0.12):.0%}.",
                        "Logo too small", loc, bbox=bbox,
                        suggestion={"replace": "Enlarge the logo or use a wider lock-up.", "operation": "rewrite"},
                    ))
                margin = min(x, y, flat.width - (x + w), flat.height - (y + h))
                required = int((tpl["clear_space_ratio"] or 0.15) * h)
                if margin < required:
                    out.append(_finding(
                        ctx, "image", "logo_clear_space", logo_rule, "likely", "low",
                        f"The logo has {margin}px clear space; the brand kit asks for {required}px "
                        f"({(tpl['clear_space_ratio'] or 0.15):.0%} of its height).",
                        "Logo needs clear space", loc, bbox=bbox,
                        suggestion={"replace": "Move the logo away from the edge or other elements.", "operation": "rewrite"},
                    ))
        elif info.graphic and logo_rule:
            out.append(_finding(
                ctx, "image", "logo_missing", logo_rule, "likely", "medium",
                "No current approved logo was found in this designed image. Add the brand mark or confirm this is a logo-free layout.",
                "No approved logo found", {"kind": "image", "asset_id": asset_id, "region": "logo"},
                bbox=(0, 0, flat.width, flat.height),
                suggestion={"replace": "Add the current logo from the brand kit.", "operation": "upload"},
            ))

    if colour_rule and info.graphic:
        brand = ctx.conn.execute(
            "SELECT name, hex, delta_e FROM brand_colours WHERE workspace_id = ? AND active = 1",
            (ctx.ws,)).fetchall()
        brand_rgb = [(_rgb(row["hex"]), row) for row in brand]
        worst = None
        for hex_value, share in info.palette:
            if share < 0.05:
                continue
            rgb = _rgb(hex_value)
            if max(rgb) - min(rgb) < NEUTRAL_SPREAD:  # neutrals are allowed freely
                continue
            nearest = min(brand_rgb, key=lambda item: delta_e_2000(rgb, item[0])) if brand_rgb else None
            if nearest is None:
                continue
            distance = delta_e_2000(rgb, nearest[0])
            tolerance = nearest[1]["delta_e"] or 10.0
            if distance > tolerance and (worst is None or distance > worst[0]):
                worst = (distance, hex_value, share, nearest[1], tolerance)
        if worst:
            distance, hex_value, share, nearest, tolerance = worst
            out.append(_finding(
                ctx, "image", "off_brand_colour", colour_rule, "likely", "medium",
                f"{hex_value} covers {share:.0%} of the design and is ΔE {distance:.1f} from the nearest approved colour "
                f"({nearest['name']} {nearest['hex']}, tolerance {tolerance:.0f}).",
                "Off-brand colour", {"kind": "image", "asset_id": asset_id, "region": "palette"},
                bbox=(0, 0, flat.width, flat.height),
                suggestion={"replace": f"Use {nearest['name']} ({nearest['hex']}) or another approved colour.",
                            "operation": "rewrite"},
            ))

    if contrast_rule and info.graphic:
        entries = [(_rgb(h), share) for h, share in info.palette if share >= 0.02]
        if len(entries) >= 2:
            darkest = min(entries, key=lambda item: _luminance(item[0]))[0]
            lightest = max(entries, key=lambda item: _luminance(item[0]))[0]
            ratio = contrast_ratio(darkest, lightest)
            if ratio < 3.0:
                out.append(_finding(
                    ctx, "accessibility", "low_text_contrast", contrast_rule, "likely", "medium",
                    f"The strongest colour pair in this graphic is {ratio:.1f}:1 ({_hex(darkest)} on {_hex(lightest)}). "
                    "WCAG asks for at least 4.5:1 for normal text and 3:1 for large text.",
                    "Low text contrast", {"kind": "image", "asset_id": asset_id, "region": "text"},
                    bbox=(0, 0, flat.width, flat.height),
                    suggestion={"replace": f"Darken the text or lighten the background; aim for 4.5:1.", "operation": "rewrite"},
                ))

    if alt_rule:
        out += _alt_findings(ctx, alt_text, alt_rule, asset_id)
    return out
