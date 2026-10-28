"""SQLite data layer for the Canonry prototype.

Schema mirrors doc Section 9.5 (workspaces, users/roles, rules, facts with
owner/source/validity/confidentiality, terms, assets, submissions/revisions,
check runs, findings, decisions/overrides, comments, approvals, append-only
audit log) and is kept Supabase-postgres-compatible in naming so the managed
pgvector swap later is a config change, not a redesign.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("CANONRY_DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "db", "canonry.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL,
  password_hash TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations (
  token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, role TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS rules (
  id TEXT NOT NULL, workspace_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  category TEXT NOT NULL, statement TEXT NOT NULL, do_example TEXT,
  dont_example TEXT, severity TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'approved', vague_flag TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (id, workspace_id)
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT NOT NULL, workspace_id TEXT NOT NULL, text TEXT NOT NULL,
  category TEXT NOT NULL, owner TEXT, source TEXT, valid_from TEXT,
  valid_to TEXT, confidential INTEGER NOT NULL DEFAULT 0,
  superseded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (id, workspace_id)
);
CREATE TABLE IF NOT EXISTS terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
  preferred TEXT, banned_or_check TEXT, note TEXT,
  severity TEXT NOT NULL DEFAULT 'medium',
  version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS rule_bindings (
  workspace_id TEXT NOT NULL, check_key TEXT NOT NULL, rule_id TEXT NOT NULL,
  PRIMARY KEY (workspace_id, check_key)
);
CREATE TABLE IF NOT EXISTS knowledge_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
  entity TEXT NOT NULL, entity_id TEXT NOT NULL, version INTEGER NOT NULL,
  action TEXT NOT NULL, snapshot_json TEXT NOT NULL, reason TEXT, by_user TEXT,
  at TEXT NOT NULL, knowledge_version INTEGER NOT NULL,
  UNIQUE (workspace_id, entity, entity_id, version)
);
CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
  title TEXT NOT NULL, channel TEXT NOT NULL, source_type TEXT NOT NULL,
  created_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft',
  risk TEXT, router_note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
  id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, content TEXT NOT NULL,
  revision_no INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_runs (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, ai_calls INTEGER DEFAULT 0, discarded INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'done', knowledge_version INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, checker TEXT NOT NULL,
  category TEXT NOT NULL, span_start INTEGER, span_end INTEGER, span_text TEXT,
  tier TEXT NOT NULL, severity TEXT NOT NULL, citations_json TEXT,
  explanation TEXT, suggestion_json TEXT, provenance_json TEXT,
  status TEXT NOT NULL DEFAULT 'open', title TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, finding_id TEXT NOT NULL,
  action TEXT NOT NULL, replacement TEXT, reason TEXT, by_user TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, by_user TEXT,
  at TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, action TEXT NOT NULL,
  reason TEXT, reviewer TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL, prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_memory (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, claim_norm TEXT NOT NULL,
  numbers_json TEXT NOT NULL, verdict TEXT NOT NULL, fact_ids TEXT NOT NULL,
  explanation TEXT, suggestion TEXT, operation TEXT, model TEXT, created_at TEXT NOT NULL,
  knowledge_version INTEGER
);
CREATE TABLE IF NOT EXISTS ai_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, task TEXT, provider TEXT,
  model TEXT, prompt_version TEXT, latency_ms INTEGER, ok INTEGER,
  cache_hit INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exempt_policies (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  scope TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created_by TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proof_of_compliance (
  id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision_id TEXT NOT NULL,
  record_json TEXT NOT NULL, content_sha256 TEXT NOT NULL, signature TEXT NOT NULL,
  public_key_fingerprint TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
  recall REAL, precision_planted REAL, precision_by_tier TEXT,
  invalid_citations INTEGER, notes TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db_path = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # migrations for databases created before these columns existed
        for table, column, ddl in (
            ("users", "password_hash", "password_hash TEXT"),
            ("claim_memory", "operation", "operation TEXT"),
            ("claim_memory", "knowledge_version", "knowledge_version INTEGER"),
            ("facts", "version", "version INTEGER NOT NULL DEFAULT 1"),
            ("terms", "version", "version INTEGER NOT NULL DEFAULT 1"),
            ("terms", "status", "status TEXT NOT NULL DEFAULT 'active'"),
        ):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if cols and column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        # the knowledge-version counter starts no lower than anything already recorded
        if not conn.execute("SELECT 1 FROM meta WHERE key='knowledge_version'").fetchone():
            seen = conn.execute("SELECT COALESCE(MAX(knowledge_version), 0) FROM check_runs").fetchone()[0]
            has_knowledge = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] > 0
            start = max(_legacy_knowledge_version(conn) if has_knowledge else 0, int(seen or 0))
            conn.execute("INSERT INTO meta (key, value) VALUES ('knowledge_version', ?)", (str(start),))
        import knowledge  # local import: knowledge.py imports this module
        knowledge.backfill_history(conn)
        conn.commit()
    finally:
        conn.close()


def gen_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


# ---- append-only, hash-chained audit log (doc T12) -------------------------

def audit(conn: sqlite3.Connection, actor: str, action: str, detail: str) -> None:
    last = conn.execute(
        "SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    prev_hash = last["hash"] if last else "GENESIS"
    at = _now()
    payload = f"{prev_hash}|{at}|{actor}|{action}|{detail}"
    h = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, detail, prev_hash, hash) "
        "VALUES (?,?,?,?,?,?)",
        (at, actor, action, detail, prev_hash, h),
    )


# ---- knowledge version: one monotonic counter, +1 per knowledge change ---------

def _legacy_knowledge_version(conn: sqlite3.Connection) -> int:
    """The pre-counter scheme (rowid sum + bump), used only to seed the counter
    so a migrated database never reports a lower version than it already did."""
    row = conn.execute(
        "SELECT (SELECT COALESCE(MAX(rowid),0) FROM rules) "
        "+ (SELECT COALESCE(MAX(rowid),0) FROM facts) "
        "+ (SELECT COALESCE(MAX(rowid),0) FROM terms) AS v"
    ).fetchone()
    bump = conn.execute("SELECT value FROM meta WHERE key='knowledge_version_bump'").fetchone()
    try:
        extra = int(bump["value"]) if bump else 0
    except (TypeError, ValueError):
        extra = 0
    return int(row["v"]) + extra


def get_knowledge_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='knowledge_version'").fetchone()
    return int(row["value"]) if row else 0


def next_knowledge_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('knowledge_version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
    )
    return get_knowledge_version(conn)


def bump_knowledge(conn: sqlite3.Connection) -> None:
    next_knowledge_version(conn)


# ---- users & sessions -------------------------------------------------------

def create_session(conn: sqlite3.Connection, user_id: str, ttl_hours: int = 24) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc).timestamp() + ttl_hours * 3600
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token_hash, user_id, _now(), datetime.fromtimestamp(expires, timezone.utc).isoformat()),
    )
    conn.commit()
    return token


def resolve_session(conn: sqlite3.Connection, token: Optional[str]) -> Optional[sqlite3.Row]:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token_hash, _now()),
    ).fetchone()
    return row


ROLE_RANK = {"creator": 0, "agency": 0, "reviewer": 1, "admin": 2}


def require_role(user: sqlite3.Row, needed: str) -> bool:
    return ROLE_RANK.get(user["role"], 0) >= ROLE_RANK[needed]
