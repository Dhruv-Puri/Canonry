# Canonry — Getting started (zero-to-running)

> No prior setup assumed. Everything below stays inside this project folder —
> a `.venv`, a `db/` folder and node_modules. Nothing is installed globally.

## 0. What you need

| Need | Check | If missing |
|------|-------|------------|
| Python ≥ 3.10 | `python --version` | from [python.org](https://www.python.org/downloads/) |
| Node.js ≥ 18 | `node --version` | from [nodejs.org](https://nodejs.org) (or use any local Node — on this dev machine a portable Node 22 already lives in `tools/`, which is gitignored, so every clone installs its own) |
| A terminal | — | any |

## 1. Run the engine (Python + FastAPI)

```bash
# from the project root — create a local virtualenv once
python -m venv .venv

# install engine deps (Windows vs mac/linux paths)
.venv/Scripts/pip install -r engine/requirements.txt    # Windows
.venv/bin/pip install -r engine/requirements.txt        # mac/linux

# start the engine: demo mode, port 8000, auto-reload (no shell variables needed)
.venv/Scripts/python engine/run_local.py        # Windows: PowerShell or Git Bash
.venv\Scripts\python engine\run_local.py        # Windows: Command Prompt
.venv/bin/python engine/run_local.py            # macOS / Linux
```

`engine/run_local.py` switches on demo mode for you (seeded workspace, password-free
personas). Starting uvicorn directly without `CANONRY_DEMO_MODE=true` runs production mode, which
needs a first administrator (`CANONRY_BOOTSTRAP_ADMIN_EMAIL` and
`CANONRY_BOOTSTRAP_ADMIN_PASSWORD`) and refuses to start without one; see
[deployment.md](deployment.md) §5.

On first start the engine:

1. creates `db/canonry.db` (schema only — no data yet),
2. **seeds** the Quillmark demo workspace from `data/*.csv`
   (rules, facts, terms, the four personas, one exemption policy),
3. answers at `http://localhost:8000` (try `GET /ai-status`).

`db/` is generated state — safe to delete any time; the next start reseeds.

## 2. Run the web app (Next.js 16)

```bash
# open a SECOND terminal, from the project root
cd web
npm install          # one-time
npm run dev          # serves http://localhost:3000
```

The web app proxies `/engine/*` to `http://localhost:8000` (see
`web/next.config.ts`). Start the engine first, then the web — otherwise the
first page load shows a network error until you refresh.

If port 3000 is busy, Next picks another port — note the one printed in the
terminal; the app itself doesn't care.

## 3. Take the 3-minute tour

1. Open `http://localhost:3000` — you're already in, no sign-in (guest mode
   acts as the creator persona; the nav's persona switcher changes roles with
   one click).
2. The dashboard lists the seeded submissions — open **Launch post — Pulse
   2.0**, the deliberately broken one: red-highlighted spans, each with an
   explanation and its citation (rule / fact / approved term).
3. Click **Accept fix** on one finding — revision 2 is created and
   re-checked instantly.
4. **Dispute** another with a reason — it lands in the Insights page.
5. **Submit for review** — the router stamps risk (see the note it prints).
6. Switch persona to **Maya (reviewer)** in the nav → approve → status
   **Signed** → click the Proof-of-Compliance link.
7. Open the PoC verify URL logged there — the public page says the seal is
   genuine. Paste the published text into it: the exact approved text says
   **Verified**, anything else says **Modified**.

## 4. Run the checks

```bash
# every suite on its own fresh database, then the evaluation gate
.venv/Scripts/python engine/tests/run_tests.py          # Windows
.venv/bin/python engine/tests/run_tests.py              # mac/linux
# → 12/12 passed

.venv/Scripts/python engine/tests/run_tests.py access   # only suites whose name contains "access"
```

## 5. Optional: light up the AI checks

Everything above runs with **no API key**; AI-assisted checks show as
*pending* (never silently skipped). To enable them:

1. Get a free key — e.g. Google AI Studio's Gemini key.
2. `cp .env.example .env` in the project root and paste the key.
3. Restart the engine. Insights → AI ledger starts recording calls
   (provider, model, latency).

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Web shows `fetch failed` | engine not running | start the engine (step 1) and refresh |
| `pip install` fails | using a global python without venv | make sure you're in `.venv` (step 1) |
| Ports clash | 3000/8000 already in use | stop the old process, or let Next pick a port |
| Any weird state in the demo data | stale db from an earlier run | `rm db/*.db*` and restart the engine — it reseeds itself |
