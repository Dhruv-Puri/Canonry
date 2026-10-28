# Canonry in 15 minutes — a beginner's tutorial

> New to the project? This page takes you from *"what is this?"* to *"I ran
> the whole loop myself"* in about fifteen minutes. No prior knowledge of
> FastAPI, Next.js or brand governance is assumed.

---

## 1. What Canonry does, in one paragraph

Marketing copy goes in. Canonry reads it against the organisation's **own
approved rules, terms and facts** — not against the internet — and reports
**findings**: "this sentence claims 5,000+ teams, but the approved fact says
2,300+ (fact F-012, rule CLM-03)". Every finding points at the exact words,
cites its source and suggests the smallest possible fix. A **person** then
accepts, edits or disputes each finding, a reviewer approves the result, and
the approval is sealed with a cryptographic signature that anyone can check
later at a public verify page. The AI never publishes, approves or rejects
anything on its own.

The whole product is that one loop:

```
draft  →  check  →  decide (human)  →  seal  →  anyone can verify
```

---

## 2. The vocabulary you will meet

| Word | Plain meaning |
|------|---------------|
| **Workspace** | One brand's universe. The demo ships with Quillmark Analytics. |
| **Knowledge base (KB)** | The brand's approved sources: **rules** (brand book), **facts** (one approved truth each), **terms** (preferred/banned words). |
| **Finding** | One reported issue: the flagged text, an explanation, a citation, a fix suggestion, and a certainty tier. |
| **Citation** | Where the finding comes from — a real rule, fact or term, with the version it was checked against. *No citation, no finding.* |
| **Tier vs severity** | Tier = how sure we are the violation is real (`definite / likely / consider`). Severity = how badly it hurts if it ships (`high / medium / low`). They are separate axes. |
| **Revision** | An immutable snapshot of the text. Accepting a fix creates revision 2, then 3, … and re-checks automatically. |
| **Decision** | A creator's accept / edit / dispute, or a reviewer's override — each is recorded with who, when and why. |
| **Proof of Compliance (PoC)** | The signed seal created on approval: a SHA-256 fingerprint of the approved text, the approver, the rules version, an Ed25519 signature and a ledger entry. |
| **VCM** | *Verified Claim Memory* — a cache of claim verdicts keyed by the numbers/units/names in the claim, so re-checks are instant and "2,300+" never quietly confirms "3,200+". |
| **Risk router** | After you submit for review, the engine stamps the item `low / medium / high / exempt` and names who reviews it. |
| **Persona** | In demo mode there is no password: choose a walkthrough role. In production, sign in with a password; an admin assigns your role with a one-use invitation. |

---

## 3. Run it locally (two terminals)

Requirements: **Python 3.11+** and **Node 20+**.

```bash
# From the Canonry project folder. These are two separate terminals.
# terminal 1 — FastAPI engine on port 8000
python -m venv .venv
.venv/Scripts/pip install -r engine/requirements.txt     # mac/linux: .venv/bin/pip
# start the engine: demo mode, port 8000, auto-reload (no shell variables needed)
.venv/Scripts/python engine/run_local.py        # Windows: PowerShell or Git Bash
.venv\Scripts\python engine\run_local.py        # Windows: Command Prompt
.venv/bin/python engine/run_local.py            # macOS / Linux

# terminal 2 — Next.js web app, from the project folder
cd web
npm ci                                                   # use npm install only if no lockfile exists
npm run dev                                              # http://localhost:3000
```

On first boot the engine creates `db/canonry.db`, loads the Quillmark demo
data from the CSVs in `data/`, and seeds one already-checked launch post so
the app never opens empty. **No AI key is needed** — the deterministic
checkers do the work and AI-assisted checks are honestly marked *pending*.

If the web app picks a different port because 3000 is busy, that is fine: the
engine URL is fixed at `http://127.0.0.1:8000` and the proxy handles the rest.

---

## 4. The guided tour (the real value of this page)

Open the web app. Work through these nine steps with the seeded demo post.

