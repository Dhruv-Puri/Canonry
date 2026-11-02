"""Round 3 media: WAV/MP3/MP4/M4A/MOV/WebM inspection, transcript linkage.

Run:  .venv/Scripts/python engine/tests/test_media.py
"""
import io
import json
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401  (first: never reach a real AI provider)

import db as _db

_db.use_test_database("canonry_media")

import assets  # noqa: E402
import documents  # noqa: E402
import media  # noqa: E402
import pipeline  # noqa: E402
from db import _now, connect, gen_id  # noqa: E402
from seed import seed  # noqa: E402

failures = []
MEDIA_UPLOADS_WIRED = False  # media.py is not connected to uploads or the pipeline yet


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def make_wav(seconds=2.0, rate=8000, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate) * channels)
    return buf.getvalue()


def make_mp3(frames=200) -> bytes:
    """MPEG1 layer 3, 128 kbps, 44100 Hz: header FF FB 90 00, then the frame body."""
    id3 = b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10
    frame = b"\xff\xfb\x90\x00" + b"\x00" * (int(144 * 128000 / 44100) - 4)
    return id3 + frame * frames


def box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + btype + payload


def make_mp4(kind: str = "mp4") -> bytes:
    """ftyp + moov(mvhd v0 + trak(tkhd v0)); timescale 1000, duration 60000 -> 60.0 s."""
    mvhd = b"\x00\x00\x00\x00" + b"\x00" * 8 + struct.pack(">II", 1000, 60000) + b"\x00" * 76
    # version+flags, creation, modification, track id, reserved, duration,
    # reserved(8), layer, group, volume, reserved, matrix(36), width, height
    tkhd = (b"\x00\x00\x00\x00" + b"\x00" * 4 + b"\x00" * 4 + b"\x00\x00\x00\x01"
            + b"\x00" * 4 + b"\x00\x00\x00\x64" + b"\x00" * 8 + b"\x00" * 2 + b"\x00" * 2
            + b"\x00" * 2 + b"\x00" * 2 + b"\x00" * 36
            + struct.pack(">II", 640 * 65536, 360 * 65536))
    trak = box(b"trak", box(b"tkhd", tkhd))
    moov = box(b"moov", box(b"mvhd", mvhd) + trak)
    brand = b"M4A " if kind == "m4a" else b"isomiso2avc1mp00a"
    return box(b"ftyp", brand + b"\x00\x00\x02\x00") + moov


def _vint(value: int, length=None) -> bytes:
    """EBML size/id integer: marker bit in the first byte."""
    if length is None:
        length = 1
        while value >= (1 << (7 * length)) - 1:
            length += 1
    return ((1 << (7 * length)) | value).to_bytes(length, "big")


def _element(id_bytes: bytes, payload: bytes, unknown=False) -> bytes:
    size = b"\x01\xff\xff\xff\xff\xff\xff\xff" if unknown else _vint(len(payload), 4)
    return id_bytes + size + payload


def make_webm(duration=3000.0, scale=1000000) -> bytes:
    """EBML header + Segment(unknown size) > Info > TimecodeScale + Duration (float64)."""
    header_payload = b"\x42\x86\x81\x01\x42\xf7\x81\x01"
    info_payload = _element(b"\x2a\xd7\xb1", scale.to_bytes(3, "big")) \
        + _element(b"\x44\x89", struct.pack(">d", duration))
    info = _element(b"\x15\x49\xa9\x66", info_payload)
    return (_element(b"\x1a\x45\xdf\xa3", header_payload)
            + _element(b"\x18\x53\x80\x67", info, unknown=True))


def run_file(name: str, data: bytes, alt: str):
    sid = gen_id("sub")
    conn.execute(
        "INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, status, created_at) "
        "VALUES (?,?,?,?,?,?,'Draft',?)", (sid, ws, name, "social", "in-house", "media-test", _now()))
    return assets.create_asset(conn, ws, sid, name, data, alt, "media-test"), sid


def run_revision(conn, sid: str, asset: dict) -> str:
    rev_no = conn.execute("SELECT COALESCE(MAX(revision_no),0)+1 AS n FROM revisions "
                          "WHERE submission_id=?", (sid,)).fetchone()["n"]
    rid = gen_id("rev")
    conn.execute(
        "INSERT INTO revisions (id, submission_id, content, revision_no, created_at, asset_id, "
        "source_kind, locator_map_json) VALUES (?,?,?,?,?,?,?,?)",
        (rid, sid, asset["extracted_text"], rev_no, _now(), asset["id"],
         asset["source_kind"], json.dumps(asset["locator_map"])),
    )
    conn.execute("UPDATE submissions SET status = CASE WHEN status='Draft' THEN 'Checked' "
                 "ELSE status END WHERE id=?", (sid,))
    return rid


