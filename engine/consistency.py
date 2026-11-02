"""One coherent set of findings (live walkthrough, 2 Nov 2026).

Different checkers look at the same words, and each one alone can be right
while the set is wrong. Three passes run on every check, after the checkers
and before anything is stored:

1. `merge_duplicates` - one card per issue (B2). Findings whose spans overlap
   and that are about the same issue (same category, or the same family:
   unsupported / contradicted / outdated claims and the India pack's
   substantiation findings; tone on nested spans) become one finding: the
   highest tier, the most specific fix, every citation, and a provenance that
   lists every check that found it. Two deterministic claim findings on
   different claims are never merged, and different families stay apart (an
   outdated product name and a contradicted count in one sentence are two
   issues).
2. `safe_fixes` - fixes that agree with each other (A2). Each one-click
   replacement is applied to a copy of the text and the deterministic checks
   (terms, claim patterns against approved facts, prices, certifications,
   superlatives, hard-sell words) re-run on the words it inserts. A fix that
   would still contain a flagged issue is corrected when the correction is
   certain (the approved fact's value, the approved term), otherwise its
   one-click fix is dropped and the explanation says why.
3. `cite_what_you_name` - citation integrity (B4). A rule id named in an
   explanation that exists in the workspace is added to the citations; an id
   that does not exist is never shown.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

import checkers
import claims
import understand

TIER_RANK = {"consider": 0, "likely": 1, "definite": 2}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
FAMILY = {
    "unsupported_claim": "claim", "contradicted_claim": "claim", "outdated_claim": "claim",
    "unsubstantiated_claim": "claim", "misleading_claim": "claim",
    "banned_term": "term", "outdated_term": "term",
}


def _family(f: Dict[str, Any]) -> str:
    return FAMILY.get(f.get("category", ""), f.get("category", ""))


def _deterministic(f: Dict[str, Any]) -> bool:
    model = (f.get("provenance") or {}).get("model") or ""
    return not model or model.startswith(("rule-patterns", "claim-memory:"))


def _span(f: Dict[str, Any]) -> Tuple[int, int]:
    s = f.get("span") or {}
    return int(s.get("start") or 0), int(s.get("end") or 0)


def _overlaps(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    (s1, e1), (s2, e2) = _span(a), _span(b)
    return bool((a.get("span") or {}).get("text")) and bool((b.get("span") or {}).get("text")) \
        and s1 < e2 and s2 < e1


def _strength(f: Dict[str, Any]) -> Tuple:
    sug = f.get("suggestion") or {}
    has_fix = bool(sug.get("replace")) and sug.get("operation", "replace") == "replace" or sug.get("operation") == "remove"
    s, e = _span(f)
    return (-TIER_RANK.get(f.get("tier"), 0), f.get("checker") == "compliance", not has_fix,
            not _deterministic(f), e - s)


def _same_issue(leader: Dict[str, Any], f: Dict[str, Any]) -> bool:
    if not _overlaps(leader, f) or _family(leader) != _family(f):
        return False
    if (leader.get("locator") or {}).get("bbox"):
        return False  # image regions are located by box, not by text
    # two rule-found claims on different words are two claims ("#1" and "5,000+ teams")
    if leader["checker"] == f["checker"] == "claims" and _deterministic(leader) and _deterministic(f):
        return False
    # two India-pack findings cite different clauses on purpose
    if leader["checker"] == f["checker"] == "compliance":
        return False
    return True


def merge_duplicates(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One finding per issue on the same words (see module docstring)."""
    order = sorted(range(len(findings)), key=lambda i: _strength(findings[i]))
    leaders: List[Dict[str, Any]] = []
    members: Dict[int, List[Dict[str, Any]]] = {}
    for i in order:
        f = findings[i]
        leader = next((ld for ld in leaders if _same_issue(ld, f)), None)
        if leader is None:
            leaders.append(f)
            members[id(f)] = []
        else:
            members[id(leader)].append(f)
    kept_ids = {id(ld) for ld in leaders}
    out = []
    for f in findings:  # keep the checkers' order
        if id(f) not in kept_ids:
            continue
        group = members[id(f)]
        if group:
            _absorb(f, group)
        out.append(f)
    return out


