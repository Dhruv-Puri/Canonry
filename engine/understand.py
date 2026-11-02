"""Understand the content before checking it (the "understand first" step).

Every check run starts here. `profile()` reads the draft the way a reviewer
would before opening the rulebook: what format it came in, what kind of piece
it is, who it is for, what it is trying to do, and which factual claims it
makes. The reading is deterministic (channel, length, hashtags, links, prices,
imperatives, headings, quotation marks, negations); no AI is needed. When an AI
provider answers the existing claim-extraction call, it may refine `kind`,
`intent` and `summary` (`refine_with_ai`); the checks themselves are always
decided by the rule-based reading, so a result never depends on which free
model happened to answer.

Which checks apply (`decide()`), by the profile:

    check                              applies when                       why
    ---------------------------------  ---------------------------------  ------------------------------------------
    call to action (messaging.cta)     promotional social post or ad      only sales copy must tell the reader what
                                       that talks prices                  to do next
    social length (social.length)      kind is a social post              the 200-word limit is a social-post rule
    hard-sell phrasing                 intent is promotional              a hard-sell list is about selling copy
    (voice.hard_sell)
    AI tone (voice.tone) and           anything published (not an         the brand voice covers every public piece;
    exclamation marks                  internal note or a policy)         the AI catches pushiness the word list
    (voice.exclamation)                                                   cannot, so it is not limited to sales copy
    sentence length                    always; limit 22 words, 30 for     legal and internal writing is judged less
    (voice.sentence_length)            an internal note, 35 for a policy  strictly than marketing copy
    India advertising pack             anything published except a        the CCPA/ASCI rules govern advertising and
    (compliance)                       policy or legal text               marketing communication; an internal note
                                                                          is not published and a policy is not an ad
    claims, terms, confidential,       always                             a wrong fact or a leaked figure is wrong
    images                                                                wherever it appears

Claims are read in context (`claim_context()`): a claim that is negated ("we
never claim to be #1") or put in someone else's mouth ("competitors say they
are the best") is not our claim and is not flagged; a claim inside quotation
marks may be someone else's words, so it is kept but lowered to Consider with
a plain explanation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import claims as _claims

KINDS = {
    "social_post": "social post",
    "ad": "ad",
    "email": "email",
    "article": "blog post or article",
    "press_release": "press release",
    "landing_page": "landing or product page",
    "internal_note": "internal note or brief",
    "policy": "policy or legal text",
    "other": "piece of content",
}
INTENTS = ("promotional", "informational", "internal")
AUDIENCES = ("customers", "partners", "internal")
FORMATS = {
    "text": "text",
    "pdf": "PDF",
    "word": "Word document",
    "image_with_words": "image with words in it",
    "image_without_words": "image without words",
}
CLAIM_LABELS = {
    "superlative": "ranking", "certification": "certification", "price": "price",
    "percent": "percentage", "date_claim": "date", "count": "customer count",
}

# ---- signals ----------------------------------------------------------------

_INTERNAL = re.compile(
    r"\b(?:internal\s+(?:note|memo|brief|use|only|draft)|for\s+internal\s+use"
    r"|do\s+not\s+(?:publish|share|forward|post)|not\s+for\s+(?:publication|external|public|release)"
    r"|team\s+(?:note|update|sync)|meeting\s+notes|action\s+items|(?:creative|campaign|content)\s+brief"
    r"|hi\s+team|hey\s+team|fyi)\b", re.IGNORECASE)
_POLICY_TITLE = re.compile(
    r"\b(?:privacy\s+policy|cookie\s+policy|refund\s+policy|terms\s+of\s+(?:service|use)|terms\s+and\s+conditions"
    r"|data\s+processing\s+agreement|acceptable\s+use\s+policy|end\s+user\s+licen[cs]e)\b", re.IGNORECASE)
_LEGAL = re.compile(
    r"\b(?:shall|hereinafter|pursuant\s+to|governing\s+law|liabilit(?:y|ies)|indemnif\w*|warrant(?:y|ies)"
    r"|grievance\s+officer|personal\s+data|data\s+principal|termination|jurisdiction)\b", re.IGNORECASE)
_PRESS_STRONG = re.compile(r"\b(?:for\s+immediate\s+release|press\s+release|media\s+contact|press\s+contact)\b",
                           re.IGNORECASE)
_PRESS_WEAK = re.compile(r"\b(?:today\s+announced|announced\s+today|about\s+[A-Z][\w ]{2,40}$)", re.MULTILINE)
_DATELINE = re.compile(r"^[A-Z][A-Z .]{2,30},\s+(?:\d{1,2}\s+)?[A-Z][a-z]+\s+\d{1,2}?,?\s*\d{4}\s*[—–-]",
                       re.MULTILINE)
_AD = re.compile(
    r"\b(?:sponsored|advertisement|shop\s+now|buy\s+now|order\s+now|\d+\s?%\s+off|sale\s+ends|offer\s+ends"
    r"|limited[- ]time\s+offer|use\s+code)\b", re.IGNORECASE)
_EMAIL = re.compile(r"^(?:subject|dear|hi|hello)\b|\bunsubscribe\b", re.IGNORECASE | re.MULTILINE)
_HASHTAG = re.compile(r"(?<![\w&])#[A-Za-z]\w+")
_URL = re.compile(r"https?://\S+|\bwww\.\S+|\b[\w-]+\.(?:com|co|in|io|ai|org|net)(?:/\S*)?", re.IGNORECASE)
# the same call-to-action words the CTA rule has always accepted, plus a few
# unambiguous ones; "start at" is a price, not a call to action
_CTA = re.compile(
    r"https?://|\b(?:sign\s+up|try|book|start\s+(?:a|your)|learn\s+more|register|contact|get\s+started"
    r"|subscribe|download|request\s+a\s+demo|shop\s+now|buy\s+now|order\s+now)\b", re.IGNORECASE)
_PRICE = re.compile(r"₹|\brs\.?\s?\d|\binr\b|/\s*(?:month|mo|year)\b|\bplans?\b|\bpricing\b", re.IGNORECASE)
_OFFER = re.compile(
    r"\b(?:free\s+trial|discount|offer|sale|limited\s+time|hurry|don'?t\s+miss|grab|act\s+now|only\s+today"
    r"|introducing|meet|launch(?:es|ed|ing)?|new)\b", re.IGNORECASE)
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S|[A-Z][^.!?\n]{2,60}$)", re.MULTILINE)
_PARTNERS = re.compile(r"\b(?:partners?|resellers?|affiliates?|agenc(?:y|ies)|distributors?)\b", re.IGNORECASE)
_EN_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are", "was", "be", "by",
            "at", "our", "your", "you", "we", "it", "this", "that", "from", "as", "not", "can", "will", "has",
            "have", "its", "their", "they", "all", "more", "new", "every", "how", "what", "who"}
_TOPICS = [
    ("pricing", re.compile(r"₹|\bprice|\bpricing\b|\bplans?\b|/\s*month\b|\bdiscount", re.IGNORECASE)),
    ("customers", re.compile(r"\bcustomers?\b|\bteams\b|\busers\b|\bclients?\b", re.IGNORECASE)),
    ("security and certification", re.compile(r"\biso\s*27001\b|\bsoc\s*2\b|\bcertif|\bsecurity\b|\bgdpr\b",
                                              re.IGNORECASE)),
    ("product launch", re.compile(r"\blaunch|\bintroducing\b|\bmeet\b|\bnew\s+version\b|\b\d+\.\d\b",
                                  re.IGNORECASE)),
    ("integrations", re.compile(r"\bintegrat", re.IGNORECASE)),
    ("reliability", re.compile(r"\buptime\b|\bsla\b|\bbackups?\b|\blatency\b", re.IGNORECASE)),
    ("people", re.compile(r"\bteam members\b|\bhiring\b|\bemployees\b|\bour people\b", re.IGNORECASE)),
    ("data privacy", re.compile(r"\bprivacy\b|\bpersonal data\b|\bdpdp\b", re.IGNORECASE)),
]

# negations that, shortly before a claim in the same clause, deny it
_NEGATION = re.compile(
    r"\b(?:never|not|no\s+longer|don'?t|do\s+not|doesn'?t|does\s+not|didn'?t|did\s+not|won'?t|will\s+not"
    r"|isn'?t|aren'?t|wasn'?t|cannot|can'?t|nor|neither)\b", re.IGNORECASE)
# someone else's claim: "competitors say they are the best"
_ATTRIBUTED = re.compile(
    r"\b(?:competitors?|rivals?|others|other\s+(?:vendors|tools|companies|platforms|brands)"
    r"|some\s+(?:vendors|tools|companies|platforms|brands)|(?:many|most)\s+(?:vendors|tools|platforms|brands))\b"
    r"[^.!?]{0,40}?\b(?:say|says|said|claim|claims|claimed|call\s+themselves|calls\s+itself|advertise|advertises"
    r"|promise|promises|boast|boasts)\b", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[.!?;\n—–]|,\s*(?:but|yet|while|whereas)\b", re.IGNORECASE)


# ---- context of a claim -------------------------------------------------------

def _clause_start(text: str, pos: int) -> int:
    start = 0
    for m in _CLAUSE_BREAK.finditer(text, 0, pos):
        # a full stop inside a number ("4.2") or a decimal version ("2.0") is not a break
        if m.group(0) == "." and m.end() < len(text) and not text[m.end()].isspace():
            continue
        start = m.end()
    return start


def _trigger_pos(text: str, start: int, end: int) -> int:
    found = _claims.find_claims(text[start:end])
    return start + found[0]["start"] if found else start


def _inside_quotes(text: str, pos: int) -> bool:
    s = text.rfind("\n", 0, pos) + 1
    before = text[s:pos]
    if before.count("“") > before.count("”"):
        return True
    return before.count('"') % 2 == 1


def claim_context(text: str, start: int, end: int) -> Optional[Dict[str, str]]:
    """Why the claim at text[start:end] may not be ours: negated, attributed to
    someone else, or quoted. None = an ordinary claim we make."""
    if not text or start < 0 or end <= start:
        return None
    trigger = _trigger_pos(text, start, end)
    clause = text[_clause_start(text, trigger):trigger]
    words = clause.split()
    near = " ".join(words[-8:])
    if _ATTRIBUTED.search(clause):
        return {"kind": "attributed",
                "why": "This describes what someone else says about themselves, not a claim you make."}
    if _NEGATION.search(near):
        return {"kind": "negated", "why": "This sentence denies the claim rather than making it."}
    if _inside_quotes(text, trigger):
        return {"kind": "quoted",
                "why": "This is inside quotation marks, so it may be someone else's words. Readers can still "
                       "take it as your claim if you publish it: keep it only if you can back it up."}
    return None


def is_claim_like(finding: Dict[str, Any]) -> bool:
    if finding.get("checker") in ("claims", "compliance"):
        return True
    if finding.get("checker") == "terminology":
        return bool(_claims.find_claims((finding.get("span") or {}).get("text") or ""))
    return False


def apply_context(findings: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """Drop claims that are negated or someone else's; lower quoted ones to Consider."""
    out = []
    for f in findings:
        span = f.get("span") or {}
        if not is_claim_like(f) or not span.get("text"):
            out.append(f)
            continue
        ctx = claim_context(text, span["start"], span["end"])
        if ctx is None:
            out.append(f)
            continue
        if ctx["kind"] in ("negated", "attributed"):
            continue
        f["tier"] = "consider"
        f["severity"] = "low"
        f["explanation"] = ctx["why"] + " " + (f.get("explanation") or "")
        f.setdefault("provenance", {})["context"] = "quoted"
        out.append(f)
    return out


