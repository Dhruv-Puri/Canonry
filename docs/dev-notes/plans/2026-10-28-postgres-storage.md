# Persistent Storage (Supabase Postgres) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The engine runs on Supabase Postgres when `CANONRY_DATABASE_URL` is set (SQLite stays the zero-setup default), and the signing key can come from an environment variable, so the deployed judge demo keeps its data and its seals across restarts.

**Architecture:** `engine/db.py` becomes the only place that knows which database is in use. `connect()` returns either the existing `sqlite3.Connection` or a thin wrapper around a psycopg connection that accepts the same `?`-placeholder SQL and returns rows readable by name and index. The handful of SQLite-only statements move behind small `db` helpers. The 10 suites run unchanged against both databases; CI runs them on a Postgres service container.

**Tech Stack:** Python 3.11+, FastAPI, `psycopg[binary]==3.3.6`, SQLite (stdlib), PyNaCl, GitHub Actions `postgres:16` service.

**Spec:** Round 1 plan Sections 9.4 and 9.8 (Supabase Postgres as the free-tier database; "same interface, swap the component"); decision log D35 (SQLite now, Postgres-compatible names, "the swap path is written up"); `docs/plan-vs-build.md` row "Supabase Postgres + pgvector" (upgrade path: point the data layer at Postgres). pgvector retrieval and row-level security are **not** in this plan (Round 3).

## Global Constraints

- With `CANONRY_DATABASE_URL` unset, behaviour is byte-for-byte today's: SQLite at `CANONRY_DB_PATH` (default `db/canonry.db`). Local runs and judges need no account.
- Postgres URL env var: `CANONRY_DATABASE_URL` (e.g. Supabase **transaction pooler**, port 6543, `?sslmode=require`).
- Signing seed env var: `CANONRY_SIGNING_SEED` — exactly 64 hex characters (32 bytes). When set, no key file is read or written.
- Driver pinned exactly: `psycopg[binary]==3.3.6` in `engine/requirements.txt`. No ORM, no migration framework.
- Free tools only (plan Section 9.8): Supabase Free, GitHub Actions service containers.
- Tests: script style (`expect(...)`, exit code), each suite on its own fresh database, run through `engine/tests/run_tests.py`. All 11 steps green on SQLite **and** on Postgres before merge.
- Record the change as decision **D54** in `docs/decision-log.md` (never rewrite earlier entries).

## Review Focus

1. **Supabase's transaction pooler (PgBouncer) rejects psycopg's auto-prepared statements** ("prepared statement … already exists") after a few queries per connection. Expected: no such error under repeated requests. → Task 2 test `pg_connection_disables_prepared_statements`.
2. **A literal `?` or `%` inside SQL text** would be corrupted by placeholder translation. Expected: only bare `?` placeholders change; `%` survives. → Task 2 test `placeholder_translation`.
3. **Integer columns compared with string parameters** (`terms.id = '3'`, from `str(entity_id)`): Postgres is strictly typed. Expected: editing, retiring and reading the history of a term works. → covered by `test_knowledge.py` on Postgres (Task 4); fix with explicit `CAST(... AS TEXT)` in `knowledge.py` queries on `terms.id` if it fails.
4. **A failed statement aborts the whole Postgres transaction** until rollback. Expected: a lost knowledge-base write race answers 409 and the next request works. → `test_knowledge.py` race test on Postgres (Task 4); `_lost_race` already rolls back first.
5. **Restart persistence.** Expected: after the engine restarts against the same database and seed, an existing seal still verifies. → Task 1 test `seal_survives_reload` and Task 4 test `seal_survives_reconnect`.

---

### Task 1: Signing key from the environment

**Files:**
- Modify: `engine/signing.py` (`load_signing_key`)
- Modify: `engine/main.py` (`_startup`: load the key once so a bad seed fails at boot)
- Create: `engine/tests/test_storage.py` (this task adds its first section; Task 2 extends it)
- Modify: `engine/tests/run_tests.py` (add `"test_storage"` to `SUITES`)

