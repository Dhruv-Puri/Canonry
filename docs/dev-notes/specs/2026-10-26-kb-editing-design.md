# Knowledge base editing — design

Status: decided by the engineering lead (the product owner delegated all calls).
Implements plan principles: "same revision + same knowledge version → same findings",
"no citation, no finding", and "every approved fact has an owner, a source and an
expiry date; when it changes, Canonry lists the already-approved content that used
the old value".

## Why

The knowledge base (rules, facts, terms) is read-only in the UI. A brand owner who
changes a price or renames a product has no way to do it, and the engine's half-built
edit paths (`PATCH /rules/{id}`, `POST /facts`) overwrite rows in place, never bump
the knowledge version and lose what earlier findings cited.

## Goals

- Reviewers and admins create, edit, retire and restore rules, facts and terms from
  the Knowledge base page.
- Every change is a new **version** with a required reason (except create), the author
  and time. Nothing is ever overwritten or deleted.
- Findings record the **version** of each rule/fact/term they cite; the review page
  shows that version's text, and says when a newer version exists.
- Signed Proofs of Compliance carry the **knowledge version** they were checked against.
- A fact change lists the approved content that relied on the old value; Insights keeps
  a live "needs re-review" list of approved content citing out-of-date versions.
- Caches never serve a verdict computed against older knowledge.

## Non-goals

- Bulk import / CSV upload in the UI; draft-and-approve workflow for rule changes
  (two-person rule); per-field permissions; real-time collaboration.
- Changing how checkers work. They keep reading the current tables.

## Anti-goals (would be a failure even if it "works")

- An approval or finding that silently changes meaning because a rule was edited later.
- A stale cached verdict surviving a fact edit.
- Creators or agency users able to change the canon.

## Decisions

1. **Append-only history, current tables as read model.** New table
   `knowledge_history` holds a full JSON snapshot per version. `rules`, `facts`,
   `terms` keep holding the current version, so no checker query changes.
2. **Per-entity version numbers** (`version` column on all three tables; seed = 1).
   Seeding and the migration write a `seed` history row for every entity.
3. **Retire, never delete.** Rule → `status='retired'` (already ignored by the citation
   check). Fact → `superseded=1` (already inactive). Term → new `status` column
   `active|retired`, filtered by the terminology checker. Restore = a new version
   copied from an earlier non-retired snapshot.
4. **Monotonic knowledge-version counter** in `meta('knowledge_version')`, incremented
   once per change, initialised on migration to at least every value already recorded
   (the old rowid-sum + bump, and the max in `check_runs`). Replaces the duplicated
   rowid-sum code in `db.py` and `pipeline.py`.
5. **Optimistic locking.** Edits send `expected_version`; a mismatch is `409`.
6. **Validation.** Rules: category, statement ≥ 10 chars, severity low/medium/high,
   status approved/draft; vague flag recomputed with the existing `lint_rule`.
   Facts: text, category, owner and source required; dates `YYYY-MM-DD`;
   `valid_to ≥ valid_from`; expiry optional but the UI marks facts without one.
   Terms: at least one of preferred / avoid; severity low/medium/high.
7. **IDs.** Rules accept an optional id `^[A-Z]{2,6}-\d{1,3}(\.\d+)?$`, else
   `<prefix>-<n+1>` using the category's existing prefix (fallback: first three letters
   of the category, upper-case). Facts: `F-<next 3-digit number>`. Terms: integer.
8. **Claim memory is stamped** with the knowledge version and reused only on an exact
   match (plan: "cache by version").
9. **Proof of Compliance** records `knowledge_version`; kind becomes
   `ProofOfCompliance/2`. Old records verify unchanged.
10. **Permissions.** Reviewer and admin edit; everyone signed in reads. Confidential
    fact visibility is unchanged here (the security pass owns it).
11. **API** lives under `/kb/{kind}` (`kind` = rules | facts | terms). The old
    `PATCH /rules/{id}` and `POST /facts` are removed (no callers).

## Left to the builder

Exact copy, form layout and component structure on the Knowledge base page, within the
existing design system (`surface`, `btn`, `field`, shadcn `Dialog`).
