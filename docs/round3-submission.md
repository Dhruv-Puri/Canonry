# Canonry — Round 3 submission (team vaidvansh6)

> Answers for the Round 3 form. Nothing here claims more than the repository and the live demo show;
> what is not done is said in §5 and in README §6.

| | |
|---|---|
| **Live link** | https://canonry-sigma.vercel.app (tick *Show me around* on a first visit, then *Continue as guest*). Engine health: https://canonry-engine.onrender.com/health. Free tier: the first visit after idle can take about 50 s; the page says so while it wakes up. |
| **Demo accounts** | Shared on purpose so you can try every role without signing up; a real deployment uses production mode (one-use invitations, own passwords, fixed roles, agencies isolated). See README, "Demo accounts". |
| **Repository** | https://github.com/Dhruv-Puri/Canonry (public; branch `main`) |
| **Final PDF** | `Canonry_Round3_Final_vaidvansh6.pdf` (attached; also in the repository at `docs/`) |

## 1. Feature list

**Core workflow (Round 2, hardened in Round 3)**
- Write, paste or upload content; checks run on save. Every finding shows the exact text, a plain
  explanation, the rule or fact it rests on (no citation, no finding), a confidence tier (*Must fix* /
  *Should fix* / *Worth a look*) and, where possible, a one-click fix; "Accept all suggested fixes" takes
  every safe one.
- **Understand first, then check:** each check starts by reading what the content is (format, kind,
  purpose, audience, language, the claims it makes) and runs only the checks that fit; claims that are
  denied, attributed to someone else or quoted are read in context; duplicate findings from different
  checkers become one card; a suggested fix is never shown if it would bring back another issue; every
  rule an explanation names is cited. The page shows what Canonry understood and which checks ran.
- Checks: approved terms and retired names, readability, tone, confidential-fact leaks, claims verified
  against an approved fact library (numbers matched exactly; expired and superseded facts caught),
  AI-assisted implied claims and tone on free models, with honest degradation when AI is unavailable.
- People decide: accept, edit or dispute each finding; risk-routed review; approve, request changes
  or override with a reason; everything recorded.
- **My work for writers:** every draft grouped as sent back, to finish, with a reviewer or approved, with
  the reviewer's verdict and words on the card; a sent-back draft opens on the reviewer's request, and
  its text can be edited into a new checked revision (files get a new version instead).
- Proof of Compliance: an Ed25519-signed, hash-chained approval record; a public page verifies pasted
  text or a published file.
- Knowledge base with versioned rules, facts and terms, change history and change-impact preview;
  insights on expiring facts, unclear rules and AI usage (internals shown to reviewers and admins);
  roles with agency scoping and confidential redaction; a daily AI allowance.
- **First-visit walkthrough:** an interactive guide that points at each next button through a full check,
  fix, review, approval and verification; off for returning visitors.

**Improvement 1 — documents and images**
- Upload PDF, Word, PNG or JPEG. PDF findings point to the **page and line**, Word findings to the
  **section and paragraph**.
- **Word fixes are made inside the .docx**, keeping its formatting; PDFs and images are corrected at the
  source and uploaded as a **new version** of the same submission.
- **Words in images are read** (Tesseract) and checked like any copy; **text contrast** is measured per
  line against WCAG AA and boxed on the preview.
- **Logo use**: the brand-kit logo is found at any size (OpenCV ORB + homography) and checked for a
  retired version, stretching, tilting, recolouring, a busy background, crowded clear space and size.