**Interfaces:**
- Produces: `signing.load_signing_key() -> nacl.signing.SigningKey` — reads `CANONRY_SIGNING_SEED` from `os.environ` at call time; if set, returns `SigningKey(bytes.fromhex(seed))`; if set but not 64 hex chars, raises `RuntimeError("CANONRY_SIGNING_SEED must be 64 hex characters (32 bytes).")`; if unset, current file behaviour.

- [ ] **Step 1: Write the failing test** (section "signing seed" of `test_storage.py`, same harness style as `test_policy.py`)

```python
seed = "ab" * 32
os.environ["CANONRY_SIGNING_SEED"] = seed
k1, k2 = signing.load_signing_key(), signing.load_signing_key()
expect(bytes(k1.verify_key) == bytes(k2.verify_key), "the same seed gives the same key")
expect(bytes(k1) == bytes.fromhex(seed), "the key is the seed from the environment")
expect(not os.path.exists(signing.KEY_PATH), "no key file is written when the seed comes from the environment")
os.environ["CANONRY_SIGNING_SEED"] = "not-hex"
try:
    signing.load_signing_key(); bad = False
except RuntimeError as e:
    bad = "64 hex characters" in str(e)
expect(bad, "a malformed seed is refused with a clear message")
# seal_survives_reload: sign with one load, verify with a fresh load
os.environ["CANONRY_SIGNING_SEED"] = seed
# a revision whose content is the approved text (verify compares against it)
conn.execute("INSERT INTO workspaces (id, name, slug, created_at) VALUES ('ws_s','S','s','t')")
conn.execute("INSERT INTO submissions (id, workspace_id, title, channel, source_type, created_by, created_at) "
             "VALUES ('sub_s','ws_s','t','web','in-house','c@x.test','t')")
conn.execute("INSERT INTO revisions (id, submission_id, content, revision_no, created_at) "
             "VALUES ('rev_s','sub_s','approved text',1,'t')")
ws, sid, rid = "ws_s", "sub_s", "rev_s"
sealed = signing.sign_approval(conn, ws, sid, rid, "approved text", "r@x.test", "reviewer")
expect(signing.verify(conn, sealed["poc_id"], "approved text")["status"] == "verified", "seal_survives_reload")
```