def _absorb(leader: Dict[str, Any], group: List[Dict[str, Any]]) -> None:
    everyone = [leader] + group
    leader["tier"] = max((g["tier"] for g in everyone), key=lambda t: TIER_RANK.get(t, 0))
    leader["severity"] = max((g["severity"] for g in everyone), key=lambda s: SEVERITY_RANK.get(s, 0))
    seen = {(c.get("type"), str(c.get("id"))) for c in leader["citations"]}
    for g in group:
        for c in g.get("citations") or []:
            key = (c.get("type"), str(c.get("id")))
            if key not in seen:
                seen.add(key)
                leader["citations"].append(c)
    prov = leader.setdefault("provenance", {})
    prov["found_by"] = [{"checker": g["checker"], "model": (g.get("provenance") or {}).get("model") or "rules",
                         "category": g["category"], "span": (g.get("span") or {}).get("text", "")}
                        for g in everyone]
    prov["found_by_label"] = f"found by {len(everyone)} checks"


# ---- conflict-safe fixes -------------------------------------------------------------

Issue = Dict[str, Any]  # {"start", "end", "what", "fix": Optional[str]}


class Scanner:
    """The deterministic checks a suggested fix must pass, on any text."""

    def __init__(self, conn: sqlite3.Connection, ws: str, facts: List[sqlite3.Row],
                 rules: Callable[[str], Optional[str]]):
        self.facts = facts
        self.cert_rule = rules("claims.certification")
        self.rule_on = {k: bool(rules(k)) for k in ("claims.statistic", "claims.superlative",
                                                     "claims.certification", "voice.hard_sell")}
        self.terms = [(t["preferred"], [v.strip() for v in (t["banned_or_check"] or "").split(",") if v.strip()])
                      for t in conn.execute("SELECT preferred, banned_or_check FROM terms "
                                            "WHERE status = 'active' AND workspace_id = ?", (ws,)).fetchall()]

    def issues(self, text: str) -> List[Issue]:
        out: List[Issue] = []
        for preferred, variants in self.terms:
            if not preferred or preferred == "-":
                continue  # check-only terms are settled by the claim checks
            for v in variants:
                if v.lower() in preferred.lower():
                    continue  # the fix would contain the variant again
                for m in re.finditer(re.escape(v), text, re.IGNORECASE):
                    out.append({"start": m.start(), "end": m.end(), "what": f'uses "{m.group(0)}"',
                                "fix": preferred})
        for c in claims.find_claims(text):
            key = {"superlative": "claims.superlative", "certification": "claims.certification"}.get(
                c["kind"], "claims.statistic")
            if not self.rule_on.get(key):
                continue
            s, e = claims._widen_to_claim(text, (c["start"], c["end"]))
            snippet = text[s:e]
            if understand.claim_context(text, s, e):
                continue
            v = claims.classify_match(c["kind"], snippet, claims.retrieve_facts(snippet, self.facts),
                                      cert_rule=self.cert_rule)
            if v["verdict"] is None:
                v = claims.superlative_verdict(snippet, [], c["trigger"]) if c["kind"] == "superlative" else \
                    {"verdict": "unsupported", "suggestion": None}
            if v["verdict"] == "supported":
                continue
            what = {"superlative": "make a ranking claim no approved fact supports",
                    "certification": "claim a certification that is not current",
                    "price": "use a price that is not the approved one",
                    "count": "use a customer count that is not the approved one"}.get(
                c["kind"], "make a claim no approved fact supports")
            out.append({"start": s, "end": e, "what": f'{what} ("{snippet}")', "fix": v.get("suggestion")})
        if self.rule_on.get("voice.hard_sell"):
            for pat in checkers.HARDSELL:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    out.append({"start": m.start(), "end": m.end(), "what": f'sound pushy ("{m.group(0)}")',
                                "fix": checkers.hard_sell_fix(m.group(0))})
        return out


def _apply(text: str, start: int, end: int, repl: str) -> str:
    return text[:start] + repl + text[end:]


