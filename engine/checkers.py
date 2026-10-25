"""Rule-based checkers (doc 9.2 "rules before AI" — fast, free, certain).

- terminology: glossary with preferred/banned alternates
- readability + social/format: sentence length, word count, CTA presence
- tone heuristic: hard-sell phrasing / exclamation abuse (consider tier)
Every finding carries citations to real rules (or terms) — no citation, no finding.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

sqlite3 = None  # type: ignore


class Ctx:
    """Everything a checker needs about the workspace & revision."""

    def __init__(self, conn, revision_id: str, channel: str, source_type: str, kv: int):
        self.conn = conn
        self.revision_id = revision_id
        self.channel = channel
        self.source_type = source_type
        self.kv = kv


def _f(ctx: Ctx, checker: str, category: str, span: Tuple[int, int, str], tier: str,
       severity: str, citations: List[Dict[str, Any]], explanation: str,
       suggestion: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
    from contract import CONTRACT_VERSION
    return {
        "id": f"fnd_{ctx.revision_id[-6:]}_{len(span[2])%997:03d}_{span[0]}",
        "revision_id": ctx.revision_id,
        "checker": checker,
        "category": category,
        "span": {"start": span[0], "end": span[1], "text": span[2]},
        "tier": tier,
        "severity": severity,
        "citations": citations,
        "explanation": explanation,
        "suggestion": {"replace": suggestion, "operation": "replace"} if suggestion else None,
        "title": title,
        "provenance": {"model": None, "prompt_version": CONTRACT_VERSION, "knowledge_version": ctx.kv},
    }


def _ci_find(text: str, needle: str) -> Optional[Tuple[int, int]]:
    if not needle:
        return None
    m = re.search(re.escape(needle), text, re.IGNORECASE)
    if m:
        return m.start(), m.end()
    return None


# ---- terminology -----------------------------------------------------------

def check_terminology(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    rows = ctx.conn.execute(
        "SELECT id, preferred, banned_or_check, note, severity FROM terms WHERE workspace_id = (SELECT DISTINCT workspace_id FROM revisions WHERE id=?) ORDER BY severity DESC",
        (ctx.revision_id,),
    ).fetchall()
    for t in rows:
        banned = t["banned_or_check"] or ""
        preferred = t["preferred"] or ""
        for variant in (v.strip() for v in banned.split(",")):
            if not variant:
                continue
            pos = _ci_find(text, variant)
            if not pos:
                continue
            span = (pos[0], pos[1], text[pos[0]:pos[1]])
            # citations: parse rule ids and fact ids out of the note
            cits: List[Dict[str, Any]] = []
            note = t["note"] or ""
            for rid in re.findall(r"rule ([A-Z]+-[\w.]+)", note):
                cits.append({"type": "rule", "id": rid})
            for fid in re.findall(r"fact ([\wC]+-\d+\b)", note):
                cits.append({"type": "fact", "id": fid})
            cits.append({"type": "term", "id": str(t["id"])})
            repl = preferred if preferred and preferred != "-" else None
            out.append(_f(
                ctx, "terminology",
                "outdated_term" if "renamed" in note.lower() else "banned_term",
                span, "definite", t["severity"] or "medium", cits,
                note or "Banned terminology",
                repl, title=f'Banned term "{variant}"',
            ))
    return out


# ---- readability / format / social ----------------------------------------

_SENT = re.compile(r"[^.!?]+[.!?]+")


def check_readability(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sentences = [s for s in (m.group(0) for m in _SENT.finditer(text)) if len(s.split()) > 5]
    long_ones = [s for s in sentences if len(s.split()) > 22]
    if long_ones:
        s = long_ones[0]
        pos = text.find(s)
        span = (pos, pos + len(s), s[:80] + ("..." if len(s) > 80 else ""))
        out.append(_f(
            ctx, "readability", "readability", span, "definite", "low",
            [{"type": "rule", "id": "VOICE-3.1"}],
            "Sentence is 22+ words; voice rule VOICE-3.1 asks for an average under 20 words per sentence.",
        ))
    words = len(text.split())
    if ctx.channel == "social" and words > 200:
        out.append(_f(
            ctx, "readability", "readability", (0, min(20, len(words)), text[:20]),
            "definite", "low", [{"type": "rule", "id": "SOC-01"}],
            f"Social posts are limited to 200 words; this draft is {words} (rule SOC-01).",
        ))
    if ctx.channel == "social" and not _ci_find(text, "http") and ("starting" in text.lower() or "start" in text.lower()):
        pos = max(0, len(text) - 20)
        out.append(_f(
            ctx, "readability", "missing_disclaimer", (pos, len(text), text[pos:].strip()[-30:] if text[pos:].strip() else "(end)"),
            "definite", "low", [{"type": "rule", "id": "MSG-03"}],
            "Sales posts end with a clear call to action (rule MSG-03); no link/CTA found.",
        ))
    return out


# ---- tone heuristics (consider tier) --------------------------------------

HARDSELL = [
    r"\bjust\s+(₹|rs\.?|inr)?\s*[\d,]+", r"grab (it|yours) now", r"don'?t miss",
    r"hurry", r"act now", r"limited time", r"only today",
]
EXCL = re.compile(r"!")


def check_tone_rules(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if len(EXCL.findall(text)) > 1:
        out.append(_f(
            ctx, "tone", "tone", (0, 0, ""), "consider", "medium",
            [{"type": "rule", "id": "VOICE-3.4"}],
            "More than one exclamation mark in the post (voice rule VOICE-3.4 allows at most one).",
            title="Tone: too many exclamation marks",
        ))
    for pat in HARDSELL:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            span = (m.start(), m.end(), text[m.start():m.end()])
            out.append(_f(
                ctx, "tone", "tone", span, "consider", "medium",
                [{"type": "rule", "id": "VOICE-3.2"}],
                '"Just ..." reads as a hard sell; voice rule VOICE-3.2 is "confident, never pushy".',
                title="Tone: hard-sell phrasing",
            ))
            break
    return out
