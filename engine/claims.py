"""Claim pipeline (Improvements 1 & 3, doc Sections 8, 9.2, 5.4).

Find every factual/promotional claim, retrieve approved facts, label each claim
supported / contradicted / outdated / unsupported, then run the citation check
and tier assignment. Rules and open-source patterns do the explicit claims with
zero AI calls; the AI only catches remaining implicit claims in one batched
call, in strict structured output. Verified Claim Memory stores verdicts keyed
by exact numbers/units/names/dates so repeat claims confirm instantly.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import gateway
from db import _now, gen_id


# ---- claim patterns (explicit claims; no AI call) ---------------------------

CLAIM_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("certification", re.compile(r"\bISO\s*27001\b|\bSOC\s*2\b|\bGDPR[- ]certified\b|\bHIPAA\b", re.IGNORECASE)),
    ("superlative", re.compile(
        r"#\d+\b|\bnumber\s*-?\s*one\b|\bno\.\s?1\b|\bbest[- ]in[- ]class\b|\bmost\s+trusted\b"
        r"|\b(?:the|a|india'?s|world'?s|asia'?s)\s+(?:best|leading|largest|fastest|biggest)\b(?!\s+practices?\b)",
        re.IGNORECASE)),
    ("count", re.compile(
        r"(?:trusted\s+by\s+|over\s+|more\s+than\s+)?"
        r"\d{1,3}(?:,\d{3})+(?=[\dxX\s]*\s*(?:teams|users|customers|people|employees))"
        r"|\b\d{1,6}\b\s*\+?\s*(?:teams|users|customers|people|employees)",
        re.IGNORECASE)),
    ("price", re.compile(
        r"(?:₹\s*|rs\.?\s*|inr\s*)\d[\d,]*|\d[\d,]*\s*/\s*(?:month|mo|year)"
        r"|\b(?:just|starting? at|from)\s+(?:₹|rs\.?|inr)?\s*\d[\d,]*\b", re.IGNORECASE)),
    ("percent", re.compile(r"\b\d+(?:\.\d+)?%")),
    ("date_claim", re.compile(r"\b(?:since|founded|launched(?:\s+in)?|available\s+since)\s+(?:19|20)\d{2}\b", re.IGNORECASE)),
]


def find_claims(text: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    taken: List[Tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(s < te and ts < e for ts, te in taken)

    for kind, pat in CLAIM_PATTERNS:
        for m in pat.finditer(text):
            s = m.start()
            # widen the span to a sensible claim phrase around the trigger
            start = max(0, s - 14)
            while start > 0 and re.match(r"[A-Za-z]", text[start - 1]) and not text[start - 1].isspace():
                start -= 1
            end = min(len(text), m.end())
            while end < len(text) and text[end].isalpha():
                end += 1
            snippet = text[start:end]
            if overlaps(s, m.end()):
                continue
            taken.append((s, m.end()))
            claims.append({"kind": kind, "trigger": m.group(0), "start": s,
                           "end": m.end(), "snippet": snippet})
    return claims


def _widen_to_claim(text: str, trigger_span: Tuple[int, int], left_max: int = 3) -> Tuple[int, int]:
    """Extend a trigger into a short claim phrase: at most left_max words back,
    never crossing sentence punctuation; complete the trailing word/unit."""
    s, e = trigger_span
    words = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", text)]
    if not words:
        return s, e
    idx = next((i for i, w in enumerate(words) if w[0] <= s < w[1]), None)
    if idx is None:
        return s, e
    lo, count = idx, 0
    while lo > 0 and count < left_max:
        prev = words[lo - 1][2]
        if any(ch in prev for ch in ",.;:!?()-—–") or prev.lower() in _CONJUNCTIONS:
            break
        lo -= 1
        count += 1
    start = words[lo][0]
    end = e
    while end < len(text) and text[end].isalnum():
        end += 1
    if not text[e - 1].isalpha():  # complete a trailing unit ("/month", "certified")
        m = re.match(r"(?:/\s*[A-Za-z]{1,9})?[ ]?([A-Za-z]{1,9})(?=[\s,.;:!?]|$)", text[end:end + 12])
        if m and m.group(1).lower() not in _CONJUNCTIONS:
            end += m.end()
    return start, end


_CONJUNCTIONS = {"and", "or", "but", "with", "while", "plus"}


def _extract_numbers(s: str) -> List[str]:
    # strip id-like tokens ("F-012", "X-101") so they never pollute numbers
    s = re.sub(r"\b[A-Z]{1,3}-\d+\b", " ", s)
    return re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", s.replace("+", ""))


def _significant(n: str) -> bool:
    return len(n) >= 3 or "," in n or "." in n or n.isdigit() and len(n) >= 3


def _canon_num(n: str) -> str:
    """Compare numbers by value, not formatting: 2300 and 2,300 are the same claim."""
    return n.replace(",", "")


def _norm_claim_key(kind: str, snippet: str) -> str:
    """VCM key: kind + numbers + units + names only (doc 5.4: '2,300+' never
    confirms '3,200+')."""
    numbers = sorted(set(_extract_numbers(snippet)))
    units = set()
    if kind == "price":
        units |= {"/month", "/year"} & ({u.lower() for u in snippet.split()} | {"slash"})
    keywords = re.findall(r"[A-Za-z]{3,}", snippet)
    salient = " ".join(
        k for k in keywords
        if k.lower() in ("iso", "teams", "customers", "users", "month", "year", "certified",
                         "trusted", "pulse", "insights", "quillmark")
    ).lower()
    return f"{kind}|{'|'.join(numbers)}|{salient}|{hashlib.sha1((kind + snippets_join(snippet)).encode()).hexdigest()[:8]}"


def snippets_join(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---- fact retrieval ----------------------------------------------------------

def visible_facts(conn: sqlite3.Connection, ws: str, include_confidential: bool) -> List[sqlite3.Row]:
    q = "SELECT * FROM facts WHERE workspace_id = ?"
    if not include_confidential:
        q += " AND confidential = 0"
    return conn.execute(q + " ORDER BY id", (ws,)).fetchall()


def _fact_active(f: sqlite3.Row) -> bool:
    today = date.today().isoformat()
    if f["superseded"]:
        return False
    if f["valid_from"] and f["valid_from"] > today:
        return False
    if f["valid_to"] and f["valid_to"] < today:
        return False
    return True


def retrieve_facts(claim_snippet: str, facts: List[sqlite3.Row], limit: int = 8) -> List[sqlite3.Row]:
    """Keyword + meaning-based search over approved facts (doc 9.2 step 4).
    Open-source local embeddings are an upgrade; keyword/package scoring keeps
    this free and fast for the event build."""
    kw = snippets_join(claim_snippet.lower())
    scored: List[Tuple[float, sqlite3.Row]] = []
    for f in facts:
        fk = snippets_join(f["text"].lower())
        overlap = len(set(_tokens(claim_snippet)) & set(_tokens(f["text"] + " " + f["category"])))
        same_numbers = any(
            n in fk for n in _extract_numbers(claim_snippet)
        )
        concept_bonus = 2.0 if same_numbers else 0.0
        prefix_bonus = 1.5 if fk[:6] and fk[:6] in kw or fk[:8] in kw else 0.0
        score = overlap * 1.0 + concept_bonus + prefix_bonus
        if score > 0:
            scored.append((score, f))
    scored.sort(key=lambda t: (-t[0], t[1]["id"]))
    return [f for _, f in scored[:limit]]


def _tokens(s: str) -> set:
    ignore = {"the", "a", "an", "of", "and", "in", "for", "with", "as", "on", "is", "are", "was", "were", "our", "your", "their", "it", "to", "by", "at", "from", "we", "who", "new"}
    SYNONYMS = {"teams": "customers", "customers": "teams", "users": "customers", "clients": "customers"}
    toks = {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in ignore}
    toks |= {SYNONYMS[w] for w in toks if w in SYNONYMS}
    return toks


# ---- verification ------------------------------------------------------------

def classify_match(claim_kind: str, snippet: str, facts: List[sqlite3.Row],
                   cert_rule: Optional[str] = None) -> Dict[str, Any]:
    """Deterministic verdict against approved facts. Returns
    {verdict, fact_ids, explanation, suggestion} or {'verdict': None}.
    `cert_rule` is the workspace rule that governs certification claims."""
    claim_numbers = _extract_numbers(snippet)
    today = date.today()
    if claim_kind == "superlative":
        return {"verdict": None}  # decided by policy, not number-matching
    shared_nums = [n for n in claim_numbers if _significant(n)]

    for f in facts:
        fn = _extract_numbers(f["text"])
        shared = [c for c in shared_nums if any(_canon_num(c) == _canon_num(x) for x in fn)]
        if not shared and claim_kind not in ("superlative", "certification"):
            continue
        active = _fact_active(f)
        legacy = f["id"].startswith("X-")
        expired = (f["valid_to"] or "") and f["valid_to"] < today.isoformat()
        if claim_kind == "certification":
            cert_active = "iso" in f["text"].lower() or "soc" in f["text"].lower()
            if not cert_active:
                continue
            if expired or legacy or "expired" in f["text"].lower():
                return (
                    {"verdict": "outdated", "fact_ids": [f["id"]], "operation": "remove",
                     "explanation": f'Certificate status: {f["text"]} (fact {f["id"]}); rule {cert_rule or "on certifications"} only allows certifications that are current. Remove the claim until renewal is approved.',
                     "suggestion": None}
                )
            if active:
                return {"verdict": "supported", "fact_ids": [f["id"]], "explanation": "", "suggestion": None}
            return {"verdict": "outdated", "fact_ids": [f["id"]], "operation": "remove", "explanation": f'Certificate fact {f["id"]} is not currently valid.', "suggestion": None}
        if shared and legacy:
            active_same_concept = next((a for a in facts if _fact_active(a) and a["category"] == f["category"] and _tokens(f["text"]).intersection(_tokens(a["text"]))), None)
            if active_same_concept is not None:
                if claim_kind == "count":
                    acon = _extract_numbers(active_same_concept["text"])
                    return {"verdict": "contradicted", "fact_ids": [active_same_concept["id"], f["id"]],
                            "explanation": f'{active_same_concept["text"]} (fact {active_same_concept["id"]}, owner {active_same_concept["owner"]}). The value you used comes from superseded fact {f["id"]}.',
                            "suggestion": re.sub(r"\d[\d,]*", acon[0] if acon else "?", snippet, count=1) if acon else None}
                if claim_kind == "price":
                    acon = _extract_numbers(active_same_concept["text"])
                    return {"verdict": "outdated", "fact_ids": [active_same_concept["id"], f["id"]],
                            "explanation": f'Current {active_same_concept["category"]} fact: {active_same_concept["text"]} (fact {active_same_concept["id"]}, valid from {active_same_concept["valid_from"]}). Your figure comes from superseded fact {f["id"]}.',
                            "suggestion": re.sub(r"\d[\d,]*", acon[0] if acon else "?", snippet, count=1) if acon else None}
        if shared and active:
            return {"verdict": "supported", "fact_ids": [f["id"]], "explanation": "", "suggestion": None}

    # active fact exists in concept but different number -> contradicted
    if claim_kind in ("count", "price"):
        concept_tokens = _tokens(snippet)
        for f in facts:
            if not _fact_active(f):
                continue
            f_tokens = _tokens(f["text"])
            if len(concept_tokens & f_tokens) >= 2 and not any(
                _canon_num(n) == _canon_num(x)
                for n in _extract_numbers(snippet) for x in _extract_numbers(f["text"])
            ):
                if claim_kind == "count" and any(
                    ("team" in t or "customer" in t) for t in concept_tokens
                ) and any(("team" in t or "customer" in t) for t in f_tokens):
                    return {"verdict": "contradicted", "fact_ids": [f["id"]],
                            "explanation": f'{f["text"]} (fact {f["id"]}, owner {f["owner"]}, valid to {f["valid_to"]}).',
                            "suggestion": re.sub(r"\d[\d,]*", _extract_numbers(f["text"])[0] if _extract_numbers(f["text"]) else "?", snippet, count=1)}
    return {"verdict": None}


def superlative_verdict(snippet: str, facts: List[sqlite3.Row], trigger: str = "",
                        rule: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Superlatives: Likely — no approved source exists behind it (the workspace's
    superlative rule; India pack CCPA)."""
    fix = superlative_fix(snippet, trigger)
    return {"verdict": "unsupported", "fact_ids": [], "operation": "replace" if fix else "remove",
            "explanation": f'No approved source supports this superlative claim (rule {rule or "on superlatives"}; India pack: CCPA 2022 requires substantiation). Drop the ranking claim or use the approved customer-count phrasing from the Fact Library.',
            "suggestion": fix}


