# Handoff Spec: Canonry review workspace (web app)

> Source: the running build on `fix/demo-journey` (Next.js 16 · React 19 · Tailwind 4 · shadcn/ui "new-york", neutral base), checked against the Round 1 plan (Sections 5.2, 6, 9.6, 10).
> Tech notes reference Tailwind utility names. Every colour, space and type size below is a **token**; raw values appear only in the token table.
> Items marked **[GAP]** are things the current build does differently from this spec, so each one is a work item.

---

## Overview

Canonry is a pre-publication review workspace. A **creator** submits marketing copy, gets **findings** (each with a highlighted span, a citation to an approved rule or fact, a confidence tier and usually a minimal fix), fixes or disputes them, and submits for review. A **reviewer** sees a risk-routed, pre-checked item, overrides findings with a reason if needed, and approves. Approval produces a signed **Proof of Compliance** that anyone can verify on a public page.

The screens, in order of importance:

| # | Route | Screen | Primary user | Job |
|---|---|---|---|---|
| 1 | `/submissions/[id]` | **Review** | creator, reviewer | fix → submit → decide. The product's core; most of this spec |
| 2 | `/new` | New content | creator | paste copy, tag channel + source, start the check |
| 3 | `/` | Submissions | everyone | queue of items with status and risk |
| 4 | `/verify/[pocId]` | Proof of Compliance | public, no sign-in | Verified / Modified / Unknown |
| 5 | `/kb` | Knowledge base | brand owner | rules, facts, terms that findings cite |
| 6 | `/insights` | Insights | brand owner | disputes, unclear rules, expiry alerts, AI ledger |

Design rules from the plan that drive this spec (cite them when making trade-offs):
- **P2 No citation, no finding.** The citation is part of every finding's UI, never hidden behind a click.
- **P3 Honest about certainty.** Definite / Likely / Consider are visually distinct, and never by colour alone.
- **P4 Minimal fixes, before/after.** A fix shows what changes, and the creator chooses.
- **P5 Humans decide.** Approve, override and dispute are explicit, reasoned actions.
- **P6 Faster than review without it.** A creator should clear a 6-finding post in under a minute.
- **WCAG 2.2 AA** (plan 9.6) and "AI checks pending, never silently skipped" (plan 9.8).

---

## Design tokens

### [GAP] Critical: the theme tokens are not defined

The components use shadcn token classes (`bg-card`, `border-border`, `border-input`, `text-muted-foreground`, `bg-muted`), but `src/app/globals.css` only defines `--background`/`--foreground`. Tailwind 4 therefore **generates none of these classes** (verified: 0 rules for each in the served CSS). In practice cards have no surface colour, muted text renders at full contrast, and borders fall back to `currentColor` (near-black). `body` also forces `Arial`, overriding the Geist font loaded in `layout.tsx`.

