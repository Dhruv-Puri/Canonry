# Usability test kit — 5 participants, SUS, one sitting

> Plan Section 11.6 commits to **5 task-based sessions per round** with the
> **System Usability Scale**, and to logging the changes they lead to. This kit
> is everything needed to run one round of those sessions and turn the answers
> into evidence. Nothing here is code — run it with real people.

---

## 1. Setup (10 minutes, before the first participant)

- Start the app: engine on `:8000`, web on `:3000` (see the tried-and-true steps
  in [getting-started.md](getting-started.md)).
- Reset to a clean demo state so every participant starts equal:

  ```bash
  cd Canonry && rm -f db/canonry.db db/canonry.db-wal db/canonry.db-shm
  # restart the engine — it re-seeds Quillmark and the demo launch post
  ```

- Have this kit open on your own screen, a timer ready, and a second device
  (or a second browser profile) for the facilitator.
- Also time **manual review of the same document** — the plan compares the two.

## 2. Who to recruit (plan Section 11.6)

People who create or approve content: classmates in marketing/media/design, the
college communications or social-media team, student-club content leads,
freelance writers. Mix at least one reviewer-minded person.

## 3. Facilitator script

1. *"You are joining a fictional brand team. Nothing you type is published, and
   there are no wrong answers — we are testing the tool, not you."*
2. Ask them to say their name and pick the **Creator** role. Do not explain the
   dashboard; let the first task do that.
3. Read each task aloud. Intervene only if someone is stuck for more than
   two minutes; note the intervention — it is a finding, not a failure.
4. Note timestamps, confusions, and every "why did it do that?" moment verbatim.

## 4. The five tasks (success = what you tick)

| # | Task | Give the participant | Success criteria | Watch for |
|---|---|---|---|---|
| T1 | **Set up a rule** | *"The brand owner wants the rule 'Never call customers 'users' in public copy.' Add it, then check what it would affect before saving."* | Rule created in the Knowledge base; the preview shows the affected approved content; the reason field is understood | Is "Preview impact" discoverable? Does the vocabulary ("don't example") land? |
| T2 | **Submit a draft** | The planted launch post: *"Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and fully ISO 27001 certified. Plans start at just ₹999/month!"* | Submission created; findings appear; participant can say what at least three highlights mean | Do they understand `definite / likely / consider`? Is the citation line read? |
| T3 | **Fix findings** | *"Make this publishable."* | At least one fix accepted (watch the revision number increase); at least one issue either fixed in their own words or disputed with a reason | Do they find Accept vs Edit vs Dispute? Is "one row per issue" (missing term duplicate) confusing? |
| T4 | **Review and approve** | *"Now you are the brand reviewer. Decide this item."* | The 409 refusal is understood (high-severity open); override-with-reason works; approval yields a Proof of Compliance | Is the refusal message read as policy or as a bug? |
| T5 | **Verify the seal** | *"Prove to someone outside the company that this was approved."* | Participant finds the `/verify/<poc_id>` page, pastes the published text and reads `Verified` correctly | Was the path obvious from the approval screen? |

**Compare with manual review:** time the same five tasks against a colleague
reviewing the launch post by hand against `data/quillmark_rules.csv` and the
fact list. Record both times in §6.

## 5. SUS questionnaire (standard, 10 items)

Ask immediately after T5. 1 = strongly disagree … 5 = strongly agree.

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

**Scoring:** odd items → (score − 1); even items → (5 − score). Sum, multiply by
2.5. That is one participant's SUS score (0–100). Average across participants;
a score ≥ 68 is "above average".

## 6. Results sheet (fill in and keep — this is the evidence)

| Participant | Role played | T1 | T2 | T3 | T4 | T5 | Total time | SUS |
|---|---|---|---|---|---|---|---|---|
| P1 | | | | | | | | |
| P2 | | | | | | | | |
| P3 | | | | | | | | |
| P4 | | | | | | | | |
| P5 | | | | | | | | |
| **Manual review (same doc)** | — | — | — | — | — | — | | — |

**Observed problems → changes made** (the plan asks for this link explicitly):

| # | What we saw | Change made | Re-checked with |
|---|---|---|---|
| 1 | | | |
| 2 | | | |

## 7. Reporting it in the submission

- State **n = 5**, the participant mix, and the average SUS with the range.
- Show the task times beside the manual-review time.
- List every change made because of the tests, and what was *not* changed (with
  a reason). Honest gaps are stronger evidence than a clean report.
