"""Lightweight audio and video verification (stdlib only, no media libraries).

What the engine can actually verify about a media file without OCR of frames or
a speech-to-text service:

* Containers are validated by their structural signature, so a renamed file or
  a truncated recording is refused, not guessed at.
* The real duration (sample accurate for WAV, an honest labelled estimate for
  MP3 CBR) and, where the container says it, the video dimensions are read
  straight from the headers.
* Transcript linkage: a published audio or video asset must come with the words
  it plays — a missing transcript is a finding, and when one is supplied the
  regular claim pipeline verifies the spoken copy against the Fact Library.

Everything is pure Python: `wave` for WAV, byte parsing for MP3 frames, box
walking for MP4/MOV/M4A and EBML parsing for WebM. No Pillow, no ffmpeg.
"""
from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from db import gen_id

MAX_SECONDS = 15 * 60  # long-form media is out of scope this round


class MediaError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class MediaInfo:
    kind: str  # "audio" | "video"
    container: str  # wav | mp3 | m4a | mp4 | mov | webm
    duration_seconds: Optional[float] = None
    estimate: bool = False  # the duration is a bit-rate estimate, not exact
    extra: Dict[str, Any] = field(default_factory=dict)  # sample_rate, channels, width, height


# ---- container detection ------------------------------------------------------

def detect(data: bytes) -> str:
    """wav | mp3 | m4a | mp4 | mov | webm, or a clean refusal."""
    if len(data) < 12:
        raise MediaError("This file is too small to be a readable audio or video file.")
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        if data[:2] == b"PK":
            raise MediaError("This is a ZIP archive, not audio.")
        return "mp3"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand[:3] == b"M4A":
            return "m4a"
        if brand == b"qt  ":
            return "mov"
        return "mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    raise MediaError("Choose a WAV, MP3, M4A, MP4, MOV or WEBM file.", 415)


# ---- parsers ------------------------------------------------------------------

def _wav(data: bytes) -> MediaInfo:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames, rate, channels = w.getnframes(), w.getframerate(), w.getnchannels()
    except (wave.Error, EOFError) as exc:
        raise MediaError("This WAV file is incomplete or unreadable.") from exc
    if not frames or not rate:
        raise MediaError("This WAV file has no audible content to verify.")
    duration = frames / float(rate)
    if duration <= 0:
        raise MediaError("This WAV file reports zero duration.")
    return MediaInfo(kind="audio", container="wav", duration_seconds=round(duration, 2),
                     extra={"sample_rate": rate, "channels": channels})


_MP3_BR_L3_V1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MP3_BR_L3_V2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_MP3_SR_V1 = (44100, 48000, 32000)
_MP3_SR_V2 = (22050, 24000, 16000)  # MPEG2; MPEG2.5 is half of V2


def _mp3(data: bytes) -> MediaInfo:
    offset = 0
    if data[:3] == b"ID3" and len(data) > 9:
        offset = 10 + ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                       | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    # find a frame sync, tolerating inline artwork or replaygain tags after ID3
    pos, limit = max(offset, 0), min(len(data) - 4, max(offset, 0) + 65536)
    while pos < limit:
        if data[pos] == 0xFF and (data[pos + 1] & 0xE0) == 0xE0:
            break
        pos += 1
    if pos >= limit or limit <= 0:
        raise MediaError("No MP3 frame was found in this file.")
    b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
    version_bits, layer_bits = (b1 >> 3) & 0x03, (b1 >> 1) & 0x03
    bitrate_index, sr_index = (b2 >> 4) & 0x0F, (b2 >> 2) & 0x03
    if layer_bits != 1 or version_bits == 1 or sr_index == 3 or bitrate_index in (0, 15):
        raise MediaError("This MP3 uses a format we cannot time (free-form or reserved values).")
    mpeg1 = version_bits == 3
    rate = int(_MP3_SR_V1[sr_index] if mpeg1
               else _MP3_SR_V2[sr_index] * (0.5 if version_bits == 0 else 1.0))
    bitrate = (_MP3_BR_L3_V1 if mpeg1 else _MP3_BR_L3_V2)[bitrate_index]
    samples = 1152 if mpeg1 else 576
    audio_bytes = max(len(data) - pos, 0)
    duration = audio_bytes * 8.0 / (bitrate * 1000.0)
    frames_estimate = int(audio_bytes / (samples / float(rate)))
    label = "MPEG1" if mpeg1 else ("MPEG2.5" if version_bits == 0 else "MPEG2")
    return MediaInfo(kind="audio", container="mp3", duration_seconds=round(duration, 2), estimate=True,
                     extra={"sample_rate": rate, "channels": 1 if (b3 >> 6) == 3 else 2,
                            "encoding": f"MP3 {label} layer 3",
                            "duration_frames_estimate": frames_estimate})