Use the same database header block as the other suites (Task 3 replaces it with `db.use_test_database("canonry_storage")`), call `init_schema()`, and point `signing.KEY_PATH` at a path under `db/` that does not exist before the test.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python engine/tests/run_tests.py storage`
Expected: FAIL (`the key is the seed from the environment` / no RuntimeError).

- [ ] **Step 3: Implement** `load_signing_key()` as in Interfaces; in `main._startup()` call `signing.load_signing_key()` before seeding so a bad seed stops the boot.

- [ ] **Step 4: Run** `.venv/Scripts/python engine/tests/run_tests.py` → `12/12 passed`.

- [ ] **Step 5: Commit** `feat(signing): read the Ed25519 seed from CANONRY_SIGNING_SEED`

---

### Task 2: Dialect-aware database layer

**Files:**
- Modify: `engine/db.py` (connect, schema, init_schema, knowledge-version counter, new helpers)
- Modify: `engine/claims.py:308` (`INSERT OR REPLACE` → `INSERT`; ids are always new, so behaviour is unchanged)
- Modify: `engine/knowledge.py:241` (catch `db.IntegrityError`), `engine/knowledge.py:280-284` (term insert via `db.insert_returning_id`)
- Modify: `engine/main.py:295` (`conn.execute("BEGIN IMMEDIATE")` → `db.begin_write(conn)`)
- Modify: `engine/requirements.txt` (add `psycopg[binary]==3.3.6`)
- Test: `engine/tests/test_storage.py` (section "database layer")

**Interfaces:**
- Produces in `db.py`:
  - `DATABASE_URL: Optional[str]` (module attribute, initialised from `CANONRY_DATABASE_URL`) and `DB_SCHEMA: Optional[str]` (from `CANONRY_DB_SCHEMA`; Postgres `search_path`, used by tests).
  - `dialect() -> Literal["sqlite", "postgres"]` — `"postgres"` iff `DATABASE_URL` is set.
  - `connect()` — SQLite: unchanged. Postgres: `PgConnection` wrapping `psycopg.connect(DATABASE_URL, prepare_threshold=None, row_factory=<Row factory>, options="-c search_path=<DB_SCHEMA>" if DB_SCHEMA)`.
  - `class PgConnection`: holds the psycopg connection as `self._conn`; `execute(sql: str, params: Sequence = ()) -> cursor` (translates placeholders), `executescript(sql: str) -> None`, `commit()`, `rollback()`, `close()`. Cursors expose `fetchone()`, `fetchall()`, `rowcount`, and iteration.
  - `class Row(dict)`: `row["col"]`, `row[0]` (by column position), `dict(row)`, `row.keys()` all work.
  - `to_pg_placeholders(sql: str) -> str`: `?` outside single-quoted literals → `%s`; every `%` → `%%`.
  - `schema_sql(dialect: str) -> str`: SQLite = today's `SCHEMA`; Postgres = same text with `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`.
  - `IntegrityError: Tuple[Type[Exception], ...]` = `(sqlite3.IntegrityError, psycopg.errors.IntegrityError)`.
  - `insert_returning_id(conn, sql: str, params: Sequence) -> int` — SQLite: `lastrowid`; Postgres: executes `sql + " RETURNING id"`.
  - `begin_write(conn) -> None` — SQLite: `BEGIN IMMEDIATE`; Postgres: no-op (psycopg already opened a transaction; the guarded `UPDATE … WHERE consumed_at IS NULL` plus `rowcount` check stays the real guard).
  - `next_knowledge_version(conn)` rewritten portably: `UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'knowledge_version'`; if `rowcount == 0`, `INSERT … VALUES ('knowledge_version', '1')`.
  - `init_schema()`: runs `schema_sql(dialect())`; the `PRAGMA table_info` column migrations and `_legacy_knowledge_version` (rowid) run **only** for SQLite; Postgres starts the counter at 0.

- [ ] **Step 1: Write the failing tests** (section "database layer", pure functions plus SQLite behaviour)

```python
expect(db.to_pg_placeholders("SELECT * FROM t WHERE a = ? AND b = '?'") ==
       "SELECT * FROM t WHERE a = %s AND b = '?'", "placeholder_translation: bare ? only")
expect(db.to_pg_placeholders("SELECT '100%' WHERE x LIKE ?") == "SELECT '100%%' WHERE x LIKE %s",
       "placeholder_translation: % is escaped")
pg = db.schema_sql("postgres")
expect("AUTOINCREMENT" not in pg and "GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" in pg, "postgres schema")
expect(db.schema_sql("sqlite") == db.SCHEMA, "sqlite schema unchanged")
r = db.Row({"id": "x", "n": 2})
expect(r["id"] == "x" and r[1] == 2 and dict(r) == {"id": "x", "n": 2} and list(r.keys()) == ["id", "n"], "Row")
conn = db.connect()
before = db.get_knowledge_version(conn)
expect(db.next_knowledge_version(conn) == before + 1, "portable knowledge-version counter")
tid = db.insert_returning_id(conn, "INSERT INTO terms (workspace_id, preferred, severity) VALUES (?,?,?)",
                             ("ws_x", "Pulse", "low"))
expect(isinstance(tid, int) and tid > 0, "insert_returning_id")
# pg_connection_disables_prepared_statements (runs only when CANONRY_TEST_DATABASE_URL is set)
if os.environ.get("CANONRY_TEST_DATABASE_URL"):
    expect(db.connect()._conn.prepare_threshold is None, "pg_connection_disables_prepared_statements")
