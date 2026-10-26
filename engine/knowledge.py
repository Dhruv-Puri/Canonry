"""Knowledge base writes and version history (rules, facts, terms).

The `rules`, `facts` and `terms` tables hold the *current* version and stay the
read model for every checker. Each change also appends a full snapshot to
`knowledge_history`, so findings and approvals can always show exactly what they
were checked against. Nothing here deletes: retiring is a status change.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from db import _now, audit, get_knowledge_version, next_knowledge_version

# API path segment -> entity name used in history and citations
ENTITIES = {"rules": "rule", "facts": "fact", "terms": "term"}
TABLES = {"rule": "rules", "fact": "facts", "term": "terms"}


def snapshot(conn: sqlite3.Connection, ws: str, entity: str, entity_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"SELECT * FROM {TABLES[entity]} WHERE id = ? AND workspace_id = ?", (entity_id, ws)
    ).fetchone()
    return dict(row) if row else None


def record_version(conn: sqlite3.Connection, ws: str, entity: str, entity_id: str, version: int,
                   action: str, reason: Optional[str], by_user: str, kv: int) -> None:
    snap = snapshot(conn, ws, entity, entity_id)
    conn.execute(
        "INSERT INTO knowledge_history (workspace_id, entity, entity_id, version, action, snapshot_json, "
        "reason, by_user, at, knowledge_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ws, entity, str(entity_id), version, action, json.dumps(snap), reason, by_user, _now(), kv),
    )


def current_version(conn: sqlite3.Connection, ws: str, entity: str, entity_id: str) -> Optional[int]:
    if entity not in TABLES:
        return None
    row = conn.execute(
        f"SELECT version FROM {TABLES[entity]} WHERE id = ? AND workspace_id = ?", (entity_id, ws)
    ).fetchone()
    return int(row["version"]) if row else None


def snapshot_at(conn: sqlite3.Connection, ws: str, entity: str, entity_id: str,
                version: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT snapshot_json FROM knowledge_history WHERE workspace_id = ? AND entity = ? "
        "AND entity_id = ? AND version = ?", (ws, entity, str(entity_id), version)
    ).fetchone()
    return json.loads(row["snapshot_json"]) if row else None


def history(conn: sqlite3.Connection, ws: str, entity: str, entity_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT h.version, h.action, h.snapshot_json, h.reason, h.by_user, u.name AS by_name, h.at, "
        "h.knowledge_version FROM knowledge_history h LEFT JOIN users u ON u.email = h.by_user "
        "WHERE h.workspace_id = ? AND h.entity = ? AND h.entity_id = ? ORDER BY h.version DESC",
        (ws, entity, str(entity_id)),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["snapshot"] = json.loads(d.pop("snapshot_json"))
        out.append(d)
    return out


# ---- writes ----------------------------------------------------------------------

class KBError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


EDITORS = ("reviewer", "admin")
SEVERITIES = ("low", "medium", "high")
RULE_ID = re.compile(r"^[A-Z]{2,6}-\d{1,3}(\.\d+)?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def lint_rule(stmt: str, do: Optional[str], dont: Optional[str], existing: List[str]) -> Optional[str]:
    """Flag rules a person cannot check: no examples, contradictory, or duplicate."""
    cheap = not stmt.strip()
    short = len(stmt.strip()) < 25
    no_examples = not (do or dont)
    words = [w.lower() for w in stmt.split()]
    lack = any(w in words for w in ("bold", "fresh", "engaging", "nice")) and no_examples
    contradictory = stmt.count(" and ") > 0 and (("formal" in words and "fresh" in words) or ("always" in words and "never" in words))
    duplicate = stmt[:40] in existing
    if contradictory:
        return "vague_contradictory"
    if duplicate:
        return "vague_duplicate"
    if short or no_examples or lack or cheap:
        return "vague_no_examples"
    return None


def _text(fields: Dict[str, Any], key: str) -> Optional[str]:
    v = fields.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _severity(fields: Dict[str, Any]) -> str:
    sev = _text(fields, "severity") or "medium"
    if sev not in SEVERITIES:
        raise KBError(422, "Severity must be low, medium or high.")
    return sev


def _rule_values(conn, ws, fields, rule_id: Optional[str]) -> Dict[str, Any]:
    category, statement = _text(fields, "category"), _text(fields, "statement")
    if not category:
        raise KBError(422, "Category is required.")
    if not statement or len(statement) < 10:
        raise KBError(422, "Statement is required (at least 10 characters).")
    status = _text(fields, "status") or "approved"
    if status not in ("approved", "draft"):
        raise KBError(422, "Status must be approved or draft (use Retire to retire a rule).")
    do, dont = _text(fields, "do_example"), _text(fields, "dont_example")
    others = [r["statement"] for r in conn.execute(
        "SELECT statement FROM rules WHERE workspace_id = ? AND id != ? AND status != 'retired'",
        (ws, rule_id or "")).fetchall()]
    return {"category": category, "statement": statement, "do_example": do, "dont_example": dont,
            "severity": _severity(fields), "status": status,
            "vague_flag": lint_rule(statement, do, dont, [s[:40] for s in others])}


def _fact_values(fields: Dict[str, Any]) -> Dict[str, Any]:
    vals = {k: _text(fields, k) for k in ("text", "category", "owner", "source", "valid_from", "valid_to")}
    for key, label in (("text", "Fact text"), ("category", "Category"), ("owner", "Owner"), ("source", "Source")):
        if not vals[key]:
            raise KBError(422, f"{label} is required.")
    for key in ("valid_from", "valid_to"):
        if vals[key] and not DATE.match(vals[key]):
            raise KBError(422, f"{key.replace('_', ' ').capitalize()} must be a date like 2026-09-30.")
    if vals["valid_from"] and vals["valid_to"] and vals["valid_to"] < vals["valid_from"]:
        raise KBError(422, "Valid to must be on or after valid from.")
    vals["confidential"] = 1 if fields.get("confidential") in (True, 1, "1", "true") else 0
    return vals


def _term_values(fields: Dict[str, Any]) -> Dict[str, Any]:
    vals = {k: _text(fields, k) for k in ("preferred", "banned_or_check", "note")}
    if not (vals["preferred"] or vals["banned_or_check"]):
        raise KBError(422, "A term needs a preferred word, a word to avoid, or both.")
    vals["severity"] = _severity(fields)
    return vals


def _values(conn, ws, entity: str, fields: Dict[str, Any], entity_id: Optional[str]) -> Dict[str, Any]:
    if entity == "rule":
        return _rule_values(conn, ws, fields, entity_id)
    if entity == "fact":
        return _fact_values(fields)
    return _term_values(fields)


def _next_rule_id(conn, ws, category: str) -> str:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM rules WHERE workspace_id = ? AND category = ?", (ws, category)).fetchall()]
    prefixes = [i.split("-")[0] for i in ids if RULE_ID.match(i)]
    prefix = max(set(prefixes), key=prefixes.count) if prefixes else (re.sub(r"[^A-Za-z]", "", category)[:3].upper() or "GEN")
    taken = [r["id"] for r in conn.execute("SELECT id FROM rules WHERE workspace_id = ? AND id LIKE ?",
                                           (ws, prefix + "-%")).fetchall()]
    nums = [re.match(rf"^{prefix}-(\d+)", i) for i in taken]
    nums = [m.group(1) for m in nums if m]
    width = max([len(n) for n in nums] or [2])
    return f"{prefix}-{(max([int(n) for n in nums] or [0]) + 1):0{width}d}"


def _next_fact_id(conn, ws) -> str:
    nums = [int(r["id"][2:]) for r in conn.execute(
        "SELECT id FROM facts WHERE workspace_id = ? AND id GLOB 'F-[0-9][0-9][0-9]'", (ws,)).fetchall()]
    return f"F-{(max(nums or [0]) + 1):03d}"


def _require_editor(user) -> None:
    if user["role"] not in EDITORS:
        raise KBError(403, "Only reviewers and admins change the knowledge base.")


def _require_reason(reason: Optional[str]) -> str:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise KBError(422, "Say why you are making this change (at least 3 characters).")
    return reason


def _entity(kind: str) -> str:
    if kind not in ENTITIES:
        raise KBError(404, "Unknown knowledge type.")
    return ENTITIES[kind]


def _locked_current(conn, ws, entity: str, entity_id: str, expected_version: Any) -> Dict[str, Any]:
    cur = snapshot(conn, ws, entity, entity_id)
    if not cur:
        raise KBError(404, f"No {entity} {entity_id}.")
    if expected_version is None or int(expected_version) != int(cur["version"]):
        raise KBError(409, f"Changed by someone else (now v{cur['version']}). Reload and try again.")
    return cur


def _is_retired(entity: str, row: Dict[str, Any]) -> bool:
    if entity == "rule":
        return row.get("status") == "retired"
    if entity == "fact":
        return bool(row.get("superseded"))
    return row.get("status") == "retired"


def _lost_race(conn) -> KBError:
    conn.rollback()
    return KBError(409, "Changed by someone else just now. Reload and try again.")


def _write(conn, ws, entity: str, entity_id: str, vals: Dict[str, Any], version: int) -> None:
    """Write the next version, but only if nobody else wrote one in the meantime."""
    cols = ", ".join(f"{k} = ?" for k in vals)
    cur = conn.execute(
        f"UPDATE {TABLES[entity]} SET {cols}, version = ? WHERE id = ? AND workspace_id = ? AND version = ?",
        (*vals.values(), version, entity_id, ws, version - 1))
    if cur.rowcount != 1:
        raise _lost_race(conn)


def _finish(conn, ws, entity: str, entity_id: str, version: int, action: str,
            reason: Optional[str], user, impact: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    kv = next_knowledge_version(conn)
    try:
        record_version(conn, ws, entity, entity_id, version, action, reason, user["email"], kv)
    except sqlite3.IntegrityError:
        raise _lost_race(conn)  # another writer recorded this version number first
    audit(conn, user["email"], f"kb_{action}_{entity}", f"{entity_id} v{version}: {reason or '-'}")
    conn.commit()
    out = {"entity": snapshot(conn, ws, entity, entity_id), "knowledge_version": kv}
    if entity == "fact":
        out["impact"] = impact or []
    return out


def create(conn, ws: str, kind: str, fields: Dict[str, Any], user, reason: Optional[str]) -> Dict[str, Any]:
    entity = _entity(kind)
    _require_editor(user)
    if entity == "rule":
        vals = _values(conn, ws, entity, fields, None)
        rid = _text(fields, "id")
        if rid:
            if not RULE_ID.match(rid):
                raise KBError(422, "Rule id must look like BRD-04 (2-6 capital letters, a dash, a number).")
            if snapshot(conn, ws, "rule", rid):
                raise KBError(409, f"Rule {rid} already exists.")
        else:
            rid = _next_rule_id(conn, ws, vals["category"])
        conn.execute(
            "INSERT INTO rules (id, workspace_id, category, statement, do_example, dont_example, severity, "
            "status, vague_flag, created_at, version) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (rid, ws, vals["category"], vals["statement"], vals["do_example"], vals["dont_example"],
             vals["severity"], vals["status"], vals["vague_flag"], _now()))
        entity_id = rid
    elif entity == "fact":
        vals = _values(conn, ws, entity, fields, None)
        entity_id = _next_fact_id(conn, ws)
        conn.execute(
            "INSERT INTO facts (id, workspace_id, text, category, owner, source, valid_from, valid_to, "
            "confidential, superseded, created_at, version) VALUES (?,?,?,?,?,?,?,?,?,0,?,1)",
            (entity_id, ws, vals["text"], vals["category"], vals["owner"], vals["source"],
             vals["valid_from"], vals["valid_to"], vals["confidential"], _now()))
    else:
        vals = _values(conn, ws, entity, fields, None)
        cur = conn.execute(
            "INSERT INTO terms (workspace_id, preferred, banned_or_check, note, severity, version, status) "
            "VALUES (?,?,?,?,?,1,'active')",
            (ws, vals["preferred"], vals["banned_or_check"], vals["note"], vals["severity"]))
        entity_id = str(cur.lastrowid)
    return _finish(conn, ws, entity, entity_id, 1, "create", _text({"r": reason}, "r"), user)


def update(conn, ws: str, kind: str, entity_id: str, fields: Dict[str, Any], expected_version: Any,
           user, reason: Optional[str]) -> Dict[str, Any]:
    entity = _entity(kind)
    _require_editor(user)
    reason = _require_reason(reason)
    cur = _locked_current(conn, ws, entity, entity_id, expected_version)
    if _is_retired(entity, cur):
        raise KBError(409, "This entry is retired. Restore it before editing.")
    # fields the caller leaves out keep their current value (never silently blanked,
    # e.g. a confidential fact must not turn public because a client omitted the flag)
    vals = _values(conn, ws, entity, {**cur, **fields}, entity_id)
    version = int(cur["version"]) + 1
    _write(conn, ws, entity, entity_id, vals, version)
    return _finish(conn, ws, entity, entity_id, version, "update", reason, user, _impact(conn, ws, entity, cur))


def retire(conn, ws: str, kind: str, entity_id: str, expected_version: Any, user,
           reason: Optional[str]) -> Dict[str, Any]:
    entity = _entity(kind)
    _require_editor(user)
    reason = _require_reason(reason)
    cur = _locked_current(conn, ws, entity, entity_id, expected_version)
    if _is_retired(entity, cur):
        raise KBError(409, "Already retired.")
    vals = {"superseded": 1} if entity == "fact" else {"status": "retired"}
    version = int(cur["version"]) + 1
    _write(conn, ws, entity, entity_id, vals, version)
    return _finish(conn, ws, entity, entity_id, version, "retire", reason, user, _impact(conn, ws, entity, cur))


def restore(conn, ws: str, kind: str, entity_id: str, to_version: Any, expected_version: Any, user,
            reason: Optional[str]) -> Dict[str, Any]:
    entity = _entity(kind)
    _require_editor(user)
    reason = _require_reason(reason)
    cur = _locked_current(conn, ws, entity, entity_id, expected_version)
    target = snapshot_at(conn, ws, entity, entity_id, int(to_version or 0))
    if not target:
        raise KBError(404, f"{entity.capitalize()} {entity_id} has no version {to_version}.")
    if _is_retired(entity, target):
        raise KBError(409, "Cannot restore a retired version.")
    keep = {"rule": ("category", "statement", "do_example", "dont_example", "severity", "status", "vague_flag"),
            "fact": ("text", "category", "owner", "source", "valid_from", "valid_to", "confidential", "superseded"),
            "term": ("preferred", "banned_or_check", "note", "severity", "status")}[entity]
    vals = {k: target.get(k) for k in keep}
    if entity == "term":
        vals["status"] = vals.get("status") or "active"
    version = int(cur["version"]) + 1
    _write(conn, ws, entity, entity_id, vals, version)
    return _finish(conn, ws, entity, entity_id, version, "restore", reason, user, _impact(conn, ws, entity, cur))


APPROVED = ("Approved", "Signed", "Exempt-approved")
CITED_ENTITY = {"fact": "fact", "rule": "rule", "pack": "rule", "term": "term"}
_NUMBER = re.compile(r"\d[\d,]*\d")


def _approved_latest(conn, ws: str):
    """Approved submissions with their latest revision."""
    return conn.execute(
        "SELECT s.id, s.title, s.status, r.id AS revision_id, r.content FROM submissions s "
        "JOIN revisions r ON r.submission_id = s.id WHERE s.workspace_id = ? AND s.status IN (?,?,?) "
        "AND r.revision_no = (SELECT MAX(revision_no) FROM revisions WHERE submission_id = s.id)",
        (ws, *APPROVED)).fetchall()


def _citations(conn, revision_id: str) -> List[Dict[str, Any]]:
    out = []
    for f in conn.execute("SELECT citations_json FROM findings WHERE revision_id = ?", (revision_id,)).fetchall():
        out.extend(json.loads(f["citations_json"] or "[]"))
    return out


def affected_approved_content(conn, ws: str, fact_id: str, old_text: str) -> List[Dict[str, Any]]:
    """Approved content that relied on a fact's old value: it cites the fact, or it
    contains one of the old text's numbers (years like 2026 are ignored)."""
    numbers = {n.replace(",", "") for n in _NUMBER.findall(old_text or "")}
    numbers = {n for n in numbers if len(n) >= 3 and not (len(n) == 4 and 1900 <= int(n) <= 2099)}
    out = []
    for s in _approved_latest(conn, ws):
        because = None
        if any(c.get("type") == "fact" and str(c.get("id")) == fact_id for c in _citations(conn, s["revision_id"])):
            because = f"cites Fact {fact_id}"
        else:
            flat = s["content"].replace(",", "")
            used = next((n for n in sorted(numbers) if n in flat), None)
            if used:
                because = f"uses {used} from the old fact text"
        if because:
            out.append({"submission_id": s["id"], "title": s["title"], "status": s["status"], "because": because})
    return out


