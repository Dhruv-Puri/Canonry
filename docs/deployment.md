# Deployment

> The FastAPI engine goes to Render (free Docker service, blueprint in
> [`render.yaml`](../render.yaml)); the Next.js web app goes to Vercel (Hobby).
> Both are free. The blueprint deploys the **judge demo**; section 5 covers a
> real, production workspace.

The browser talks only to the **web** origin. Next's rewrite in
`web/next.config.ts` forwards `/engine/*` to the engine, so session cookies stay
same-origin and no CORS setup is needed.

---

## 1. Engine → Render

1. Push this repository to GitHub.
2. In Render: **New → Blueprint**, select the repository. Render reads
   `render.yaml` and creates `canonry-engine` from `engine/Dockerfile`.
3. Render asks for the values marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `CANONRY_APP_ORIGINS` | the exact web origin from step 2 below, e.g. `https://canonry.vercel.app` (you can fill it in after the web deploy, then redeploy the engine) |
   | `GEMINI_API_KEY` | optional free key (section 4); leave empty and AI checks show as *pending* |

   The blueprint already sets `CANONRY_DEMO_MODE=true` and
   `CANONRY_COOKIE_SECURE=true`.
4. Wait for the first build. The health check is `/health`:

   ```bash
   curl -s https://canonry-engine.onrender.com/health
   # {"ok":true,"demo_mode":true}
   ```

   A free instance sleeps when idle; the first request after that takes about 30 seconds.

## 2. Web → Vercel

1. In Vercel: **Add New → Project**, import the same repository.
2. Set **Root directory** to `web`. Vercel detects Next.js.
3. Add `CANONRY_ENGINE_URL` for Production and Preview, set to the Render URL
   from step 1 (e.g. `https://canonry-engine.onrender.com`).

   Vercel reads it at **build time** (the rewrite in `web/next.config.ts` is
   compiled with it): after changing it, redeploy the web project.
4. Deploy and open the URL. Put that origin into the engine's
   `CANONRY_APP_ORIGINS` if you have not yet.

## 3. Check the deployed pair

```bash
WEB=https://your-project.vercel.app

curl -s -o /dev/null -w "%{http_code}\n" "$WEB/"          # 200
curl -s "$WEB/engine/health"                                # {"ok":true,"demo_mode":true}
curl -s "$WEB/engine/auth-mode"                             # registration: demo
```

Then walk the core journey once in the browser:

1. Sign in as `arjun@quillmark` (creator; no password in demo mode). Open
   **Launch post — Pulse 2.0** (seeded on first boot).
2. Accept a suggested fix: revision 2 is created and re-checked.
3. Dispute a finding with a reason.
4. Submit for review. The router stamps a risk level.
5. Sign out and sign in as `maya@quillmark` (reviewer). Override any remaining
   high finding with a reason, then **Approve & sign**.
6. Open the public `/verify/<poc_id>` link in a private window: the seal is
   genuine. Paste the approved text: **Verified**. Change one word: **Modified**.

## 4. Optional: AI checks

Everything works with no AI provider: rule-based findings always arrive and AI
checks (implied claims, tone) are marked *pending*, never silently skipped. To
turn them on, set one key on the engine service:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> (free tier) |
| `GROQ_API_KEY` | <https://console.groq.com/keys> |
| `OPENROUTER_API_KEY` | <https://openrouter.ai/keys> |
| `OLLAMA_URL` | a local Ollama server (no key; nothing leaves your machine) |

The gateway tries them in that order and falls through on rate limits, errors
and empty answers.

