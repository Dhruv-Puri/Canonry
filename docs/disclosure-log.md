# Disclosure log

> Plan Section 11.4 / Section 15 require a disclosure log of **AI tools, APIs,
> libraries and templates, recorded as they are used**. Entries are added as
> things enter the build; nothing is silently included.

---

## 1. AI assistance used to write the product

| Where | Tool | What it did | Human control |
|---|---|---|---|
| Planning (Round 1) | Anthropic Claude via Claude Code | Research synthesis and drafting of the plan document | Team directed and reviewed; disclosed in the plan PDF (page 16) |
| Build (Round 2) | Anthropic Claude / Codebuff agents | Drafted engine and web code, tests and documentation under the team's direction | Every change reviewed by the team, run against the suites, and committed deliberately; the eval harness measures the product, not the assistant |
| Build (Round 3) | Anthropic Claude via Claude Code | Drafted engine and web code, tests, browser test scripts, documentation and the final PDF under the team's direction | Same as Round 2: the team set the scope, reviewed every change and merged it through GitHub pull requests after the suites and the browser run passed |
| Build (Round 3) | GitHub Copilot coding agent | Two commits on 1 Nov (`af3f5e3`, `c5ecbbd`): approval signing kept in one transaction; SQLite lock escalation for concurrent review actions | Opened as a pull request and merged by the team after review |
| Build (Round 3) | Google Gemini (chat) | Drafted a UX brief (role-specific views and tours, contrast) that the team then filtered; only the parts the team kept were built | Brief only; no code from it was committed |

## 2. AI **inside** the product (runtime)

The product calls an AI provider **only** for the two jobs rules cannot do:
finding *implicit* claims and judging tone against the brand's own voice rules.
Everything else is deterministic.

| Provider | Purpose | Status in the submitted demo |
|---|---|---|
| Google AI Studio — Gemini (free tier, default `gemini-3.1-flash-lite`, then other free Gemini models when it is busy) | implicit-claim extraction, claim verification, tone check, and (Round 3) one image-understanding call per checked image; first in the fallback chain | **configured on the live demo** (key held only on Render) |
| Groq (free tier, default `llama-3.1-8b-instant`) | same text tasks, second in the chain | configured on the live demo as a fallback |
| OpenRouter (free models, default `meta-llama/llama-3.3-70b-instruct:free`) | same tasks, third in the chain | not configured |
| Ollama (local, default `llama3.1:8b`, set `OLLAMA_URL`) | same tasks, last in the chain; nothing leaves the machine | not configured |

- Budget: at most 3 batched calls per 1,000-word check, enforced in
  `engine/gateway.py` (`call_budget_ok`).
- Data policy: only the content and the publishable facts go to a provider —
  never the whole knowledge base and never a confidential fact (the pipeline
  verifies claims against publishable facts only; `test_gateway.py` checks
  every outgoing request).
- Models are defaults, not dependencies: each can be changed with
  `CANONRY_<PROVIDER>_MODEL`.
- With **no** provider configured (a local run without a `.env`, and every
  test suite) no content leaves the machine at all; rule checks still run and
  AI checks are marked pending with the reason.
- Each person has a daily AI allowance (5 checks; 50 per workspace), so one
  visitor cannot use up the free keys for everyone.

## 3. External services and data

| Service | Use | Notes |
|---|---|---|
| Google AI Studio, Groq | AI providers for the live demo (section 2) | Free tiers; only the content being checked and publishable facts are sent |
| No telemetry | The engine and web app store everything in their own SQLite database | No analytics scripts in the web app |
| GitHub Actions | CI (tests, evaluation gate, type-check, build, dependency audits) | Free tier; no secrets required |
| Render (free web service) | hosts the engine for the judge demo (`render.yaml`) | Ephemeral disk; demo data only |
| Vercel (Hobby) | hosts the web app | Proxies `/engine/*` to Render |

**Demo data is fictional.** Quillmark Analytics, its people, prices, customer
counts and certifications are invented for the challenge ("Quillmark" is not a
real company). No customer, employer or third-party confidential material is
present in the repository or the demo database.

## 4. Open-source libraries

Engine (`engine/requirements.txt`): **FastAPI**, **uvicorn**, **httpx**,
**pydantic**, **PyNaCl** (Ed25519 signing); Round 3: **pypdf** (PDF text and
stamps), **lxml** (Word files), **Pillow** (images), **NumPy** and
**OpenCV** (headless; logo matching), **psycopg** (optional Postgres +
pgvector path). **Tesseract OCR** (Apache 2.0) is installed in the Docker image
to read words in images.
Python standard library supplies SQLite, CSV, hashing and the rest.

Web (`web/package.json`): **Next.js 16** (App Router), **React 19**,
**Tailwind CSS 4** (via `@tailwindcss/turbopack`), **lucide-react** (icons),
**radix-ui** primitives, **class-variance-authority**, **cn**, TypeScript.

Development-only: `pip-audit` (CI dependency scan), `npm audit`, `ruff` (lint, dead-code check).
No component library, dashboard template or boilerplate project was copied into
this repository: the UI primitives are thin wrappers over Radix, and the design
language is the team's own (`design.md` at the repository root of the
workspace).

## 5. Assets

| Asset | Origin | Licence/notes |
|---|---|---|
| Fonts | Geist Sans, Geist Mono, Source Serif 4 via `next/font/google` | Open Font Licence, self-hosted by the Next build |
| Icons | lucide-react | ISC licence |
| Brand mark | Drawn in code (`components/brand.tsx`) | Team's own |
| Seed CSV data | Written by the team | Fictional; see §3 |
| India pack clauses | Quoted from the CCPA Guidelines for Prevention of Misleading Advertisements (2022) and the ASCI Code, each with its source link | Public regulatory text, cited |
| ASCI test cases | 45 ad lines quoted from published reports of upheld ASCI complaints (bestmediainfo, mediabrief), with links (`data/compliance/india_asci_cases.jsonl`) | Short quotations used for testing |
| Demo logo and files | `data/brand/`, `data/demo/`: drawn and written by the team | Fictional brand |

## 6. Templates and scaffolding

None. The repository was created by hand for this challenge; no starter
template, generator output or third-party scaffold was used.

---

*Last updated: 2026-11-03. Add an entry whenever a new tool, service, library or
asset enters the build.*
