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
import time
import traceback
from typing import Any, Dict, List, Optional

import assets
import checkers
import claims
import compliance
import consistency
import contract
import documents
import gateway
import images
import knowledge
import quota
import understand
import vision
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


def _is_ai_finding(provenance: Dict[str, Any]) -> bool:
    model = provenance.get("model") or ""
    return bool(model) and not model.startswith(("rule-patterns", "claim-memory:"))


def _carried_ai_findings(conn: sqlite3.Connection, prev_revision_id: str, revision_id: str,
                         text: str) -> List[Dict[str, Any]]:
    """The previous revision's AI findings whose flagged text is still in `text`,
    re-anchored on the new revision. Resolving one finding changes one phrase;
    the AI's judgement of the rest of the copy still stands."""
    out: List[Dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM findings WHERE revision_id = ? AND status IN ('open', 'disputed')",
                          (prev_revision_id,)).fetchall():
        prov = json.loads(r["provenance_json"] or "{}")
        span = r["span_text"] or ""
        if not _is_ai_finding(prov) or not span or span not in text:
            continue
        starts, i = [], text.find(span)
        while i >= 0:
            starts.append(i)
            i = text.find(span, i + 1)
        start = min(starts, key=lambda s: abs(s - (r["span_start"] or 0)))
        out.append({
            "id": gen_id("fnd"), "revision_id": revision_id, "checker": r["checker"], "category": r["category"],
            "span": {"start": start, "end": start + len(span), "text": span},
            "tier": r["tier"], "severity": r["severity"], "citations": json.loads(r["citations_json"] or "[]"),
            "explanation": r["explanation"], "suggestion": json.loads(r["suggestion_json"] or "null"),
            "title": r["title"], "provenance": prov,
        })
    return out


def _ai_reason_of(conn: sqlite3.Connection, revision_id: str) -> Optional[str]:
    """Why the AI checks of `revision_id` didn't run (None = they did)."""
    row = conn.execute("SELECT status, ai_reason FROM check_runs WHERE revision_id = ? "
                       "ORDER BY started_at DESC LIMIT 1", (revision_id,)).fetchone()
    if row is None or row["status"] not in ("done", "ai_pending"):
        return "provider_unavailable"  # never finished: no AI result to keep
    return row["ai_reason"]


def _names(conn: sqlite3.Connection, ws: str) -> List[str]:
    """Product and company names the workspace's terms know (current and retired)."""
    names: List[str] = []
    for t in conn.execute("SELECT preferred, banned_or_check FROM terms WHERE workspace_id = ? AND status = 'active'",
                          (ws,)).fetchall():
        for n in [t["preferred"] or ""] + (t["banned_or_check"] or "").split(","):
            n = n.strip()
            if len(n.split()) >= 2 and all(w[:1].isupper() for w in n.split()):
                names.append(n)
    return names


