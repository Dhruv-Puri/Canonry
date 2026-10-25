# Canonry — brand-governance copilot for marketing content

> **CodeStar 30 · Round 2 build · Team VAIDVANSH6**
> Content goes in → it is checked against the approved brand guidelines, facts
> and terms → every issue comes back **explained and cited** → a **human**
> decides → the approval is **cryptographically provable**.

Canonry's core promise, verbatim from the Round 1 plan: *"Rules before AI —
deterministic checks are free, fast and certain; the AI only handles what rule patterns cannot* — held to strictly in this build. The AI never auto-changes your content. It surfaces **findings**; the reviewer decides.

- **Live app**: `http://localhost:3000` (web) + `http://localhost:8000` (engine API)
- **Guest-friendly**: anyone can open the app and use every feature without credentials — one click logs them in as a demo persona (or the current session user is used if already signed in).
- **Works with no AI key**: rule-based findings always arrive; AI-assisted checks are marked *pending* (never silently skipped) until a free-tier key is added.

---

## 1. What it does (30-second version)

1. A creator pastes marketing content into **New submission**, picks a channel
   (`social / web / blog / email / print`) and a source type
   (`in-house / agency / ai-assisted`).
2. The **engine** runs the check pipeline against the workspace's approved
   rulebook, fact library and terminology glossary and returns **findings**:
   each has a highlighted span, an explanation, a citation to the *real* rule
   or fact behind it, and when possible a suggested replacement.
3. The creator **accepts / edits / disputes** each finding. Accepting rewrites
   the draft and immediately **re-checks** (revision 2, 3, …).
4. The creator submits for review. A router stamps it
   `low / medium / high / exempt` and routes to the right reviewer
   (public-channel + AI-assisted + contradicted claims ⇒ *high*). Exemption policies auto-approve a *narrow, logged* lane.
5. The reviewer **approves, requests changes or explicitly overrides** with a
   reason. High-severity findings cannot be approved — the human decides,
   never the AI.
6. Approval produces a **Proof of Compliance**: a SHA-256 fingerprint of the
   approved text plus who approved it, against which rules and when —
   signed (Ed25519) and entered into a hash-chained ledger.
7. `/verify/<poc_id>` is a **public, no-login** page answering
   `Verified / Modified / Unknown` for that seal.

## 2. Feature checklist (all working end to end)

| # | Feature | Where |
|---|---------|-------|
| 1 | Rulebook CRUD + vague-rule linting (`vague_no_examples` etc.) | engine `/rules/*`, web `Knowledge base` |
| 2 | Fact Library with owner, source, validity window, confidentiality, supersede | engine `/facts`, web `Knowledge base` |
| 3 | Terminology glossary (preferred/banned) | engine `/terms`, web `Knowledge base` |
| 4 | Deterministic claim labelling (supported/contradicted/outdated/unsupported) with **substring matching** | `engine/claims.py` |
| 5 | Verified Claim Memory (VCM) — verdicts re-used keyed by normalised numbers/units/names | `claims.vcm_store / vcm_lookup` |
| 6 | Single batched AI call for *implicit* claims + tone (strict JSON, key-less degradation) | `engine/pipeline.py`, `engine/gateway.py` |
| 7 | Citation check — *no citation, no finding*; invalid citations are discarded & counted | `claims.citation_check` |
| 8 | Finding Contract v1 (`finding@1`) — one versioned shape for every checker | `engine/contract.py` |
| 9 | Three-tier certainty: `definite / likely / consider` on every finding | contract tiers |
| 10 | Risk router (high/medium/low/exempt) with exemption policies | `main.compute_risk` |
| 11 | Accept / edit / dispute workflow + revision history + automatic re-check | engine `/submissions/*/resolve` |
| 12 | Reviewer approve / request-changes / **explicit override with reason** | engine `/submissions/*/review` |
| 13 | High-severity hard block on approval (409) | `main.review` |
| 14 | Proof of Compliance: canonical record, Ed25519 signature, hash-chained ledger, public verify | `engine/signing.py`, `/verify/[pocId]` |
| 15 | Insights: disputes/overrides feed, expiry alerts, AI-call ledger, "possibly unclear rules" | engine `/insights`, `/alerts/*` |
| 16 | MCP **Canon Connector** (Model Context Protocol) so AI editors can read approved facts before drafting | `engine/mcp_server.py` |
| 17 | Append-only, hash-chained **audit log** of every human action | `db.audit` in every endpoint |

