"""Check-run orchestrator (doc Sections 6.1 step 3, 9.2, 9.7).

Order: rules before AI; rule-based checks first (fast, free, certain), then
retrospective claim checks (deterministic first, one batched AI call only for
remaining implicit claims), then citation check discards invalid findings and
tiers are assigned. If no AI provider is configured, rule-based findings still
arrive and AI checks are marked pending — never silently skipped.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List

import checkers
import claims
import contract
import gateway
import knowledge
from db import _now, gen_id, get_knowledge_version

PROMPT_VERSION = "claims@4"
CLAIM_TITLES = {"contradicted": "Contradicted claim", "outdated": "Outdated claim",
                "unsupported": "Unsupported claim"}
TONE_PROMPT_VERSION = "tone@1"

TONE_SYSTEM = (
    "You judge tone for a brand. Judge ONLY against the voice rules and examples given "
    "(never general internet style). You know nothing else about the company. "
    "Return ONLY JSON: {\"tone_findings\": [{\"span\": \"<exact substring>\", \"explanation\": \"one sentence citing the voice rule id\", \"fix\": \"<minimal replacement>\"}]}. "
    "If nothing conflicts, return an empty list. Max 2 items."
)


_CITED_ENTITY = {"fact": "fact", "rule": "rule", "pack": "rule", "term": "term"}


def _pin_citation_versions(conn: sqlite3.Connection, ws: str, citations: List[Dict[str, Any]]) -> None:
    """Record which version of each rule/fact/term a finding cites, so the
    finding keeps showing what it was checked against after later edits."""
    for c in citations:
        entity = _CITED_ENTITY.get(c.get("type"))
        if entity:
            v = knowledge.current_version(conn, ws, entity, str(c["id"]))
            if v is not None:
                c["version"] = v


def run_check(conn: sqlite3.Connection, revision_id: str) -> Dict[str, Any]:
    rev = conn.execute("SELECT * FROM revisions WHERE id = ?", (revision_id,)).fetchone()
    sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (rev["submission_id"],)).fetchone()
    ws = sub["workspace_id"]
    text = rev["content"]
    words = len(text.split())
    kv_bumped = get_knowledge_version(conn)
    ctx = checkers.Ctx(conn, revision_id, sub["channel"], sub["source_type"], kv_bumped, ws=ws)

    run_id = gen_id("run")
    conn.execute(
        "INSERT INTO check_runs (id, revision_id, started_at, status, knowledge_version) VALUES (?,?,?,?,?)",
        (run_id, revision_id, _now(), "running", kv_bumped),
    )
    ai_calls_before = gateway.successful_calls(conn)

    findings: List[Dict[str, Any]] = []
    findings += checkers.check_terminology(ctx, text)
    findings += checkers.check_readability(ctx, text)
    findings += checkers.check_tone_rules(ctx, text)
    findings += checkers.check_confidential(ctx, text)

    # claims are verified against publishable facts only: a confidential fact can
    # never support public copy, and its text must never reach an explanation or
    # an AI provider (leaks of confidential facts are check_confidential's job)
    facts = claims.visible_facts(conn, ws, include_confidential=False)

    # --- explicit claims (no AI call) -------------------------------------
    # each claim kind is enforced by a workspace rule; a retired rule = check off
    stat_rule = ctx.rule("claims.statistic")
    kind_rule = {"superlative": ctx.rule("claims.superlative"),
                 "certification": ctx.rule("claims.certification")}
    seen_spans: set = set()
    all_claim_spans: List[tuple] = []  # including supported claims
    for c in claims.find_claims(text):
        s, e = claims._widen_to_claim(text, (c["start"], c["end"]))
        span_text = text[s:e]
        if not span_text or span_text in seen_spans:
            continue
        if not kind_rule.get(c["kind"], stat_rule):
            continue
        seen_spans.add(span_text)
        all_claim_spans.append((s, e))
        numbers = claims._extract_numbers(span_text)
        key = claims._norm_claim_key(c["kind"], span_text)
        cached = claims.vcm_lookup(conn, ws, key, numbers, kv_bumped)
        op = "replace"
        if cached is not None:
            verdict, fact_ids = cached["verdict"], json.loads(cached["fact_ids"])
            explanation, suggestion = cached["explanation"], cached["suggestion"]
            op = (cached["operation"] if ("operation" in cached.keys() and cached["operation"]) else "replace")
            model_note = f'claim-memory:{cached["model"]}'
        else:
            retrieved = claims.retrieve_facts(span_text, facts)
            v = claims.classify_match(c["kind"], span_text, retrieved, cert_rule=kind_rule["certification"])
            if v["verdict"] is None:
                if c["kind"] == "superlative":
                    v = claims.superlative_verdict(span_text, retrieved, c["trigger"], rule=kind_rule["superlative"])
                else:
                    v = {"verdict": "unsupported", "fact_ids": [],
                         "explanation": f"No approved fact in the Fact Library supports this figure or claim (rule {stat_rule} requires every statistic to trace to an approved fact).",
                         "suggestion": None}
            verdict, fact_ids = v["verdict"], v["fact_ids"]
            explanation, suggestion = v["explanation"], v.get("suggestion")
            op = v.get("operation", "replace") if isinstance(v, dict) else "replace"
            claims.vcm_store(conn, ws, key, numbers, verdict, fact_ids, explanation, suggestion, "rule-patterns", op,
                              kv=kv_bumped)
            model_note = "rule-patterns+retrieval"
        if verdict == "supported":
            # verified claim: reviewer collapses it (doc 5.4 review-by-exception)
            continue
        citations = [{"type": "fact", "id": fid} for fid in fact_ids]
        rule = kind_rule.get(c["kind"], stat_rule)
        if c["kind"] in kind_rule or not citations:
            citations.append({"type": "rule", "id": rule})
        findings.append({
            "id": gen_id("fnd"), "revision_id": revision_id, "checker": "claims",
            "category": verdict + "_claim", "span": {"start": s, "end": e, "text": span_text},
            "tier": claims.tier_for("claims", verdict), "severity":
                "high" if verdict in ("contradicted", "outdated") else "medium",
            "citations": citations, "explanation": explanation,
            "suggestion": {"replace": suggestion, "operation": op} if (suggestion or op != "replace") else None,
            "title": CLAIM_TITLES.get(verdict, "Claim issue"),
            "provenance": {"model": model_note, "prompt_version": PROMPT_VERSION,
                           "knowledge_version": kv_bumped},
        })

    # --- AI: implicit claims + tone (one batched call each, strict JSON) ----
    def budget_left() -> bool:
        return gateway.call_budget_ok(words, gateway.successful_calls(conn) - ai_calls_before)

    ai_pending = False
    budget = budget_left()
    providers = gateway.any_available()
    implicit = claims.ai_implicit_claims(text, budget, conn) if providers else None
    if implicit is None and providers and not budget:
        ai_pending = True
    if implicit:
        verified = claims.ai_verify_claims(
            text, [{"snippet": i["claim"]} for i in implicit], facts, budget_left(), conn)
        for v in verified:
            if v["verdict"] == "supported":
                continue
            pos = text.find(v["snippet"])
            cits = [{"type": "fact", "id": fid} for fid in v["fact_ids"]]
            if not cits and stat_rule:
                cits = [{"type": "rule", "id": stat_rule}]
            if not cits:
                continue  # the statistic rule is retired: nothing to cite, no finding
            findings.append({
                "id": gen_id("fnd"), "revision_id": revision_id, "checker": "claims",
                "category": v["verdict"] + "_claim",
                "span": {"start": pos, "end": pos + len(v["snippet"]), "text": v["snippet"]},
                "tier": claims.tier_for("claims", v["verdict"]),
                "severity": "high" if v["verdict"] in ("contradicted", "outdated") else "medium",
                "citations": cits, "explanation": v["explanation"],
                "suggestion": {"replace": v["suggestion"], "operation": "replace"} if v.get("suggestion") else None,
                "title": CLAIM_TITLES.get(v["verdict"], "Claim issue"),
                "provenance": {"model": v["model"], "prompt_version": PROMPT_VERSION,
                               "knowledge_version": kv_bumped},
            })
    elif implicit is None:
        ai_pending = True  # no provider or call refused: implicit checks pending ([] = ran, found none)

    tone_rule = ctx.rule("voice.tone")
    if providers and tone_rule:
        tone_out = gateway.gateway_call(
            "tone_check",
            [{"role": "system", "content": TONE_SYSTEM},
             {"role": "user", "content":
              "VOICE RULES:\n" + "\n".join(
                  f'{r["id"]}: {r["statement"]} [do: {r["do_example"] or "-"} | don\'t: {r["dont_example"] or "-"}]'
                  for r in conn.execute(
                      "SELECT id, statement, do_example, dont_example FROM rules "
                      "WHERE workspace_id = ? AND category = 'Voice' AND status='approved'",
                      (ws,)).fetchall())
              + "\n\nCONTENT:\n" + text}],
            conn=conn, budget_ok=budget_left(), prompt_version=TONE_PROMPT_VERSION,
        )
        if not tone_out:
            ai_pending = True  # provider listed but the tone call failed or was over budget
        else:
            data = gateway.parse_json_out(tone_out["text"])
            for t in (data or {}).get("tone_findings", [])[:2]:
                span_text = t.get("span", "")
                if span_text and span_text in text:
                    pos = text.find(span_text)
                    findings.append({
                        "id": gen_id("fnd"), "revision_id": revision_id, "checker": "tone",
                        "category": "tone",
                        "span": {"start": pos, "end": pos + len(span_text), "text": span_text},
                        "tier": "consider", "severity": "medium",
                        "citations": [{"type": "rule", "id": tone_rule}],
                        "explanation": t.get("explanation", "Tone conflicts with the brand voice rules."),
                        "suggestion": {"replace": t.get("fix"), "operation": "replace"} if t.get("fix") else None,
                        "title": "Tone: judgement call",
                        "provenance": {"model": tone_out["model"], "prompt_version": TONE_PROMPT_VERSION,
                                       "knowledge_version": kv_bumped},
                    })

    # claims are more specific: drop terminology/redundant findings whose span
    # is fully covered by a claims finding (keeps exactly one row per issue)
    claims_spans = [f["span"] for f in findings if f["checker"] == "claims"]
    findings = [
        f for f in findings
        if f["checker"] != "terminology" or not any(
            c["start"] <= f["span"]["start"] and c["end"] >= f["span"]["end"]
            for c in claims_spans
        )
    ]
    # check-only terms ("trusted by" = keep only with an approved count) are
    # settled by the claim pipeline: inside any judged claim, they yield to it
    findings = [
        f for f in findings
        if f["checker"] != "terminology" or f["suggestion"] or not any(
            s <= f["span"]["start"] and e >= f["span"]["end"] for s, e in all_claim_spans
        )
    ]

    # a finding the creator disputed (or a reviewer overrode) stays decided on
    # later revisions while its span is unchanged
    decided = {
        (r["checker"], r["category"], r["span_text"]): r["status"]
        for r in conn.execute(
            "SELECT f.checker, f.category, f.span_text, f.status FROM findings f "
            "JOIN revisions v ON v.id = f.revision_id "
            "WHERE v.submission_id = ? AND v.id != ? AND f.status = 'disputed'",
            (rev["submission_id"], revision_id),
        ).fetchall()
    }

    # --- citation check (no citation, no finding) + persistence -------------
    kept, discarded = [], 0
    seen_final: set = set()
    for f in findings:
        span_text = f["span"].get("text", "")
        span_key = (span_text, f["span"].get("start"))
        if span_text and span_key in seen_final:
            discarded += 1
            continue
        f["status"] = decided.get((f["checker"], f["category"], f["span"]["text"]), "open")
        if not contract.conforms(f):
            discarded += 1
            if os.environ.get("CANON_DEBUG"):
                print("[discard:contract]", f["checker"], f["category"])
            continue
        if not claims.citation_check(conn, ws, f, text):
            discarded += 1
            if os.environ.get("CANON_DEBUG"):
                print("[discard:citation]", f["checker"], f["category"],
                      repr(f["span"].get("text", ""))[:50], [c["id"] for c in f["citations"]])
            continue
        if span_text:
            seen_final.add(span_key)
        _pin_citation_versions(conn, ws, f["citations"])
        conn.execute(
            "INSERT INTO findings (id, revision_id, checker, category, span_start, span_end, "
            "span_text, tier, severity, citations_json, explanation, suggestion_json, "
            "provenance_json, status, title) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f["id"], revision_id, f["checker"], f["category"], f["span"]["start"],
                f["span"]["end"], f["span"]["text"], f["tier"], f["severity"],
                json.dumps(f["citations"]), f["explanation"],
                json.dumps(f["suggestion"]), json.dumps(f["provenance"]),
                f["status"], f.get("title"),
            ),
        )
        kept.append(f)

    calls_after = gateway.successful_calls(conn)
    status = "ai_pending" if ai_pending else "done"
    conn.execute(
        "UPDATE check_runs SET finished_at = ?, ai_calls = ?, discarded = ?, status = ? WHERE id = ?",
        (_now(), calls_after - ai_calls_before, discarded, status, run_id),
    )
    conn.commit()
    return {"run_id": run_id, "findings": kept, "discarded": discarded, "ai_pending": ai_pending,
            "knowledge_version": kv_bumped, "ai_calls": calls_after - ai_calls_before}