def superlative_fix(snippet: str, trigger: str) -> Optional[str]:
    """Minimal fix: remove the ranking words (and an owner like "India's"),
    keep the noun: "India's #1 analytics" -> "an analytics"."""
    if not trigger or trigger not in snippet:
        return None
    before, after = snippet.split(trigger, 1)
    before_words = before.split()
    dropped_owner = bool(before_words) and re.search(r"'s$", before_words[-1]) is not None
    if dropped_owner:
        before_words = before_words[:-1]
    if re.match(r"(?i)(the|a)\s", trigger):  # "the leading" -> keep the article
        before_words.append(trigger.split()[0])
    rest = after.strip()
    if not rest:
        return None
    if dropped_owner and (not before_words or before_words[-1].lower() not in ("a", "an", "the")):
        before_words.append("an" if rest[0].lower() in "aeiou" else "a")
    return " ".join(before_words + [rest])


# ---- Verified Claim Memory ---------------------------------------------------

def vcm_lookup(conn: sqlite3.Connection, ws: str, key: str, claim_numbers: List[str], kv: int):
    """Reuse a stored verdict only when numbers/units/names match exactly and it
    was reached against the same knowledge version (plan: "cache by version")."""
    row = conn.execute(
        "SELECT * FROM claim_memory WHERE workspace_id = ? AND claim_norm = ? AND knowledge_version = ?",
        (ws, key, kv),
    ).fetchone()
    if not row:
        return None
    stored = set(json.loads(row["numbers_json"]))
    if stored != set(claim_numbers):
        return None  # never reuse across different numbers
    conn.execute("UPDATE claim_memory SET created_at = ? WHERE id = ?", (_now(), row["id"]))
    conn.commit()
    return row


