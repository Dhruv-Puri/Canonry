"""Seed-data integrity: the CSVs parse into the columns they claim, and the
seeded workspace keeps confidential facts confidential and vague rules flagged.

Run:  .venv/Scripts/python engine/tests/test_seed_data.py
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the engine package

import db as _db

_db.DB_PATH = os.path.join(os.path.dirname(_db.DB_PATH), "canonry_seedcheck.db")
for suffix in ("", "-wal", "-shm"):
    p = _db.DB_PATH + suffix
    if os.path.exists(p):
        os.remove(p)

from db import connect  # noqa: E402
from seed import DATA_DIR, seed  # noqa: E402

failures = []


def expect(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


def rows(name):
    with open(os.path.join(DATA_DIR, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- every CSV row has exactly the header's columns (no unquoted commas) ----
for name in ("quillmark_rules.csv", "quillmark_facts.csv", "quillmark_terms.csv"):
    bad = [r.get("id") or r.get("preferred") for r in rows(name) if None in r or None in r.values()]
    expect(not bad, f"{name}: every row has exactly the header's columns {bad or ''}")

rules = rows("quillmark_rules.csv")
bad_sev = [r["id"] for r in rules if r["severity"] not in ("low", "medium", "high")]
expect(not bad_sev, f"rules: severity is low/medium/high {bad_sev or ''}")
bad_status = [r["id"] for r in rules if r["status"] not in ("approved", "draft", "retired")]
expect(not bad_status, f"rules: status is approved/draft/retired {bad_status or ''}")

facts = rows("quillmark_facts.csv")
bad_conf = [f["id"] for f in facts if f["confidential"] not in ("0", "1")]
expect(not bad_conf, f"facts: confidential is 0 or 1 {bad_conf or ''}")

# ---- what the seeded workspace actually contains ----
seed()
conn = connect()
try:
    conf = {r["id"]: r["confidential"] for r in conn.execute("SELECT id, confidential FROM facts WHERE id LIKE 'CONF-%'")}
    expect(conf and all(conf.values()), f"every CONF-* fact is seeded confidential {conf}")

    vague = {r["id"]: r["vague_flag"] for r in conn.execute(
        "SELECT id, vague_flag FROM rules WHERE id IN ('VOI-05','MSG-06','TERM-08','STYLE-02')")}
    expect(len(vague) == 4 and all(vague.values()), f"the four deliberately vague rules are flagged {vague}")

    stmts = {r["id"]: r["statement"] for r in conn.execute(
        "SELECT id, statement FROM rules WHERE id IN ('BRD-01','BRD-02','MSG-01','SOC-02','TMP-01','CLM-03')")}
    expect(stmts.get("BRD-01", "").endswith("Paper #F8FAFC only."), "BRD-01 keeps its whole statement")
    expect("recoloured" in stmts.get("BRD-02", ""), "BRD-02 keeps its whole statement")
    expect("honest pricing" in stmts.get("MSG-01", ""), "MSG-01 keeps its whole statement")
    expect("approved list" in stmts.get("SOC-02", ""), "SOC-02 keeps its whole statement")
    expect("customer count" in stmts.get("TMP-01", ""), "TMP-01 keeps its whole statement")
    dont = conn.execute("SELECT dont_example FROM rules WHERE id='CLM-03'").fetchone()[0]
    expect(dont == "Our 10,000 happy users.", f"CLM-03 keeps its whole don't-example ({dont!r})")
finally:
    conn.close()

# ---- first boot: one checked demo post so the workspace is never empty ----
import main  # noqa: E402

main._seed_demo_submission()
main._seed_demo_submission()  # second boot must not add another
conn = connect()
try:
    subs = conn.execute("SELECT id, status, created_by FROM submissions").fetchall()
    expect(len(subs) == 1, f"exactly one demo submission after two boots ({len(subs)})")
    if subs:
        n = conn.execute(
            "SELECT COUNT(*) FROM findings f JOIN revisions r ON r.id = f.revision_id WHERE r.submission_id = ?",
            (subs[0]["id"],)).fetchone()[0]
        expect(subs[0]["status"] == "Checked" and n >= 4, f"demo post is checked with real findings ({subs[0]['status']}, {n})")
        expect(subs[0]["created_by"] == "arjun@quillmark", "demo post belongs to the demo creator")
finally:
    conn.close()

print()
if failures:
    print(f"{len(failures)} SEED-DATA CHECK(S) FAILED")
    sys.exit(1)
print("ALL SEED-DATA CHECKS PASSED")