**Daily allowance.** Free keys run out without warning, so AI-assisted checks are
rationed: 5 per person and 50 per workspace each day (reset at 00:00 UTC). A check
counts only once a provider has answered; failed attempts cost nothing. Out of
tries, rule-based checks still run and the screen says why AI was skipped. Change
the limits with `CANONRY_AI_DAILY_PER_USER` and `CANONRY_AI_DAILY_PER_WORKSPACE`
(whole numbers; `0` per user turns AI off for individuals). A malformed value stops
the engine at startup with a clear message. It spends at most three answered calls per 1,000-word check
and never sends confidential facts. Free model names change: override one with
`CANONRY_GEMINI_MODEL`, `CANONRY_GROQ_MODEL`, `CANONRY_OPENROUTER_MODEL` or
`CANONRY_OLLAMA_MODEL`. Never commit a key.

## 5. Demo mode versus production

| | Demo mode (`CANONRY_DEMO_MODE=true`, the blueprint) | Production (`false`, the engine default) |
|---|---|---|
| Sign-in | pick a persona, no password | email + password (≥ 12 characters) |
| New people | anyone, any role | one-use invitation from an admin, role fixed by the invitation |
| Data | seeded Quillmark workspace | empty workspace; every built-in check starts with a baseline rule until your rulebook is imported |
| Self-approval | allowed, labelled in the signed seal | refused: a different reviewer must approve |
| Use it for | judging, demos, usability tests | real brand content |

Anyone with a demo link can act as any role, so never put real brand material in
a demo deployment.

To run production, set on the engine:

| Variable | Notes |
|---|---|
| `CANONRY_DEMO_MODE` | `false` (or remove it) |
| `CANONRY_BOOTSTRAP_ADMIN_EMAIL` | the first administrator (Render secret) |
| `CANONRY_BOOTSTRAP_ADMIN_PASSWORD` | ≥ 12 characters (Render secret; remove after the first boot) |
| `CANONRY_APP_ORIGINS` | the exact web origin |
| `CANONRY_COOKIE_SECURE` | `true` (serve over HTTPS) |
| `CANONRY_WORKSPACE_NAME` | optional, 1–100 characters |

The engine refuses to start in production without a valid bootstrap admin.
`/engine/auth-mode` then reports `registration: invitation-only`.

## 6. Persistence

Render free instances have an **ephemeral filesystem**. On restart the SQLite
database and the Ed25519 signing key are recreated: the demo re-seeds itself,
and seals signed before the restart verify as `unknown`. That is fine for a
demo, not for a real workspace. Keep the database and the key on the same
durable mount and point `CANONRY_DB_PATH` / `CANONRY_SIGNING_KEY` at it:

| Deployment | Cost | Data and seals survive a restart? |
|---|---|---|
| Render free web service | ₹0 | No (demo only) |
| Render instance + disk at `/app/db` (`disk:` block in `render.yaml`) | paid | Yes |
| `docker run -p 8000:8000 -v canonry-data:/app/db canonry-engine` | ₹0 | Yes |
| Hugging Face Spaces (free Docker Space) | ₹0 | No |

Build the image from the repository root: `docker build -f engine/Dockerfile -t canonry-engine .`

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Web shows "Engine error" right after a deploy | The free engine is still waking up (~30 s). Reload. |
| `/engine/...` returns 502 | The engine is down or `CANONRY_ENGINE_URL` is wrong; check the Render logs and `/health`, then redeploy the web project. |
| Every button answers 403 "Cross-origin requests are not allowed" | `CANONRY_APP_ORIGINS` does not exactly match the web origin (scheme, host, no trailing slash). |
| Sign-in works locally but not when deployed | `CANONRY_COOKIE_SECURE=true` needs HTTPS; check `CANONRY_APP_ORIGINS` and that the web project was rebuilt after setting `CANONRY_ENGINE_URL`. |
| Production engine stops at startup | The bootstrap admin email or password is missing or invalid. |
| An invited person cannot join | Invitations are one-use, expire after 72 hours and are bound to the invited email; issue a new one. |
| A verify page says `unknown` | The seal was signed on an earlier instance (section 6), or the id is mistyped. |
| AI checks stay *pending* | The banner says why: no provider configured (section 4), the person's or workspace's daily allowance is used up, or every provider failed (see Insights → AI ledger). |