def _ebml_id(data: bytes, pos: int) -> Tuple[Optional[int], int]:
    """One EBML variable-size integer, marker bit kept (element ids are the raw value)."""
    if pos >= len(data):
        return None, 0
    first = data[pos]
    length = 1
    while length <= 8 and not first & (0b1000_0000 >> (length - 1)):
        length += 1
    if length > 8 or pos + length > len(data):
        return None, 0
    value = first
    for i in range(pos + 1, pos + length):
        value = (value << 8) | data[i]
    return value, length


def _ebml_size(enc: int, length: int) -> Optional[int]:
    """Actual size from a length-encoded size field; None = unknown (all ones)."""
    mask = (1 << (7 * length)) - 1
    value = enc & mask
    return None if value == mask else value


def _matroska(data: bytes) -> MediaInfo:
    """Minimal EBML walk: Segment > Info > TimecodeScale + Duration."""
    scale, duration = 1_000_000, None

    def elements(start: int, end: int, depth: int):
        pos = start
        while pos < end - 12:
            eid, n = _ebml_id(data, pos)
            if eid is None or n == 0:
                return
            pos += n
            senc, n2 = _ebml_id(data, pos)
            if senc is None or n2 == 0:
                return
            size = _ebml_size(senc, n2)
            pos += n2
            if size is None:  # unknown size: this well-known case, only Segment and cluster-like
                if depth == 0:
                    yield eid, pos, end - pos
                return
            yield eid, pos, size
            pos += size

    top = list(elements(0, len(data), 0))
    for eid, vp, size in top:
        if eid != 0x18538067:  # Segment
            continue
        for eid2, vp2, size2 in elements(vp, min(vp + size, len(data)), 1):
            if eid2 != 0x1549A966:  # Info
                continue
            for eid3, vp3, size3 in elements(vp2, min(vp2 + size2, len(data)), 2):
                if eid3 == 0x2AD7B1 and size3 <= 8:  # TimecodeScale (uint)
                    scale = int.from_bytes(data[vp3:vp3 + size3], "big") or 1_000_000
                elif eid3 == 0x4489 and size3 in (4, 8):  # Duration (float)
                    raw = data[vp3:vp3 + size3]
                    duration = struct.unpack(">f" if size3 == 4 else ">d", raw)[0]
            break
        break
    if duration is None or duration <= 0 or duration != duration:  # also NaN
        raise MediaError("This WebM file does not carry a finishable duration header "
                         "(streaming recordings need a downloaded copy).")
    seconds = duration * scale / 1_000_000_000
    if seconds > MAX_SECONDS * 4:
        raise MediaError("This recording reports an implausible duration header.")
    return MediaInfo(kind="video", container="webm", duration_seconds=round(seconds, 2),
                     extra={"container": "webm"})


def _mp4_boxes(data: bytes, start: int, end: int, depth: int = 0):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        btype = data[pos + 4:pos + 8]
        header = 8
        if size == 1:  # 64-bit large box
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:  # extends to end of file
            size = end - pos
        if size < header or pos + size > end:
            return
        yield btype, pos + header, size - header
        if depth < 6 and btype in (b"moov", b"trak", b"mdia", b"minf", b"udta"):
            yield from _mp4_boxes(data, pos + header, pos + size, depth + 1)
        pos += size