def correct_fix(scanner: Scanner, text: str, start: int, end: int, repl: str,
                passes: int = 5) -> Tuple[Optional[str], Optional[str]]:
    """(the replacement to offer, or None; what would still be wrong, or None).
    The replacement is corrected in place when every remaining issue has a
    certain fix; the text outside the replaced words never changes."""
    prefix, suffix = text[:start], text[end:]
    candidate = _apply(text, start, end, repl)
    for _ in range(passes):
        lo, hi = len(prefix), len(candidate) - len(suffix)
        if hi < lo or not candidate.startswith(prefix) or not candidate.endswith(suffix):
            return None, "change words outside the flagged text"
        found = [i for i in scanner.issues(candidate) if i["start"] < max(hi, lo + 1) and lo < i["end"]]
        if not found:
            return candidate[lo:hi], None
        fixable = next((i for i in found if i["fix"] is not None and candidate[i["start"]:i["end"]] != i["fix"]), None)
        if fixable is None:
            return None, found[0]["what"]
        candidate = _apply(candidate, fixable["start"], fixable["end"], fixable["fix"])
    remaining = [i for i in scanner.issues(candidate)
                 if i["start"] < len(candidate) - len(suffix) and len(prefix) < i["end"]]
    return None, remaining[0]["what"] if remaining else "keep changing"


def safe_fixes(scanner: Scanner, findings: List[Dict[str, Any]], text: str) -> None:
    """Make every one-click replacement safe to accept (module docstring, pass 2)."""
    for f in findings:
        sug = f.get("suggestion") or {}
        repl = sug.get("replace")
        span = f.get("span") or {}
        if not repl or sug.get("operation", "replace") != "replace" or not span.get("text"):
            continue
        start, end = span["start"], span["end"]
        if text[start:end] != span["text"]:
            continue
        fixed, problem = correct_fix(scanner, text, start, end, repl)
        prov = f.setdefault("provenance", {})
        if fixed is not None and fixed != repl:
            prov["fix_corrected"] = {"from": repl, "to": fixed}
            f["suggestion"] = dict(sug, replace=fixed)
            f["explanation"] = (f.get("explanation") or "").rstrip() + \
                " The suggested fix also uses the approved wording, so accepting it leaves no other issue behind."
        elif fixed is None:
            prov["fix_dropped"] = {"suggested": repl, "because": problem}
            f["suggestion"] = None
            f["explanation"] = (f.get("explanation") or "").rstrip() + \
                f" Fix in your own words: the suggested rewrite would still {problem}."


# ---- citation integrity ------------------------------------------------------------------

RULE_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,7}-\d+(?:\.\d+)*\b")
FACT_OK_CATEGORIES = ("outdated_claim", "outdated_term", "contradicted_claim", "outdated_name", "outdated_price")


def cite_what_you_name(conn: sqlite3.Connection, ws: str, findings: List[Dict[str, Any]]) -> None:
    """Every rule an explanation names is cited; a name that is not a rule (or
    an approved fact) in this workspace is taken out of the explanation."""
    rules = {r["id"] for r in conn.execute(
        "SELECT id FROM rules WHERE workspace_id = ? AND status = 'approved'", (ws,)).fetchall()}
    facts = {r["id"]: r for r in conn.execute(
        "SELECT id, superseded, valid_from, valid_to, confidential FROM facts WHERE workspace_id = ?",
        (ws,)).fetchall()}
    prefixes = {r.split("-")[0] for r in rules}
    for f in findings:
        explanation = f.get("explanation") or ""
        cited = {(c.get("type"), str(c.get("id"))) for c in f.get("citations") or []}
        unknown = []
        for rid in dict.fromkeys(RULE_ID.findall(explanation)):
            if rid in rules:
                if ("rule", rid) not in cited:
                    f["citations"].append({"type": "rule", "id": rid})
                    cited.add(("rule", rid))
            elif rid in facts:
                row = facts[rid]
                usable = not row["confidential"] and (
                    claims._fact_active(row) or f.get("category") in FACT_OK_CATEGORIES)
                if ("fact", rid) not in cited and usable:
                    f["citations"].append({"type": "fact", "id": rid})
                    cited.add(("fact", rid))
            elif (f.get("checker") != "compliance" and rid.split("-")[0] in prefixes
                  and not any(str(c.get("id")) == rid or rid in str(c.get("ref") or "") for c in f["citations"])):
                unknown.append(rid)
        if unknown:
            for rid in unknown:
                explanation = re.sub(r"\s*\(?\b(?:rule\s+)?" + re.escape(rid) + r"\b\)?", "", explanation)
            ids = [str(c["id"]) for c in f["citations"] if c.get("type") == "rule"]
            explanation = explanation.strip() or "This conflicts with your brand rules."
            if ids and not any(i in explanation for i in ids):
                explanation = explanation.rstrip(". ") + f" (rule {ids[0]})."
            f["explanation"] = explanation
            f.setdefault("provenance", {})["explanation_fixed"] = f"named {', '.join(unknown)}, not in the rulebook"
