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
        "SELECT id, preferred, banned_or_check, note, severity FROM terms WHERE status = 'active' AND workspace_id = "
        "(SELECT s.workspace_id FROM revisions r JOIN submissions s ON s.id = r.submission_id WHERE r.id = ?) "
        "ORDER BY severity DESC",
        (ctx.revision_id,),
    ).fetchall()
    for t in rows:
        banned = t["banned_or_check"] or ""
        preferred = t["preferred"] or ""
        for variant in (v.strip() for v in banned.split(",")):
            if not variant:
                continue
            # every occurrence, not just the first: a second "Quillmark Insights"
            # must not slip through to approval
            for m in re.finditer(re.escape(variant), text, re.IGNORECASE):
                span = (m.start(), m.end(), m.group(0))
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


# ---- confidential information ----------------------------------------------

_STOP = {"the", "and", "for", "with", "from", "this", "that", "our", "are", "was", "not", "has", "have",
         "will", "under", "into", "per", "via", "all", "its", "out", "new", "use", "can", "you", "your",
         "as", "of", "in", "on", "to", "by", "at", "is", "it", "an", "or", "we", "be", "do", "if", "so", "up",
         "internal", "confidential", "publish", "review", "target", "upcoming", "planned", "unannounced",
         "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "q1", "q2", "q3", "q4"}
_NUM = re.compile(r"\d+(?:\.\d+)?%?")
_WORD = re.compile(r"[a-z][a-z0-9-]+")


def _sentences(text: str):
    # a full stop ends a sentence only before whitespace or the end ("4.2 crore" stays whole)
    for m in re.finditer(r"(?:[^.!?]|[.!?](?=\S))+[.!?]*", text):
        s = m.group(0)
        lead = len(s) - len(s.lstrip())
        body = s.strip()
        if body:
            yield m.start() + lead, m.start() + lead + len(body), body


def _distinctive_numbers(fact_text: str) -> List[str]:
    out = []
    for n in _NUM.findall(fact_text):
        digits = n.rstrip("%")
        if "." in n or n.endswith("%") or (len(digits) >= 3 and not (len(digits) == 4 and 1900 <= int(digits) <= 2099)):
            out.append(n)
    return out


def check_confidential(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    """Flag sentences that repeat confidential facts (plan: "protected confidential
    information"). A distinctive figure plus a word from the fact is definite; a
    distinctive two-word phrase alone is likely. The finding names the fact's owner,
    never its text."""
    out: List[Dict[str, Any]] = []
    facts = ctx.conn.execute(
        "SELECT id, text, owner FROM facts WHERE confidential = 1 AND superseded = 0 AND workspace_id = "
        "(SELECT s.workspace_id FROM revisions r JOIN submissions s ON s.id = r.submission_id WHERE r.id = ?)",
        (ctx.revision_id,),
    ).fetchall()
    flagged = set()
    for start, end, sentence in _sentences(text):
        low = sentence.lower()
        words = set(_WORD.findall(low))
        for f in facts:
            ftext = f["text"].lower()
            fwords = [w for w in _WORD.findall(ftext) if w not in _STOP and len(w) >= 2]
            figure = next((n for n in _distinctive_numbers(ftext)
                           if re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", low)), None)
            figure_hit = figure is not None and any(w in words for w in fwords)
            pairs = [f"{a} {b}" for a, b in zip(fwords, fwords[1:]) if f"{a} {b}" in ftext]
            phrase = next((p for p in pairs if p in low), None)
            if not (figure_hit or phrase) or (start, f["id"]) in flagged:
                continue
            flagged.add((start, f["id"]))
            what = f'the figure "{figure}"' if figure_hit else f'"{phrase}"'
            finding = _f(
                ctx, "confidential", "confidential_leak", (start, end, sentence),
                "definite" if figure_hit else "likely", "high",
                [{"type": "fact", "id": f["id"]}],
                f"This sentence repeats confidential information ({what}, owned by {f['owner'] or 'its owner'}). "
                "Confidential facts are never published; remove it or ask the owner.",
                title="Confidential information",
            )
            finding["suggestion"] = {"operation": "remove"}
            out.append(finding)
    return out


def check_readability(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sentences = [s for s in (m.group(0) for m in _SENT.finditer(text)) if len(s.split()) > 5]
    long_ones = [s for s in sentences if len(s.split()) > 22]
    if long_ones:
        s = long_ones[0].strip()
        pos = text.find(s)
        out.append(_f(
            ctx, "readability", "readability", (pos, pos + len(s), s), "definite", "low",
            [{"type": "rule", "id": "VOICE-3.1"}],
            f"Sentence is {len(s.split())} words; voice rule VOICE-3.1 asks for an average under 20 words per sentence.",
        ))
    words = len(text.split())
    if ctx.channel == "social" and words > 200:
        first = next((m.group(0).strip() for m in _SENT.finditer(text)), text[:80].strip())
        pos = text.find(first)
        out.append(_f(
            ctx, "readability", "readability", (pos, pos + len(first), first),
            "definite", "low", [{"type": "rule", "id": "SOC-01"}],
            f"Social posts are limited to 200 words; this draft is {words} (rule SOC-01).",
        ))
    # a social post that talks pricing is a sales post: it should end with a CTA
    is_sales = re.search(r"₹|/\s*(?:month|mo|year)\b|\bplans?\b|\bpricing\b", text, re.IGNORECASE)
    has_cta = re.search(r"https?://|\b(?:sign up|try|book|start (?:a|your)|learn more|register|contact|get started)\b",
                        text, re.IGNORECASE)
    if ctx.channel == "social" and is_sales and not has_cta:
        last = [m for m in _SENT.finditer(text)]
        s, e = (last[-1].start(), last[-1].end()) if last else (0, len(text))
        while s < e and text[s].isspace():
            s += 1
        out.append(_f(
            ctx, "readability", "missing_cta", (s, e, text[s:e]),
            "consider", "low", [{"type": "rule", "id": "MSG-03"}],
            "Sales posts end with a clear call to action (rule MSG-03); no link or CTA found. Add one in your own words.",
            title="No call to action",
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
            phrase = text[m.start():m.end()]
            # "just ₹999" -> "₹999": drop the pushy word, keep the fact
            fix = re.sub(r"^just\s+", "", phrase, flags=re.IGNORECASE) if phrase.lower().startswith("just") else None
            out.append(_f(
                ctx, "tone", "tone", (m.start(), m.end(), phrase), "consider", "medium",
                [{"type": "rule", "id": "VOICE-3.2"}],
                f'"{phrase}" reads as a hard sell; voice rule VOICE-3.2 is "confident, never pushy".',
                fix, title="Tone: hard-sell phrasing",
            ))
            break
    return out
