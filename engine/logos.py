"""Find the brand's logos in an image and measure how each one is used.

ORB features plus a RANSAC homography locate a logo at any size, including a
stretched, squashed or tilted one: the logo is also matched in pre-stretched
forms, because ORB features alone do not survive a strong one-axis stretch.
The homography gives the logo's true width, its aspect change and its tilt.

A match is then verified on the pixels: the logo's own shapes must be present
where the homography puts them (text set in the same typeface as a wordmark
is not a logo). Which logo it is (current or retired) is decided by shape
first, then colour, so a current logo printed in the wrong colour reads as
"recoloured", not as an old version.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

TEMPLATE_WIDTH = 480          # templates are matched at this width (then stretched)
STRETCHES = (1.0, 0.7, 1.4, 0.5, 2.0)
SCENE_SIDES = (1600, 3200)    # long side the scene is read at; the second pass finds small logos
RATIO_TEST = 0.8
MIN_INLIERS = 12
MIN_SHAPE_RECALL = 0.7        # share of the logo's ink found where the logo should be
INK_DELTA = 15.0              # Lab distance from the background that counts as ink


@dataclass
class Template:
    id: str
    name: str
    variant: str              # "current" or a retired variant
    rgba: Image.Image
    min_width_ratio: float
    clear_space_ratio: float


@dataclass
class Match:
    template: Template
    quad: List[Tuple[float, float]]   # logo corners in the image: TL, TR, BR, BL
    bbox: Tuple[int, int, int, int]   # axis-aligned x, y, w, h
    width: float                      # rendered width along the logo's own top edge
    height: float
    aspect_change: float              # rendered aspect / approved aspect (1.0 = undistorted)
    rotation: float                   # degrees, positive = clockwise
    colour_delta: float               # mean ΔE of the logo's ink against the approved artwork
    background_clutter: float         # share of the area behind the logo that is not plain
    clear_space_clutter: float        # share of the clear-space ring taken by other content
    clear_space_px: int               # clear space the rule asks for
    edge_margin: int                  # distance from the logo to the nearest image edge
    shape_score: float


def _np():
    import cv2
    import numpy as np
    return cv2, np


def _rgb_on_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def _ink_mask(rgba: Image.Image):
    """Where the artwork has ink: its alpha, or (opaque files) pixels unlike the corner colour."""
    cv2, np = _np()
    arr = np.array(rgba.convert("RGBA"))
    alpha = arr[:, :, 3]
    if alpha.min() < 250:
        return alpha > 128
    lab = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    corner = np.median(np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]]), axis=0)
    return np.linalg.norm(lab - corner, axis=2) > INK_DELTA


def _orb():
    cv2, _ = _np()
    return cv2.ORB_create(nfeatures=3000, scaleFactor=1.2, nlevels=10, edgeThreshold=15,
                          patchSize=15, fastThreshold=10)


def _template_features(tpl: Template):
    cv2, np = _np()
    flat = _rgb_on_white(tpl.rgba)
    base = TEMPLATE_WIDTH / flat.width
    out = []
    for sx in STRETCHES:
        size = (max(8, int(flat.width * base * sx)), max(8, int(flat.height * base)))
        gray = cv2.cvtColor(np.array(flat.resize(size, Image.LANCZOS)), cv2.COLOR_RGB2GRAY)
        kp, des = _orb().detectAndCompute(gray, None)
        if des is not None and len(kp) >= MIN_INLIERS:
            out.append((kp, des, base * sx, base))
    return out


def _geometry(quad) -> Tuple[float, float, float, float, float, float]:
    _, np = _np()
    q = np.asarray(quad, dtype=np.float64)
    top, bottom = np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3])
    left, right = np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])
    rotation = math.degrees(math.atan2(q[1][1] - q[0][1], q[1][0] - q[0][0]))
    return top, bottom, left, right, (top + bottom) / 2, rotation


def _plausible(quad, tpl_size) -> Optional[Tuple[float, float, float, float]]:
    """Reject homographies no real placement produces; return width, height, aspect change, tilt."""
    cv2, np = _np()
    q = np.asarray(quad, dtype=np.float32).reshape(-1, 1, 2)
    if not cv2.isContourConvex(q):
        return None
    top, bottom, left, right, width, rotation = _geometry(quad)
    if min(top, bottom, left, right) < 4:
        return None
    if max(top, bottom) / min(top, bottom) > 1.3 or max(left, right) / min(left, right) > 1.3:
        return None  # strong perspective: not how a logo is placed in a flat graphic
    height = (left + right) / 2
    w, h = tpl_size
    aspect = (width / height) / (w / h)
    if not 0.33 < aspect < 3.0:
        return None
    return width, height, aspect, rotation


def _lab(arr):
    cv2, np = _np()
    return cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)


def _compare(scene_rgb, H, tpl: Template, rendered_width: float) -> Tuple[float, float, float]:
    """Warp the image back onto the template: (shape recall, colour ΔE, clutter behind).
    Colour and clutter are read away from the artwork's edges: at small sizes the
    edges blur into the background and would read as a recolour or as clutter."""
    cv2, np = _np()
    w, h = tpl.rgba.size
    warped = cv2.warpPerspective(scene_rgb, np.linalg.inv(H), (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
    ink = _ink_mask(tpl.rgba)
    if ink.sum() < 20 or (~ink).sum() < 20:
        return 0.0, 999.0, 0.0
    band = max(1, int(math.ceil(2.0 * w / max(rendered_width, 1.0))))  # ~2 image pixels, in template pixels
    kernel = np.ones((2 * band + 1, 2 * band + 1), np.uint8)
    core = cv2.erode(ink.astype(np.uint8), kernel).astype(bool)
    clear = ~cv2.dilate(ink.astype(np.uint8), kernel).astype(bool)
    if core.sum() < 20:
        core = ink
    if clear.sum() < 20:
        clear = ~ink
    lab = _lab(warped)
    background = np.median(lab[clear], axis=0)
    distance = np.linalg.norm(lab - background, axis=2)
    recall = float((distance[ink] > INK_DELTA).mean())
    clutter = float((distance[clear] > INK_DELTA).mean())
    art = _lab(np.array(_rgb_on_white(tpl.rgba)))
    colour = float(np.linalg.norm(lab[core] - art[core], axis=1).mean())
    return recall, colour, clutter


def _ring_clutter(scene_rgb, bbox, pad: int) -> Tuple[float, int]:
    """Share of the clear-space ring around the logo that is not plain background,
    and the logo's distance to the nearest image edge."""
    _, np = _np()
    H, W = scene_rgb.shape[:2]
    x, y, w, h = bbox
    margin = int(min(x, y, W - (x + w), H - (y + h)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    if pad <= 0 or x1 <= x0 or y1 <= y0:
        return 0.0, margin
    region = _lab(np.ascontiguousarray(scene_rgb[y0:y1, x0:x1]))
    ring = np.ones(region.shape[:2], dtype=bool)
    ring[max(0, y - y0):max(0, y - y0) + h, max(0, x - x0):max(0, x - x0) + w] = False
    if ring.sum() < 20:
        return 0.0, margin
    background = np.median(region[ring], axis=0)
    distance = np.linalg.norm(region - background, axis=2)
    return float((distance[ring] > INK_DELTA).mean()), margin


def find(img: Image.Image, templates: Sequence[Template]) -> Optional[Match]:
    """The best-verified logo in the image, or None when no logo is there."""
    if not templates:
        return None
    cv2, np = _np()
    scene = np.array(_rgb_on_white(img))
    gray_full = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
    features = [(tpl, _template_features(tpl)) for tpl in templates]
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    for side in SCENE_SIDES:
        up = side / max(gray_full.shape)  # small images are enlarged, huge ones reduced
        gray = cv2.resize(gray_full, None, fx=up, fy=up,
                          interpolation=cv2.INTER_CUBIC if up > 1.0 else cv2.INTER_AREA)
        kps, dess = _orb().detectAndCompute(gray, None)
        if dess is None or len(kps) < MIN_INLIERS:
            continue
        # 1. where is a logo, and how is it placed? (any template's shapes will do)
        placements = []
        for tpl, variants in features:
            w, h = tpl.rgba.size
            for kp, des, bx, by in variants:
                pairs = matcher.knnMatch(des, dess, k=2)
                good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < RATIO_TEST * b.distance]
                if len(good) < MIN_INLIERS:
                    continue
                src = np.float32([kp[m.queryIdx].pt for m in good])
                dst = np.float32([kps[m.trainIdx].pt for m in good])
                H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
                if H is None or int(mask.sum()) < MIN_INLIERS:
                    continue
                # map ORIGINAL template pixels to ORIGINAL image pixels
                Ht = np.diag([1 / up, 1 / up, 1.0]) @ H @ np.diag([bx, by, 1.0])
                corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
                quad = cv2.perspectiveTransform(corners, Ht).reshape(-1, 2)
                geometry = _plausible(quad, (w, h))
                if geometry:
                    placements.append((int(mask.sum()), Ht, quad, geometry, tpl))
        if not placements:
            continue
        placements.sort(key=lambda p: -p[0])
        # 2. the strongest placement whose pixels really show a logo; which logo it
        #    is: the best shape match, then the closest colours
        best = None
        for inliers, Ht, quad, (width, height, aspect, rotation), found_with in placements[:6]:
            for tpl in templates:
                tw, th = tpl.rgba.size
                fw, fh = found_with.rgba.size
                H = Ht if (tw, th) == (fw, fh) else Ht @ np.diag([fw / tw, fh / th, 1.0])
                recall, colour, clutter = _compare(scene, H, tpl, width)
                if recall < MIN_SHAPE_RECALL:
                    continue
                key = (round(recall, 2), -colour)
                if best is None or key > best[0]:
                    best = (key, tpl, quad, width, height, aspect, rotation, colour, clutter, recall)
            if best is not None:
                break
        if best is None:
            continue
        _, tpl, quad, width, height, aspect, rotation, colour, clutter, recall = best
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))
        bbox = (x0, y0, int(max(xs)) - x0, int(max(ys)) - y0)
        pad = int(round((tpl.clear_space_ratio or 0.15) * height))
        ring, margin = _ring_clutter(scene, bbox, pad)
        return Match(template=tpl, quad=[(float(a), float(b)) for a, b in quad], bbox=bbox, width=float(width),
                     height=float(height), aspect_change=float(aspect), rotation=float(rotation),
                     colour_delta=float(colour), background_clutter=float(clutter), clear_space_clutter=ring,
                     clear_space_px=pad, edge_margin=margin, shape_score=float(recall))
    return None


def describe(m: Optional[Match]) -> Optional[Dict[str, Any]]:
    if not m:
        return None
    return {"logo": m.template.name, "variant": m.template.variant, "bbox": list(m.bbox),
            "width": round(m.width), "aspect_change": round(m.aspect_change, 3), "rotation": round(m.rotation, 1),
            "colour_delta": round(m.colour_delta, 1), "background_clutter": round(m.background_clutter, 3),
            "clear_space_clutter": round(m.clear_space_clutter, 3)}
