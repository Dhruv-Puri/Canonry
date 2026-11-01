"""Data layer for the Canonry prototype: SQLite by default, Postgres when asked.

With no ``CANONRY_DATABASE_URL`` this is exactly the zero-setup SQLite database
judges run locally. When the variable is set the same SQL runs on Postgres
(Neon/Supabase free tier), which adds durable storage, pgvector embeddings and
row-level security.

The dialect layer is deliberately small: ``connect()`` returns an object that
accepts ``?`` placeholders and rows readable by name and by position, so none of
the engine modules above need to know which database answered.

Signing, uploads and webhook delivery all live here so a restart cannot lose the
database and the Ed25519 key separately (see docs/deployment.md).
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DB_PATH = os.environ.get("CANONRY_DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "db", "canonry.db")
# Postgres (Neon/Supabase). Unset = SQLite, the zero-setup local/default mode.
DATABASE_URL: Optional[str] = os.environ.get("CANONRY_DATABASE_URL") or None
# Postgres search_path for isolated test schemas (used by the suites).
DB_SCHEMA: Optional[str] = os.environ.get("CANONRY_DB_SCHEMA") or None

APP_ROLE = "canonry_app"
EMBEDDING_DIM = 768

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
  consumed_at TEXT, workspace_id TEXT
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
  revision_no INTEGER NOT NULL, created_at TEXT NOT NULL,
  asset_id TEXT, source_kind TEXT NOT NULL DEFAULT 'text', locator_map_json TEXT
);
CREATE TABLE IF NOT EXISTS check_runs (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, ai_calls INTEGER DEFAULT 0, discarded INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'done', knowledge_version INTEGER DEFAULT 0,
  by_user TEXT, ai_reason TEXT
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, checker TEXT NOT NULL,
  category TEXT NOT NULL, span_start INTEGER, span_end INTEGER, span_text TEXT,
  tier TEXT NOT NULL, severity TEXT NOT NULL, citations_json TEXT,
  explanation TEXT, suggestion_json TEXT, provenance_json TEXT,
  status TEXT NOT NULL DEFAULT 'open', title TEXT,
  locator_json TEXT, location_key TEXT
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
  public_key_fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
  asset_id TEXT, content_kind TEXT NOT NULL DEFAULT 'text', stamped_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS proof_files (
  poc_id TEXT PRIMARY KEY, bytes BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
  recall REAL, precision_planted REAL, precision_by_tier TEXT,
  invalid_citations INTEGER, notes TEXT
);
-- Round 3: uploaded files, brand kit, compliance packs, API keys and webhooks.
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, submission_id TEXT,
  kind TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0, sha256 TEXT NOT NULL,
  width INTEGER, height INTEGER, page_count INTEGER,
  alt_text TEXT, dhash TEXT, palette_json TEXT, metadata_json TEXT,
  created_by TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_data (
  asset_id TEXT PRIMARY KEY, bytes BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_logos (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  variant TEXT NOT NULL DEFAULT 'current', asset_id TEXT NOT NULL,
  dhash TEXT NOT NULL, width INTEGER, height INTEGER,
  min_width_ratio REAL NOT NULL DEFAULT 0.05,
  clear_space_ratio REAL NOT NULL DEFAULT 0.15,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_colours (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  hex TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'primary',
  delta_e REAL NOT NULL DEFAULT 10.0, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS compliance_packs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
  source TEXT NOT NULL, description TEXT, url TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pack_clauses (
  id TEXT NOT NULL, version INTEGER NOT NULL, pack_id TEXT NOT NULL,
  source TEXT NOT NULL, ref TEXT NOT NULL, heading TEXT, text TEXT NOT NULL,
  url TEXT, severity TEXT NOT NULL DEFAULT 'medium',
  triggers_json TEXT, requirements_json TEXT, exemptions_json TEXT,
  embedding_json TEXT, embedding_model TEXT, content_hash TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
  PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS workspace_packs (
  workspace_id TEXT NOT NULL, pack_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  activated_by TEXT, activated_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, pack_id)
);
CREATE TABLE IF NOT EXISTS embedding_cache (
  hash TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,
  vector_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (hash, model)
);
CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  prefix TEXT UNIQUE NOT NULL, key_hash TEXT NOT NULL, scopes_json TEXT NOT NULL,
  created_by TEXT, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
  workspace_id TEXT NOT NULL, key TEXT NOT NULL, endpoint TEXT NOT NULL,
  request_hash TEXT NOT NULL, response_json TEXT, status INTEGER NOT NULL DEFAULT 200,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, key, endpoint)
);
CREATE TABLE IF NOT EXISTS webhook_endpoints (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, url TEXT NOT NULL,
  secret_salt TEXT NOT NULL, events_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, description TEXT,
  created_by TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
  event TEXT NOT NULL, payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT, last_status INTEGER, last_error TEXT,
  created_at TEXT NOT NULL, delivered_at TEXT, locked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_revision ON findings (revision_id);
CREATE INDEX IF NOT EXISTS idx_revisions_submission ON revisions (submission_id);
CREATE INDEX IF NOT EXISTS idx_assets_submission ON assets (submission_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_pending ON webhook_deliveries (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_pack_clauses_pack ON pack_clauses (pack_id, active);
"""

