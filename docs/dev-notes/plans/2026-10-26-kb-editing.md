# Knowledge Base Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reviewers and admins can create, edit, retire and restore rules, facts and terms, with every change versioned so findings and signed approvals keep pointing at exactly what they were checked against.

**Architecture:** A new `engine/knowledge.py` owns all knowledge writes: it validates, updates the current row in `rules`/`facts`/`terms` (still the read model for every checker), appends a full snapshot to `knowledge_history`, and advances a monotonic knowledge-version counter. The pipeline pins citation versions and stamps claim memory with the knowledge version; the web Knowledge base page gains forms, history and restore.

**Tech Stack:** Python 3.11, FastAPI, SQLite (engine); Next.js 16 / React 19 / Tailwind 4 (web). Tests are the repo's script style (`expect(cond, msg)`, exit 1 on failure), run with the venv Python.

**Spec:** `docs/superpowers/specs/2026-10-26-kb-editing-design.md`

## Global Constraints

- Nothing in `rules`, `facts`, `terms` or `knowledge_history` is ever deleted; retire is a status change.
- Every update, retire and restore requires `reason` (stripped length ≥ 3); create's reason is optional.
- Only roles `reviewer` and `admin` may write; others get `403`.
- `expected_version` mismatch → `409` with detail `"Changed by someone else (now vN). Reload and try again."`.
- Validation failures → `422` with a plain-English `detail` string naming the field.
- Severity values: `low`, `medium`, `high`. Rule status values: `approved`, `draft`, `retired`. Term status: `active`, `retired`.
- Dates are `YYYY-MM-DD`.
- Work stays uncommitted (owner's instruction): every task ends by running all suites instead of committing.
- Test command prefix (from `engine/`): `PYTHONIOENCODING=utf-8 $VENV/Scripts/python` where `$VENV` is the engine venv.

## Review Focus

- Two editors save the same fact from stale pages → the second gets 409, not a silent overwrite (Task 2, `stale expected_version is refused`).
- Retiring a term must stop it being flagged on the very next check (Task 2, `retired term no longer flagged`).
- Restoring to a retired snapshot or to a version that doesn't exist → 409 / 404, never a corrupt row (Task 2, `restore rejects retired or unknown version`).
- A fact edit after a claim was verified must not reuse the old verdict (Task 3, `claim memory not reused across knowledge versions`).
- An existing local database (already seeded, no history) must migrate in place on startup without losing data or lowering the knowledge version (Task 1, `migration backfills history and never lowers the version`).

---

### Task 1: Version history core and migration

**Files:**
- Create: `engine/knowledge.py`
- Modify: `engine/db.py` (schema, `init_schema` migration, replace `knowledge_version`/`bump_knowledge`/`get_knowledge_version`)
- Modify: `engine/seed.py` (write `seed` history rows; terms get `status`)
- Modify: `engine/pipeline.py:40-48` (use `get_knowledge_version`)
- Test: `engine/test_knowledge.py` (new, script style, own DB `canonry_knowledge.db`)

**Interfaces:**
- Produces (in `engine/db.py`):
  - table `knowledge_history(id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL, snapshot_json TEXT NOT NULL, reason TEXT, by_user TEXT, at TEXT NOT NULL, knowledge_version INTEGER NOT NULL, UNIQUE(workspace_id, entity, entity_id, version))`
  - columns `facts.version INTEGER NOT NULL DEFAULT 1`, `terms.version INTEGER NOT NULL DEFAULT 1`, `terms.status TEXT NOT NULL DEFAULT 'active'`, `claim_memory.knowledge_version INTEGER` (added by migration if missing)
  - `get_knowledge_version(conn) -> int` (reads `meta('knowledge_version')`)
  - `next_knowledge_version(conn) -> int` (increments, returns new value)
  - `bump_knowledge(conn) -> None` kept as a thin alias of `next_knowledge_version` (seed and the repair script call it)
- Produces (in `engine/knowledge.py`):
  - `ENTITIES = {"rules": "rule", "facts": "fact", "terms": "term"}`
  - `snapshot(conn, ws: str, entity: str, entity_id: str) -> Optional[dict]` (current row as dict)
  - `record_version(conn, ws, entity, entity_id, version: int, action: str, reason: Optional[str], by_user: str, kv: int) -> None`
  - `current_version(conn, ws, entity, entity_id) -> Optional[int]`
  - `snapshot_at(conn, ws, entity, entity_id, version: int) -> Optional[dict]`
  - `history(conn, ws, entity, entity_id) -> List[dict]` (newest first; each has version, action, snapshot, reason, by_user, at, knowledge_version)
  - `backfill_history(conn) -> int` (writes a `seed` row for every entity with no history; returns count)

- [ ] **Step 1: Write the failing tests** in `engine/test_knowledge.py`:
  - `seed writes history`: after `seed()`, `history(conn, ws, "rule", "BRD-01")` has one row, `action == "seed"`, `version == 1`, `snapshot["statement"]` equals the rules row.
  - `every entity has history`: count of distinct `(entity, entity_id)` in `knowledge_history` == rules + facts + terms row counts.
  - `next_knowledge_version is monotonic`: `a = get_knowledge_version(conn)`; `next_knowledge_version(conn) == a + 1`; `get_knowledge_version(conn) == a + 1`.
  - `migration backfills history and never lowers the version`: build a DB the old way (run `init_schema()` then delete all `knowledge_history` rows, drop meta key `knowledge_version`, set meta `knowledge_version_bump` to `'95'`, insert a `check_runs` row with `knowledge_version = 500`), call `init_schema()` again → history rows exist for every entity and `get_knowledge_version(conn) >= 500`.
- [ ] **Step 2: Run** `... test_knowledge.py` → FAIL (`ModuleNotFoundError: knowledge` / missing table).
- [ ] **Step 3: Implement** schema + migration in `db.py`. Migration order inside `init_schema()`: add missing columns via `PRAGMA table_info`; create `knowledge_history`; if `meta('knowledge_version')` is absent, set it to `max(old_rowid_sum + old_bump, max(check_runs.knowledge_version), 1)`; then `knowledge.backfill_history(conn)` (import inside the function to avoid a cycle). `seed.py` calls `record_version(..., action="seed", by_user="system")` per inserted entity, using one `next_knowledge_version` for the whole seed.
- [ ] **Step 4: Replace** the rowid-sum block in `pipeline.py` with `kv_bumped = get_knowledge_version(conn)`.
- [ ] **Step 5: Run** `test_knowledge.py`, `test_seed_data.py`, `test_engine.py`, `test_regressions.py` → all PASS.

---

### Task 2: Write API (create / update / retire / restore / history)

**Files:**
- Modify: `engine/knowledge.py` (write functions + validation)
- Modify: `engine/main.py` (routes under `/kb`; delete `PATCH /rules/{rule_id}` and `POST /facts` + `FactIn`; `GET /rules|/facts|/terms` unchanged in shape but now include `version`, terms include `status`)
- Modify: `engine/checkers.py:61` (terms query)
- Test: `engine/test_knowledge.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces (in `knowledge.py`), all raising `KBError(status: int, detail: str)` on refusal:
  - `create(conn, ws, kind: str, fields: dict, user: Row, reason: Optional[str]) -> dict` → `{"entity": <current row dict>, "knowledge_version": int}`
  - `update(conn, ws, kind, entity_id, fields: dict, expected_version: int, user, reason: str) -> dict` → same shape plus `"impact"` for facts (Task 4 fills it; return `[]` until then)
  - `retire(conn, ws, kind, entity_id, expected_version, user, reason) -> dict`
  - `restore(conn, ws, kind, entity_id, to_version: int, expected_version, user, reason) -> dict`
- Routes (`kind` ∈ rules | facts | terms, else 404):
  - `POST /kb/{kind}` body `{fields..., reason?}` → 200 `create` result
  - `PUT /kb/{kind}/{id}` body `{fields..., expected_version, reason}`
  - `POST /kb/{kind}/{id}/retire` body `{expected_version, reason}`
  - `POST /kb/{kind}/{id}/restore` body `{version, expected_version, reason}`
  - `GET /kb/{kind}/{id}/history` → `{"versions": history(...)}` (any signed-in user)
- Editable fields — rules: `id?` (create only), `category, statement, do_example, dont_example, severity, status` (status ∈ approved|draft); facts: `text, category, owner, source, valid_from, valid_to, confidential` (bool→0/1); terms: `preferred, banned_or_check, note, severity`.
- Every write: one `next_knowledge_version`, one `record_version`, one `audit(conn, user email, "kb_<action>_<entity>", "<id> v<n>: <reason>")`, then commit.
- Rule writes recompute `vague_flag = lint_rule(statement, do, dont, other statements)` (move `lint_rule` from `main.py` into `knowledge.py`; `main.py` imports it).
- Retire: rule `status='retired'`, fact `superseded=1`, term `status='retired'`. Retiring an already-retired entity → 409 `"Already retired"`.
- Restore copies the editable fields of `snapshot_at(to_version)`; target missing → 404; target snapshot retired → 409 `"Cannot restore a retired version"`.
- Terms query in `checkers.check_terminology` becomes `... FROM terms WHERE workspace_id = ? AND status = 'active'` with the workspace from `submissions` joined through the revision.

- [ ] **Step 1: Write the failing tests** (via `TestClient(main.app)`, logging in as maya/arjun with `POST /login`):
  - `creator cannot edit`: arjun `PUT /kb/rules/BRD-01` → 403.
  - `create rule assigns category prefix`: maya `POST /kb/rules {"category":"Brand","statement":"Never place the logo on photos of people.","severity":"low"}` → id `BRD-03`, `version == 1`, history has `create`.
  - `explicit bad rule id refused`: `{"id":"brand 1", ...}` → 422.
  - `update bumps version and knowledge version`: PUT BRD-01 with `expected_version=1, reason="palette refresh"` → version 2, response `knowledge_version` > previous `get_knowledge_version`.
  - `update without reason refused`: reason `"  "` → 422.
  - `stale expected_version is refused`: PUT BRD-01 again with `expected_version=1` → 409 and detail contains `"now v2"`.
  - `fact validation`: `POST /kb/facts` missing `owner` → 422; `valid_to < valid_from` → 422; `valid_to="30/09/2026"` → 422.
  - `create fact numbering`: valid fact → id matches `^F-\d{3}$` and is greater than every existing `F-\d{3}`.
  - `term needs a word`: `POST /kb/terms {"note":"x"}` → 422.
  - `retired term no longer flagged`: submit `"Our employees love it."` → a terminology finding on `employees`; retire term 3 (`employees`) with reason; submit the same text → no terminology finding.
  - `retire twice refused`: retiring term 3 again → 409.
  - `restore brings back an earlier version`: restore BRD-01 `version=1` (`expected_version=2`) → version 3 whose statement equals the v1 statement; history shows `restore`.
  - `restore rejects retired or unknown version`: restore term 3 to its retired version → 409; restore BRD-01 to version 99 → 404.
  - `history newest first`: `GET /kb/rules/BRD-01/history` → versions `[3,2,1]`.
- [ ] **Step 2: Run** → FAIL (404 on `/kb/...`).
- [ ] **Step 3: Implement** the four write functions, validation, ID allocation (spec decision 7) and routes; map `KBError` to `HTTPException`.
- [ ] **Step 4: Run** all four suites → PASS.

---

### Task 3: Version-pinned citations, version-stamped claim memory, PoC knowledge version

**Files:**
- Modify: `engine/pipeline.py` (before INSERT of findings, add `version` to each fact/rule/term/pack citation)
- Modify: `engine/claims.py:280-305` (`vcm_lookup(conn, ws, key, claim_numbers, kv: int)`, `vcm_store(..., kv: int)`; reuse only when `row["knowledge_version"] == kv`)
- Modify: `engine/main.py` `get_submission` (excerpt from `snapshot_at(version)` when present; add `current_version`)
- Modify: `engine/signing.py` (`knowledge_version` in record; kind `ProofOfCompliance/2`)
- Test: `engine/test_knowledge.py`

**Interfaces:**
- Consumes: `current_version`, `snapshot_at`, `get_knowledge_version`.
- Produces: citation dicts `{"type", "id", "version": int, ...}`; in `GET /submissions/{id}` each such citation also has `"current_version": int` and `excerpt` from the pinned snapshot.

- [ ] **Step 1: Write the failing tests:**
  - `citations carry versions`: submit the launch post → every fact/rule/term citation has an integer `version`.
  - `old finding shows the text it was checked against`: note the excerpt of the `TERM-04` citation; update `TERM-04`'s statement (reason given); `GET /submissions/{id}` → that citation's `excerpt` is the old statement, `version` unchanged, `current_version == version + 1`.
  - `claim memory not reused across knowledge versions`: `vcm_store(conn, ws, "k1", ["2300"], "supported", ["F-012"], "x", None, "m", kv=7)`; `vcm_lookup(conn, ws, "k1", ["2300"], kv=7)` is not None; `vcm_lookup(..., kv=8)` is None; a pre-existing row with `knowledge_version NULL` is never returned.
  - `PoC records knowledge version`: approve a clean submission → `GET /verify/{poc}` record has `knowledge_version` == value at approval and `kind == "ProofOfCompliance/2"`; an old-shape record still verifies (existing regression suite covers verify).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** as listed; existing `claim_memory` rows have `knowledge_version NULL` and are therefore never reused.
- [ ] **Step 4: Run** all suites → PASS.

---

### Task 4: Fact-change impact and "needs re-review" list

**Files:**
- Modify: `engine/knowledge.py` (`affected_approved_content(conn, ws, fact_id: str, old_text: str) -> List[dict]`; called by `update`/`retire`/`restore` for facts)
- Modify: `engine/main.py` (`GET /kb/stale-approvals`)
- Test: `engine/test_knowledge.py`

**Interfaces:**
- Produces: impact items `{"submission_id", "title", "status", "because"}`; `GET /kb/stale-approvals` → `{"items": [{"submission_id","title","status","cites": "<Type> <id> v<n>", "current_version": int}]}`.
- Approved statuses: `Approved`, `Signed`, `Exempt-approved`.
- `affected_approved_content` matches approved submissions whose latest revision (a) has a finding citing the fact id, or (b) contains any number token of ≥ 3 digits from `old_text` (regex `\d[\d,]*\d`, compared with commas removed). `because` says which.
- Stale approvals = approved submissions whose latest revision has a citation with `version < current_version` of that entity.

- [ ] **Step 1: Write the failing tests:**
  - `fact edit lists approved content using the old number`: create + approve (maya) a submission containing `"2,300+ teams"`; `PUT /kb/facts/F-012` changing the count → response `impact` contains that submission with `because` mentioning `2300`.
  - `unrelated approved content not listed`: an approved submission without the number or a citation is absent.
  - `stale approvals after rule edit`: submit `"Quillmark Insights is here."` (finding cites `TERM-04`); arjun submits for review; maya overrides that finding (`action:"override"`, `finding_id`, reason) and approves, so the approved revision still carries the citation; update `TERM-04` (reason given) → `GET /kb/stale-approvals` lists that submission with `cites == "Rule TERM-04 v<old>"` and `current_version == old + 1`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** all suites → PASS.

---

### Task 5: Knowledge base page — edit, retire, restore, history

**Files:**
- Modify: `web/src/lib/api.ts` (types `Rule`, `Fact`, `Term` incl. `version`/`status`; `KBKind = "rules" | "facts" | "terms"`; `HistoryEntry`)
- Create: `web/src/app/kb/editor.tsx` (client: `EntityForm`, `HistoryDialog`, `ImpactNotice`)
- Modify: `web/src/app/kb/page.tsx`

**Interfaces:**
- Consumes: Task 2 routes; Task 4 `impact` on fact responses.
- Behaviour fixed by this plan:
  - Editors (`me.role` reviewer|admin) see "New rule/fact/term", and per card "Edit", "History", "Retire" (or "Restore" when retired). Others see read-only cards plus "History".
  - Edit/create opens a shadcn `Dialog` with the fields of Task 2; update/retire/restore require a reason field (≥ 3 chars) before the submit button enables.
  - A `409` keeps the dialog open and shows the server detail with a "Reload" button that refetches the entity.
  - Toolbar per tab: search box (matches id/statement/text/term words, case-insensitive) and "Show retired" toggle (off by default).
  - Card shows `v<n>`; facts without `valid_to` show a "No expiry set" warning chip; retired cards are dimmed with a "Retired" badge.
  - History dialog lists versions newest first: version, action, author, date, reason, and the fields that changed vs the previous version (old struck through, new beside it); each non-retired older version has "Restore this version" (editors only).
  - After a fact save with non-empty `impact`, show an inline notice listing each item as a link to `/submissions/{id}` with its `because`.
- [ ] **Step 1:** `npx tsc --noEmit` and `npm run build` pass.
- [ ] **Step 2: Manual check in the running app** as Maya: create a rule, edit it twice, view history, restore v1, retire it, toggle "Show retired"; as Arjun the edit buttons are absent and `PUT` is 403 in the network tab. Edit fact F-012's number and see the impact notice list the approved post.

---

### Task 6: Versions on the review page and re-review list on Insights

**Files:**
- Modify: `web/src/lib/api.ts` (`Citation` gains `version?: number; current_version?: number`)
- Modify: `web/src/app/submissions/[id]/detail.tsx` (citation line)
- Modify: `web/src/app/insights/page.tsx` (new card from `GET /kb/stale-approvals`)

**Interfaces:**
- Consumes: Task 3 citation fields; Task 4 endpoint.
- Citation line reads `Rule TERM-04 v1:` and, when `current_version > version`, appends a warning chip `Updated since (now v2)` linking to `/kb`.
- Insights card "Approved content to re-review": each item links to its submission and shows `cites`; empty state "Every approved item cites current knowledge."
- [ ] **Step 1:** `npx tsc --noEmit` and `npm run build` pass.
- [ ] **Step 2: Manual check:** after Task 5's edits, an older finding shows `Updated since (now vN)`, and Insights lists the approved post.
