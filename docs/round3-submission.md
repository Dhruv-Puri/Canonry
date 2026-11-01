# Canonry — Round 3 submission (team vaidvansh6)

> Draft answers for the Round 3 form. Sections marked **[pending]** are filled in once their testing
> is finished; nothing here claims more than the repository and the live demo show.

| | |
|---|---|
| **Live link** | https://canonry-sigma.vercel.app (pick a role, *Continue as guest*). Engine: https://canonry-engine.onrender.com/health. Free tier: the first visit after idle can take about 50 s. |
| **Repository** | https://github.com/Dhruv-Puri/Canonry (public; branch `main`) |
| **Final PDF** | [pending] |

## 1. Feature list

**Core workflow (Round 2, hardened in Round 3)**
- Write or upload content; checks run on save. Every finding shows the exact text, a plain explanation,
  the rule or fact it rests on (no citation, no finding), a confidence tier (Definite / Likely / Consider)
  and, where possible, a one-click fix.
- Checks: approved terms and retired names, readability, tone, confidential-fact leaks, claims verified
  against an approved fact library (numbers matched exactly; expired and superseded facts caught),
  AI-assisted implied claims and tone on free models, with honest degradation when AI is unavailable.
- People decide: accept, edit or dispute each finding; risk-routed review; approve, request changes or
  override with a reason; everything recorded.
- Proof of Compliance: an Ed25519-signed, hash-chained approval record; a public page verifies pasted
  text or a published file.
- Knowledge base with versioned rules, facts and terms, change history and change-impact preview;
  insights on expiring facts, unclear rules and AI usage; roles with agency scoping and confidential
  redaction; a daily AI allowance.

**Improvement 1 — documents and images (Round 3)**
- Upload PDF, Word, PNG or JPEG. PDF findings point to the **page and line**, Word findings to the
  **section and paragraph**.
- **Word fixes are made inside the .docx**, keeping its formatting; PDFs and images are corrected at the
  source and uploaded as a **new version** of the same submission.
- **Words in images are read** (Tesseract) and checked like any copy; **text contrast** is measured per
  line against WCAG AA and boxed on the preview.
- **Logo use**: the brand-kit logo is found at any size and checked for a retired version, stretching,
  tilting, recolouring, a busy background, crowded clear space and minimum size.
- Brand-palette check and alt-text check.
- The approved file carries its **signed proof in its own metadata** (PDF, Word, PNG, JPEG); the public
  verify page accepts the file, and a changed file or a copied seal does not verify.

**Improvement 2 — publishing gate: REST API + webhooks** [pending — after testing]

**Improvement 3 — India advertising compliance pack** [pending — after testing]

## 2. Architecture summary

One FastAPI engine holds every rule and check; a Next.js 16 web app renders the screens and reaches the
engine through a same-origin proxy (`/engine/*`), so cookies stay first-party and there is no CORS. The
engine stores everything in SQLite (WAL) with a Postgres-compatible schema; a Postgres connection is
supported. A check run goes: rule checkers → claim pipeline (patterns, fact retrieval, Verified Claim
Memory) → AI gateway (Gemini → Groq → OpenRouter → Ollama, free tiers, confidential data never sent)
→ India compliance pack → finding-contract and citation check → stored. Uploaded files are parsed into text with a
locator map (page/line, paragraph, or image box); image checks (palette, contrast, logo with OpenCV ORB +
homography, alt text) run on the pixels. Approvals are signed with Ed25519 and, for files, stamped into
the file. Deployed on free tiers: Render (engine, Docker with Tesseract) and Vercel (web).
Details: README §5 and [architecture.md](architecture.md); decisions with reasons: [decision-log.md](decision-log.md).

## 3. Improvements completed after Round 2

| # | Improvement | Status | Evidence |
|---|---|---|---|
| 1 | Documents and images | Done | README §12 "Improvement 1 — delivered"; suites `test_documents`, `test_image_text`, `test_logos`, `test_docx_fix`, `test_review_r3` |
| 2 | REST API + webhooks + demo publisher | [pending] | |
| 3 | India compliance pack with retrieval | [pending] | |

Reliability work across the product: [pending — journey, bad input, double actions, refresh, phone].

## 4. Testing details

- **Automated:** `python engine/tests/run_tests.py` runs 19 suites on a fresh database each, plus the
  evaluation gate (precision and recall per checker on a frozen split). The suites never call a real AI
  provider; malformed AI answers are tested with a fake provider. CI runs them on every push with a web
  type-check, a production build, `pip-audit` and `npm audit`.
- **Browser:** a scripted walk-through of every role and file type in Edge [pending: final numbers].
- **Code review:** an independent review of the Round 3 branch; every Important finding fixed with a
  test that failed first (docs/progress.md §0).
- **Bugs found by testing and fixed:** docs/progress.md §0, §7, §8.
- **Usability:** [pending — honest description of what was and was not run].

## 5. Roadmap

[pending — written last, from what testing showed is missing]