def _asset_meta(conn: sqlite3.Connection, asset_id: Optional[str], source_kind: str,
                locator_map: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the profile needs to know about an uploaded file."""
    meta: Dict[str, Any] = {}
    if source_kind == "image":
        meta["image_words"] = sum(1 for b in locator_map or [] if b.get("region") == images.IMAGE_TEXT_REGION)
    if asset_id:
        row = assets.get_asset(conn, asset_id) or {}
        meta.update({k: row.get(k) for k in ("filename", "page_count", "alt_text") if row.get(k) is not None})
    return meta


def _previous_ai_profile(conn: sqlite3.Connection, revision_id: str) -> Dict[str, Any]:
    """The AI's reading of the previous revision (a resolve re-check makes no AI call).
    Its summary counted the old claims, so only kind and intent carry over."""
    row = conn.execute("SELECT profile_json FROM check_runs WHERE revision_id = ? ORDER BY started_at DESC LIMIT 1",
                       (revision_id,)).fetchone()
    try:
        prev = json.loads(row["profile_json"]) if row and row["profile_json"] else {}
    except (TypeError, ValueError):
        return {}
    if prev.get("decided_by") != "rules+ai":
        return {}
    return {k: prev[k] for k in ("kind", "intent") if k in prev}


def _previous_vision(conn: sqlite3.Connection, revision_id: str) -> Optional[Dict[str, Any]]:
    """The image reading stored with the previous revision's check (resolve re-checks make no AI call)."""
    row = conn.execute("SELECT vision_json FROM check_runs WHERE revision_id = ? ORDER BY started_at DESC LIMIT 1",
                       (revision_id,)).fetchone()
    try:
        return json.loads(row["vision_json"]) if row and row["vision_json"] else None
    except (TypeError, ValueError):
        return None


def run_check(conn: sqlite3.Connection, revision_id: str, actor: Optional[str] = None,
              reuse_ai_from: Optional[str] = None) -> Dict[str, Any]:
    """Check one revision. `actor` (an email) is charged one AI try if a provider answers.
    `reuse_ai_from` (a previous revision id) skips the AI calls and carries that
    revision's AI findings forward: resolving a finding re-checks instantly."""
    rev = conn.execute("SELECT * FROM revisions WHERE id = ?", (revision_id,)).fetchone()
    sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (rev["submission_id"],)).fetchone()
    ws = sub["workspace_id"]
    text = rev["content"]
    source_kind = (rev["source_kind"] if "source_kind" in rev.keys() else None) or "text"
    asset_id = rev["asset_id"] if "asset_id" in rev.keys() else None
    try:
        locator_map = json.loads(rev["locator_map_json"] or "[]") if "locator_map_json" in rev.keys() else []
    except (TypeError, ValueError):
        locator_map = []
    words = len(text.split())
    kv_bumped = get_knowledge_version(conn)
    ctx = checkers.Ctx(conn, revision_id, sub["channel"], sub["source_type"], kv_bumped, ws=ws)
    # understand first: what this content is decides which checks apply and how
    profile = understand.profile(text, sub["channel"], source_kind,
                                 _asset_meta(conn, asset_id, source_kind, locator_map), names=_names(conn, ws))
    ctx.profile = profile

    run_id = gen_id("run")
    conn.execute(
        "INSERT INTO check_runs (id, revision_id, started_at, status, knowledge_version, by_user) VALUES (?,?,?,?,?,?)",
        (run_id, revision_id, _now(), "running", kv_bumped, actor),
    )
    ai_calls_before = gateway.successful_calls(conn)

    findings: List[Dict[str, Any]] = []
    findings += checkers.check_terminology(ctx, text)
    findings += checkers.check_readability(ctx, text)
    findings += checkers.check_tone_rules(ctx, text)
    findings += checkers.check_confidential(ctx, text)

    # image checkers work on the uploaded pixels, not the alt text
    image_raw: Optional[bytes] = None
    asset_row: Dict[str, Any] = {}
    if asset_id and source_kind == "image":
        raw = assets.asset_bytes(conn, asset_id)
        asset_row = assets.get_asset(conn, asset_id) or {}
        image_raw = raw
        if raw:
            try:
                with images.PIXEL_WORK:
                    findings += images.check_image(ctx, raw, asset_row.get("alt_text"),
                                                   asset_id, asset_row.get("filename") or "",
                                                   ocr_result=assets.image_ocr(asset_row))
            except images.ImageError as exc:
                if os.environ.get("CANON_DEBUG"):
                    print("[image skip]", exc)

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
    ai_deadline = gateway.ai_deadline()

    vision_calls = 0  # the image call has its own place: it never uses up the text checks' budget

    def budget_left() -> bool:
        return time.monotonic() < ai_deadline and gateway.call_budget_ok(
            words, gateway.successful_calls(conn) - ai_calls_before - vision_calls)

    # why the AI checks did not (fully) run; None = they ran. Checked in order: a
    # provider exists, then the daily allowance (quota.py), then each call's answer
    ai_reason: Optional[str]
    if reuse_ai_from:
        # resolving one finding: keep the AI's still-valid findings, skip the calls
        findings += _carried_ai_findings(conn, reuse_ai_from, revision_id, text)
        ai_reason = _ai_reason_of(conn, reuse_ai_from)
    else:
        ai_reason = None if gateway.any_available() else "no_provider"
        if ai_reason is None:
            ai_reason = quota.blocked(conn, ws, actor)
    use_ai = ai_reason is None and not reuse_ai_from

    def missed() -> None:  # an AI call gave no usable answer
        nonlocal ai_reason
        if ai_reason is None:
            if time.monotonic() >= ai_deadline:
                ai_reason = "time_budget"
            elif not budget_left():
                ai_reason = "budget"
            else:
                ai_reason = "provider_unavailable"

    ai_profile: Dict[str, Any] = {}  # the AI's reading, from the claim-extraction call (no extra call)
    seen: Optional[Dict[str, Any]] = None  # what the image shows (vision.py), one call per checked image

    def ai_checks() -> None:
        nonlocal seen, vision_calls
        if use_ai and image_raw and gateway.vision_available():
            before = gateway.successful_calls(conn)
            seen = vision.ask(conn, ws, image_raw, sub["title"] or "", asset_row.get("alt_text"),
                              time.monotonic() < ai_deadline, ai_deadline)
            vision_calls = gateway.successful_calls(conn) - before
            if seen is None:
                missed()
        implicit = claims.ai_implicit_claims(text, budget_left(), conn, deadline=ai_deadline,
                                             profile_out=ai_profile) if use_ai else None
        if use_ai and implicit is None:
            missed()
        if implicit:
            verified = claims.ai_verify_claims(
                text, [{"snippet": i["claim"]} for i in implicit], facts, budget_left(), conn,
                deadline=ai_deadline)
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

        tone_rule = ctx.rule("voice.tone") if ctx.applies("voice.tone") else None
        if use_ai and tone_rule:
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
                deadline=ai_deadline,
            )
            if not tone_out:
                missed()
            else:
                items = gateway.json_list(gateway.parse_json_out(tone_out["text"]), "tone_findings") or []
                for t in items[:2]:
                    if not isinstance(t, dict):
                        continue  # the answer's shape is not trusted: malformed items are dropped
                    span_text = t.get("span")
                    if isinstance(span_text, str) and span_text and span_text in text:
                        explanation, fix = t.get("explanation"), t.get("fix")
                        t = {"explanation": explanation if isinstance(explanation, str) and explanation.strip() else
                             "Tone conflicts with the brand voice rules.",
                             "fix": fix if isinstance(fix, str) and fix.strip() else None}
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
                                           "knowledge_version": kv_bumped, "profile": ctx.why("voice.tone")},
                        })

    if use_ai:
        # Free models can take up to a minute. SQLite has one write lock for the whole
        # database, so release it while the AI thinks: the revision and the "running"
        # check row are saved now, and nobody else's write waits on this check.
        conn.commit()
        try:
            ai_checks()
        except Exception:  # noqa: BLE001 - a surprising AI answer must never cost the rule findings
            traceback.print_exc()
            missed()

    # India pack: deterministic triggers over the retrieved clause candidates. It
    # runs after claims so a legal risk cites its own clause even where a brand
    # claim already answered the factual question.
    if ctx.applies("india_pack"):
        for f in compliance.check(ctx, text):
            f["provenance"]["profile"] = ctx.why("india_pack")
            findings.append(f)

    # what the picture shows: a resolve re-check reuses the last reading (no call)
    if reuse_ai_from and image_raw:
        seen = _previous_vision(conn, reuse_ai_from)
    if seen:
        try:
            findings = consistency.merge_seen(findings, vision.findings(ctx, seen, asset_id, facts))
            vision.suggest_alt_text(findings, seen, consistency.Scanner(conn, ws, facts, ctx.rule))
        except Exception:  # noqa: BLE001 - a surprising reading must never cost the rule findings
            traceback.print_exc()

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

    # read in context: a denied or someone else's claim is not ours; a quoted one is lowered
    findings = understand.apply_context(findings, text)
    # one coherent set: one card per issue, fixes that agree, citations that match the words
    findings = consistency.merge_duplicates(findings)
    consistency.safe_fixes(consistency.Scanner(conn, ws, facts, ctx.rule), findings, text)
    consistency.cite_what_you_name(conn, ws, findings)

    if reuse_ai_from:
        ai_profile.update(_previous_ai_profile(conn, reuse_ai_from))
    profile = understand.refine_with_ai(profile, ai_profile or None)

    # a finding the creator disputed (or a reviewer overrode) stays decided on
    # later revisions while its span is unchanged
    decided = {}
    for r in conn.execute(
            "SELECT f.checker, f.category, f.span_text, f.location_key, f.status FROM findings f "
            "JOIN revisions v ON v.id = f.revision_id "
            "WHERE v.submission_id = ? AND v.id != ? AND f.status = 'disputed'",
            (rev["submission_id"], revision_id)).fetchall():
        decided[(r["checker"], r["category"], r["span_text"])] = r["status"]
        if r["location_key"]:
            decided[("key", r["location_key"])] = r["status"]

    # --- citation check (no citation, no finding) + persistence -------------
    kept, discarded = [], 0
    seen_final: set = set()
    for f in findings:
        span_text = f["span"].get("text", "")
        # Every finding gets a stable location identity before dedupe; image
        # findings have no text span, so an empty span can never merge them.
        if not f.get("locator"):
            if source_kind == "image" and locator_map:
                f["locator"] = images.locate(locator_map, f["span"]["start"], f["span"]["end"], asset_id)
            elif source_kind in ("pdf", "docx") and locator_map:
                f["locator"] = documents.locate(locator_map, f["span"]["start"], f["span"]["end"],
                                                source_kind, asset_id)
            elif span_text:
                f["locator"] = {"kind": "text", "asset_id": asset_id,
                                "char_start": f["span"]["start"], "char_end": f["span"]["end"]}
        f["location_key"] = contract.location_key(f)
        span_key = f["location_key"]
        if span_key in seen_final:
            discarded += 1
            continue
        f["status"] = decided.get(("key", f["location_key"]),
                                   decided.get((f["checker"], f["category"], f["span"]["text"]), "open")
                                   if span_text else "open")
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
        seen_final.add(span_key)
        _pin_citation_versions(conn, ws, f["citations"])
        conn.execute(
            "INSERT INTO findings (id, revision_id, checker, category, span_start, span_end, "
            "span_text, tier, severity, citations_json, explanation, suggestion_json, "
            "provenance_json, status, title, locator_json, location_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f["id"], revision_id, f["checker"], f["category"], f["span"]["start"],
                f["span"]["end"], f["span"]["text"], f["tier"], f["severity"],
                json.dumps(f["citations"]), f["explanation"],
                json.dumps(f["suggestion"]), json.dumps(f["provenance"]),
                f["status"], f.get("title"), json.dumps(f.get("locator")), f["location_key"],
            ),
        )
        kept.append(f)

    calls_after = gateway.successful_calls(conn)
    ai_pending = ai_reason is not None
    status = "ai_pending" if ai_pending else "done"
    conn.execute(
        "UPDATE check_runs SET finished_at = ?, ai_calls = ?, discarded = ?, status = ?, ai_reason = ?, "
        "profile_json = ?, vision_json = ? WHERE id = ?",
        (_now(), calls_after - ai_calls_before, discarded, status, ai_reason,
         json.dumps(profile, ensure_ascii=False), json.dumps(seen, ensure_ascii=False) if seen else None, run_id),
    )
    conn.commit()
    return {"run_id": run_id, "findings": kept, "discarded": discarded, "ai_pending": ai_pending,
            "ai_reason": ai_reason, "profile": profile,
            "knowledge_version": kv_bumped, "ai_calls": calls_after - ai_calls_before}