```

- [ ] **Step 2: Run to verify it fails** — `run_tests.py storage` → FAIL (`to_pg_placeholders` not defined).

- [ ] **Step 3: Implement** the Interfaces above in `db.py`; import psycopg lazily inside the Postgres branch and inside the `IntegrityError` definition (fall back to `(sqlite3.IntegrityError,)` if psycopg is missing) so SQLite-only installs still start. Apply the four call-site changes listed under Files.

- [ ] **Step 4: Run** `.venv/Scripts/python engine/tests/run_tests.py` → all green on SQLite; `ruff check engine --select F,E9` clean.

- [ ] **Step 5: Commit** `feat(db): dialect-aware connection layer; Postgres via CANONRY_DATABASE_URL`

---

### Task 3: One test-database helper for every suite

**Files:**
- Modify: `engine/db.py` (two helpers)
- Modify: the 11 suite headers in `engine/tests/test_*.py` and `engine/evaluation/evaluate.py` (replace the copy-pasted "set `DB_PATH`, delete the files" block)
- Modify: `engine/tests/test_regressions.py:172` (MCP subprocess env)

**Interfaces:**
- Produces in `db.py`:
  - `use_test_database(name: str) -> None` — `name` is today's file stem (e.g. `"canonry_policy"`). If `CANONRY_TEST_DATABASE_URL` is set: `DATABASE_URL = <that url>`, `DB_SCHEMA = name`, then `DROP SCHEMA IF EXISTS <name> CASCADE; CREATE SCHEMA <name>`. Otherwise: `DATABASE_URL = None`, `DB_PATH = db/<name>.db`, remove the file and its `-wal`/`-shm`.
  - `subprocess_env() -> Dict[str, str]` — `os.environ` plus `CANONRY_DB_PATH`, and `CANONRY_DATABASE_URL` / `CANONRY_DB_SCHEMA` when on Postgres, so a child process (the MCP server) opens the same database.

- [ ] **Step 1: Write the failing test** (`test_storage.py`, section "test databases")

```python
db.use_test_database("canonry_storage_a")
c = db.connect(); db.init_schema(); c.execute("INSERT INTO meta (key, value) VALUES ('probe', '1')"); c.commit(); c.close()
db.use_test_database("canonry_storage_a")
db.init_schema(); c = db.connect()
expect(c.execute("SELECT COUNT(*) FROM meta WHERE key = 'probe'").fetchone()[0] == 0, "use_test_database starts empty")
env = db.subprocess_env()
expect(("CANONRY_DB_SCHEMA" in env) == (db.dialect() == "postgres"), "subprocess_env carries the database")
```

- [ ] **Step 2: Run** `run_tests.py storage` → FAIL (`use_test_database` not defined).

- [ ] **Step 3: Implement** the two helpers; replace each suite's header block with `db.use_test_database("<its current stem>")` (keep the stems: `canonry_test`, `canonry_identity`, `canonry_knowledge`, `canonry_regress`, `canonry_seedcheck`, `canonry_edge`, `canonry_policy` and `canonry_policy_blank`, `canonry_access`, `canonry_workflow`, `canonry_gateway`, `canonry_storage`; evaluate.py keeps `CANONRY_EVAL_DB` override and stem `canonry_eval`); `test_regressions.py` passes `env=db.subprocess_env()` to the MCP subprocess.

- [ ] **Step 4: Run** `run_tests.py` → all green on SQLite.

- [ ] **Step 5: Commit** `test: one helper picks each suite's fresh database (SQLite or Postgres)`

---

### Task 4: Every suite green on Postgres

**Files:**
- Modify: whichever engine modules the Postgres run flags (expected: none beyond Review Focus item 3)
- Test: `engine/tests/test_storage.py` (section "postgres round trip", skipped on SQLite)