def _mp4(data: bytes, container: str) -> MediaInfo:
    width = height = None
    timescale = duration = None
    for btype, vp, size in _mp4_boxes(data, 0, len(data)):
        if btype == b"mvhd":
            version = data[vp]
            if version == 1:
                if vp + 32 <= vp + size:
                    timescale = struct.unpack(">I", data[vp + 20:vp + 24])[0]
                    duration = struct.unpack(">Q", data[vp + 24:vp + 32])[0]
            elif vp + 20 <= vp + size:
                timescale = struct.unpack(">I", data[vp + 12:vp + 16])[0]
                duration = struct.unpack(">I", data[vp + 16:vp + 20])[0]
        elif btype == b"tkhd":
            version = data[vp]
            base = vp + 76 if version == 0 else vp + 84
            if base + 8 <= vp + size:
                w = struct.unpack(">I", data[base:base + 4])[0] / 65536.0
                h = struct.unpack(">I", data[base + 4:base + 8])[0] / 65536.0
                if w > 1 and h > 1:
                    width, height = int(round(w)), int(round(h))
    if not duration or not timescale:
        raise MediaError("This file's movie header is missing or truncated ('moov' not found).")
    seconds = duration / float(timescale)
    if seconds <= 0:
        raise MediaError("This " + container + " file reports zero duration.")
    kind = "video" if width and container != "m4a" else "audio"
    extra: Dict[str, Any] = {"container": container}
    if kind == "video" and width:
        extra.update(width=width, height=height)
    return MediaInfo(kind=kind, container=container, duration_seconds=round(seconds, 2), extra=extra)


# ---- public surface -----------------------------------------------------------

def inspect(data: bytes) -> MediaInfo:
    """Parse one media file; raises MediaError with a user-facing reason."""
    container = detect(data)
    parsers = {"wav": _wav, "mp3": _mp3, "webm": _matroska,
               "m4a": lambda d: _mp4(d, "m4a"), "mp4": lambda d: _mp4(d, "mp4"),
               "mov": lambda d: _mp4(d, "mov")}
    info = parsers[container](data)
    if info.duration_seconds and info.duration_seconds > MAX_SECONDS:
        raise MediaError("Media files are limited to 15 minutes; longer recordings "
                         "need a transcript review instead.", 413)
    return info


def format_clock(seconds: Optional[float]) -> str:
    if not seconds or seconds < 0:
        return "0:00"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def describe(locator: Optional[Dict[str, Any]]) -> str:
    """Readable locator label for audio/video findings, in the describe() family."""
    if not locator:
        return ""
    kind = locator.get("kind")
    if kind not in ("audio", "video"):
        return ""
    label = kind
    if locator.get("char_start") is not None:
        label += " · transcript"
    return label


def check_media(ctx, kind: str, transcript: Optional[str], asset_id: str,
                filename: str = "") -> List[Dict[str, Any]]:
    """Findings for one audio/video asset. The bound rule switches the check off."""
    rule = ctx.rule("media.transcript")
    if not rule:
        return []
    text = (transcript or "").strip()
    if text:
        return []
    label = "audio" if kind == "audio" else "video"
    noun = "recording" if kind == "audio" else "video"
    return [{
        "id": gen_id("fnd"), "revision_id": ctx.revision_id, "checker": "media",
        "category": "missing_transcript",
        "span": {"start": 0, "end": 0, "text": ""},
        "tier": "consider", "severity": "medium",
        "citations": [{"type": "rule", "id": rule}],
        "explanation": (f"This {label} is published without a transcript. Everything a person "
                        f"hears also needs to be checkable: without the words, spoken claims cannot "
                        f"be traced to an approved fact. Attach a transcript when submitting."),
        "suggestion": {"replace": f"Paste or attach a transcript of this {noun}.",
                       "operation": "rewrite"},
        "title": f"Missing {label} transcript",
        "provenance": {"model": None, "prompt_version": "media@1", "knowledge_version": ctx.kv},
        "locator": {"kind": kind, "asset_id": asset_id},
        "location_key": f"media|missing_transcript|media:{asset_id}",
    }]


def locating(source_kind: str, start: int, end: int, asset_id: Optional[str]) -> Dict[str, Any]:
    """Locator for a finding span inside a supplied transcript."""
    return {"kind": source_kind, "asset_id": asset_id, "char_start": start, "char_end": end}
