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
    expect(not report["false_alarms"], "no false legal alarms in the eval set")

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

print()
if failures:
    print(f"{len(failures)} COMPLIANCE CHECK(S) FAILED")
    sys.exit(1)
print("ALL COMPLIANCE CHECKS PASSED")
