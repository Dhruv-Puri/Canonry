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

import logos
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


ALT_REGION = "alt text"
IMAGE_TEXT_REGION = "text in image"


def image_text(alt_text: Optional[str], ocr_result: Optional[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """The text an image's checks read: its alt text, then each line read from the
    pixels; and a locator map so a finding can point at the alt text or at the
    box of the line on the image."""
    alt = (alt_text or "").strip()
    parts: List[str] = []
    blocks: List[Dict[str, Any]] = []
    at = 0
    if alt:
        parts.append(alt)
        blocks.append({"start": 0, "end": len(alt), "region": ALT_REGION})
        at = len(alt)
    lines = [ln for ln in (ocr_result or {}).get("lines") or [] if (ln.get("text") or "").strip()]
    for i, line in enumerate(lines):
        sep = ("\n\n" if i == 0 else "\n") if parts else ""
        at += len(sep)
        parts.append(sep + line["text"])
        blocks.append({"start": at, "end": at + len(line["text"]), "region": IMAGE_TEXT_REGION,
                       "line": i + 1, "bbox": list(line["bbox"])})
        at += len(line["text"])
    return "".join(parts), blocks


def locate(locator_map: List[Dict[str, Any]], start: int, end: int,
           asset_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    for block in locator_map or []:
        if block["start"] <= start <= block["end"]:
            loc: Dict[str, Any] = {"kind": "image", "asset_id": asset_id, "region": block["region"],
                                   "char_start": start - block["start"],
                                   "char_end": max(start - block["start"], end - block["start"])}
            if block.get("bbox"):
                loc["bbox"] = list(block["bbox"])
                loc["line"] = block["line"]
            return loc
    return None


def in_image_text(locator_map: List[Dict[str, Any]], start: Optional[int]) -> bool:
    """True when a character offset falls in words read from the pixels."""
    if start is None:
        return False
    loc = locate(locator_map, start, start)
    return bool(loc and loc["region"] == IMAGE_TEXT_REGION)


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


def _logo_templates(ctx) -> List["logos.Template"]:
    rows = ctx.conn.execute(
        "SELECT l.*, d.bytes FROM brand_logos l LEFT JOIN asset_data d ON d.asset_id = l.asset_id "
        "WHERE l.workspace_id = ? AND l.active = 1", (ctx.ws,)).fetchall()
    out = []
    for row in rows:
        if not row["bytes"]:
            continue
        try:
            art = _open(bytes(row["bytes"]))
        except ImageError:
            continue
        out.append(logos.Template(row["id"], row["name"], row["variant"], art.convert("RGBA"),
                                  row["min_width_ratio"] or 0.12, row["clear_space_ratio"] or 0.15))
    return out


ASPECT_TOLERANCE = 0.06   # a logo more than 6% wider or taller than approved is distorted
TILT_TOLERANCE = 3.0      # degrees
RECOLOUR_DELTA = 20.0     # mean ΔE of the logo's ink against the approved artwork
BUSY_BACKGROUND = 0.08    # share of the area behind the logo that is not plain
CLEAR_SPACE_CLUTTER = 0.03


def _logo_findings(ctx, flat: Image.Image, templates, logo_rule: Optional[str], use_rule: Optional[str],
                   asset_id: str, graphic: bool) -> List[Dict[str, Any]]:
    """Version, size and clear space cite the logo rule; distortion, colour and
    background cite the logo-use rule (Quillmark: BRD-02)."""
    out: List[Dict[str, Any]] = []
    match = logos.find(flat, templates)
    loc = {"kind": "image", "asset_id": asset_id, "region": "logo"}
    if match is None:
        if graphic and logo_rule:
            out.append(_finding(
                ctx, "image", "logo_missing", logo_rule, "consider", "low",
                "No approved logo was found in this designed image. If it is meant to carry the brand, add the "
                "current logo from the brand kit.", "No approved logo found", loc,
                suggestion={"replace": "Add the current logo from the brand kit.", "operation": "upload"}))
        return out
    tpl, bbox = match.template, match.bbox
    if tpl.variant != "current":
        if logo_rule:
            out.append(_finding(
                ctx, "image", "logo_outdated", logo_rule, "definite", "high",
                f"This is the retired logo “{tpl.name}”. Use the current approved logo.",
                "Old logo version", loc, bbox=bbox,
                suggestion={"replace": "Replace with the current logo from the brand kit.", "operation": "upload"}))
        return out  # judging how a retired logo is placed would only add noise
    if logo_rule:
        share = match.width / max(flat.width, 1)
        if share < tpl.min_width_ratio:
            out.append(_finding(
                ctx, "image", "logo_too_small", logo_rule, "likely", "medium",
                f"The logo is {round(match.width)} px wide, {share:.0%} of the image; the brand kit asks for at "
                f"least {tpl.min_width_ratio:.0%} ({round(tpl.min_width_ratio * flat.width)} px here).",
                "Logo too small", loc, bbox=bbox,
                suggestion={"replace": "Enlarge the logo or use a wider lock-up.", "operation": "rewrite"}))
        crowded = match.clear_space_clutter > CLEAR_SPACE_CLUTTER
        if crowded or match.edge_margin < match.clear_space_px:
            why = (f"other content takes up {match.clear_space_clutter:.0%} of the clear space around it"
                   if crowded else f"it sits {match.edge_margin} px from the edge of the image")
            out.append(_finding(
                ctx, "image", "logo_clear_space", logo_rule, "likely", "low",
                f"The logo needs {match.clear_space_px} px of clear space on every side "
                f"({tpl.clear_space_ratio:.0%} of its height), but {why}.",
                "Logo needs clear space", loc, bbox=bbox,
                suggestion={"replace": "Move other elements, or the logo, to free the clear space.",
                            "operation": "rewrite"}))
    if use_rule:
        change = match.aspect_change - 1.0
        if abs(change) > ASPECT_TOLERANCE or abs(match.rotation) > TILT_TOLERANCE:
            parts = []
            if abs(change) > ASPECT_TOLERANCE:
                parts.append(f"stretched {abs(change):.0%} {'wider' if change > 0 else 'narrower'} than approved"
                             if change > 0 else f"squashed {abs(change):.0%} narrower than approved")
            if abs(match.rotation) > TILT_TOLERANCE:
                parts.append(f"tilted {abs(match.rotation):.0f}°")
            out.append(_finding(
                ctx, "image", "logo_distorted", use_rule, "definite", "medium",
                f"The logo is {' and '.join(parts)} (rule {use_rule}). Scale it evenly and keep it level.",
                "Logo is distorted", loc, bbox=bbox,
                suggestion={"replace": "Place the logo from the brand kit at its original proportions.",
                            "operation": "upload"}))
        if match.colour_delta > RECOLOUR_DELTA:
            out.append(_finding(
                ctx, "image", "logo_recoloured", use_rule, "likely", "medium",
                f"The logo's colours differ from the approved artwork (average ΔE {match.colour_delta:.0f}; "
                f"rule {use_rule}). Use the logo file from the brand kit without recolouring it.",
                "Logo is recoloured", loc, bbox=bbox,
                suggestion={"replace": "Use the approved logo file without changing its colours.",
                            "operation": "upload"}))
        if match.background_clutter > BUSY_BACKGROUND:
            out.append(_finding(
                ctx, "image", "logo_busy_background", use_rule, "likely", "medium",
                f"The background behind the logo is busy ({match.background_clutter:.0%} of it is not plain; rule "
                f"{use_rule}), so the mark is hard to read. Place it on a plain brand colour.",
                "Logo on a busy background", loc, bbox=bbox,
                suggestion={"replace": "Put the logo on a plain Paper or brand-colour area.",
                            "operation": "rewrite"}))
    return out


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
                filename: str = "", ocr_result: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return image/accessibility findings. Any rule that is unbound switches its check off."""
    img = _open(data)
    flat = _flatten(img)
    info = inspect(data)
    out: List[Dict[str, Any]] = []
    logo_rule = ctx.rule("brand.logo")
    logo_use_rule = ctx.rule("brand.logo_use")
    colour_rule = ctx.rule("brand.colour")
    contrast_rule = ctx.rule("accessibility.contrast")
    alt_rule = ctx.rule("accessibility.alt_text")

    templates = _logo_templates(ctx) if (logo_rule or logo_use_rule) else []
    if templates:
        out += _logo_findings(ctx, flat, templates, logo_rule, logo_use_rule, asset_id, info.graphic)

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

    lines = [ln for ln in (ocr_result or {}).get("lines") or [] if ln.get("ratio") is not None]
    if contrast_rule and lines:
        # measured on the words actually read: each line's ink against its background
        for line in lines:
            if line["ratio"] >= line["needs"]:
                continue
            kind = "large text" if line["needs"] == 3.0 else "normal text"
            out.append(_finding(
                ctx, "accessibility", "low_text_contrast", contrast_rule, "likely", "medium",
                f"“{line['text']}” has a contrast ratio of about {line['ratio']:.1f}:1 against its "
                f"background; WCAG AA asks for {line['needs']:.1f}:1 for {kind}.",
                "Text is hard to read", {"kind": "image", "asset_id": asset_id, "region": IMAGE_TEXT_REGION,
                                         "line": lines.index(line) + 1},
                bbox=line["bbox"],
                suggestion={"replace": "Darken the text or lighten the background; aim for "
                                       f"{line['needs']:.1f}:1 or more.", "operation": "rewrite"},
            ))
    elif contrast_rule and info.graphic and not (ocr_result or {}).get("lines"):
        # no words could be read: only a rough colour-pair estimate, never more than "consider"
        entries = [(_rgb(h), share) for h, share in info.palette if share >= 0.02]
        if len(entries) >= 2:
            darkest = min(entries, key=lambda item: _luminance(item[0]))[0]
            lightest = max(entries, key=lambda item: _luminance(item[0]))[0]
            ratio = contrast_ratio(darkest, lightest)
            if ratio < 3.0:
                out.append(_finding(
                    ctx, "accessibility", "low_text_contrast", contrast_rule, "consider", "low",
                    f"No text could be read in this image, so this is an estimate: its most distant colours are "
                    f"only {ratio:.1f}:1 apart ({_hex(darkest)} and {_hex(lightest)}). If it carries text, "
                    "check it meets 4.5:1 (3:1 for large text).",
                    "Check text contrast", {"kind": "image", "asset_id": asset_id, "region": "text"},
                    bbox=(0, 0, flat.width, flat.height),
                    suggestion={"replace": "Darken the text or lighten the background; aim for 4.5:1.",
                                "operation": "rewrite"},
                ))

    if alt_rule:
        out += _alt_findings(ctx, alt_text, alt_rule, asset_id)
    return out
