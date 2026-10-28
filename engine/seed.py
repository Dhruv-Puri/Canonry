"""Seed the Quillmark Analytcs demo workspace (doc Sections 1, 6.2, 9.5).

Loaded from CSV in the folder (M1 demo data via CSV): ~40 brand-book rules with
a few deliberately vague ones, ~60 approved facts (some expiring/superseded),
the glossary, demo personas and one exemption policy.
"""
from __future__ import annotations

import csv
import os
import sqlite3
from typing import Iterable

import knowledge
import policy
from db import (
    audit, bump_knowledge, connect, gen_id, init_schema,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _rows(name: str) -> Iterable[dict]:
    path = os.path.join(DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield row


def is_seeded(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) c FROM workspaces").fetchone()
    return row["c"] > 0


# the Quillmark brand book's own rule for each built-in check
QUILLMARK_BINDINGS = {
    "claims.statistic": "CLM-01", "claims.superlative": "CLM-02", "claims.certification": "CLM-05",
    "voice.sentence_length": "VOICE-3.1", "voice.hard_sell": "VOICE-3.2", "voice.tone": "VOICE-3.2",
    "voice.exclamation": "VOICE-3.4", "social.length": "SOC-01", "messaging.cta": "MSG-03",
}


def seed() -> str:
    init_schema()
    conn = connect()
    try:
        if is_seeded(conn):
            row = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
            # databases seeded before rule bindings existed get them on next boot
            policy.ensure_bindings(conn, row["id"], QUILLMARK_BINDINGS)
            conn.commit()
            return row["id"]
        ws_id = "ws_quillmark"
        at = "seed"
        conn.execute(
            "INSERT INTO workspaces (id, name, slug, created_at) VALUES (?,?,?,?)",
            (ws_id, "Quillmark Analytics", "quillmark", at),
        )
        users = [
            ("maya", "maya@quillmark", "Maya (Brand & Content Manager)", "reviewer"),
            ("arjun", "arjun@quillmark", "Arjun (Product Marketer)", "creator"),
            ("riya", "riya@agency", "Riya (Agency Copywriter)", "agency"),
            ("karan", "karan@quillmark", "Karan (Head of Marketing, final approver)", "admin"),
        ]
        for uid, email, name, role in users:
            conn.execute(
                "INSERT INTO users (id, workspace_id, email, name, role, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (uid, ws_id, email, name, role, at),
            )
        n_rules = 0
        for r in _rows("quillmark_rules.csv"):
            stmt = (r.get("statement") or "").strip()
            if not stmt or stmt == "statement":
                continue
            vague = None
            if r.get("do_example") in ("vague_no_examples", "vague_contradictory", "vague_duplicate"):
                vague = r["do_example"]
            conn.execute(
                "INSERT INTO rules (id, workspace_id, category, statement, do_example, "
                "dont_example, severity, status, vague_flag, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    r["id"], ws_id, r["category"], stmt,
                    r.get("do_example") if r.get("do_example") and not vague else None,
                    r.get("dont_example") if r.get("dont_example") and r["dont_example"] not in ("vague_no_examples", "vague_contradictory", "vague_duplicate", "") else None,
                    r.get("severity") or "medium",
                    r.get("status") or "approved",
                    vague, at,
                ),
            )
            n_rules += 1
        n_facts = 0
        for f in _rows("quillmark_facts.csv"):
            conn.execute(
                "INSERT INTO facts (id, workspace_id, text, category, owner, source, "
                "valid_from, valid_to, confidential, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f["id"], ws_id, f["text"], f["category"], f.get("owner"),
                    f.get("source"), f.get("valid_from") or None,
                    f.get("valid_to") or None,
                    int(f.get("confidential") or 0), at,
                ),
            )
            n_facts += 1
        n_terms = 0
        for t in _rows("quillmark_terms.csv"):
            pref = (t.get("preferred") or "").strip()
            banned = (t.get("banned_or_check") or "").strip()
            if not pref and not banned:
                continue
            conn.execute(
                "INSERT INTO terms (workspace_id, preferred, banned_or_check, note, severity) "
                "VALUES (?,?,?,?,?)",
                (
                    ws_id, pref or None, banned or None, t.get("note"),
                    t.get("severity") or "medium",
                ),
            )
            n_terms += 1
        conn.execute(
            "INSERT INTO exempt_policies (id, workspace_id, name, scope, active, created_by, "
            "created_at) VALUES (?,?,?,?,1,?,?)",
            (
                gen_id("exp"), ws_id,
                "Email digests with zero open findings",
                '{"channel":"email","requires":"zero_open_findings","spot_audit_rate":0.10}',
                "maya", at,
            ),
        )
        policy.ensure_bindings(conn, ws_id, QUILLMARK_BINDINGS)
        bump_knowledge(conn)
        knowledge.backfill_history(conn)  # version 1 of every seeded rule, fact and term
        audit(
            conn, "system", "seed_workspace",
            f"Quillmark demo data: {n_rules} rules, {n_facts} facts, {n_terms} terms",
        )
        conn.commit()
        return ws_id
    finally:
        conn.close()


if __name__ == "__main__":
    import db as _db
    print("db:", os.path.abspath(_db.DB_PATH))
    print("workspace:", seed())
