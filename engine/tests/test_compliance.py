"""India pack: retrieval, deterministic verdicts, citations and the eval gate.

Run:  .venv/Scripts/python engine/tests/test_compliance.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_ai  # noqa: E402,F401

import db as _db

_db.use_test_database("canonry_compliance")

import api  # noqa: E402
import compliance  # noqa: E402
import embeddings  # noqa: E402
import main  # noqa: E402
from db import connect  # noqa: E402
from seed import seed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

main.DEMO_MODE = True  # the demo workspace; production mode would demand a bootstrap admin
main.COOKIE_SECURE = False

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


ws = seed()
conn = connect()
try:
    clauses = compliance.active_clauses(conn, ws)
    expect(len(clauses) >= 13, f"pack clauses are installed ({len(clauses)})")
    expect(all(c.get("triggers") for c in clauses), "every clause carries deterministic triggers")
    status = embeddings.status(conn)
    expect(status["clauses"] == len(clauses), f"every clause has a vector ({status})")
    expect(status["dimensions"] == 768, "vectors use the 768-dim pgvector column width")

    # the web UI/API must receive the legal reference, not just a rule id
    class C:
        pass
    ctx = C()
    ctx.conn, ctx.ws, ctx.kv, ctx.revision_id = conn, ws, 0, "eval"
    free = compliance.check(ctx, "Get a free 14-day trial at just ₹999 per month.")
    expect(len(free) == 1 and free[0]["tier"] == "definite", f"free-with-price is Definite ({len(free)})")
    cite = free[0]["citations"][0]
    expect(cite["ref"] == "Section 5" and "CCPA" in cite["source"] and cite["url"].startswith("https://"),
           f"finding cites the exact clause with a source ({cite})")

    # a compliant near-miss must stay quiet: no legal warning without a breach
    safe = compliance.check(ctx, "Start a free trial with no credit card required.")
    expect(not safe, "compliant free-trial copy produces no finding")

    # ordinary marketing copy must not raise a legal warning at any tier
    ordinary = [
        "Our partner network spans 40 cities.",
        "Become a partner and grow with us.",
        "We partnered with IIT Delhi on the research.",
        "Setup takes only 5 minutes.",
        "Your first 3 reports are on us.",
        "Faster than ever, simpler than before.",
        "Better than yesterday, every day.",
        "Feel free to ask about the subscription that fits your team.",
        "Call our toll-free number to renew your subscription.",
        "Our customers win back 6 hours a week.",
        "Help your sales team win more deals with Pulse.",
        "The winner of our hackathon will be announced on Friday.",
        "Our ambassador loves the new dashboards #ad",
        "Quillmark Pulse 2.0 is an analytics platform trusted by 2,300+ teams. Plans start at ₹1,299/month.",
    ]
    for text in ordinary:
        out = compliance.check(ctx, text)
        expect(not out, f"no legal warning on ordinary copy: {text!r} "
                        f"({[(f['citations'][0]['ref'], f['span']['text']) for f in out]})")
    # ...while the real thing is still caught
    caught = {
        "Pulse is faster than Excel for pivot tables.": "Chapter IV, §1",
        "Only 3 units left at this price!": "Section 3",
        "Enter our lucky draw to win an iPhone.": "Section 12(f)",
        "Our brand ambassador loves the app.": "Section 14",
    }
    for text, ref in caught.items():
        refs = [f["citations"][0]["ref"] for f in compliance.check(ctx, text)]
        expect(ref in refs, f"{ref} still catches {text!r} ({refs})")

    # switching the pack off switches its checks off, not just its display
    conn.execute("UPDATE workspace_packs SET active = 0 WHERE workspace_id = ? AND pack_id = 'in_advertising'", (ws,))
    conn.commit()
    expect(not compliance.check(ctx, "Get a free trial at just ₹999 per month."),
           "inactive pack produces no findings")
    conn.execute("UPDATE workspace_packs SET active = 1 WHERE workspace_id = ? AND pack_id = 'in_advertising'", (ws,))
    conn.commit()

    # evaluation gate: the number the submission is judged on
    report = compliance.evaluate(conn, ws)
    expect(report["samples"] >= 25, f"labelled eval set is large enough ({report['samples']})")
    expect(report["precision_definite"] >= 0.95,
           f"Definite precision meets 95% ({report['precision_definite']})")
    expect(report["recall"] >= 0.85, f"recall meets 85% ({report['recall']})")
    expect(not report["false_alarms"], f"no false legal alarms in the eval set, at any tier ({report['false_alarms']})")

    # real cases: ad lines ASCI upheld complaints against, quoted from published reports
    # (data/compliance/india_asci_cases.jsonl). Before 2 Nov 2026 the pack caught 2 of 45.
    rows = [json.loads(line) for line in open(os.path.join(compliance.DATA_DIR, "india_asci_cases.jsonl"), encoding="utf-8")
            if line.strip() and not line.startswith("#")]
    upheld = [r for r in rows if r["kind"] == "upheld"]
    caught, loud = [], []
    for r in rows:
        refs = {c["ref"] for f in compliance.check(ctx, r["text"]) for c in f["citations"]}
        if r["kind"] == "upheld" and refs & set(r["accept"]):
            caught.append(r["text"])
        if r["kind"] == "control" and refs:
            loud.append((r["text"], sorted(refs)))
    print(f"      ASCI cases: caught {len(caught)}/{len(upheld)}; misses: "
          f"{[r['text'] for r in upheld if r['text'] not in caught]}")
    expect(len(upheld) >= 40 and len(caught) / len(upheld) >= 0.9,
           f"at least 90% of real upheld ASCI ad lines get a cited warning ({len(caught)}/{len(upheld)})")
    expect(not loud, f"no warning on compliant lines that use the same words ({loud})")

    # the public API response carries the same contract-v2 citation
    key = api.create_key(conn, ws, "compliance-test", ["check", "read"], "test")["key"]
    conn.commit()
finally:
    conn.close()

with TestClient(main.app) as client:
    r = client.post("/api/v1/checks",
                    headers={"Authorization": f"Bearer {key}", "Idempotency-Key": "compliance-0001"},
                    json={"title": "Free claim", "channel": "web", "content": "Get a free trial at just ₹999 per month."})
    expect(r.status_code == 200, f"API check succeeds ({r.status_code})")
    body = r.json()
    hits = [f for f in body["findings"] if f["checker"] == "compliance"]
    expect(hits and hits[0]["citations"][0]["ref"] == "Section 5",
           f"API finding carries the clause reference ({hits[:1]})")
    cited = client.get("/api/v1/compliance/packs", headers={"Authorization": f"Bearer {key}"}).json()
    expect(cited["packs"] and cited["packs"][0]["clauses"] >= 13, "pack overview reports installed clauses")

    # the pack switch: an admin turns the pack off and on from the settings page
    def login(email):
        c = TestClient(main.app, raise_server_exceptions=False)
        assert c.post("/login", json={"email": email}).status_code == 200
        return c

    admin, creator = login("karan@quillmark"), login("arjun@quillmark")
    r = creator.post("/compliance/packs/in_advertising", json={"active": False})
    expect(r.status_code == 403, f"only an admin switches a pack ({r.status_code})")
    r = admin.post("/compliance/packs/no_such_pack", json={"active": False})
    expect(r.status_code == 404, f"unknown pack: 404 ({r.status_code})")
    r = admin.post("/compliance/packs/in_advertising", json={"active": False})
    expect(r.status_code == 200 and not r.json()["packs"][0]["workspace_active"], f"admin switches the pack off ({r.status_code})")
    seed()  # what every restart runs
    expect(not admin.get("/compliance/packs").json()["packs"][0]["workspace_active"],
           "a restart keeps the admin's choice")
    r = client.post("/api/v1/checks", headers={"Authorization": f"Bearer {key}"},
                    json={"title": "Off", "channel": "web", "content": "Get a free trial at just ₹999 per month."})
    expect(not [f for f in r.json()["findings"] if f["checker"] == "compliance"], "with the pack off, no legal findings")
    r = admin.post("/compliance/packs/in_advertising", json={"active": True})
    expect(r.status_code == 200 and r.json()["packs"][0]["workspace_active"], "admin switches the pack back on")
    r = client.post("/api/v1/checks", headers={"Authorization": f"Bearer {key}"},
                    json={"title": "On", "channel": "web", "content": "Get a free trial at just ₹999 per month."})
    expect([f for f in r.json()["findings"] if f["checker"] == "compliance"], "with the pack on, the finding is back")
    with connect() as c:
        actions = [row["action"] for row in c.execute("SELECT action FROM audit_log").fetchall()]
    expect("pack_disable" in actions and "pack_enable" in actions, "the switch is in the audit trail")

print()
if failures:
    print(f"{len(failures)} COMPLIANCE CHECK(S) FAILED")
    sys.exit(1)
print("ALL COMPLIANCE CHECKS PASSED")