def vcm_store(conn: sqlite3.Connection, ws: str, key: str, numbers: List[str], verdict: str,
              fact_ids: List[str], explanation: str, suggestion: Optional[str], model: str,
              operation: Optional[str] = None, *, kv: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO claim_memory (id, workspace_id, claim_norm, numbers_json, verdict, fact_ids, explanation, suggestion, operation, model, created_at, knowledge_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (gen_id("vcm"), ws, key, json.dumps(list(set(numbers))), verdict,
         json.dumps(fact_ids), explanation, suggestion, operation, model, _now(), kv),
    )
    conn.commit()


# ---- AI: implicit claims + verification (batched, strict JSON) ---------------

IMPLICIT_PROMPT_VERSION = "claims@4"

CLAIM_EXTRACT_SYSTEM = (
    "You are a brand-compliance claim extractor. From the submitted content, list IMPLICIT "
    "promotional or factual claims that make a statement a company must stand behind "
    "(quality, ranking, results, guarantees, certifications, comparisons, adjectives with factual weight). "
    "Do NOT include simple descriptions, opinions without factual weight, or questions. "
    "Each item: {claim: <exact substring of content>, .\"} "
    "Answer ONLY with JSON: {\"claims\": [{\"claim\": \"...\"}]}. Use exact substrings. Max 8 items."
)

VERIFY_SYSTEM = (
    "You verify promotional claims for a brand. You know NOTHING about the company except the "
    "approved facts provided. If no provided fact supports the claim, answer 'unsupported'. "
    "Never use outside knowledge. For each claim return verdict: supported | contradicted | outdated | unsupported, "
    "cited fact ids from the provided list, a one-sentence explanation citing fact ids, and a minimal fix "
    "(replace only the wrong words). Answer ONLY JSON: "
    '{"claims": [{"claim": "...", "verdict": "...", "fact_ids": ["F-012"], "explanation": "...", "fix": "..."}]}'
)


def ai_implicit_claims(text: str, budget_ok: bool, conn: sqlite3.Connection) -> Optional[List[Dict[str, str]]]:
    out = gateway.gateway_call(
        "extract_implicit_claims",
        [{"role": "system", "content": CLAIM_EXTRACT_SYSTEM},
         {"role": "user", "content": text[:4000]}],
        conn=conn, budget_ok=budget_ok,
    )
    if out is None:
        return None
    data = gateway.parse_json_out(out["text"])
    if not data or not isinstance(data.get("claims"), list):
        return None
    valid: List[Dict[str, str]] = []
    for c in data["claims"][:8]:
        claim = str(c.get("claim", "")).strip()
        if claim and claim in text:  # position validated against original text
            valid.append({"claim": claim, "start": text.find(claim)})
    return valid


def ai_verify_claims(text: str, pending: List[Dict[str, Any]], facts: List[sqlite3.Row],
                     budget_ok: bool, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    facts_blob = "\n".join(
        f'{f["id"]}: {f["text"]} (valid {f["valid_from"] or "?"} to {f["valid_to"] or "?"})'
        for f in facts[:40]
    )
    out = gateway.gateway_call(
        "verify_claims",
        [{"role": "system", "content": VERIFY_SYSTEM},
         {"role": "user", "content": "APPROVED FACTS:\n" + facts_blob + "\n\nCLAIMS:\n" +
          "\n".join("- " + c["snippet"] for c in pending)}],
        conn=conn, budget_ok=budget_ok,
    )
    if out is None:
        return []
    data = gateway.parse_json_out(out["text"])
    results = []
    if data and isinstance(data.get("claims"), list):
        known_ids = {f["id"] for f in facts}
        for c in data["claims"]:
            snippet = c.get("claim")
            if not snippet or snippet not in text:
                continue  # invalid span -> discarded
            fact_ids = [i for i in (c.get("fact_ids") or []) if i in known_ids]
            results.append({
                "snippet": snippet, "verdict": str(c.get("verdict", "unsupported")),
                "fact_ids": fact_ids, "explanation": c.get("explanation", ""),
                "suggestion": c.get("fix"), "model": out["model"],
            })
    return results


# ---- citation check & tiers (doc 9.2 steps 5-7; Improvement 3) ----------------

def citation_check(conn: sqlite3.Connection, ws: str, finding: Dict[str, Any], text: str) -> bool:
    """A finding whose citation does not exist, is inactive, or does not match
    the text is discarded."""
    for c in finding.get("citations", []):
        if c["type"] == "fact":
            row = conn.execute(
                "SELECT id, superseded, valid_from, valid_to, confidential FROM facts WHERE id = ? AND workspace_id = ?",
                (c["id"], ws),
            ).fetchone()
            if not row:
                return False
            # the fact must be real; an expired/superseded fact may only be
            # cited as evidence BY an outdated/contradicted finding itself
            if not _fact_active(row) and finding.get("category") not in (
                "outdated_claim", "outdated_term", "contradicted_claim",
                "outdated_name", "outdated_price",
            ):
                return False
        elif c["type"] == "rule":
            row = conn.execute(
                "SELECT id FROM rules WHERE id = ? AND workspace_id = ? AND status = 'approved'",
                (c["id"], ws),
            ).fetchone()
            if not row:
                return False
        elif c["type"] == "pack":
            row = conn.execute(
                "SELECT id FROM rules WHERE id = ? AND workspace_id = ?",
                (c["id"], ws),
            ).fetchone()
            if not row:
                return False
    span = finding.get("span") or {}
    t = span.get("text") or ""
    if t and t not in text:
        return False
    return True


def tier_for(checker: str, verdict: str, severities_based_on: Any = None) -> str:
    """Objective, data-contradicted issues = definite. Policy-only judgements =
    likely. Tone = consider (doc Section 5.2 principle 3 / Section 8)."""
    if checker == "tone":
        return "consider"
    if verdict in ("supported",):
        return "definite"
    if verdict in ("contradicted", "outdated"):
        return "definite"
    if verdict == "unsupported":
        return "likely"
    return "likely"