**Interfaces:**
- Consumes: `db.use_test_database`, `db.connect`, `signing.sign_approval`, `signing.verify` (Tasks 1–3).

- [ ] **Step 1: Write the test** `seal_survives_reconnect` (runs only when `CANONRY_TEST_DATABASE_URL` is set): seed via `seed.seed()`, sign an approval, close the connection, reset `signing`'s cached state (none expected), open a new connection, assert `signing.verify(conn, poc_id, text)["status"] == "verified"`.

- [ ] **Step 2: Start a Postgres 15+** — any of: a free Supabase project (Settings → Database → connection string), a local install, or the CI service (Task 5). Set `CANONRY_TEST_DATABASE_URL` to it.

- [ ] **Step 3: Run** `.venv/Scripts/python engine/tests/run_tests.py` with that variable set. Expected first-run failures, if any, are the Review Focus items; fix each at its source (typed comparison → explicit `CAST`; grouping or ordering differences → make the query deterministic with `ORDER BY`). Do not weaken assertions.

- [ ] **Step 4: Run** again → `12/12 passed` on Postgres; then unset the variable and run → `12/12 passed` on SQLite.

- [ ] **Step 5: Commit** `fix: engine queries portable to Postgres; suites green on both databases`

---

### Task 5: CI runs the suites on Postgres too

**Files:**
- Modify: `.github/workflows/ci.yml` (new job `engine-postgres`)

- [ ] **Step 1: Add the job** — `runs-on: ubuntu-latest`; `services.postgres: image: postgres:16`, env `POSTGRES_PASSWORD: canonry`, ports `5432:5432`, health check `pg_isready`; steps as the existing `engine` job, with `CANONRY_TEST_DATABASE_URL: postgresql://postgres:canonry@localhost:5432/postgres` on the test step.

- [ ] **Step 2: Verify** — push the branch; the Actions run shows both `engine` (SQLite) and `engine-postgres` green.

- [ ] **Step 3: Commit** `ci: run every suite against Postgres 16`

---

### Task 6: Deployment configuration and documentation

**Files:**
- Modify: `render.yaml` (add `CANONRY_DATABASE_URL` and `CANONRY_SIGNING_SEED`, both `sync: false`, with a comment)
- Modify: `.env.example` (both variables, commented, with how to generate the seed)
- Modify: `docs/deployment.md` (§6 Persistence: Supabase steps — create project, copy the **transaction pooler** URL with `sslmode=require`, set the two variables on Render; generate the seed with `python -c "import secrets; print(secrets.token_hex(32))"`; table row "Render free + Supabase Free: ₹0, data and seals survive restarts: Yes")
- Modify: `README.md` (§5 tech table "SQLite, or Supabase Postgres"; §10 remove the "free hosting is ephemeral" limitation or narrow it to "without `CANONRY_DATABASE_URL`")
- Modify: `docs/plan-vs-build.md` (Supabase row: "SQLite by default; Supabase Postgres supported"), `docs/progress.md` (§9 gap list), `docs/decision-log.md` (append D54)
- Modify: `docs/architecture.md` §5 (one paragraph: dialect selection and the `db` helpers)

- [ ] **Step 1: Make the edits.** D54 text: "Postgres storage | `CANONRY_DATABASE_URL` switches the engine to Postgres (Supabase transaction pooler); SQLite stays the default; signing seed from `CANONRY_SIGNING_SEED`; CI runs every suite on both | Working | <date> | Free-tier hosting resets its disk on restart; judges' data and seals must survive (plan Sections 9.4, 9.8; D35 upgrade path)".

- [ ] **Step 2: Verify** — link check over `README.md` and `docs/*.md` reports none broken; `run_tests.py` green.

- [ ] **Step 3: Commit** `docs: Supabase persistence for the deployed demo (D54)`