def stale_approvals(conn, ws: str) -> List[Dict[str, Any]]:
    """Approved content whose findings cite a rule, fact or term that has changed since."""
    out = []
    for s in _approved_latest(conn, ws):
        seen = set()
        for c in _citations(conn, s["revision_id"]):
            entity = CITED_ENTITY.get(c.get("type"))
            if not entity or not c.get("version"):
                continue
            now = current_version(conn, ws, entity, str(c["id"]))
            key = (entity, str(c["id"]))
            if now and now > c["version"] and key not in seen:
                seen.add(key)
                out.append({"submission_id": s["id"], "title": s["title"], "status": s["status"],
                            "cites": f"{entity.capitalize()} {c['id']} v{c['version']}", "current_version": now})
    return out


def _impact(conn, ws, entity: str, before: Dict[str, Any]) -> List[Dict[str, Any]]:
    if entity != "fact":
        return []
    return affected_approved_content(conn, ws, str(before["id"]), before.get("text") or "")


def backfill_history(conn: sqlite3.Connection) -> int:
    """Give every entity without history a `seed` row at its current version."""
    kv = get_knowledge_version(conn)
    n = 0
    for entity, table in TABLES.items():
        rows = conn.execute(
            f"SELECT t.id, t.workspace_id, t.version FROM {table} t WHERE NOT EXISTS ("
            "SELECT 1 FROM knowledge_history h WHERE h.workspace_id = t.workspace_id "
            "AND h.entity = ? AND h.entity_id = CAST(t.id AS TEXT))", (entity,)
        ).fetchall()
        for r in rows:
            record_version(conn, r["workspace_id"], entity, r["id"], r["version"] or 1, "seed", None, "system", kv)
            n += 1
    return n