**Fix:** replace `globals.css` with the token set below (the standard shadcn neutral theme plus Canonry's semantic tokens), and delete the `font-family: Arial` line.

### Core tokens (shadcn neutral, light / dark)

| Token (CSS var → Tailwind) | Light | Dark | Usage |
|---|---|---|---|
| `--background` → `bg-background` | `oklch(1 0 0)` | `oklch(0.145 0 0)` | page |
| `--foreground` → `text-foreground` | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | body text, primary buttons (bg) |
| `--card` → `bg-card` | `oklch(1 0 0)` | `oklch(0.205 0 0)` | finding cards, panels |
| `--muted` → `bg-muted` | `oklch(0.97 0 0)` | `oklch(0.269 0 0)` | chips, code, skeletons |
| `--muted-foreground` → `text-muted-foreground` | `oklch(0.556 0 0)` | `oklch(0.708 0 0)` | secondary text (≥ 4.5:1 on background) |
| `--border` → `border-border` | `oklch(0.922 0 0)` | `oklch(1 0 0 / 10%)` | card and section borders |
| `--input` → `border-input` | `oklch(0.922 0 0)` | `oklch(1 0 0 / 15%)` | form controls |
| `--ring` → `ring-ring` | `oklch(0.708 0 0)` | `oklch(0.556 0 0)` | focus rings |
| `--destructive` | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` | error text, blocking states |
| `--radius` | `0.625rem` | — | `rounded-lg` = radius, `rounded-md` = radius − 2px |

### Canonry semantic tokens (add to `@theme inline`)

| Token | Light (bg / fg) | Dark (bg / fg) | Usage | Non-colour cue (required) |
|---|---|---|---|---|
| `tier-definite` | red-100 / red-800 | red-950 / red-200 | Definite badge | label text "Definite" + solid underline on span |
| `tier-likely` | amber-100 / amber-800 | amber-950 / amber-200 | Likely badge | label "Likely" + dashed underline |
| `tier-consider` | slate-100 / slate-700 | slate-800 / slate-200 | Consider badge | label "Consider" + dotted underline |
| `highlight` | amber-100 @70% | amber-900 @40% | span `<mark>` background | underline style per tier (above) |
| `highlight-active` | amber-200 | amber-800 | span whose card is hovered or focused | 2px outline in `ring` |
| `status-signed` | emerald-100 / emerald-800 | emerald-950 / emerald-200 | Signed, Approved, Exempt-approved | label text |
| `status-review` | blue-100 / blue-800 | blue-950 / blue-200 | In review | label text |
| `status-checked` | yellow-100 / yellow-800 | yellow-950 / yellow-200 | Checked | label text |
| `status-changes` | orange-100 / orange-800 | orange-950 / orange-200 | Changes requested **[GAP: currently grey]** | label text |
| `risk-low / medium / high / exempt` | emerald / amber / red / violet border + 700 text | same hues, 300 text | Risk pill (outline style) | "RISK: LOW" text |
| `notice-success / warning / error` | emerald-50 / amber-50 / red-50 bg with 800 text | 950 @40% bg with 200 text | Banners | leading icon + text |

### Type, spacing, layout

| Token | Value | Usage |
|---|---|---|
| `font-sans` | Geist (`--font-geist-sans`) | all UI text |
| `font-mono` | Geist Mono | rule/fact IDs, suggested-fix text |
| `text-page-title` | `text-xl` / semibold / `tracking-tight` | H1 on every screen |
| `text-body` | `text-sm` (14px) | most UI copy |
| `text-content` | `text-[15px]` / `leading-relaxed` | the submitted copy being reviewed (slightly larger: it's the thing being read) |
| `text-meta` | `text-xs` (12px) | citations, provenance, hints |
| `text-chip` | `text-[11px]` / medium | badges only; never body copy |
| `space-section` | `space-y-4` (16px) | between page sections |
| `space-card` | `p-3.5` (14px), `p-4` (16px) for panels | card padding |
| `space-stack` | `space-y-2` (8px) | items in a list |
| `layout-max` | `max-w-6xl` (1152px), gutter `px-4` | app shell |
| `layout-form-max` | `max-w-2xl` (672px) | New content, Verify |
| `control-h` | `h-9` (36px) default; `h-8` compact | inputs, selects, buttons |
| `target-min` | 24×24px minimum hit area (WCAG 2.5.8) | **[GAP]** `text-xs` link "Use a clean sample post" and `px-2.5 py-1` buttons are ~22px tall; raise to `h-8` |

---

## Layout and responsive behaviour

### App shell
- Header `h-14`, sticky (`sticky top-0 z-40`) **[GAP: currently scrolls away]**, with a translucent background blur. Contents: wordmark "Canonry", the workspace name, 4 nav links, and on the right the persona switcher plus the current persona's name and role.
- Main `max-w-6xl px-4 py-6`. Footer `text-meta`.

| Breakpoint | Shell changes |
|---|---|
| ≥ 1024 (`lg`) | Everything inline. |
| 640–1023 (`sm`–`md`) | Persona name label hidden (only the select shows). Nav stays inline. |
| < 640 | **[GAP]** Today the nav (4 links) plus select overflow at 360px. Spec: nav moves to a second row, `overflow-x-auto`, with the active link scrolled into view; wordmark and persona select stay on row 1. No horizontal page scroll at 320px (WCAG 1.4.10). |

### Review screen: two-column at desktop **[GAP: currently one stacked column]**
Why: the plan's Figure 2 places the copy and its findings side by side. A reviewer reads a highlight and its reason without scrolling between them, which is the single biggest speed win (P6).

| Breakpoint | Layout |
|---|---|
| ≥ 1024 | Header block (title, badges, routing note, banners) full width. Below it a 12-col grid with `gap-6`: **Content panel** `col-span-7`, `sticky top-20`, `max-h-[calc(100vh-6rem)] overflow-auto`; **Findings column** `col-span-5`. Decision trail full width below. |
| 768–1023 | Same two columns at 6/6. |
| < 768 | Single column: Content panel (not sticky) → action bar → findings → trail. Action bar becomes a sticky bottom bar (`sticky bottom-0`, `bg-background/95`, top border) so Submit / Approve is always reachable one-handed. |

---

## Components

| Component | Variants | Props / data | Notes |
|---|---|---|---|
| `StatusBadge` | Draft, Checked, In review, Changes requested, Approved, Exempt-approved, Signed | `status` | Pill, `text-chip`. Add the `status-changes` style. |
| `RiskBadge` | low, medium, high, exempt | `risk` | Outline pill, uppercase, renders nothing when null. |
| `LevelBadge` | definite, likely, consider (+ severity suffix if not medium) | `tier`, `severity` | Text always present (P3). |
| `CategoryBadge` | per `CATEGORY_LABEL` | `category` | Falls back to the category with underscores replaced. Add a label for every contract category, e.g. `missing_cta` = "No call to action". |
| `ContentWithSpans` | default, historical (no highlights) | `content`, `findings`, `activeFindingId` | See the interaction spec. **[GAP]** Overlapping spans are silently dropped today: split the text into segments at every span boundary and attach all covering findings to each segment. |
| `FindingCard` | open, accepted, edited, disputed (collapsed); creator mode / reviewer mode | `finding`, `role`, `inReview`, handlers | The core component; full anatomy below. |
| `FixPreview` **[new]** | replace, remove | `before`, `after` | Inline diff: `before` struck through in `text-destructive`, `after` in `font-mono` on `bg-muted`. P4 requires before/after; today only the replacement shows. |
| `ReasonPicker` **[new]** | dispute, override | `value`, `note` | Select with the plan's fixed reasons: *Rule doesn't apply · Rule unclear · Fact outdated · AI misread · Other*, plus an optional note. Structured reasons are what Improvement 2 ("possibly unclear rules") counts; free text alone can't be aggregated. |
| `ActionBar` | creator (Re-check, Submit for review), reviewer (Approve, Request changes) | `status`, `role`, `openHigh` | Exactly one primary button per bar. |
| `Notice` | success, warning, error, info | `tone`, `children`, optional action | Replaces the five ad-hoc banner class strings. `role="status"` for success/info, `role="alert"` for errors. |
| `StatCard` | — | `value`, `label`, `hint` | Dashboard and Insights share it (two copies exist today: merge). |

### FindingCard anatomy (top to bottom)
1. **Badge row:** `CategoryBadge` · `LevelBadge` · checker chip (`terminology`/`claims`/`tone`/`readability`), plus a status chip when not open.
2. **Quoted span:** left border `amber-400`, italic, clamp 3 lines. Clicking it scrolls the content panel to the mark.
3. **Explanation:** `text-body`, full length, never truncated (it's the "why").
4. **Citations:** one line each, `"Fact F-012: 2,300+ active customer teams · owner Marketing Ops · valid to 2027-03-31"`. IDs in `font-mono`. Excerpt clamps to 2 lines with a "Show more" toggle. Confidential facts show the excerpt only, plus a `confidential` chip.
5. **Provenance:** `text-meta`: "Deterministic rule check" or "AI-assisted · gemini-2.0-flash · claims@4". AI findings also get an **AI-generated** chip (plan Section 10 transparency) **[GAP]**.
6. **Actions** (open findings on the latest revision only):
   - *Creator:* `FixPreview` + **Accept fix** (primary, small) · **Edit in my words** (reveals input + Apply) · **Dispute** (reveals `ReasonPicker` + Submit). Only one of Edit/Dispute is expanded at a time **[GAP: today both inputs show at once, so cards are tall and noisy]**.
   - *Reviewer, item In review:* **Override** (reveals `ReasonPicker` + Confirm override). Accept/Edit/Dispute are hidden for reviewers.
   - *Admin:* both sets; reviewer set first when In review.

---

## States and interactions

### Review screen

| Element | State | Behaviour |
|---|---|---|
| Page | Loading | Skeleton: title bar, a content block (4 lines), 3 card outlines. No layout shift on load. |
| Page | Not found / 404 | `Notice` error: "This submission doesn't exist or you don't have access." + link to Submissions. |
| Page | Engine unreachable | `Notice` error with **Retry** button. The nav shows "Offline" instead of "connecting…" forever **[GAP]**. |
| AI status banner **[GAP: missing]** | `check_run.status = ai_pending` | Info `Notice` above the findings: "Rule-based checks are complete. AI checks (implied claims, tone) are pending: no AI provider is configured." Plan 9.8 forbids silently skipping; today the UI never says so. The engine already returns `ai_pending` on submit and resolve, and `GET /submissions/{id}` must expose the latest check run's status. |
| Content mark | Default | `highlight` bg + tier underline. `title` attribute shows category · tier. |
| Content mark | Hover / focus of its card | `highlight-active` + ring; the card gets `ring-2 ring-ring`. Two-way: hovering a mark highlights its card. |
| Content mark | Click / Enter | Scroll the findings column to the card (`scrollIntoView({block: "nearest"})`), move focus to the card heading, flash `highlight-active` for 600ms. |
| Revision select | Older revision chosen | Highlights removed, findings header reads "(historical)", actions hidden, info `Notice`: "You're viewing revision 2 of 4. Back to latest." **[GAP]** Add a **Compare with previous** toggle showing a word diff (insertions `bg-emerald-100 underline`, deletions `line-through text-destructive`). Plan Section 7 lists the revision diff as a Round 2 deliverable. |
| Accept fix | Click | Disable **all** finding actions (one request at a time; every resolve creates a revision). Button text "Applying…" with spinner. On success: content re-renders, the revision number increments, focus moves to the **next open finding's** heading, and the live region announces "Fix applied. Revision 3 · 4 findings open." |
| Accept fix | Error | Error `Notice` at the card, keeping its message (e.g. the 409 text from the engine); actions re-enable. |
| Dispute / Override | Submit with no reason | Submit disabled until a reason is selected (the engine also rejects it with 400). |
| Dispute / Override | Success | Card collapses to a one-line summary: category · "Disputed by Arjun: Rule unclear" · **Undo** (Round 3). It moves to a "Resolved" group under the open findings. |
| Findings list | Zero open | Success `Notice`: "No open findings. Ready to submit for review." with **Submit for review** inside it as the primary action. |
| Findings list | Ordering | Open first, sorted by severity (high → low), then position in the text. Resolved findings in a collapsed "Resolved (n)" group. |
| Submit for review | Click | Button "Submitting…". On success the status pill flips to In review, the routing note appears ("Risk LOW · fast track to one reviewer"), and the live region announces it. Hidden unless status is Draft, Checked or Changes requested. |
| Approve | Open high-severity findings exist | Disabled, **with the reason visible as text** under the bar: "2 high-severity findings must be resolved or overridden first." A `title` tooltip alone isn't reachable by keyboard or touch **[GAP]**. |
| Approve | Click | Opens a confirm dialog: "Approve and sign revision 3? This creates a Proof of Compliance for this exact text." [Cancel] [Approve & sign]. Why: signing is irreversible and public. On success: success `Notice` "Signed. [Open verification page]", status → Signed, ActionBar hidden. |
| Request changes | Click | Requires a comment (disabled until there is one). Status → Changes requested; the creator's Submit button reappears. |
| Buttons (all) | Hover | Primary: `opacity-90`. Secondary/outline: `bg-muted`. |
| Buttons (all) | Focus-visible | `ring-[3px] ring-ring/50` (match shadcn `Button`). **[GAP]** Hand-rolled buttons have no focus style today; switch to `components/ui/button.tsx`. |
| Buttons (all) | Disabled | `opacity-40`, `cursor-not-allowed`, `aria-disabled`; keep the reason text visible. |

### New content (`/new`)

| Element | State | Behaviour |
|---|---|---|
| Title | Empty | Submit disabled. Max **120 chars** with a counter from 100 on. |
| Channel | Options | social · web · blog · email · sales **[GAP: add sales; the plan lists it]**. Default: social. |
| Source | Options | in-house · agency · ai-assisted **[GAP: the UI sends `member`; the engine and plan use `in-house`]**. Default: in-house. AI-assisted raises routed risk, so explain that in a helper line under the field. |
| Content | Limits | Max **10,000 characters** for Round 2 (≈ 1,500 words; the plan's 30s check target is per 1,000 words). Live word count bottom-right of the textarea; over the limit shows an error and disables submit. |
| Content | Prefill | Use the plan's Section 1 post **verbatim, including ₹** (the prefill says "Rs", which the price rule doesn't match the same way). "Use a clean sample" stays as a secondary text button at the 24px minimum height. |
| Submit | Busy | "Checking…" plus spinner; inputs read-only. Expect 1–3s without AI, up to 30s with it. After 3s show the hint "Rule checks done, waiting for AI checks…" |
| Submit | Error | Inline error under the button with the message, `role="alert"`; inputs stay editable. |

### Submissions (`/`)

| Element | State | Behaviour |
|---|---|---|
| List | Empty | Dashed-border empty state with a **"Load the demo launch post"** primary button that calls `POST /submissions` with the plan post. **[GAP]** The README promises a pre-seeded broken post, but the dashboard is empty on a fresh database, which is the first thing a judge sees. |
| Row | Default | Title (semibold, 1 line, ellipsis), status, risk, channel · source chip, "n open findings" right-aligned, content preview clamped to 1 line, router note in `text-meta`. |
| Row | Hover / focus | Border to `foreground/25`; whole row is one link with a visible focus ring. |
| Filters **[Round 3]** | — | "Needs my review" (reviewer default), "My drafts" (creator default), "All". |
| Stat cards | < 640 | **[GAP]** `grid-cols-3` is forced at all widths; use `grid-cols-1 sm:grid-cols-3`. |

### Verify (`/verify/[pocId]`)

| State | Headline | Notes |
|---|---|---|
| Loading | "Checking the seal…" | Skeleton record. |
| verified | "Verified: this approval is intact" (success, check icon) | Show approver, role, date, rules version in plain language first. Raw record (hashes, IDs) goes in a `<details>` "Technical record" disclosure; today the raw key-value dump is the only view **[GAP]**. |
| modified | "Modified: the content changed after approval" (error) | Explain: "The text no longer matches what was approved on {date}." |
| signature_invalid | "Signature check failed" (error) | — |
| unknown | "We can't find this Proof of Compliance" (neutral) | Suggest checking the link. |
| **[Round 3]** | — | "Paste text to verify" textarea, so a publisher can check a copy against the seal. The engine's `verify()` already accepts content. |

Use real icons (lucide `CircleCheck`, `TriangleAlert`, `CircleX`, `CircleHelp`) instead of the "✓ ⚠ ✗ ？" glyphs, which render inconsistently and are read aloud oddly by screen readers.

### Knowledge base and Insights
- **[GAP] Terms tab shows no banned words.** The page reads `t.avoid`, but the API returns `banned_or_check`. Rename the field.
- Rules: the "possibly unclear" chip gets a tooltip and an inline explanation of the flag (`no_examples` → "No do/don't example, so it can't be tested"). Round 2 plan items still missing from the UI: CSV import with lint results, rule edit with **change preview** (the engine endpoints exist).
- Insights: "Submissions by status" renders as "3 / 1 / 2" with labels in the hint, which is hard to read. Use a small labelled list or one stat per status. Category names use `CATEGORY_LABEL`, not the raw `unsupported claim` string.

---

## Edge cases

- **Very long copy (5,000+ words):** the content panel scrolls inside its sticky column; the findings column paginates past 50 findings ("Show 50 more").
- **Long single tokens (URLs, hashes):** `break-words` in content, `break-all` in the verify record.
- **Span not found in the current text** (stale finding): hide its mark; the card shows "This text has changed since the check. Re-check." with a Re-check button.
- **Overlapping spans:** a segment covered by two findings uses the higher tier's underline; its `title` lists both; clicking cycles through them.
- **Zero-length span** (e.g. the "too many exclamation marks" finding is document-level): no mark; the card shows "Applies to the whole text" in place of the quote.
- **International text:** the content area keeps `whitespace-pre-wrap` and doesn't uppercase or truncate user copy. Allow ~30% expansion for UI strings (German, Hindi): badge labels may wrap, with no fixed widths on chips. Use the ₹ symbol and Indian digit grouping in demo data, as the plan does.
- **Slow connection / free-tier cold start** (Render and Spaces sleep, ~30–50s first hit): after 5s of loading show "Waking the analysis engine (free hosting); this can take up to a minute on first visit."
- **Missing data:** a citation whose rule/fact lookup fails shows the bare ID plus "(source unavailable)" and must not crash the card. `valid_to = null` reads "no expiry".
- **Concurrent edits:** if a resolve returns 404 (finding belongs to an older revision), reload and show "This submission was updated. You're now on the latest revision."

---

## Animation / motion

| Element | Trigger | Animation | Duration | Easing |
|---|---|---|---|---|
| Buttons, links, rows | hover / focus | colour, opacity, border | 150ms | `ease-out` |
| Mark ↔ card | hover / focus of either | background to `highlight-active` | 150ms | `ease-out` |
| Mark | scroll-to after click | background flash (active → default) | 600ms | `ease-in-out` |
| Finding card | resolved | height collapse + fade to summary row | 200ms | `ease-out` |
| Notices | appear | fade + 4px slide down | 150ms | `ease-out` |
| Skeletons | loading | `animate-pulse` | — | — |

All motion is wrapped in `motion-safe:`. With `prefers-reduced-motion: reduce`, colour changes stay and movement is removed.

---

## Accessibility notes

- **Landmarks:** `header`, `nav aria-label="Main"`, `main`, `footer`. One `h1` per page. Review screen headings: h2 "Content", h2 "Findings", h3 per finding (category + tier, e.g. "Contradicted claim, Definite"), h2 "Decision trail".
- **Focus order on Review:** title → ActionBar (Submit / Approve) → revision select → content marks (in text order) → finding cards (in list order; inside each: quote → actions) → trail.
- **Marks** are focusable (`tabIndex=0`, `role="button"`), with `aria-describedby` pointing to their card's heading. Keys: Enter/Space jump to the card; Escape returns focus to the mark.
- **Live region:** one `aria-live="polite"` region on the Review page announces the outcome of every action (fix applied, disputed, submitted, approved, errors). Errors use `role="alert"`.
- **After an action,** focus never drops to `<body>`: it moves to the next open finding, or to the success notice when none are left.
- **Disabled controls** keep their reason as visible text, programmatically linked via `aria-describedby`.
- **Forms:** every input has a visible `<label>` (the edit and dispute inputs rely on placeholders today **[GAP]**). Required fields carry `aria-required`. Inline errors go in `aria-describedby`.
- **Colour independence:** tiers, status and risk always carry text, and span underline styles differ per tier. Check contrast for `text-chip` (11px) at ≥ 4.5:1 in both themes.
- **Persona switcher:** labelled select. Switching announces "Signed in as Maya, Reviewer".
- **Approve dialog:** shadcn `Dialog` (Radix), focus trapped, Escape closes, initial focus on Cancel (signing is irreversible).
- **Automated check:** add axe-core to CI per plan 9.6, plus a manual keyboard-only pass of the demo journey.

---

## Implementation order (suggested)

1. Tokens in `globals.css` + Geist font: one file, fixes every screen's look.
2. Review screen: AI-pending banner, collapsed-by-default Edit/Dispute, `ReasonPicker`, visible approve-block reason, focus management + live region.
3. Demo-post button on the empty dashboard; `/new` source values and ₹ prefill; KB terms field fix.
4. Two-column Review layout + mark ↔ card linking; `FixPreview`.
5. Revision diff; Verify page plain-language summary + icons.
6. Mobile shell (nav second row, sticky action bar); axe-core in CI.