# ---- the profile ----------------------------------------------------------------

def _format(source_kind: str, asset_meta: Optional[Dict[str, Any]]) -> str:
    kind = (source_kind or "text").lower()
    if kind == "pdf":
        return "pdf"
    if kind in ("docx", "word"):
        return "word"
    if kind == "image":
        words = (asset_meta or {}).get("image_words") or 0
        return "image_with_words" if words else "image_without_words"
    return "text"


def _language(text: str) -> Tuple[str, Optional[str]]:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en", None
    non_latin = sum(1 for ch in letters if ord(ch) > 0x24F)
    note = ("Written mostly in a language other than English. Canonry's word lists and patterns are in "
            "English, so fewer issues may be found: read it yourself too.")
    if non_latin / len(letters) > 0.3:
        return "other", note
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) >= 12 and sum(1 for w in words if w in _EN_STOP) / len(words) < 0.08:
        return "other", note
    return "en", None


def _products(text: str, names: Iterable[str]) -> List[str]:
    found: List[Tuple[int, str]] = []
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        m = re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE)
        if m and not any(s <= m.start() < s + len(n) for s, n in found):
            found.append((m.start(), text[m.start():m.end()]))
    if not found:
        # no workspace names: a capitalised name after "Meet"/"Introducing", or two capitalised words
        m = re.search(r"\b(?:Meet|Introducing|Try)\s+([A-Z][\w-]+(?:\s+[A-Z][\w-]+){0,2})", text) or \
            re.search(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b", text)
        if m:
            found.append((m.start(1), m.group(1)))
    found.sort()
    return [n for _, n in found]


def _claims_made(text: str) -> List[Dict[str, Any]]:
    out = []
    for c in sorted(_claims.find_claims(text), key=lambda c: c["start"]):
        s, e = _claims._widen_to_claim(text, (c["start"], c["end"]))
        label = CLAIM_LABELS.get(c["kind"], "claim")
        if c["kind"] == "count" and not re.search(r"teams|customers|users|clients", text[s:e], re.IGNORECASE):
            label = "count"
        ctx = claim_context(text, s, e)
        out.append({"type": label, "text": text[s:e], "ours": ctx is None or ctx["kind"] == "quoted",
                    **({"note": ctx["why"]} if ctx else {})})
    return out


def _kind(text: str, channel: str, words: int) -> Tuple[str, str]:
    """(kind, the main reason in plain words)."""
    head = text[:400]
    title = "\n".join(text.strip().splitlines()[:2])
    if _INTERNAL.search(text):
        return "internal_note", "it says it is internal or not for publication"
    if _POLICY_TITLE.search(title) or len(set(m.group(0).lower() for m in _LEGAL.finditer(text))) >= 3:
        return "policy", "it reads like a policy or legal text"
    if _PRESS_STRONG.search(text) or (_DATELINE.search(head) and _PRESS_WEAK.search(text)):
        return "press_release", "it has the marks of a press release"
    channel = (channel or "").lower()
    if channel == "social":
        return "social_post", "it was submitted for a social channel"
    if channel == "email" or (_EMAIL.search(text) and channel not in ("web", "blog")):
        return "email", "it was submitted as an email"
    if _AD.search(text) or (channel == "sales" and words <= 80):
        return "ad", "it is short sales copy with an offer"
    if channel == "blog":
        return "article", "it was submitted for the blog"
    if channel in ("web", "sales"):
        return "landing_page", "it was submitted for a web page"
    if _HASHTAG.search(text) and words <= 280:
        return "social_post", "it uses hashtags"
    if words > 250 and len(_HEADING.findall(text)) >= 2:
        return "article", "it is long and has headings"
    return "other", "no clear signal"


def _intent(text: str, kind: str, has_cta: bool, claims_made: List[Dict[str, Any]]) -> Tuple[str, str]:
    if kind == "internal_note":
        return "internal", "it is written for the team"
    if kind == "policy":
        return "informational", "it explains rules rather than selling"
    signals = []
    if _PRICE.search(text):
        signals.append("prices")
    if has_cta:
        signals.append("a call to action")
    if _OFFER.search(text):
        signals.append("offer or launch words")
    if any(c["type"] == "ranking" and c["ours"] for c in claims_made):
        signals.append("a ranking claim")
    if _HASHTAG.search(text):
        signals.append("hashtags")
    if any(re.search(p, text, re.IGNORECASE) for p in _hard_sell_patterns()):
        signals.append("hard-sell phrasing")
    if signals:
        return "promotional", "it has " + _join(signals)
    if kind in ("ad",):
        return "promotional", "ads sell"
    return "informational", "it informs without selling"


def _hard_sell_patterns() -> List[str]:
    import checkers  # local: checkers imports this module's caller chain
    return checkers.HARDSELL


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _join(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def summarise(p: Dict[str, Any]) -> str:
    kind_label = KINDS.get(p["kind"], "piece of content")
    if p["kind"] in ("internal_note", "policy"):
        lead = f"{_article(kind_label).capitalize()} {kind_label}"
    else:
        lead = f"{_article(p['intent']).capitalize()} {p['intent']} {kind_label}"
    fmt = {"pdf": " in a PDF", "word": " in a Word file", "image_with_words": " shown as an image with words",
           "image_without_words": " shown as an image without words"}.get(p["format"], "")
    product = f" for {p['product'][0]}" if p.get("product") else ""
    ours = [c for c in p["claims"] if c["ours"]]
    if ours:
        n = len(ours)
        kinds = [f"{_article(c['type'])} {c['type']}" for c in ours]
        what = f" that makes {n} factual claim{'s' if n != 1 else ''}: {_join(kinds)}"
    else:
        what = " that makes no factual claims"
    others = len(p["claims"]) - len(ours)
    tail = (f" ({others} more {'is' if others == 1 else 'are'} denied or someone else's, so "
            f"{'it is' if others == 1 else 'they are'} not treated as yours)") if others else ""
    return f"{lead}{fmt}{product}{what}{tail}."


def profile(text: str, channel: str, source_kind: str = "text", asset_meta: Optional[Dict[str, Any]] = None,
            names: Iterable[str] = ()) -> Dict[str, Any]:
    """What this content is, in plain words, before any rule runs (no AI)."""
    text = text or ""
    words = len(text.split())
    fmt = _format(source_kind, asset_meta)
    kind, kind_why = _kind(text, channel, words)
    has_cta = bool(_CTA.search(text))
    claims_made = _claims_made(text)
    intent, intent_why = _intent(text, kind, has_cta, claims_made)
    audience = ("internal" if intent == "internal" else
                "partners" if len(_PARTNERS.findall(text)) >= 2 or re.search(r"\b(?:dear|hi)\s+partners?\b", text,
                                                                               re.IGNORECASE) else "customers")
    language, language_note = _language(text)
    p: Dict[str, Any] = {
        "version": "profile@1",
        "format": fmt, "format_label": FORMATS[fmt],
        "kind": kind, "kind_label": KINDS[kind],
        "intent": intent, "audience": audience,
        "language": language, "language_note": language_note,
        "product": _products(text, names),
        "topics": [name for name, pat in _TOPICS if pat.search(text)],
        "claims": claims_made,
        "has_cta": has_cta,
        "words": words,
        "hashtags": len(_HASHTAG.findall(text)),
        "links": len(_URL.findall(text)),
        "why": {"kind": kind_why, "intent": intent_why},
        "decided_by": "rules",
    }
    p["summary"] = summarise(p)
    p["checks"] = [{"check": k, "applies": a, "why": w} for k, (a, w) in decide(p).items()]
    return p


# ---- which checks apply ----------------------------------------------------------

def decide(p: Dict[str, Any]) -> Dict[str, Tuple[bool, str]]:
    """check key -> (applies, plain reason). See the module docstring's table."""
    kind, intent = p["kind"], p["intent"]
    label = KINDS.get(kind, "piece of content")
    promo = intent == "promotional"
    public = kind not in ("internal_note", "policy")
    return {
        "messaging.cta": (promo and kind in ("social_post", "ad"),
                          f"Call to action is checked on promotional social posts and ads; this is "
                          f"{_article(intent)} {intent} {label}."),
        "social.length": (kind == "social_post",
                          f"The social-post length limit applies to social posts; this is {_article(label)} {label}."),
        "voice.hard_sell": (promo, f"Hard-sell phrasing is checked on promotional copy; this is {intent}."),
        "voice.tone": (public, f"The AI tone check runs on anything published, where pushiness can hide in "
                               f"plain words; this is {_article(label)} {label}."),
        "voice.exclamation": (public, f"Exclamation marks are checked on anything published; this is "
                                      f"{_article(label)} {label}."),
        "voice.sentence_length": (True, f"Sentences over {sentence_limit(p)} words are flagged for "
                                        f"{_article(label)} {label}."),
        "india_pack": (public, f"The India advertising pack checks published marketing; this is "
                               f"{_article(label)} {label}."),
    }


def sentence_limit(p: Optional[Dict[str, Any]]) -> int:
    kind = (p or {}).get("kind")
    return {"policy": 35, "internal_note": 30}.get(kind, 22)


def applies(p: Optional[Dict[str, Any]], check: str) -> Tuple[bool, str]:
    """Does `check` apply under profile `p`? No profile = everything applies (old behaviour)."""
    if not p:
        return True, ""
    return decide(p).get(check, (True, ""))


# ---- AI refinement (folded into the claim-extraction call) --------------------------

AI_PROFILE_INSTRUCTION = (
    " Also describe the content in a \"profile\" object: {\"kind\": one of "
    + ", ".join(KINDS) + ", \"intent\": one of " + ", ".join(INTENTS)
    + ", \"summary\": one plain sentence a newcomer understands}."
)


def valid_ai_profile(data: Any) -> Optional[Dict[str, str]]:
    """The AI's profile answer if its shape is exactly what was asked; else None."""
    if not isinstance(data, dict):
        return None
    raw = data.get("profile")
    if not isinstance(raw, dict):
        return None
    out: Dict[str, str] = {}
    kind, intent, summary = raw.get("kind"), raw.get("intent"), raw.get("summary")
    if isinstance(kind, str) and kind.strip().lower() in KINDS:
        out["kind"] = kind.strip().lower()
    if isinstance(intent, str) and intent.strip().lower() in INTENTS:
        out["intent"] = intent.strip().lower()
    if isinstance(summary, str) and 10 <= len(summary.strip()) <= 300 and "\n" not in summary.strip():
        out["summary"] = summary.strip()
    return out or None


def refine_with_ai(p: Dict[str, Any], ai: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Fold the AI's reading into the profile. The checks already ran on the rule
    reading; when the AI disagrees, both readings are kept so a reviewer sees it."""
    if not ai:
        return p
    rules_view = {"kind": p["kind"], "intent": p["intent"], "summary": p["summary"]}
    for key in ("kind", "intent", "summary"):
        if key in ai:
            p[key] = ai[key]
    p["kind_label"] = KINDS.get(p["kind"], p.get("kind_label"))
    p["decided_by"] = "rules+ai"
    if p["kind"] != rules_view["kind"] or p["intent"] != rules_view["intent"]:
        p["rules_view"] = rules_view
    return p
