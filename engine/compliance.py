"""India advertising compliance pack (CCPA 2022 + ASCI Code), with clause retrieval.

Two layers, on purpose:

1. **Deterministic triggers** decide the verdict. Each clause carries a small set
   of regular expressions; a match produces a finding at a fixed tier. Numbers
   and prices are never interpreted by a model, so "₹999" can never blur into
   "₹99".
2. **Retrieval** supplies the legal basis. Clauses are embedded once (local
   feature-hash embeddings by default, Gemini optionally) and stored in
   `pack_clauses`; a sentence retrieves the nearest clauses from pgvector on
   Postgres or cosine ranking on SQLite. The finding cites the exact clause,
   with its reference, source and URL.

Triggers only run over the retrieved candidates (plus keyword matches), so the
RAG layer is real: if a clause is not retrieved, it cannot produce a finding.
The pack is data (`data/compliance/india_advertising_pack.json`), so a new
market is a new pack, not a code change.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import checkers
import embeddings
from db import _now, gen_id, get_knowledge_version
from contract import location_key

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "compliance")
PACK_FILE = os.path.join(DATA_DIR, "india_advertising_pack.json")
EVAL_FILE = os.path.join(DATA_DIR, "india_eval.jsonl")
PACK_ID = "in_advertising"
FIX_BY_CATEGORY = {
    "bait_advertising": "State the actual quantity and the date the offer ends.",
    "surrogate_advertising": "Remove the indirect reference to the restricted product, or stop advertising it.",
    "free_claim": "Remove 'free' or state the direct cost the consumer must pay.",
    "children_directed": "Remove the pressure to buy or collect; address the adult purchaser instead.",
    "missing_disclosure": "Put the actual conditions in the advertisement, not just 'conditions apply'.",
    "unsubstantiated_claim": "Replace the absolute claim with a result you can substantiate from an approved fact.",
    "misleading_claim": "State the range or the fixed benefit, and qualify the promise.",
    "endorsement_disclosure": "Disclose the material connection and the basis of the endorsement.",
    "comparative_advertising": "Name the like-for-like basis and cite the substantiation, or drop the comparison.",
}


def load_pack(path: str = PACK_FILE) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _clause_version(conn, clause_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) v FROM pack_clauses WHERE id = ?", (clause_id,)).fetchone()
    return int(row["v"] or 0) if row else 0


def ensure_pack(conn, workspace_id: str, pack_path: str = PACK_FILE) -> Dict[str, Any]:
    """Install or upgrade the pack. Idempotent; a changed clause becomes a new
    version, so findings keep citing the text that was in force when checked."""
    pack = load_pack(pack_path)
    existing = conn.execute("SELECT * FROM compliance_packs WHERE id = ?", (pack["id"],)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO compliance_packs (id, name, version, source, description, url, active, created_at) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (pack["id"], pack["name"], pack["version"], pack["source"],
             pack.get("description", ""), pack.get("url", ""), _now()),
        )
    else:
        conn.execute(
            "UPDATE compliance_packs SET name=?, version=?, source=?, description=?, url=? WHERE id=?",
            (pack["name"], pack["version"], pack["source"], pack.get("description", ""),
             pack.get("url", ""), pack["id"]),
        )
    installed = 0
    for clause in pack["clauses"]:
        canonical = json.dumps(clause, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = __import__("hashlib").sha256(canonical.encode("utf-8")).hexdigest()
        row = conn.execute(
            "SELECT version, content_hash FROM pack_clauses WHERE id = ? ORDER BY version DESC LIMIT 1",
            (clause["id"],)).fetchone()
        if row and row["content_hash"] == digest:
            continue
        version = (int(row["version"]) + 1) if row else 1
        vec = embeddings.cached_embed(conn, clause["text"] + " " + clause.get("heading", ""))
        conn.execute(
            "UPDATE pack_clauses SET active = 0 WHERE id = ? AND version <> ?", (clause["id"], version))
        conn.execute(
            "INSERT INTO pack_clauses (id, version, pack_id, source, ref, heading, text, url, severity, "
            "triggers_json, requirements_json, exemptions_json, embedding_json, embedding_model, "
            "content_hash, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (clause["id"], version, pack["id"], clause["source"], clause["ref"],
             clause.get("heading", ""), clause["text"], clause.get("url", ""),
             (clause.get("severity") or "medium").lower(),
             json.dumps(clause.get("triggers", [])),
             json.dumps(clause.get("requirements", [])),
             json.dumps(clause.get("exempt_if", [])),
             json.dumps(vec), embeddings.model_name(), digest, _now()),
        )
        if __import__("db").dialect() == "postgres":
            try:
                conn.execute(
                    "UPDATE pack_clauses SET embedding = ?::vector WHERE id = ? AND version = ?",
                    (embeddings.vector_literal(vec), clause["id"], version))
            except Exception:
                pass  # lexical + JSON vectors still work if pgvector is unavailable
        installed += 1
    conn.execute(
        "INSERT INTO workspace_packs (workspace_id, pack_id, active, activated_by, activated_at) "
        "VALUES (?,?,1,'system',?) ON CONFLICT (workspace_id, pack_id) DO NOTHING",
        (workspace_id, pack["id"], _now()),
    )  # an upgrade never overrides an admin who switched the pack off
    return {"pack_id": pack["id"], "version": pack["version"], "installed_clauses": installed}


def enabled_pack_versions(conn, workspace_id: str) -> Dict[str, str]:
    try:
        rows = conn.execute(
            "SELECT p.id, p.version FROM compliance_packs p JOIN workspace_packs w "
            "ON w.pack_id = p.id WHERE w.workspace_id = ? AND w.active = 1 AND p.active = 1",
            (workspace_id,)).fetchall()
        return {r["id"]: r["version"] for r in rows}
    except Exception:
        return {}


def active_clauses(conn, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT c.* FROM pack_clauses c JOIN workspace_packs w ON w.pack_id = c.pack_id "
        "WHERE w.workspace_id = ? AND w.active = 1 AND c.active = 1 ORDER BY c.source, c.ref",
        (workspace_id,)).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        for field in ("triggers_json", "requirements_json", "exemptions_json"):
            try:
                data[field[:-5]] = json.loads(data.get(field) or "[]")
            except (TypeError, ValueError):
                data[field[:-5]] = []
        out.append(data)
    return out


def _candidate_clauses(conn, workspace_id: str, sentence: str, all_clauses: List[Dict[str, Any]],
                       limit: int = 8) -> List[Dict[str, Any]]:
    """Vector top-k, unioned with clauses sharing distinctive keywords.

    The union protects recall when a regulation uses different vocabulary from
    the advertisement; ranking then decides which clause each finding cites.
    """
    retrieved = embeddings.top_clauses(conn, workspace_id, sentence, limit=limit)
    by_id = {c["id"]: c for c in all_clauses}
    out: List[Dict[str, Any]] = []
    seen = set()
    for hit in retrieved:
        clause = by_id.get(hit["id"])
        if clause is None:
            continue
        clause = dict(clause, retrieval_score=hit.get("score"))
        out.append(clause)
        seen.add(clause["id"])
    words = {w for w in re.findall(r"[a-z]{4,}", sentence.lower())
             if w not in {"this", "that", "with", "from", "your", "have", "will", "more", "than"}}
    keyword_hits = []
    for clause in all_clauses:
        if clause["id"] in seen:
            continue
        body = (clause.get("heading", "") + " " + clause.get("text", "")).lower()
        overlap = sum(1 for w in words if w in body)
        # Trigger vocabulary is the clause's own shortlist: "guaranteed" lives in
        # the substantiation trigger, not in the legal prose, and must still be able
        # to retrieve the clause that governs it.
        trigger_words = {w for t in clause.get("triggers", [])
                         for w in re.findall(r"[a-z]{4,}", (t.get("pattern") or "").lower())}
        trigger_overlap = sum(1 for w in words if w in trigger_words)
        if overlap >= 3 or trigger_overlap >= 1:
            keyword_hits.append((overlap + trigger_overlap, clause))
    keyword_hits.sort(key=lambda item: item[0], reverse=True)
    for _score, clause in keyword_hits[:3]:
        out.append(dict(clause, retrieval_score=None))
    return out


def _exempt(clause: Dict[str, Any], sentence: str) -> bool:
    for pattern in clause.get("exemptions", []):
        try:
            if re.search(pattern, sentence, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _finding(ctx, clause: Dict[str, Any], trigger: Dict[str, Any], match: re.Match,
             sentence: str) -> Dict[str, Any]:
    start, end = match.start(), match.end()
    span = match.group(0)
    tier = (trigger.get("tier") or "likely").lower()
    severity = (trigger.get("severity") or clause.get("severity") or "medium").lower()
    if severity not in ("high", "medium", "low"):
        severity = "medium"
    citation = {
        "type": "pack", "id": clause["id"], "version": clause.get("version"),
        "ref": clause.get("ref"), "source": clause.get("source"),
        "url": clause.get("url"), "excerpt": clause.get("text"),
        "active": True,
    }
    explanation = (
        f"{trigger.get('why') or 'This sentence conflicts with the clause.'} "
        f"Cited: {clause.get('source')} {clause.get('ref')} — {clause.get('heading')}."
    )
    return {
        "id": gen_id("fnd"), "revision_id": ctx.revision_id, "checker": "compliance",
        "category": trigger.get("category") or "misleading_claim",
        "span": {"start": start, "end": end, "text": span},
        "tier": tier, "severity": severity,
        "citations": [citation],
        "explanation": explanation,
        "suggestion": {"replace": FIX_BY_CATEGORY.get(trigger.get("category"), "Rewrite this sentence to comply."),
                       "operation": "rewrite"},
        "title": clause.get("heading") or "India advertising rule",
        "provenance": {"model": "rule-patterns+pgvector", "prompt_version": "compliance@1",
                       "knowledge_version": ctx.kv},
        "location_key": f"compliance|{trigger.get('category')}|{clause.get('ref')}|{start}:{span}",
    }


def check(ctx, text: str) -> List[Dict[str, Any]]:
    """Return compliance findings for `text`. Inactive packs produce nothing."""
    if not ctx.ws:
        return []
    clauses = active_clauses(ctx.conn, ctx.ws)
    if not clauses:
        return []
    findings: List[Dict[str, Any]] = []
    sentences = list(checkers._sentences(text))
    for index, (s_start, s_end, sentence) in enumerate(sentences):
        candidates = _candidate_clauses(ctx.conn, ctx.ws, sentence, clauses)
        best_by_issue: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # a qualifier often follows in the next sentence ("Win a prize? See full
        # terms at ..."), so exemptions look one sentence ahead
        following = sentences[index + 1][2] if index + 1 < len(sentences) else ""
        for clause in candidates:
            if _exempt(clause, sentence + " " + following):
                continue
            for trigger in clause.get("triggers", []):
                pattern = trigger.get("pattern") or ""
                if not pattern:
                    continue
                try:
                    match = re.search(pattern, sentence, re.IGNORECASE)
                except re.error:
                    continue
                if not match:
                    continue
                finding = _finding(ctx, clause, trigger, match, sentence)
                # absolute offsets in the whole revision
                finding["span"]["start"] += s_start
                finding["span"]["end"] += s_start
                finding["location_key"] = (
                    f"compliance|{finding['category']}|{clause.get('ref')}|"
                    f"{finding['span']['start']}:{finding['span']['text']}"
                )
                key = (finding["category"], str(clause.get("ref")))
                prev = best_by_issue.get(key)
                if prev is None or _tier_rank(finding["tier"]) > _tier_rank(prev["tier"]):
                    best_by_issue[key] = finding
        findings.extend(best_by_issue.values())
    return findings


def _tier_rank(tier: str) -> int:
    return {"consider": 0, "likely": 1, "definite": 2}.get(tier, 0)


def set_pack_active(conn, workspace_id: str, pack_id: str, active: bool, by: str) -> None:
    """Switch a pack on or off for one workspace. Off means its checks stop, not
    just its display; findings already stored keep their citations."""
    if not conn.execute("SELECT 1 FROM compliance_packs WHERE id = ?", (pack_id,)).fetchone():
        raise KeyError(pack_id)
    conn.execute(
        "INSERT INTO workspace_packs (workspace_id, pack_id, active, activated_by, activated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT (workspace_id, pack_id) DO UPDATE SET active = ?, "
        "activated_by = ?, activated_at = ?",
        (workspace_id, pack_id, int(active), by, _now(), int(active), by, _now()))


def pack_overview(conn, workspace_id: str) -> Dict[str, Any]:
    packs = [dict(r) for r in conn.execute(
        "SELECT p.*, w.active AS workspace_active FROM compliance_packs p "
        "LEFT JOIN workspace_packs w ON w.pack_id = p.id AND w.workspace_id = ? "
        "ORDER BY p.name", (workspace_id,)).fetchall()]
    for pack in packs:
        count = conn.execute(
            "SELECT COUNT(*) c FROM pack_clauses WHERE pack_id = ? AND active = 1",
            (pack["id"],)).fetchone()
        pack["clauses"] = count["c"] if count else 0
    return {"packs": packs, "retrieval": embeddings.status(conn)}


def _eval_rows() -> List[Dict[str, Any]]:
    if not os.path.exists(EVAL_FILE):
        return []
    rows = []
    with open(EVAL_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def evaluate(conn, workspace_id: str) -> Dict[str, Any]:
    """Measure the pack on the labelled decision set. Precision is reported at
    the Definite bar, the release gate (≥95%); recall is over all expected
    violations. A false positive at any tier is a false legal warning, so it is
    reported too."""
    rows = _eval_rows()
    if not rows:
        return {"samples": 0, "error": "no evaluation set"}
    definite_tp = definite_fp = expected_definite = 0
    caught = expected_total = 0
    misses, false_alarms = [], []
    for row in rows:
        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.conn, ctx.ws, ctx.kv, ctx.revision_id = conn, workspace_id, 0, "eval"
        found = check(ctx, row["text"])
        cited = {c["ref"] for f in found for c in f["citations"]}
        expected = set(row.get("expected", []))
        expected_total += len(expected)
        hit = expected & cited
        caught += len(hit)
        if expected - cited:
            misses.append({"text": row["text"], "missed": sorted(expected - cited)})
        definite_found = {c["ref"] for f in found if f["tier"] == "definite" for c in f["citations"]}
        for ref in expected:
            # the label says whether this violation must reach the Definite bar
            if ref in row.get("definite", expected):
                expected_definite += 1
                if ref in definite_found:
                    definite_tp += 1
        for ref in definite_found - expected:
            definite_fp += 1
        for f in found:
            for c in f["citations"]:
                if c["ref"] not in expected:
                    false_alarms.append({"text": row["text"], "wrong": c["ref"], "tier": f["tier"]})
    precision = definite_tp / (definite_tp + definite_fp) if (definite_tp + definite_fp) else 1.0
    recall = caught / expected_total if expected_total else 1.0
    return {
        "samples": len(rows),
        "expected": expected_total,
        "caught": caught,
        "recall": round(recall, 4),
        "definite_expected": expected_definite,
        "definite_true_positives": definite_tp,
        "definite_false_positives": definite_fp,
        "precision_definite": round(precision, 4),
        "precision_target": 0.95,
        "recall_target": 0.85,
        "passes": precision >= 0.95 and recall >= 0.85,
        "misses": misses[:12],
        "false_alarms": false_alarms[:12],
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db
    from seed import seed

    db.init_schema()
    ws = seed()
    conn = db.connect()
    try:
        print(json.dumps(evaluate(conn, ws), indent=2))
    finally:
        conn.close()