- **Image understanding**: with Gemini, one call per image says what Canonry sees (brands, ours or a
  competitor's, retired names, claims drawn into the picture, whether it fits its caption) and suggests alt
  text accepted in one click; findings cite rules and are never above *Should fix*. Without AI, the rule-based
  checks above run as before.
- Brand-palette check and alt-text check.
- The approved file carries its **signed proof in its own metadata** (PDF, Word, PNG, JPEG); the public
  verify page accepts the file, and a changed file or a copied seal does not verify.

**Improvement 2 — publishing gate: REST API + signed webhooks**
- Versioned API (`/api/v1`) with per-workspace keys (stored hashed, scoped, revocable), idempotent
  requests, size limits and plain error codes; uploads and checks through the API.
- Webhooks on *checked*, *approved* and *signed*, HMAC-SHA256 signed, retried on a schedule in the
  background, with rotate/disable and a delivery log; webhook addresses are re-checked before every
  attempt (no internal or private addresses).
- A **demo publisher** (`/engine/cms` on the live site) that holds a post until a signed webhook arrives
  and publishes only if the approved content's hash matches.
- Admin page to create keys (shown once), endpoints and secrets.

**Improvement 3 — India advertising compliance pack**
- Rules from the CCPA Guidelines (2022) and the ASCI Code; every legal finding cites the exact clause
  with a link; the pack can be switched on and off per workspace.
- Clause retrieval with embeddings (local, in SQLite on the demo; Postgres + pgvector supported in code).
- Its own 32-sentence set: 100% precision and recall, no false alarm at any tier; ordinary copy stays silent.
- Tested on real ASCI decisions, honestly: 43 of 45 on the first set of upheld ad lines, but those patterns
  were written after reading them. A **blind test** on 220 more claims quoted from ASCI's own monthly
  releases showed what generalises: 43% caught before any change; after new general claim families written
  on two months (127/148), a third month held out and scored once catches **35 of 72 (49%)**, up from 21.

## 2. Architecture summary

One FastAPI engine holds every rule and check; a Next.js 16 web app renders the screens and reaches the
engine through a same-origin proxy (`/engine/*`), so cookies stay first-party and there is no CORS. The
engine stores everything in SQLite (WAL) with a Postgres-compatible schema; a Postgres connection is
supported. A check run goes: **understand the content** (profile, which checks apply) → rule checkers →
claim pipeline (patterns, fact retrieval, Verified Claim Memory) → AI gateway (Gemini → Groq →
OpenRouter → Ollama, free tiers, 15 s per call and a second model asked after 4 s, confidential data never sent) → India compliance pack →
merge duplicates, conflict-safe fixes, finding contract and citation check → stored. Uploaded files are
parsed into text with a locator map (page/line, paragraph, or image box); image checks (palette,
contrast, logo, alt text) run on the pixels. Approvals are signed with Ed25519 and, for files, stamped
into the file. The publishing gate adds an authenticated API and HMAC-signed webhooks. Deployed on free
tiers: Render (engine, Docker with Tesseract) and Vercel (web).
Details: README §3 and [architecture.md](architecture.md); decisions with reasons: [decision-log.md](decision-log.md).

## 3. Improvements completed after Round 2

| # | Improvement | Status | Evidence |
|---|---|---|---|
| 1 | Documents and images | Done | README §2; suites `test_documents`, `test_image_text`, `test_logos`, `test_docx_fix`, `test_review_r3` |
| 2 | REST API + signed webhooks + demo publisher | Done (Google Docs add-on, a stretch goal, not built) | README §2; suites `test_api`, `test_publisher` (real HTTP webhooks) |
| 3 | India compliance pack with retrieval | Done on SQLite; a blind test on ASCI decisions it had not seen catches 35/72 (49%); Postgres + pgvector in code, not deployed | README §2; suite `test_compliance` and its evaluation gate |

Also in Round 3: image understanding with a vision model (`test_vision`), a knowledge base that grows
from claims writers keep making (`test_suggested_facts`), the "understand first" analysis
(`test_understanding`), a first-visit walkthrough and a role tour, **My work** with text editing for
writers (`test_creator_work`), whole-phrase banned-term matching (`test_term_matching`), checks that
stay at 3–5 s when a free AI model stalls (a second model is asked after 4 s; `test_gateway`),
security fixes (a copied seal verified as genuine; Word zip bombs; webhook address checks; a race that
could sign twice), and reliability fixes (an intermittent server error on submit; one slow AI call
locking every other visitor out; two tabs undoing each other's fixes; plain messages when the engine
is down or waking up).

## 4. Testing details

- **Automated:** `python engine/tests/run_tests.py` runs **32 suites** on a fresh database each, plus the
  evaluation gate (precision and recall per checker on a frozen split). The suites never call a real AI
  provider; malformed AI answers and slow models are tested with fake providers. CI runs them on every
  push with a web type-check, a production build, `pip-audit` and `npm audit`.
- **Browser:** `e2e/journey.py` drives Microsoft Edge through every role's journey, hostile input (blank,
  120,000 characters, emoji/Hindi/RTL/HTML, wrong, renamed, cut-off and 0-byte files), double clicks,
  refresh and back, two tabs, an expired session, unknown ids and every screen at 1280 and 390 px:
  **185/185** on the final build. Two scripts click exactly what a person would: the first-visit
  walkthrough (**27/27**) and the writer's sent back → edit → send again → approved loop (**16/16**),
  both locally and on the live site with real AI and OCR.
- **Code review:** an independent review of the Round 3 branch; every Important finding fixed with a
  test that failed first (docs/progress.md §0).
- **Bugs found by testing and fixed:** docs/progress.md §0, §7, §8.
- **Usability:** the five-person SUS study is prepared ([usability-test-kit.md](usability-test-kit.md))
  but has **not** been run; the team ran an internal heuristic review of every screen with the browser
  walk instead, which is not a substitute for user testing.

## 5. Roadmap

See README §7: managed Postgres + pgvector live; the India pack blind-tested on newer ASCI
decisions; the five-person usability study; a larger, independently labelled evaluation set; signing
keys that survive restarts; checks where people write (Google Docs add-on, MCP connector); audio
and video (the header module exists, not yet wired); more formats and market packs.

## 6. Team and contributions

- **Vansh Vaid (team leader):** product direction; web app and review workflow; Round 3 file checks on
  the shared pipeline (Word, OCR, logos), image understanding, understand-first checks, the India pack's
  real-case test, the growing knowledge base, large-image memory limits, My work and text editing, the
  slow-AI fixes, browser test scripts, deployments, documentation and this PDF.
- **Dhruv Puri:** initial engine; Gemini fallbacks and the admin, agency and review pages; the Round 3
  base for all three improvements (uploads and stamping, REST API and webhooks, demo publisher, India
  pack with clause retrieval, admin API page); the role tour and document viewer; the audio/video
  module and the API-gate test.
- Details with commit ids: README §8. AI assistance: docs/disclosure-log.md.
