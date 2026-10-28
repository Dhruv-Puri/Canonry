# Changelog — progress against the Round 1 plan

> Plan Section 11.4 asks for a changelog **linked to the milestones** that shows
> progress against the plan. This is that record. Every entry names the evidence
> a judge can run or read; nothing here is a claim without a pointer.

---

## Round 2 · The Build — milestone status

| Milestone (plan Section 11.2) | Status | What shipped | Evidence |
|---|---|---|---|
| **M1 · Foundations** | ✅ code done, deployment pending | SQLite schema (`engine/db.py`) with Postgres-compatible naming; sign-in + roles (`/login`, `/join`, `access.py`); Finding Contract `finding@1` (`engine/contract.py`); provider-agnostic gateway that degrades honestly (`engine/gateway.py`); Quillmark demo data via CSV (`data/*.csv`, `engine/seed.py`) | `test_engine.py`, `test_identity.py`, `test_seed_data.py`; deployment steps in [deployment.md](deployment.md) |
| **M2 · Knowledge base** | ✅ done | Rules / facts / terms with versioned writes, reasons and full history; CSV import with vague-rule linting (`lint_rule`); rule tests & change preview endpoint (`/rules/{id}/preview-change`) now surfaced in the editor | `test_knowledge.py`; KB screen; `docs/progress.md` §7 |
| **M3 · Check pipeline** | ✅ done | Terminology, readability/CTA, tone, confidential checks; deterministic claim labelling; batched AI path (pending without a key); citation check with discard counters; tiers; **Verified Claim Memory** keyed by numbers/units/names and knowledge version | `test_engine.py`, `test_regressions.py`; `evaluate.py` |
| **M4 · Workflow** | ✅ done | Accept / edit / dispute with forced reasons; immutable revisions, automatic re-check; **revision diff view** (word-level, previous ↔ current); risk router (low/medium/high/exempt) with exemption policies; reviewer approve / request-changes / override-with-reason; high-severity 409 block; hash-chained audit log | `test_engine.py`, `test_identity.py`, `test_edge_cases.py`; submission detail screen |
| **M5 · Standout features** | ✅ done | **Proof of Compliance** (SHA-256 + Ed25519 + hash-chained ledger + public `/verify/<id>` page); **Canon Connector** (MCP over stdio, role-filtered facts); **Rule tests & change preview** (proposed edit → newly-broken approved content) | `test_engine.py`, `test_regressions.py` (MCP subprocess), `test_edge_cases.py` (preview) |
| **M6 · Evidence** | ✅ code-side done, human tasks open | **Evaluation baseline** (`engine/evaluation/eval_set.jsonl` + `evaluate.py`, frozen split, results committed in `eval_baseline.json`, gate wired into CI); architecture write-up (`docs/architecture.md`); decision log continued ([decision-log.md](decision-log.md)); disclosure log ([disclosure-log.md](disclosure-log.md)); usability-test kit ready to run ([usability-test-kit.md](usability-test-kit.md)) | `python engine/evaluation/evaluate.py`; `.github/workflows/ci.yml` |

**Still open for the Round 2 package (not code):** free-tier deployment to a
public URL, 5 usability tests with SUS, and the demo video — see
[deployment.md](deployment.md) and [usability-test-kit.md](usability-test-kit.md).

---

## 2026-10-26 · Initial build (`699e7d7`)

- Engine: schema, seed CSVs, checkers, claim pipeline, VCM, citation check,
  signing, MCP server, FastAPI endpoints.
- Web: dashboard, new submission, submission detail, knowledge base, insights,
  public verify — all reachable without credentials via one-click personas.
- Suites: `test_engine.py`, `test_identity.py`, `test_knowledge.py`,
  `test_seed_data.py`.

## 2026-10-27 · Hardening + evidence (`9a90cee`)

**Bugs found by testing and fixed** (full table in [progress.md](progress.md) §7):
invalid logins accepted, a 500 on an unknown resolve action, two silent no-op
decisions, overrides for findings that did not exist, a wrong-shape `/insights`
payload, number-format false positives, dashboard counts summed across old
revisions, and decimal-aware sentence splitting.

**Added in the same pass**

| Area | What | Verified by |
|---|---|---|
| Evaluation | `engine/evaluation/eval_set.jsonl` (20 labelled samples, ~30% frozen) + `evaluate.py`; baseline committed; per-tier and per-checker precision/recall; invalid-citation count; `--check` regression gate | `evaluate.py --check` → gate passed; CI step |
| Workflow | Revision diff view (word-level, +n/−m summary) on the submission detail | `npx tsc --noEmit`; browser walkthrough |
| Knowledge base | Rule-change preview in the editor: proposed rule text is tested against approved content before saving; shows what would newly break and what would be freed | `test_edge_cases.py` (section 10) |
| CI | GitHub Actions: all six suites, evaluation gate, type-check, production build, `pip-audit`, `npm audit` | `.github/workflows/ci.yml` |
| Docs | Beginner tutorial, deployment guide, disclosure log, usability kit, this changelog | linked from the README |

## 2026-10-28 · Review fixes, structure, deployment

A code review and browser checks found nine defects; each was first reproduced by a failing test,
then fixed (table in [progress.md](progress.md) §8, decisions D43–D52 in the
[decision log](decision-log.md)).

| Area | What | Verified by |
|---|---|---|
| Checks | Rule bindings: every built-in check cites the workspace's own rule; baseline rules for a fresh workspace | `test_policy.py` |
| Access | Agency scoping on every cross-submission read; confidential text redacted everywhere | `test_access.py` |
| Workflow | Content locked in review and after approval; the engine tells the UI what each status allows | `test_workflow.py` |
| Proof of Compliance | Public page checks pasted published text (Verified / Modified); no emails | `test_workflow.py` |
| AI gateway | Provider adapters (Gemini, Groq, OpenRouter, local Ollama), real fallback, honest ledger, confidential facts never sent | `test_gateway.py` (faked providers) |
| Contract | Every finding validated against `finding@1` before storage | all suites |
| Repository | Tests in `engine/tests/` with one runner, evaluation in `engine/evaluation/`, decision log in `docs/`, dead code removed, judge-demo blueprint (`render.yaml`), `/health` endpoint, deployment guide rewritten | `run_tests.py` → 11/11; `npm run build` |

## 2026-10-28 · Daily AI allowance

| Area | What | Verified by |
|---|---|---|
| AI gateway | Daily allowance: 5 AI-assisted checks per person, 50 per workspace (configurable); failed provider calls never charged; admins not exempt (D53) | `test_quota.py` |
| Web | The "AI checks are pending" banner now says exactly why (no key, your allowance, workspace allowance, provider busy, per-check budget) and when it resets; an "AI checks today: n of 5" counter | browser check of the production build |
| Startup | Clearer error when production mode lacks an admin: it now points to `CANONRY_DEMO_MODE=true` for local demos | — |
| Tests | Suites and the evaluation never reach a real AI provider (`CANONRY_ENV_FILE=""`, provider keys cleared); a local `.env` with a real key had made the suites call Gemini | full run with a real key present: 12/12, zero real calls |
| Local start | `engine/run_local.py`: one start command for PowerShell, cmd, Git Bash and macOS (demo mode, port 8000, auto-reload); the README's shell-specific command failed in PowerShell | started from PowerShell with no variables set |

**Deliberately deferred to Round 3** (unchanged from plan M7–M10): pgvector
retrieval on managed Postgres, rule editor impact preview for *create* flows,
reviewer inbox with SLA timers, image checks, Brand Blast Radius.
