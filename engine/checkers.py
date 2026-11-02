"""Rule-based checkers (doc 9.2 "rules before AI" — fast, free, certain).

- terminology: glossary with preferred/banned alternates
- readability + social/format: sentence length, word count, CTA presence
- tone heuristic: hard-sell phrasing / exclamation abuse (consider tier)
Every finding carries citations to real rules (or terms) — no citation, no finding.
"""
from __future__ import annotations

import functools
import re
from typing import Any, Dict, List, Optional, Tuple

import policy
import understand
from contract import CONTRACT_VERSION



class Ctx:
    """Everything a checker needs about the workspace & revision."""

    def __init__(self, conn, revision_id: str, channel: str, source_type: str, kv: int,
                 ws: Optional[str] = None):
        self.conn = conn
        self.revision_id = revision_id
        self.channel = channel
        self.source_type = source_type
        self.kv = kv
        self.ws = ws or self._workspace()
        self._rules: Dict[str, Optional[str]] = {}
        # what the content is (understand.profile); None = every check applies
        self.profile: Optional[Dict[str, Any]] = None

    def applies(self, check_key: str) -> bool:
        """Does this check apply to this kind of content? (understand.decide)"""
        return understand.applies(self.profile, check_key)[0]

    def why(self, check_key: str) -> Optional[str]:
        """The profile decision behind a finding, for its provenance."""
        if not self.profile:
            return None
        return understand.applies(self.profile, check_key)[1] or None

    def _workspace(self) -> Optional[str]:
        row = self.conn.execute(
            "SELECT s.workspace_id FROM revisions r JOIN submissions s ON s.id = r.submission_id WHERE r.id = ?",
            (self.revision_id,)).fetchone() or self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
        return row[0] if row else None

    def rule(self, check_key: str) -> Optional[str]:
        """The rule this built-in check cites in this workspace; None = check is off."""
        if check_key not in self._rules:
            self._rules[check_key] = policy.rule_for(self.conn, self.ws, check_key)
        return self._rules[check_key]