## 3. Quick start (clone → clone-ready)

Run the engine then pick any of: Vite/Next/Hono/anything front-end — or use the shipped `web/` app, which expects the engine at `http://localhost:8000` (or set `NEXT_PUBLIC_ENGINE_URL`).

```bash
# 1. Engine (Python + FastAPI)
python -m venv .venv
.venv/Scripts/pip install -r engine/requirements.txt   # use pip3 / venv/bin on mac/linux
cd engine && ../.venv/Scripts/python -m uvicorn main:app --port 8000 --reload

# 2. Web (Next.js 16, App Router)
cd web && npm install && npm run dev   # → http://localhost:3000
```

For full detail — including the portable-Node fallback and where to get free
AI keys — see **[docs/getting-started.md](docs/getting-started.md)**.

## 4. Tech at a glance

| Layer | Choice | Why |
|-------|--------|-----|
| Engine API | Python 3.12 + FastAPI | typed models + auto OpenAPI fits the Finding Contract |
| Database | SQLite (WAL) | zero-config prototype; schema mirrors managed Postgres so the pgvector swap is config, not redesign |
| Claims retrieval | substring scoring over the Fact Library | demo-first; swap to pgvector later |
| AI | Gemini → Groq → OpenRouter fallback chain (free tiers) | width-first testing, call budget ✔ |
| Signing | Ed25519 (PyNaCl) | tamper-evident Proof of Compliance |
| Web | Next.js 16 + React 19 + Tailwind 4 | App Router, shadcn ui, dark default |
| Protocol | MCP over JSON-RPC 2.0 stdio | AI editors read approved facts |

## 5. Repository map

```
canonry/
├── README.md                  ← you are here
├── .env.example               ← copy to .env, fill one key (or none!)
├── docs/
│   ├── architecture.md        ← system design, diagrams, data model
│   ├── design.md              ← product rules & the thinking behind them
│   ├── approach.md            ← Round-1 plan → Round-2 build (+ changes)
│   ├── progress.md            ← what's done, tests, known gaps, Round-3
│   └── getting-started.md     ← zero-to-running in 10 minutes
├── engine/                    ← FastAPI app (all intelligence lives here)
│   ├── main.py                ← endpoints: auth, rules/facts/terms, submissions
│   ├── pipeline.py            ← check-run orchestrator
│   ├── claims.py              ← claim detection, retrieval, verification, VCM
│   ├── checkers.py            ← terminology / readability / tone heuristics
│   ├── gateway.py             ← provider-agnostic AI gateway
│   ├── contract.py            ← the versioned Finding Contract
│   ├── signing.py             ← Proof-of-Compliance signing & verify
│   ├── mcp_server.py          ← Canon Connector (MCP over stdio)
│   ├── seed.py                ← fills the Quillmark demo workspace from CSV
│   └── test_engine.py         ← end-to-end smoke test (TestClient)
├── web/                       ← Next.js 16 app (App Router)
│   └── src/
│       ├── app/               ← page routes (/, /new, /submissions/…, /kb, /insights, /verify/…)
│       ├── components/        ← TopNav, persona switcher, primitives
│       └── lib/               ← api client, persona model
├── data/                      ← seed CSVs (rules / facts / terms)
├── db/                        ← SQLite files + signing seed (generated; gitignored)
└── Canonry_Round1_Plan_vaidvansh6.pdf   ← the approved Round-1 plan
```

## 6. Documentation

| Doc | Audience | Read it for |
|-----|----------|-------------|
| [getting-started](docs/getting-started.md) | new developers | install, run, test in 10 min |
| [architecture](docs/architecture.md) | everyone | how the pieces fit; diagrams; data model |
| [design](docs/design.md) | reviewers & judges | product-rule decisions, finding contract, tiers |
| [approach](docs/approach.md) | everyone | how we attacked the problem, and what changed from Round 1 |
| [progress](docs/progress.md) | everyone | shipped features, tests, remaining gaps, Round-3 list |

## 7. Licensing / ownership

All code in this repository was written by team VAIDVANSH6 for CodeStar 30.
The problem statement and Round-1 plan are referenced from the PDF in the
repository root; brand/glossary seed data is fictional (Quillmark Analytics).