1. **Identify yourself.** Type a name, keep *Creator*, press **Enter
   workspace**. This performs a real engine login and drops a session cookie.
2. **Look at the dashboard.** *Your submissions* lists items with their status
   (Draft → Checked → In review → Signed) and a live count of **open
   findings on the latest revision**. The stat tiles count approved rules,
   facts, awaiting review and signed items.
3. **Open "Launch post — Pulse 2.0".** This is the plan's example, already
   checked. The text shows coloured highlights; the findings panel lists each
   issue with its category badge (e.g. *Contradicted claim*), its certainty
   tier, a readable explanation and — under it — the citation: `Fact F-012
   v1: 2,300+ active customer teams`.
4. **Accept one fix.** Press **Accept fix** on a finding that offers one.
   The engine rewrites exactly the flagged span, creates **revision 2** and
   re-checks it automatically. The counter updates; the earlier revs remain
   available in the *Revision* dropdown.
5. **Dispute something.** Open *Fix it in your own words, or dispute*, give a
   reason and send it. Disputes are first-class: they appear in Insights and
   carry forward onto the next revision, because a real reviewer wants to see
   what the humans disagreed with.
6. **Submit for review.** Press **Submit for review**. The router stamps the
   item (public channel + AI-assisted + contradicted claims ⇒ **high** risk)
   and the note names the reviewer.
7. **Switch hats.** Use the profile menu to join as a **Reviewer** (or switch
   your role). Try to approve with a `high`-severity finding still open — the
   engine refuses with a 409 and explains the policy. Now **override** that
   finding *with a reason*; the override is logged, then approval succeeds.
8. **Check the seal.** Open `/verify/<poc_id>` from the signed item. That page
   needs no login. It first confirms the seal is genuine; then paste the text
   as it was published: the approved text answers **Verified**, anything else
   **Modified** (an unknown id answers **Unknown**). The approved text itself
   is never shown on the public page.
9. **Wander through Insights.** Disputes and overrides, fact-expiry alerts
   with the approved content they affect, the "possibly unclear rules" list,
   and the AI-call ledger (empty while no key is configured).

That is the whole product. Everything else in the repo exists to make those
nine steps trustworthy.

---

## 5. The same thing from the terminal (for developers)

The web app only calls the engine, so you can too. The session is a cookie:

```bash
# sign in (demo personas are seeded)
curl -s -c /tmp/cj -X POST localhost:8000/login \
  -H 'content-type: application/json' -d '{"email":"arjun@quillmark"}'

# submit the plan's launch post and read the findings
curl -s -b /tmp/cj -X POST localhost:8000/submissions \
  -H 'content-type: application/json' \
  -d '{"title":"t","channel":"social","source_type":"ai-assisted",
       "content":"Meet Quillmark Insights 2.0 — India'"'"'s #1 analytics platform, trusted by 5,000+ teams and fully ISO 27001 certified. Plans start at just ₹999/month!"}' \
  | python -m json.tool | head -40

# public verify needs no cookie
curl -s localhost:8000/verify/poc_xxxxxxxxxxxx
```