def _f(ctx: Ctx, checker: str, category: str, span: Tuple[int, int, str], tier: str,
       severity: str, citations: List[Dict[str, Any]], explanation: str,
       suggestion: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
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

def term_variants(banned: Optional[str]) -> List[str]:
    """The phrases in a term's "instead of" list. Commas separate phrases, but not the comma
    inside a number: "5,000+ teams" is one phrase. (Splitting it made "5" a banned word, so
    "Setup takes 5 minutes" got a Must fix.)"""
    return [v.strip() for v in re.split(r",(?!\d{3}(?!\d))", banned or "") if v.strip()]


@functools.lru_cache(maxsize=512)  # built once per phrase: a long draft asks thousands of times
def term_pattern(variant: str) -> "re.Pattern[str]":
    """Match a phrase as whole words and whole numbers: "#1" is not inside "#10", and
    "5,000+ teams" is not inside "25,000+ teams"."""
    left = r"(?<![\w])" if variant[:1].isalnum() else ""
    right = r"(?![\w])" if variant[-1:].isalnum() else ""
    if variant[-1:].isdigit():
        right = r"(?![\w,.]?\d)(?![\w])"  # "#1" must not continue as "#10" or "#1.5"
    return re.compile(left + re.escape(variant) + right, re.IGNORECASE)


def check_terminology(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    rows = ctx.conn.execute(
        "SELECT id, preferred, banned_or_check, note, severity FROM terms WHERE status = 'active' AND workspace_id = ? "
        "ORDER BY severity DESC",
        (ctx.ws,),
    ).fetchall()
    for t in rows:
        banned = t["banned_or_check"] or ""
        preferred = t["preferred"] or ""
        for variant in term_variants(banned):
            # every occurrence, not just the first: a second "Quillmark Insights"
            # must not slip through to approval
            for m in term_pattern(variant).finditer(text):
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


# ---- confidential information ----------------------------------------------

_STOP = {"the", "and", "for", "with", "from", "this", "that", "our", "are", "was", "not", "has", "have",
         "will", "under", "into", "per", "via", "all", "its", "out", "new", "use", "can", "you", "your",
         "as", "of", "in", "on", "to", "by", "at", "is", "it", "an", "or", "we", "be", "do", "if", "so", "up",
         "internal", "confidential", "publish", "review", "target", "upcoming", "planned", "unannounced",
         "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "q1", "q2", "q3", "q4"}
_NUM = re.compile(r"\d+(?:\.\d+)?%?")
_WORD = re.compile(r"[a-z][a-z0-9-]+")


_SENTENCE = re.compile(
    r"(?:(?<![A-Za-z])(?:Rs|No|Nos)\.\s*(?=\d)"
    r"|(?<![A-Za-z])(?:Dr|Mr|Mrs|Ms|Prof|St)\.\s+(?=[A-Z])"
    r"|(?<![A-Za-z])(?:Pvt|Ltd|Inc|Co|vs|approx|incl|e\.g|i\.e)\.\s+(?=[\w(₹])"
    r"|[^.!?]|[.!?](?=\S))+[.!?]*")


def _sentences(text: str):
    # a full stop ends a sentence only before whitespace or the end ("4.2 crore" stays whole)
    # ...and nor does the full stop of "Rs. 999", "No. 1", "Dr. Mehta" or "Pvt. Ltd."
    for m in _SENTENCE.finditer(text):
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
        "SELECT id, text, owner FROM facts WHERE confidential = 1 AND superseded = 0 AND workspace_id = ?",
        (ctx.ws,),
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


def _noted(ctx: Ctx, finding: Dict[str, Any], check_key: str) -> Dict[str, Any]:
    """Record which profile decision let this check run (provenance)."""
    why = ctx.why(check_key)
    if why:
        finding["provenance"]["profile"] = why
    return finding


def check_readability(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # the same sentence splitter the confidential checker uses: a full stop ends
    # a sentence only before whitespace, so "4.2 crore" stays one sentence
    sentences = [(s, e, body) for s, e, body in _sentences(text) if len(body.split()) > 5]
    limit = understand.sentence_limit(ctx.profile)  # 22 words; looser for a policy or an internal note
    long_ones = [x for x in sentences if len(x[2].split()) > limit]
    rule = ctx.rule("voice.sentence_length")
    if long_ones and rule:
        pos, end, s = long_ones[0]
        out.append(_noted(ctx, _f(
            ctx, "readability", "readability", (pos, end, s), "definite", "low",
            [{"type": "rule", "id": rule}],
            f"Sentence is {len(s.split())} words; voice rule {rule} asks for an average under 20 words per sentence.",
        ), "voice.sentence_length"))
    words = len(text.split())
    rule = ctx.rule("social.length")
    is_social = ctx.applies("social.length") if ctx.profile else ctx.channel == "social"
    if is_social and words > 200 and rule:
        first_span = next(iter(_sentences(text)), None)
        first = first_span[2] if first_span else text[:80].strip()
        pos = first_span[0] if first_span else text.find(first)
        out.append(_noted(ctx, _f(
            ctx, "readability", "readability", (pos, pos + len(first), first),
            "definite", "low", [{"type": "rule", "id": rule}],
            f"Social posts are limited to 200 words; this draft is {words} (rule {rule}).",
        ), "social.length"))
    # a promotional social post or ad that talks pricing is a sales post: it
    # should end with a CTA (an internal note quoting a price is not)
    is_sales = re.search(r"₹|/\s*(?:month|mo|year)\b|\bplans?\b|\bpricing\b", text, re.IGNORECASE)
    has_cta = ctx.profile["has_cta"] if ctx.profile else re.search(
        r"https?://|\b(?:sign up|try|book|start (?:a|your)|learn more|register|contact|get started)\b",
        text, re.IGNORECASE)
    rule = ctx.rule("messaging.cta")
    is_selling = ctx.applies("messaging.cta") if ctx.profile else ctx.channel == "social"
    if is_selling and is_sales and not has_cta and rule:
        last = list(_sentences(text))
        s, e = (last[-1][0], last[-1][1]) if last else (0, len(text))
        while s < e and text[s].isspace():
            s += 1
        out.append(_noted(ctx, _f(
            ctx, "readability", "missing_cta", (s, e, text[s:e]),
            "consider", "low", [{"type": "rule", "id": rule}],
            f"Sales posts end with a clear call to action (rule {rule}); no link or CTA found. Add one in your own words.",
            title="No call to action",
        ), "messaging.cta"))
    return out


# ---- tone heuristics (consider tier) --------------------------------------

HARDSELL = [
    r"\bjust\s+(₹|rs\.?|inr)?\s*[\d,]+", r"grab (it|yours) now", r"don'?t miss",
    r"hurry", r"act now", r"limited time", r"only today",
]
EXCL = re.compile(r"!")


def hard_sell_fix(phrase: str) -> Optional[str]:
    """"just ₹999" -> "₹999": drop the pushy word, keep the fact. None = no
    deterministic fix (the writer rephrases)."""
    if phrase.lower().startswith("just"):
        return re.sub(r"^just\s+", "", phrase, flags=re.IGNORECASE)
    return None


def check_tone_rules(ctx: Ctx, text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    rule = ctx.rule("voice.exclamation") if ctx.applies("voice.exclamation") else None
    if len(EXCL.findall(text)) > 1 and rule:
        out.append(_noted(ctx, _f(
            ctx, "tone", "tone", (0, 0, ""), "consider", "medium",
            [{"type": "rule", "id": rule}],
            f"More than one exclamation mark in the post (voice rule {rule} allows at most one).",
            title="Tone: too many exclamation marks",
        ), "voice.exclamation"))
    rule = ctx.rule("voice.hard_sell") if ctx.applies("voice.hard_sell") else None
    for pat in HARDSELL if rule else ():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            phrase = text[m.start():m.end()]
            out.append(_noted(ctx, _f(
                ctx, "tone", "tone", (m.start(), m.end(), phrase), "consider", "medium",
                [{"type": "rule", "id": rule}],
                f'"{phrase}" reads as a hard sell (voice rule {rule}: confident, never pushy).',
                hard_sell_fix(phrase), title="Tone: hard-sell phrasing",
            ), "voice.hard_sell"))
            break
    return out
