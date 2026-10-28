# Round 1 plan vs. Round 2 build

> The Round 1 plan (`Canonry_Round1_Plan_vaidvansh6.pdf`) is the yardstick for
> "progress against the plan". This page lists, section by section, what the
> plan committed to for Round 2, what the build does, **every change and why**,
> and what is still open. Section numbers refer to the plan. Decisions are dated
> in the [decision log](decision-log.md); evidence per milestone is in the
> [changelog](changelog.md).

---

## 1. Summary

| Plan commitment | Status |
|---|---|
| **Must** list (Section 11.3): rules, facts and terms → text submission → terminology and claim checks → cited findings with tiers → fix/dispute → risk routing → review/override → approve → history and revision diff | ✅ all delivered |
| **Should** list: Verified Claim Memory, Proof of Compliance, Canon Connector, rule tests, exemption policies, tone check, rule linting, CSV import | ✅ all delivered; some lighter than planned (section 3) |
| **Could** list: DOCX/PDF upload, basic insights, 20-sample evaluation set, monitoring dashboards | ◐ insights and the 20-sample evaluation set delivered; DOCX import for rules only; no monitoring dashboards |
| The three improvements (Section 8) | ✅ Round 2 scope delivered for all three ([README §3](../README.md#3-the-three-improvements-we-committed-to)) |
| Milestones M1–M6 (Section 11.2) | ✅ M2–M5 done; M1 and M6 done except the items in section 5 |

## 2. Milestones (Section 11.2)

| Milestone | Plan's "done when…" | Status |
|---|---|---|
| M1 · Foundations | A creator and a reviewer can log in on the deployed app | Code, CI and deployment blueprint done; the public deployment is being set up by the team |
| M2 · Knowledge base | Demo brand loaded; vague rules flagged | ✅ 43 rules, 41 facts, 10 terms; vague rules flagged at import |
| M3 · Check pipeline | Cited findings appear in the UI | ✅ |
| M4 · Workflow | The core journey runs end to end | ✅ (tested through the API and in the browser) |
| M5 · Standout features | An approved asset verifies; an AI assistant drafts using the canon | ✅ seal + public verify; Canon Connector over MCP |
| M6 · Evidence | Round 2 package complete | Evaluation baseline, architecture, decision and disclosure logs done; usability tests not yet run |

## 3. What changed from the plan, and why

### Architecture and tools (Sections 9.4 and 9.8)

| Plan said | Build does | Why | Upgrade path |
|---|---|---|---|
| Supabase Postgres + pgvector, row-level security | SQLite (WAL) with Postgres-compatible table and column names; access rules enforced in one engine module (`access.py`) | Judges and developers run it with no account or setup; one place to test role rules (`test_access.py`) | Point the data layer at Postgres; move `access.py` rules into RLS policies |
| fastembed embeddings + similarity search for facts and Claim Memory candidates | Keyword and number scoring over the Fact Library; Claim Memory reuses a verdict only on an exact claim key | For figures, exact matching *is* the rule ("2,300+" must never match "3,200+"); deterministic and free | pgvector retrieval for implied claims (Round 3) |
| FastAPI background tasks as the job queue | Checks run inline, recorded in `check_runs` | Short text checks do not need a queue yet | Queue adapter behind the `check_runs` seam |
| Email + Google sign-in | **Demo mode**: password-free personas for judges and tests. **Production mode**: passwords (PBKDF2) and one-use, role-bound invitations | The Round 2 criterion is that a judge can use the product without help (D36); production mode keeps real use secure | Google/SSO behind the same session layer |
| pypdf + python-docx for uploads | Content is pasted as text; rules import from Markdown, text and Word (.docx, parsed with the standard library) | Text covers the core loop; DOCX/PDF content upload was a "Could" | Content upload in Round 3 (plan Section 5, formats) |
| Sentry, Langfuse, OpenTelemetry | AI call ledger in the database (every attempt, provider, model, prompt version, latency, success) shown on Insights | Same visibility for AI calls with no extra service; no paid or hosted dependency | Add Sentry/Langfuse exporters |
| Vitest, Playwright, pytest; Dependabot, CodeQL | 10 Python suites through FastAPI's test client, evaluation gate, web type-check and production build, `pip-audit` and `npm audit` in CI | Covers the engine, where all product logic lives | Web unit and E2E tests, CodeQL (Round 3) |
| Finding contract validated with JSON Schema on both sides | Validated server-side (pydantic) before every finding is stored; TypeScript type on the web side | One enforcement point; the contract had drifted and enforcement caught it (D49) | Publish the JSON Schema from the pydantic model |
| AI cascade: small model first, larger model when confidence is low | Fixed fallback order: Gemini → Groq → OpenRouter → local Ollama | Simpler and predictable on free tiers | Confidence-based routing in the gateway |

### Standout features (Section 5.4)

| Plan said (Round 2) | Build does | Why |
|---|---|---|
| Canon Connector: look up a fact, check a claim, get the rules for a channel | ✅ as planned (`engine/mcp_server.py`), role-filtered | — |
| Verified Claim Memory with similarity match, diff-only re-checks, collapsed review view | Exact-key reuse tied to the knowledge version; whole revisions re-checked (repeat claims answered from memory); verified claims are not shown as findings | Exactness first (D38); diff-only re-checks matter for long documents, which come with uploads |
| Rule tests on every save; AI tests on demand; impact preview | Impact preview before a rule edit: which approved content would newly break or be freed | The preview is what protects approved content; per-example test runs come next |
| Proof of Compliance with a metadata stamp in PNG/JPEG/PDF and a demo publisher check | Signed record, hash-chained ledger and public verify page; the publisher check is "paste the published text" (D46) | Content is text this round, so there is no file to stamp |
| Escalation matrix with role and region routing, exemptions, SLA reminders | Risk from channel, source and open findings → low / medium / high / exempt; one seeded exemption policy (logged); no region routing or SLA timers yet | Core routing first; region and SLA need real reviewer queues (Round 3) |

### Design decisions made during the build (not in the plan)

| Change | Why | Decision |
|---|---|---|
| **Rule bindings**: each built-in check cites the workspace's own rule; a fresh workspace gets baseline rules | The engine originally only worked with the demo's rule ids | D43 |
| **Lifecycle lock**: content cannot change in review or after approval | Approved content must stay what the seal and audit trail describe | D45 |
| Claims verified against **publishable facts only** | A confidential fact can never support public copy; it must never reach an AI provider | D47 |
| **Versioned knowledge base** (history, restore, stale-approval list) | Findings must show which version of a rule or fact they were checked against | changelog 2026-10-27 |
| **Confidential-leak checker** | The brief asks to protect confidential material; drafts are now checked for it | `checkers.check_confidential` |
| Local **Ollama** as the last fallback | Plan Section 10: a local-model mode for confidential content | D48 |

## 4. Added beyond the plan

- Production mode with invitation-only sign-up and no self-approval, alongside the demo mode.
- `/health` endpoint and a one-file Render blueprint for the judge demo.
- A faked-provider test suite, so the AI path is tested in CI without keys or network.

## 5. Still open from the Round 2 plan

| Item | Plan section | Status |
|---|---|---|
| Public deployment | M1 | Blueprint and guide ready ([deployment.md](deployment.md)); deployment by the team |
| 5 usability tests with SUS | 11.6, M6 | Kit ready ([usability-test-kit.md](usability-test-kit.md)); sessions not run yet |
| Check-speed and verify-time measurements in CI | 9.6 | Not measured in CI yet |
| Accessibility checks (axe-core) in CI | 9.6 | Round 3 (M10) |
| Monitoring dashboards | 11.3 (Could) | Round 3 |

Everything Round 3 is unchanged from the plan (M7–M10): images and accessibility
checks, Brand Blast Radius, India pack, public API and webhooks, calibrated tiers.