Every engine endpoint is documented automatically at
`http://localhost:8000/docs` (FastAPI's OpenAPI UI) — handy for exploring
without reading `main.py` first.

---

## 6. What happens inside one "Check"

```
1. terminology   — banned/outdated glossary words            (deterministic)
2. readability   — long sentences, social word limit, CTA    (deterministic)
3. tone          — hard-sell phrasing, "!" abuse             (heuristic)
4. confidential  — sentences repeating confidential facts    (deterministic)
5. claims        — every number/claim matched to the fact
                   library; verdicts stored in VCM; only the
                   *implicit* leftovers go to one batched AI call
6. citation check— a finding whose citation is dead/inactive
                   is discarded and counted, never shown
7. tiers         — certainty assigned from the verdict
```

Rules before AI is not a slogan here — it is the code order. Code map:
`engine/checkers.py`, `engine/claims.py`, `engine/pipeline.py`; the shared
output shape is the versioned **Finding Contract** in `engine/contract.py`.

---

## 7. Run the tests (all suites, fresh databases)

Each suite boots its own database file, so your demo data is never touched.

```bash
# every suite on its own fresh database, then the evaluation gate
.venv/Scripts/python engine/tests/run_tests.py          # Windows
.venv/bin/python engine/tests/run_tests.py              # mac/linux
# → 12/12 passed

.venv/Scripts/python engine/tests/run_tests.py access   # only suites whose name contains "access"
```

| Suite (`engine/tests/`) | What it proves |
|---|---|
| `test_engine` | the core end-to-end journey |
| `test_identity` | roles, secrecy, sessions |
| `test_knowledge` | versioned knowledge-base writes and their impact |
| `test_regressions` | bugs found in review stay fixed |
| `test_seed_data` | the demo CSVs load cleanly |
| `test_edge_cases` | input validation and edge cases |
| `test_policy` | every check cites the workspace's own rule, demo or not |
| `test_access` | agency partners see only their own work; confidential text stays hidden |
| `test_workflow` | content is locked in review and after approval; public verification |
| `test_gateway` | AI fallback chain, honest call ledger, nothing confidential sent (faked providers, no network) |
| `test_quota` | daily AI allowance: 5 per person, 50 per workspace, clear reasons when out of tries, failed provider calls never charged |

Each prints `ALL … TESTS PASSED` and exits 0 when healthy.

---

## 8. Common tasks

**Check your own copy** — dashboard → *Check a draft* → paste text, pick a
channel, press **Check draft** (or press the *Launch post with issues* chip
to see a bad example).

**Add a rule** — *Knowledge base* → Rules → add with a reason. Rules are
versioned: nothing is ever overwritten, and each version keeps its history.

**Import a rulebook** — open *Knowledge base → Rules → Import rulebook* and
select a Markdown, text, or Word (`.docx`) file up to 5 MB. Read and edit each
suggestion, remove irrelevant paragraphs, then save the reviewed set as
**drafts**. Drafts do not affect checks until an authorized reviewer/admin
edits and approves them. For structured CSV, use `POST /rules/import` with
columns `id,category,statement,do_example,dont_example,severity`; that legacy
CSV route directly imports rules, so use the preview UI for prose rulebooks.

**Add a fact** — Knowledge base → Facts. Facts need an owner and may carry a
validity window; expired or superseded facts can only ever be cited *as the
reason a claim is outdated*, never as support.

**Retire a term** — Knowledge base → Terms → Retire. Retired terms stop being
flagged immediately; the history keeps the paper trail.

**Switch persona in a hurry** — the profile menu in the top bar performs the
engine login round-trip for you.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Web shows "Engine error …" | The engine is not running on port 8000. Start terminal 1. |
| `Address already in use` for 8000 | Another engine is alive: `netstat -ano \| grep :8000`, stop that PID. |
| AI findings say *pending* | No provider key — by design. Add a free key in the root `.env` (see `docs/progress.md` §4) or ignore it; deterministic checks already work. |
| Production sign-in says "Sign in required" after login | Keep the engine behind the same-origin `/engine` proxy; production cookies are Secure and require HTTPS. Do not disable `CANONRY_COOKIE_SECURE` on a public deployment. |
| Invite is rejected | Invitations are one-use, expire after 72 hours, and are bound to the invited email. Ask an admin to issue a fresh link for the same address. |
| A verify page says *Modified* | The pasted text differs from what was approved — someone changed the copy after signing. That is the seal doing its job. |
| Approve is refused with 409 | Open `high`-severity findings, or the item is not *In review*. Resolve/override with a reason. |

---

## 10. Where to go next

| Doc | Read it for |
|-----|-------------|
| [getting-started.md](getting-started.md) | install/run details, free AI keys |
| [architecture.md](architecture.md) | how the two services fit; data model; algorithms |
| [design.md](design.md) | product rules and the reasoning behind them |
| [progress.md](progress.md) | what is shipped, what is deliberately out, known gaps |
| `../README.md` | the one-page project overview |
