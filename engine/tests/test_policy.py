"""Built-in checks cite the workspace's own rules (fresh test DBs).

Every built-in check enforces a rule. Which rule it cites comes from the
workspace's rule bindings, never from an id written into the code, so a
workspace that is not the Quillmark demo still gets cited findings, and a
retired rule switches its check off instead of producing discarded findings.

Run:  .venv/Scripts/python engine/tests/test_policy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package
import offline_ai  # noqa: E402,F401  (first: tests never reach a real AI provider)

import db as _db

_DB_DIR = os.path.dirname(_db.DB_PATH)


def _fresh(name):
    _db.DB_PATH = os.path.join(_DB_DIR, name)
    for suffix in ("", "-wal", "-shm"):
        p = _db.DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)


_fresh("canonry_policy.db")

from fastapi.testclient import TestClient  # noqa: E402

from db import _now, connect, create_session, init_schema  # noqa: E402
from seed import seed  # noqa: E402

init_schema()
seed()

import main as engine  # noqa: E402
import policy  # noqa: E402

engine.COOKIE_SECURE = False
engine.DEMO_MODE = True

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def cited(findings):
    return {c["id"] for f in findings for c in f["citations"] if c["type"] == "rule"}


POST = ("The best analytics platform, trusted by 9,000+ teams. Reports load 47% faster. "
        "Plans start at just ₹999/month!! Grab it now before the offer ends.")

# --- 1. the demo workspace binds every check to its own Quillmark rule ------------
print("== demo workspace")
conn = connect()
bound = policy.bindings(conn, "ws_quillmark")
expect(set(bound) == set(policy.CHECKS), f"every built-in check is bound ({len(bound)}/{len(policy.CHECKS)})")
expect(bound.get("claims.statistic") == "CLM-01" and bound.get("claims.superlative") == "CLM-02",
       "claim checks keep the Quillmark ids CLM-01 / CLM-02")
expect(not conn.execute("SELECT 1 FROM rules WHERE id LIKE 'BASE-%'").fetchone(),
       "no baseline rules are added where the workspace already has its own")

c = TestClient(engine.app, raise_server_exceptions=False)
c.post("/login", json={"email": "arjun@quillmark"})
r = c.post("/submissions", json={"title": "p", "channel": "social", "source_type": "in-house", "content": POST}).json()
ids = cited(r["findings"])
expect({"CLM-01", "CLM-02"} <= ids, f"demo findings cite CLM-01 and CLM-02 ({sorted(ids)})")
expect(r["discarded"] == 0, f"nothing discarded for a missing citation ({r['discarded']})")

# --- 2. retiring a bound rule switches its check off (not a silent discard) -------
print("== retired rule")
maya = TestClient(engine.app, raise_server_exceptions=False)
maya.post("/login", json={"email": "maya@quillmark"})
v = conn.execute("SELECT version FROM rules WHERE id='CLM-02'").fetchone()[0]
rr = maya.post("/kb/rules/CLM-02/retire", json={"expected_version": v, "reason": "superlatives handled by legal"})
expect(rr.status_code == 200, f"CLM-02 retired ({rr.status_code})")
r = c.post("/submissions", json={"title": "p2", "channel": "social", "source_type": "in-house", "content": POST}).json()
cats = [f["category"] for f in r["findings"]]
expect("CLM-02" not in cited(r["findings"]), "no finding cites the retired rule")
expect(r["discarded"] == 0, f"the switched-off check produces no discarded findings ({r['discarded']})")
expect("unsupported_claim" in cats, f"other claim checks still run ({cats})")
conn.close()

# --- 3. a workspace without demo data gets the baseline rules -------------------
print("== workspace without demo data")
_fresh("canonry_policy_blank.db")
init_schema()
conn = connect()
conn.execute("INSERT INTO workspaces (id, name, slug, created_at) VALUES ('ws_blank','Blank Co','blank',?)", (_now(),))
conn.execute("INSERT INTO users (id, workspace_id, email, name, role, created_at) "
             "VALUES ('u1','ws_blank','writer@blank.co','Writer','creator',?)", (_now(),))
policy.ensure_bindings(conn, "ws_blank")
conn.commit()
bound = policy.bindings(conn, "ws_blank")
expect(set(bound) == set(policy.CHECKS), f"every check bound in a blank workspace ({len(bound)})")
base = conn.execute("SELECT COUNT(*) FROM rules WHERE workspace_id='ws_blank' AND status='approved'").fetchone()[0]
expect(base == len(set(bound.values())), f"one approved baseline rule per bound id ({base})")
hist = conn.execute("SELECT COUNT(*) FROM knowledge_history WHERE workspace_id='ws_blank' AND entity='rule'").fetchone()[0]
expect(hist == base, f"baseline rules have version history like any other rule ({hist})")
policy.ensure_bindings(conn, "ws_blank")
again = conn.execute("SELECT COUNT(*) FROM rules WHERE workspace_id='ws_blank'").fetchone()[0]
expect(again == base, "installing twice changes nothing")

token = create_session(conn, "u1")
w = TestClient(engine.app, raise_server_exceptions=False, headers={"X-Canon-Session": token})
r = w.post("/submissions", json={"title": "b", "channel": "social", "source_type": "in-house", "content": POST}).json()
cats = sorted({f["category"] for f in r["findings"]})
expect("unsupported_claim" in cats, f"unsupported claims found without the demo rulebook ({cats})")
expect("tone" in cats, "tone heuristics found without the demo rulebook")
expect(cited(r["findings"]) <= set(bound.values()), f"every rule citation is a bound baseline rule ({sorted(cited(r['findings']))})")
expect(r["discarded"] == 0, f"nothing discarded ({r['discarded']})")
expect(all("CLM-" not in f["explanation"] and "VOICE-" not in f["explanation"] for f in r["findings"]),
       "explanations name the bound rule, not a demo id")
conn.close()

print()
if failures:
    print(f"{len(failures)} POLICY TEST(S) FAILED")
    raise SystemExit(1)
print("ALL POLICY TESTS PASSED")
