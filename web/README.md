# Canonry Web (Next.js 16)

The front end of [Canonry](../README.md) — the brand-governance copilot.
It renders the screens only; **all product intelligence lives in the engine**
(`../engine`, FastAPI on port 8000), reached through a same-origin proxy at
`/engine/*` (configured in `next.config.ts`), so session cookies just work.

## Screens

| Route | What it does |
|-------|--------------|
| `/` | Dashboard — workspace stats + submission list |
| `/new` | New submission (channel + source type + content, prefilled demo post) |
| `/submissions/[id]` | **The core screen** — highlighted spans, findings w/ citations, accept/edit/dispute, revisions, submit-for-review, reviewer actions, PoC link |
| `/kb` | Knowledge base — rules / facts / terms (add + list) |
| `/insights` | Disputes & overrides feed, fact-expiry alerts (with affected approved content), AI-call ledger, possibly-unclear rules |
| `/verify/[pocId]` | **Public** Proof-of-Compliance verifier — no login needed |

## Running

```bash
npm install
npm run dev     # http://localhost:3000 (engine must be on :8000 first)
```

Guest access: the nav's persona switcher signs you in as any of the four
seeded demo roles with one real engine `POST /login` — no credentials, so a
judge can use the product immediately.

 Stack: Next.js 16 (App Router) · React 19 · Tailwind CSS 4 · shadcn-style UI primitives.