ws = seed()
conn = connect()
try:
    # ---- containers are detected structurally ---------------------------------
    expect(media.detect(make_wav()) == "wav", "WAV detects as wav")
    expect(media.detect(make_mp3()) == "mp3", "MP3 with an ID3 tag detects as mp3")
    expect(media.detect(make_mp4()) == "mp4", "MP4 with an isom brand detects as mp4")
    expect(media.detect(make_mp4("m4a")) == "m4a", "an M4A brand detects as m4a")
    expect(media.detect(make_webm()) == "webm", "EBML header detects as webm")
    for name, raw in (("empty", b""), ("png bytes", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40),
                      ("zip named .mp3", b"PK\x03\x04" + b"\x00" * 40)):
        try:
            media.detect(raw)
            expect(False, f"{name} is refused")
        except media.MediaError:
            expect(True, f"{name} is refused")

    # ---- durations and dimensions ---------------------------------------------
    info = media.inspect(make_wav(2.0, 8000, 2))
    expect(abs((info.duration_seconds or 0) - 2.0) < 0.01, f"WAV duration is exact ({info})")
    expect(info.extra["sample_rate"] == 8000 and info.extra["channels"] == 2, f"WAV rate/channels ({info.extra})")

    info = media.inspect(make_mp3())
    expect(info.estimate, "MP3 duration is labelled an estimate")
    expect(abs((info.duration_seconds or 0) - 83400 * 8 / 128000) < 0.01, f"MP3 duration estimate ({info})")
    expect(info.extra["sample_rate"] == 44100, f"MP3 sample rate ({info.extra['sample_rate']})")

    info = media.inspect(make_mp4())
    expect(info.kind == "video" and info.extra.get("width") == 640 and info.extra.get("height") == 360,
           f"MP4 kind and dimensions ({info.kind}, {info.extra.get('width')}x{info.extra.get('height')})")
    expect(abs((info.duration_seconds or 0) - 60.0) < 0.001, f"MP4 duration ({info.duration_seconds})")
    info = media.inspect(make_mp4("m4a"))
    expect(info.kind == "audio", "M4A without a video track is audio")

    info = media.inspect(make_webm())
    expect(abs((info.duration_seconds or 0) - 3.0) < 0.01, f"WebM duration via TimecodeScale ({info})")

    # corrupt media is refused with a readable reason
    for name, raw, needle in (
        ("truncated WAV", make_wav()[:20], "incomplete"),
        ("MP3 with reserved values", b"\xff\xfb\xf0\x44" + b"\x00" * 200, "cannot time"),
        ("MP4 without a moov atom", box(b"ftyp", b"isomiso2avc1mp00a\x00\x00\x02\x00")
                                    + box(b"free", b"\x00" * 16), "moov"),
    ):
        try:
            media.inspect(raw)
            expect(False, f"{name} is refused")
        except media.MediaError as exc:
            expect(needle in str(exc), f"{name} refused: {str(exc)[:60]}")

    # Audio and video upload is not wired into the product yet (README §13 roadmap):
    # the parsing above is the module's tested part; the upload path below runs once
    # assets.py accepts media files.
    if MEDIA_UPLOADS_WIRED:
        # ---- the real path: upload an audio asset, run the pipeline ----------------
        wav_bytes = make_wav(30.0, 44100, 1)
        asset_raw, sid_raw = run_file("voiceover-no-transcript.wav", wav_bytes, "")
        result = pipeline.run_check(conn, run_revision(conn, sid_raw, asset_raw))
        cats = {f["category"] for f in result["findings"]}
        expect("missing_transcript" in cats, f"no-transcript audio gets a media finding ({sorted(cats)})")
        med = [f for f in result["findings"] if f["checker"] == "media"]
        expect(med and med[0]["locator"]["kind"] == "audio" and med[0]["locator"]["asset_id"] == asset_raw["id"],
               f"media finding carries an audio locator ({med[:1]})")
        expect(med and med[0]["citations"][0]["type"] == "rule" and med[0]["citations"][0]["id"],
               "media finding cites the bound rule")
        expect(documents.describe(med[0]["locator"]) == "audio", "locator label for audio")

        # ---- a transcript routes the words into the claim pipeline -----------------
        transcript = "Meet Quillmark Insights 2.0, trusted by 5,000+ teams."
        asset_t, sid_t = run_file("voiceover-claims.mp3", make_mp3(), transcript)
        result = pipeline.run_check(conn, run_revision(conn, sid_t, asset_t))
        med2 = [f for f in result["findings"] if f["checker"] == "media"]
        expect(not med2, "a transcript satisfies the media check")
        claim_hits = [f for f in result["findings"] if f["checker"] == "claims" and f["status"] == "open"]
        expect(claim_hits, f"transcript claims are checked ({[f['category'] for f in claim_hits]})")
        loc = claim_hits[0]["locator"] if claim_hits else {}
        expect(loc.get("kind") == "audio" and loc.get("char_start") is not None,
               f"claim findings on the transcript carry audio locators ({loc})")
        if loc:
            expect(documents.describe(loc) == "audio · transcript",
                   f"transcript locator label ({loc})")

        # ---- upload validation ------------------------------------------------------
        try:
            run_file("notes.pdf", wav_bytes, "")
            expect(False, "a WAV renamed .pdf is refused")
        except assets.UploadError as exc:
            expect("extension is not" in str(exc), f"extension mismatch message ({str(exc)[:70]})")
        big = wav_bytes * 400  # ~48 MB > the 25 MB audio limit
        try:
            run_file("big.wav", big, "")
            expect(False, "oversized audio is refused")
        except assets.UploadError as exc:
            expect("larger than" in str(exc), f"size limit message ({str(exc)[:70]})")

        # asset rows expose duration + container metadata for the UI
        row = assets.get_asset(conn, asset_raw["id"])
        expect(abs((row["duration_seconds"] or 0) - 30.0) < 0.01 and row["media"].get("container") == "wav",
               "asset exposes duration and container metadata")
    else:
        print("skip: audio/video upload is not wired into the product yet (roadmap)")
    print()
finally:
    conn.close()

if failures:
    print(f"{len(failures)} MEDIA CHECK(S) FAILED")
    sys.exit(1)
print("ALL MEDIA CHECKS PASSED")
