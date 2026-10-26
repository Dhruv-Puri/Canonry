"""Knowledge base editing: version history, write API, pinned citations,
version-stamped claim memory and fact-change impact (fresh test DB).

Run:  .venv/Scripts/python engine/test_knowledge.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_knowledge.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from db import connect, get_knowledge_version, init_schema, next_knowledge_version  # noqa: E402
from seed import seed  # noqa: E402

import knowledge  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


init_schema()
WS = seed()

# ---- Task 1: history core -----------------------------------------------------
conn = connect()
try:
    h = knowledge.history(conn, WS, "rule", "BRD-01")
    row = conn.execute("SELECT statement FROM rules WHERE id='BRD-01'").fetchone()
    expect(len(h) == 1 and h[0]["action"] == "seed" and h[0]["version"] == 1,
           f"seed writes history ({[(x['action'], x['version']) for x in h]})")
    expect(h and h[0]["snapshot"]["statement"] == row["statement"], "seed snapshot matches the current row")

    n_hist = conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT entity, entity_id FROM knowledge_history)").fetchone()[0]
    n_ent = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("rules", "facts", "terms"))
    expect(n_hist == n_ent, f"every entity has history ({n_hist} of {n_ent})")

    a = get_knowledge_version(conn)
    b = next_knowledge_version(conn)
    conn.commit()
    expect(b == a + 1 and get_knowledge_version(conn) == a + 1, f"next_knowledge_version is monotonic ({a} -> {b})")

    # an old-style database: no history, no counter, an old bump and a high check_runs value
    conn.execute("DELETE FROM knowledge_history")
    conn.execute("DELETE FROM meta WHERE key='knowledge_version'")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('knowledge_version_bump', '95')")
    conn.execute("INSERT INTO check_runs (id, revision_id, started_at, status, knowledge_version) "
                 "VALUES ('run_old', 'rev_old', 'x', 'done', 500)")
    conn.commit()
finally:
    conn.close()

init_schema()  # startup migration on the old-style database
conn = connect()
try:
    n_hist = conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT entity, entity_id FROM knowledge_history)").fetchone()[0]
    expect(n_hist == n_ent and get_knowledge_version(conn) >= 500,
           f"migration backfills history and never lowers the version ({n_hist}, kv={get_knowledge_version(conn)})")
    conn.execute("DELETE FROM check_runs WHERE id='run_old'")
    conn.commit()
finally:
    conn.close()

# ---- Task 2: write API -------------------------------------------------------
import re  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


def client(email):
    c = TestClient(main.app)
    c.post("/login", json={"email": email})
    return c


maya, arjun = client("maya@quillmark"), client("arjun@quillmark")


def submit(c, content, channel="web"):
    return c.post("/submissions", json={"title": "kb test", "channel": channel,
                                        "source_type": "in-house", "content": content}).json()


r = arjun.put("/kb/rules/BRD-01", json={"category": "Brand", "statement": "x" * 20, "severity": "low",
                                         "status": "approved", "expected_version": 1, "reason": "try"})
expect(r.status_code == 403, f"creator cannot edit ({r.status_code})")

r = maya.post("/kb/rules", json={"category": "Brand", "statement": "Never place the logo on photos of people.",
                                  "do_example": "Logo on a plain Paper panel.", "severity": "low"})
body = r.json() if r.status_code == 200 else {}
new_rule = (body.get("entity") or {})
expect(r.status_code == 200 and new_rule.get("id") == "BRD-04" and new_rule.get("version") == 1,
       f"create rule assigns category prefix ({r.status_code} {new_rule.get('id')} {r.text[:120] if r.status_code != 200 else ''})")
conn = connect()
h = knowledge.history(conn, WS, "rule", "BRD-04")
conn.close()
expect([x["action"] for x in h] == ["create"], f"create is in history ({[x['action'] for x in h]})")

r = maya.post("/kb/rules", json={"id": "brand 1", "category": "Brand", "statement": "A long enough statement.",
                                  "severity": "low"})
expect(r.status_code == 422, f"explicit bad rule id refused ({r.status_code})")

conn = connect()
kv_before = get_knowledge_version(conn)
conn.close()
BRD01_V1 = maya.get("/rules").json()["rules"]
BRD01_V1 = next(x for x in BRD01_V1 if x["id"] == "BRD-01")["statement"]
r = maya.put("/kb/rules/BRD-01", json={"category": "Brand", "do_example": "Primary CTA in Teal #0E7C7B.",
                                        "statement": "Use the approved palette: Ink #101828, Teal #0E7C7B, Paper #F8FAFC, Sand #F4EBDD.",
                                        "severity": "low", "status": "approved", "expected_version": 1,
                                        "reason": "palette refresh"})
body = r.json() if r.status_code == 200 else {}
expect(r.status_code == 200 and body.get("entity", {}).get("version") == 2 and body.get("knowledge_version", 0) > kv_before,
       f"update bumps version and knowledge version ({r.status_code} {r.text[:120]})")

r = maya.put("/kb/rules/BRD-01", json={"category": "Brand", "statement": "Use the approved palette everywhere.",
                                        "severity": "low", "status": "approved", "expected_version": 2, "reason": "  "})
expect(r.status_code == 422, f"update without reason refused ({r.status_code})")

r = maya.put("/kb/rules/BRD-01", json={"category": "Brand", "statement": "Use the approved palette everywhere.",
                                        "severity": "low", "status": "approved", "expected_version": 1, "reason": "stale"})
expect(r.status_code == 409 and "now v2" in r.text, f"stale expected_version is refused ({r.status_code} {r.text[:100]})")

GOOD_FACT = {"text": "Quillmark Pulse supports 14 dashboard languages.", "category": "product",
             "owner": "Product", "source": "Release notes 2.0", "valid_from": "2026-10-01", "valid_to": "2027-09-30"}
r = maya.post("/kb/facts", json={k: v for k, v in GOOD_FACT.items() if k != "owner"})
expect(r.status_code == 422, f"fact without owner refused ({r.status_code})")
r = maya.post("/kb/facts", json={**GOOD_FACT, "valid_to": "2026-01-01"})
expect(r.status_code == 422, f"fact ending before it starts refused ({r.status_code})")
r = maya.post("/kb/facts", json={**GOOD_FACT, "valid_to": "30/09/2026"})
expect(r.status_code == 422, f"fact with a non-ISO date refused ({r.status_code})")
existing_f = [int(f["id"][2:]) for f in maya.get("/facts").json()["facts"] if re.fullmatch(r"F-\d{3}", f["id"])]
r = maya.post("/kb/facts", json=GOOD_FACT)
fid = (r.json().get("entity") or {}).get("id", "") if r.status_code == 200 else ""
expect(re.fullmatch(r"F-\d{3}", fid or "") is not None and int(fid[2:]) > max(existing_f),
       f"create fact numbering ({r.status_code} {fid})")

r = maya.post("/kb/terms", json={"note": "x", "severity": "low"})
expect(r.status_code == 422, f"term needs a word ({r.status_code})")

flagged = lambda res: any(f["checker"] == "terminology" and "employees" in f["span"]["text"]  # noqa: E731
                          for f in res["findings"])
expect(flagged(submit(arjun, "Our employees love it.")), "term 'employees' is flagged before retiring")
term3 = next(t for t in maya.get("/terms").json()["terms"] if t["banned_or_check"] == "employees")
r = maya.post(f"/kb/terms/{term3['id']}/retire", json={"expected_version": term3["version"], "reason": "people-language rule dropped"})
expect(r.status_code == 200, f"retire term ({r.status_code} {r.text[:100]})")
expect(not flagged(submit(arjun, "Our employees love it.")), "retired term no longer flagged")
r = maya.post(f"/kb/terms/{term3['id']}/retire", json={"expected_version": term3["version"] + 1, "reason": "again"})
expect(r.status_code == 409, f"retire twice refused ({r.status_code})")

r = maya.post("/kb/rules/BRD-01/restore", json={"version": 1, "expected_version": 2, "reason": "undo palette change"})
body = r.json() if r.status_code == 200 else {}
expect(r.status_code == 200 and body.get("entity", {}).get("version") == 3
       and body.get("entity", {}).get("statement") == BRD01_V1,
       f"restore brings back an earlier version ({r.status_code} {r.text[:120]})")
r = maya.post(f"/kb/terms/{term3['id']}/restore", json={"version": term3["version"] + 1,
                                                          "expected_version": term3["version"] + 1, "reason": "x y z"})
expect(r.status_code == 409, f"restore to a retired version refused ({r.status_code})")
r = maya.post("/kb/rules/BRD-01/restore", json={"version": 99, "expected_version": 3, "reason": "x y z"})
expect(r.status_code == 404, f"restore to an unknown version refused ({r.status_code})")

CSV = ('id,category,statement,do_example,dont_example,severity\n'
       'BRD-02,Brand,"Logo is never stretched, recoloured or placed over busy photos.",Logo on Paper.,Logo at 300%.,low\n')
r = maya.post("/rules/import", json={"csv": CSV})
brd02 = next(x for x in maya.get("/rules").json()["rules"] if x["id"] == "BRD-02")
expect(r.status_code == 200 and r.json().get("updated") == 1 and brd02["version"] == 2
       and brd02["statement"].endswith("busy photos."),
       f"CSV import versions an existing rule and keeps quoted commas ({r.status_code} v{brd02['version']} {brd02['statement'][:40]})")

r = arjun.get("/kb/rules/BRD-01/history")
expect(r.status_code == 200 and [v["version"] for v in r.json()["versions"]] == [3, 2, 1],
       f"history newest first ({r.status_code} {r.text[:80]})")

# ---- Task 3: pinned citations, version-stamped claim memory, PoC ---------------
import claims  # noqa: E402

LAUNCH = ("Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams "
          "and fully ISO 27001 certified. Plans start at just ₹999/month!")
res = submit(arjun, LAUNCH, channel="social")
cits = [c for f in res["findings"] for c in f["citations"] if c["type"] in ("fact", "rule", "term", "pack")]
expect(cits and all(isinstance(c.get("version"), int) for c in cits),
       f"citations carry versions ({[(c['id'], c.get('version')) for c in cits][:6]})")

detail = arjun.get(f"/submissions/{res['submission_id']}").json()
term04 = next((c for f in detail["findings"] for c in f["citations"] if c["type"] == "rule" and c["id"] == "TERM-04"), None)
old_excerpt = term04["excerpt"] if term04 else None
rule = next(x for x in maya.get("/rules").json()["rules"] if x["id"] == "TERM-04")
r = maya.put("/kb/rules/TERM-04", json={**{k: rule[k] for k in ("category", "do_example", "dont_example", "severity", "status")},
                                         "statement": "Product names must match the approved names list (Quillmark Pulse since June 2026).",
                                         "expected_version": rule["version"], "reason": "clearer wording"})
detail = arjun.get(f"/submissions/{res['submission_id']}").json()
after = next((c for f in detail["findings"] for c in f["citations"] if c["type"] == "rule" and c["id"] == "TERM-04"), {})
expect(r.status_code == 200 and old_excerpt and after.get("excerpt") == old_excerpt
       and after.get("version") == rule["version"] and after.get("current_version") == rule["version"] + 1,
       f"old finding shows the text it was checked against (v{after.get('version')} now v{after.get('current_version')})")

conn = connect()
try:
    conn.execute("INSERT INTO claim_memory (id, workspace_id, claim_norm, numbers_json, verdict, fact_ids, created_at) "
                 "VALUES ('vcm_legacy', ?, 'k0', '[\"2300\"]', 'supported', '[]', 'x')", (WS,))
    claims.vcm_store(conn, WS, "k1", ["2300"], "supported", ["F-012"], "x", None, "m", kv=7)
    expect(claims.vcm_lookup(conn, WS, "k1", ["2300"], kv=7) is not None, "claim memory reused at the same knowledge version")
    expect(claims.vcm_lookup(conn, WS, "k1", ["2300"], kv=8) is None, "claim memory not reused across knowledge versions")
    expect(claims.vcm_lookup(conn, WS, "k0", ["2300"], kv=7) is None, "unversioned (legacy) claim memory is never reused")
finally:
    conn.close()

clean = submit(arjun, "Quillmark Pulse helps team members see their numbers. Start your free trial at quillmark.co/pulse.")
sid = clean["submission_id"]
arjun.post(f"/submissions/{sid}/submit-review")
conn = connect()
kv_at_approval = get_knowledge_version(conn)
conn.close()
ap = maya.post(f"/submissions/{sid}/review", json={"action": "approve"}).json()
rec = arjun.get(f"/verify/{ap.get('poc_id')}").json().get("record", {}) if ap.get("poc_id") else {}
expect(rec.get("knowledge_version") == kv_at_approval and rec.get("kind") == "ProofOfCompliance/2",
       f"PoC records knowledge version ({rec.get('knowledge_version')} vs {kv_at_approval}, {rec.get('kind')})")

# ---- Task 4: fact-change impact and the re-review list --------------------------
def approve(content):
    s = submit(arjun, content)["submission_id"]
    arjun.post(f"/submissions/{s}/submit-review")
    maya.post(f"/submissions/{s}/review", json={"action": "approve"})
    return s


uses_count = approve("Quillmark Pulse is trusted by 2,300+ teams. Start your free trial at quillmark.co/pulse.")
f012 = next(f for f in maya.get("/facts").json()["facts"] if f["id"] == "F-012")
r = maya.put("/kb/facts/F-012", json={**{k: f012[k] for k in ("category", "owner", "source", "valid_from", "valid_to")},
                                       "text": "2,500+ active customer teams", "expected_version": f012["version"],
                                       "reason": "Q4 registry count"})
impact = r.json().get("impact", []) if r.status_code == 200 else []
hit = next((i for i in impact if i["submission_id"] == uses_count), None)
expect(r.status_code == 200 and hit is not None and "2300" in hit["because"].replace(",", ""),
       f"fact edit lists approved content using the old number ({r.status_code} {impact})")
expect(all(i["submission_id"] != sid for i in impact), "unrelated approved content is not listed")

s = submit(arjun, "Quillmark Insights is here.")["submission_id"]
arjun.post(f"/submissions/{s}/submit-review")
det = maya.get(f"/submissions/{s}").json()
fnd = next(f for f in det["findings"] if any(c["type"] == "rule" and c["id"] == "TERM-04" for c in f["citations"]))
old_v = next(c["version"] for c in fnd["citations"] if c["id"] == "TERM-04")
maya.post(f"/submissions/{s}/review", json={"action": "override", "finding_id": fnd["id"], "reason": "launch name kept on purpose"})
maya.post(f"/submissions/{s}/review", json={"action": "approve"})
rule = next(x for x in maya.get("/rules").json()["rules"] if x["id"] == "TERM-04")
maya.put("/kb/rules/TERM-04", json={**{k: rule[k] for k in ("category", "statement", "do_example", "severity", "status")},
                                     "dont_example": "Quillmark Insights", "expected_version": rule["version"],
                                     "reason": "add a don't example"})
r = arjun.get("/kb/stale-approvals")
items = r.json().get("items", []) if r.status_code == 200 else []
item = next((i for i in items if i["submission_id"] == s), None)
expect(item is not None and item["cites"] == f"Rule TERM-04 v{old_v}" and item["current_version"] == rule["version"] + 1,
       f"stale approvals after rule edit ({r.status_code} {item})")

# ---- final review fixes ------------------------------------------------------
conf = next(f for f in maya.get("/facts").json()["facts"] if f["id"] == "CONF-01")
r = maya.put("/kb/facts/CONF-01", json={"text": conf["text"] + " (board review Q1)", "expected_version": conf["version"],
                                         "reason": "clarify timing"})
after = next(f for f in maya.get("/facts").json()["facts"] if f["id"] == "CONF-01")
expect(r.status_code == 200 and after["confidential"] == 1 and after["owner"] == conf["owner"],
       f"PUT keeps fields it does not mention (confidential stays 1) ({r.status_code} conf={after['confidential']})")

# a concurrent writer already took the next version: the loser gets 409, not a 500
conn = connect()
try:
    v = knowledge.current_version(conn, WS, "rule", "CLM-01")
    conn.execute("INSERT INTO knowledge_history (workspace_id, entity, entity_id, version, action, snapshot_json, at, "
                 "knowledge_version) VALUES (?, 'rule', 'CLM-01', ?, 'update', '{}', 'x', 0)", (WS, v + 1))
    conn.commit()
finally:
    conn.close()
r = maya.put("/kb/rules/CLM-01", json={"statement": "Every statistic in public content must trace to an approved fact.",
                                        "expected_version": v, "reason": "race"})
expect(r.status_code == 409, f"a write that loses a race is a 409, not a crash ({r.status_code})")

print()
if failures:
    print(f"{len(failures)} KNOWLEDGE TEST(S) FAILED")
    sys.exit(1)
print("ALL KNOWLEDGE TESTS PASSED")