# Postgres-only objects: pgvector columns/indexes and the RLS role. Each statement
# is attempted on its own so an older pgvector or a restricted role degrades to
# the lexical fallback instead of stopping the boot.
POSTGRES_EXTRAS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "ALTER TABLE pack_clauses ADD COLUMN IF NOT EXISTS embedding vector(768)",
    "ALTER TABLE embedding_cache ADD COLUMN IF NOT EXISTS embedding vector(768)",
    "CREATE INDEX IF NOT EXISTS idx_pack_clauses_embedding ON pack_clauses USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_embedding_cache_embedding ON embedding_cache USING hnsw (embedding vector_cosine_ops)",
)

# (table, policy predicate). Child tables reach their workspace through the
# parent row; the workspace id comes from a transaction-local setting so one
# pooled connection can never leak the previous request's workspace.
RLS_TABLES: Tuple[Tuple[str, str], ...] = (
    ("workspaces", "id = current_setting('canonry.workspace_id', true)"),
    ("users", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("sessions", "EXISTS (SELECT 1 FROM users u WHERE u.id = sessions.user_id "
                 "AND u.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("invitations", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("rules", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("facts", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("terms", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("rule_bindings", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("knowledge_history", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("submissions", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("claim_memory", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("exempt_policies", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("revisions", "EXISTS (SELECT 1 FROM submissions s WHERE s.id = revisions.submission_id "
                  "AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("check_runs", "EXISTS (SELECT 1 FROM revisions r JOIN submissions s ON s.id = r.submission_id "
                   "WHERE r.id = check_runs.revision_id AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("findings", "EXISTS (SELECT 1 FROM revisions r JOIN submissions s ON s.id = r.submission_id "
                 "WHERE r.id = findings.revision_id AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("decisions", "EXISTS (SELECT 1 FROM revisions r JOIN submissions s ON s.id = r.submission_id "
                  "WHERE r.id = decisions.revision_id AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("comments", "EXISTS (SELECT 1 FROM revisions r JOIN submissions s ON s.id = r.submission_id "
                 "WHERE r.id = comments.revision_id AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("approvals", "EXISTS (SELECT 1 FROM submissions s WHERE s.id = approvals.submission_id "
                  "AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("proof_of_compliance", "EXISTS (SELECT 1 FROM submissions s WHERE s.id = proof_of_compliance.submission_id "
                            "AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("proof_files", "EXISTS (SELECT 1 FROM proof_of_compliance p JOIN submissions s ON s.id = p.submission_id "
                    "WHERE p.id = proof_files.poc_id AND s.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("assets", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("asset_data", "EXISTS (SELECT 1 FROM assets a WHERE a.id = asset_data.asset_id "
                   "AND a.workspace_id = current_setting('canonry.workspace_id', true))"),
    ("brand_logos", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("brand_colours", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("workspace_packs", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("api_keys", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("idempotency", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("webhook_endpoints", "workspace_id = current_setting('canonry.workspace_id', true)"),
    ("webhook_deliveries", "workspace_id = current_setting('canonry.workspace_id', true)"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dialect() -> str:
    return "postgres" if DATABASE_URL else "sqlite"


# ---- portable connection objects --------------------------------------------

class Row(dict):
    """A row readable by column name and by position, like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PgCursor:
    """Small cursor facade exposing the sqlite3 cursor surface the engine uses."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return row if isinstance(row, Row) else Row(row)

    def fetchall(self):
        return [r if isinstance(r, Row) else Row(r) for r in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield row if isinstance(row, Row) else Row(row)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)


def to_pg_placeholders(sql: str) -> str:
    """`?` (outside quoted literals) -> `%s`; `%` -> `%%` for psycopg."""
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class PgConnection:
    """Wraps psycopg so the engine's sqlite-shaped SQL keeps working."""

    def __init__(self, conn, schema: Optional[str]):
        self._conn = conn
        self._schema = schema

    def execute(self, sql: str, params: Sequence = ()) -> PgCursor:
        cursor = self._conn.execute(to_pg_placeholders(sql), tuple(params))
        return PgCursor(cursor)

    def executescript(self, sql: str) -> None:
        for statement in (s.strip() for s in sql.split(";")):
            if statement:
                self._conn.execute(to_pg_placeholders(statement))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def connect(service: bool = False):
    """Open the database. `service=True` skips the RLS app role (migrations,
    login/session lookup, public verification). SQLite ignores the flag."""
    if dialect() == "sqlite":
        db_path = os.path.abspath(DB_PATH)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    import psycopg  # local import: SQLite-only installs never need the driver

    options = f"-c search_path={DB_SCHEMA}" if DB_SCHEMA else None
    conn = psycopg.connect(DATABASE_URL, prepare_threshold=None, connect_timeout=10,
                           row_factory=_pg_row_factory, options=options)
    if not service:
        conn.execute(f"SET ROLE {APP_ROLE}")
    return PgConnection(conn, DB_SCHEMA)


def _pg_row_factory(cursor):
    names = [d.name for d in cursor.description] if cursor.description else []

    def make(values):
        return Row(zip(names, values))

    return make


def set_workspace(conn, workspace_id: Optional[str]) -> None:
    """Scope this transaction to one workspace (Postgres RLS). No-op on SQLite."""
    if conn is None or dialect() == "sqlite" or not workspace_id:
        return
    conn.execute("SELECT set_config('canonry.workspace_id', ?, true)", (workspace_id,))


# ---- helpers used by the portable call sites ---------------------------------

def insert_returning_id(conn, sql: str, params: Sequence = ()) -> int:
    if dialect() == "sqlite":
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid)
    cur = conn.execute(sql + " RETURNING id", tuple(params))
    return int(cur.fetchone()[0])


def begin_write(conn) -> None:
    """Start a write transaction. Postgres is already in one after the first
    statement; SQLite needs BEGIN IMMEDIATE to take the write lock early."""
    if dialect() == "sqlite":
        conn.execute("BEGIN IMMEDIATE")


INTEGRITY_ERRORS: Tuple[type, ...] = (sqlite3.IntegrityError,)
if DATABASE_URL:
    try:
        import psycopg.errors as _pg_errors  # type: ignore

        INTEGRITY_ERRORS = (sqlite3.IntegrityError, _pg_errors.IntegrityError)
    except Exception:  # pragma: no cover - driver missing only in odd installs
        pass


def schema_sql(dialect_name: Optional[str] = None) -> str:
    sql = SCHEMA
    if (dialect_name or dialect()) == "postgres":
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
        sql = sql.replace("BLOB NOT NULL", "BYTEA NOT NULL")
    return sql


def _is_safe_schema(name: Optional[str]) -> bool:
    return bool(name) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or "") is not None


def init_schema() -> None:
    conn = connect(service=True)
    try:
        if dialect() == "sqlite":
            conn.executescript(schema_sql("sqlite"))
            _sqlite_migrations(conn)
            # indexes on migrated columns come after the ALTERs: an existing
            # database does not have them when the base schema runs
            conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_location ON findings (location_key)")
        else:
            # pgvector must exist before the schema's vector columns/indexes.
            try:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.commit()
            except Exception:
                conn.rollback()
            conn.executescript(schema_sql("postgres"))
            _postgres_migrations(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_location ON findings (location_key)")
            for statement in POSTGRES_EXTRAS:
                if "CREATE EXTENSION" in statement:
                    continue
                try:
                    conn.execute(statement)
                    conn.commit()
                except Exception:
                    conn.rollback()
            _setup_rls(conn)
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


def _sqlite_migrations(conn) -> None:
    for table, column, ddl in (
        ("users", "password_hash", "password_hash TEXT"),
        ("claim_memory", "operation", "operation TEXT"),
        ("claim_memory", "knowledge_version", "knowledge_version INTEGER"),
        ("facts", "version", "version INTEGER NOT NULL DEFAULT 1"),
        ("terms", "version", "version INTEGER NOT NULL DEFAULT 1"),
        ("terms", "status", "status TEXT NOT NULL DEFAULT 'active'"),
        ("check_runs", "by_user", "by_user TEXT"),
        ("check_runs", "ai_reason", "ai_reason TEXT"),
        ("invitations", "workspace_id", "workspace_id TEXT"),
        ("revisions", "asset_id", "asset_id TEXT"),
        ("revisions", "source_kind", "source_kind TEXT NOT NULL DEFAULT 'text'"),
        ("revisions", "locator_map_json", "locator_map_json TEXT"),
        ("findings", "locator_json", "locator_json TEXT"),
        ("findings", "location_key", "location_key TEXT"),
        ("proof_of_compliance", "asset_id", "asset_id TEXT"),
        ("proof_of_compliance", "content_kind", "content_kind TEXT NOT NULL DEFAULT 'text'"),
        ("proof_of_compliance", "stamped_sha256", "stamped_sha256 TEXT"),
    ):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _postgres_migrations(conn) -> None:
    for table, column, ddl in (
        ("users", "password_hash", "password_hash TEXT"),
        ("claim_memory", "operation", "operation TEXT"),
        ("claim_memory", "knowledge_version", "knowledge_version INTEGER"),
        ("facts", "version", "version INTEGER NOT NULL DEFAULT 1"),
        ("terms", "version", "version INTEGER NOT NULL DEFAULT 1"),
        ("terms", "status", "status TEXT NOT NULL DEFAULT 'active'"),
        ("check_runs", "by_user", "by_user TEXT"),
        ("check_runs", "ai_reason", "ai_reason TEXT"),
        ("invitations", "workspace_id", "workspace_id TEXT"),
        ("revisions", "asset_id", "asset_id TEXT"),
        ("revisions", "source_kind", "source_kind TEXT NOT NULL DEFAULT 'text'"),
        ("revisions", "locator_map_json", "locator_map_json TEXT"),
        ("findings", "locator_json", "locator_json TEXT"),
        ("findings", "location_key", "location_key TEXT"),
        ("proof_of_compliance", "asset_id", "asset_id TEXT"),
        ("proof_of_compliance", "content_kind", "content_kind TEXT NOT NULL DEFAULT 'text'"),
        ("proof_of_compliance", "stamped_sha256", "stamped_sha256 TEXT"),
    ):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}")


def _setup_rls(conn) -> None:
    """Create the RLS role, grant it the table surface, and enable policies.

    The owner keeps full access for migrations, login and public verification;
    every request path uses the app role with a workspace setting.
    """
    try:
        conn.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'canonry_app') "
            "THEN CREATE ROLE canonry_app NOLOGIN; END IF; END $$;"
        )
        conn.execute("DO $$ BEGIN EXECUTE format('GRANT canonry_app TO %I', current_user); END $$;")
        schema = DB_SCHEMA or "public"
        conn.execute(f'GRANT USAGE ON SCHEMA {schema} TO canonry_app')
        conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO canonry_app')
        conn.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO canonry_app')
        for table, predicate in RLS_TABLES:
            conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.execute(f"DROP POLICY IF EXISTS {table}_workspace ON {table}")
            conn.execute(
                f"CREATE POLICY {table}_workspace ON {table} FOR ALL TO canonry_app "
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        conn.commit()
    except Exception:
        # A restricted database (no CREATE ROLE) still works single-tenant; the
        # engine logs nothing secret and keeps the access.py rules in force.
        conn.rollback()


# ---- test databases ----------------------------------------------------------

def use_test_database(name: str) -> None:
    """Point this process at a fresh database named `name`.

    SQLite: db/<name>.db, removed first. Postgres (`CANONRY_TEST_DATABASE_URL`):
    a dedicated schema, dropped and recreated. Called before any connection.
    """
    global DATABASE_URL, DB_SCHEMA, DB_PATH
    test_url = os.environ.get("CANONRY_TEST_DATABASE_URL")
    if test_url:
        DATABASE_URL, DB_SCHEMA = test_url, name
        conn = connect(service=True)
        try:
            conn.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
            conn.execute(f"CREATE SCHEMA {name}")
            conn.commit()
        finally:
            conn.close()
        return
    DATABASE_URL, DB_SCHEMA = None, None
    DB_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", name + ".db"))
    for suffix in ("", "-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)


def subprocess_env() -> Dict[str, str]:
    """Environment for a child process (the MCP server) opening the same database."""
    env = dict(os.environ)
    if dialect() == "postgres":
        env["CANONRY_DATABASE_URL"] = DATABASE_URL or ""
        env["CANONRY_DB_SCHEMA"] = DB_SCHEMA or ""
    else:
        env["CANONRY_DB_PATH"] = DB_PATH
    return env


_gen_id_counter = 0


def gen_id(prefix: str) -> str:
    global _gen_id_counter
    _gen_id_counter += 1
    return f"{prefix}_{secrets.token_hex(6)}"


# ---- append-only, hash-chained audit log (doc T12) -------------------------

def audit(conn, actor: str, action: str, detail: str) -> None:
    last = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = last["hash"] if last else "GENESIS"
    at = _now()
    payload = f"{prev_hash}|{at}|{actor}|{action}|{detail}"
    h = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, detail, prev_hash, hash) VALUES (?,?,?,?,?,?)",
        (at, actor, action, detail, prev_hash, h),
    )


# ---- knowledge version: one monotonic counter, +1 per knowledge change --------

def _legacy_knowledge_version(conn) -> int:
    """The pre-counter scheme (rowid sum + bump), used only to seed the counter
    so a migrated database never reports a lower version than it already did."""
    if dialect() == "postgres":
        return 0
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


def get_knowledge_version(conn) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='knowledge_version'").fetchone()
    return int(row["value"]) if row else 0


def next_knowledge_version(conn) -> int:
    """Portable counter bump: UPDATE then INSERT when the row is missing."""
    cur = conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'knowledge_version'"
    )
    if cur.rowcount == 0:
        conn.execute("INSERT INTO meta (key, value) VALUES ('knowledge_version', '1')")
    return get_knowledge_version(conn)


def bump_knowledge(conn) -> None:
    next_knowledge_version(conn)


# ---- users & sessions -------------------------------------------------------

def create_session(conn, user_id: str, ttl_hours: int = 24) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc).timestamp() + ttl_hours * 3600
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token_hash, user_id, _now(), datetime.fromtimestamp(expires, timezone.utc).isoformat()),
    )
    conn.commit()
    return token


def resolve_session(conn, token: Optional[str]):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token_hash, _now()),
    ).fetchone()


ROLE_RANK = {"creator": 0, "agency": 0, "reviewer": 1, "admin": 2}


def require_role(user, needed: str) -> bool:
    return ROLE_RANK.get(user["role"], 0) >= ROLE_RANK[needed]
