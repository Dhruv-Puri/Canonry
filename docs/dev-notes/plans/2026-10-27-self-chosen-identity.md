# Self-chosen Identity and Role-enforced Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** People enter Canonry by typing their own name and choosing a role (no login, no preset characters), and the engine enforces what each role may see and do.

**Architecture:** New engine endpoints `POST /join`, `PATCH /me`, `POST /logout` create and edit a password-less user with a session cookie. Display names travel in API payloads (`by_name`, `reviewer_name`) so the web app no longer needs the hard-coded persona list. Role rules live in one engine module (`access.py`) used by `/facts`, `/submissions`, `GET /submissions/{id}` and approvals.

**Tech Stack:** Python 3.11 / FastAPI / SQLite (engine); Next.js 16 / React 19 (web). Script-style tests (`expect(cond, msg)`).

**Spec:** decisions stated to the owner in chat on 2026-10-27 (owner delegated design calls): self-chosen name + role; confidential facts hidden from creator/agency; agency sees only own submissions; self-approval allowed but labelled; role changes audited; `/login` kept for scripts.

## Global Constraints

- Roles: `creator`, `reviewer`, `agency`, `admin` (labels: Creator, Reviewer, Agency partner, Brand admin).
- Name: stripped, 2–40 characters; otherwise 422 `"Name must be 2–40 characters."`. Unknown role → 422 `"Role must be creator, reviewer, agency or admin."`.
- Joined users get id `usr_<hex>` and email `<id>@guest.canonry` (unique, never shown).
- Confidential fact text shown to creator/agency is exactly `"[Confidential — visible to reviewers and admins]"`.
- Work stays uncommitted (owner's instruction).

## Review Focus

- A person who switches Creator → Reviewer must gain KB write access on the very next request (Task 1, `role switch takes effect immediately`).
- Two people choosing the same name must stay two distinct people (Task 1, `same name, different people`).
- A creator must not see confidential text through any path: `/facts`, finding citations, KB history snapshots (Task 2, three tests).
- Agency must not open another person's submission by guessing its id (Task 2, `agency cannot open others' submissions`).
- Self-approval must be recorded in the signed record, not only in the UI (Task 3, `self-approval is labelled in the PoC`).

---

### Task 1: Join, rename/switch role, logout (engine)

**Files:** Modify `engine/main.py` (routes); Create `engine/test_identity.py`.

**Interfaces — Produces:**
- `POST /join {name, role}` → `{"id","name","role"}` + `canonry_session` cookie.
- `PATCH /me {name?, role?}` → updated user; audit action `profile_change` with `"<old role> -> <new role>"` when the role changes.
- `POST /logout` → `{"ok": true}`; deletes the session row and clears the cookie.

- [ ] RED tests: `join creates the person`, `join validates name` (`"A"`, 41 chars → 422), `join validates role` (`"boss"` → 422), `same name, different people`, `role switch takes effect immediately` (creator `PUT /kb/rules/BRD-01` 403 → `PATCH /me {role:"reviewer"}` → 200), `role switch is audited`, `logout ends the session` (`/me` → 401).
- [ ] Implement; run all suites.

### Task 2: Role-enforced visibility (engine)

**Files:** Create `engine/access.py`; Modify `engine/main.py` (`/facts`, `/submissions`, `GET /submissions/{id}`, KB history); Test `engine/test_identity.py`.

**Interfaces — Produces (`access.py`):** `CONFIDENTIAL_PLACEHOLDER`, `can_see_confidential(user) -> bool` (reviewer, admin), `can_see_submission(user, sub) -> bool` (agency only own), `redact_fact(d: dict, user) -> dict`.

- [ ] RED tests: `creator sees confidential facts redacted`, `reviewer sees confidential text`, `citations to confidential facts are redacted for creators`, `KB history redacts confidential snapshots for creators`, `agency lists only own submissions`, `agency cannot open others' submissions` (404).
- [ ] Implement; run all suites.

### Task 2b: Confidential-leak check (engine) — added during execution

Found while writing Task 2: drafts that repeat a confidential fact ("Our MRR is 4.2 crore") produced no finding at all.

**Files:** Modify `engine/checkers.py` (`check_confidential(ctx, text)`), `engine/pipeline.py` (register), `engine/contract.py` (category `confidential_leak`), `web/src/lib/api.ts` (label "Confidential information").

- A sentence containing a distinctive number from a confidential fact (has `.` or `%`, or ≥ 3 digits and not a year 1900–2099) **and** another significant word of that fact → `definite`/`high`, suggestion: remove the sentence.
- A sentence containing a significant two-word phrase of a confidential fact → `likely`/`high`.
- Citation: the fact; explanation names its owner, never its text.
- [ ] RED tests: `a leaked figure is a definite confidential finding`, `a leaked phrase is a likely confidential finding`, `ordinary copy raises no confidential finding`.

### Task 3: Names in payloads and labelled self-approval (engine)

**Files:** Modify `engine/main.py` (detail payload, review), `engine/signing.py` (record field), `engine/knowledge.py` (history `by_name`); Test `engine/test_identity.py`.

- [ ] RED tests: `decisions and approvals carry names` (`by_name`, `reviewer_name` equal the chosen names), `KB history carries names`, `self-approval is labelled in the PoC` (person creates, switches to reviewer, approves → response `self_approved: true`, approval reason starts with `[self-approved]`, PoC record `self_approved: true`), `approval by someone else is not self-approved`.
- [ ] Implement; run all suites.

### Task 4: Web — welcome screen, profile menu, names from the engine

**Files:** Create `web/src/lib/roles.ts` (labels, one-line descriptions, icons); Create `web/src/components/welcome.tsx`; Modify `web/src/components/site-nav.tsx`, `web/src/lib/api.ts` (drop guest auto-login; 401 → identity event), `web/src/app/layout.tsx` (gate), pages using `personaName`; Delete `web/src/lib/personas.ts`.

- [ ] Behaviour: no session → full-page welcome (name field, four role cards, "Enter workspace"); nav chip shows initials, name, role; menu: four roles (current checked), "Change name", "Switch person". Review page shows a "Self-approved" warning chip on such approvals.
- [ ] `npx tsc --noEmit`, `npm run build`; real-browser walkthrough: join as a new name/creator, submit, switch to reviewer, approve (self-approved chip), rename, switch person → welcome.
