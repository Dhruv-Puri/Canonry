"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import { api, ApiError, type Submission } from "@/lib/api";

/** The draft every walkthrough starts from: a few mistakes Canonry is built to catch. */
export const SAMPLE_DRAFT =
  "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by " +
  "5,000+ teams and fully ISO 27001 certified. Plans start at just ₹999/month!";

const FIXED_KEY = "canonry.walkthrough.fixed";
const HIDDEN_KEY = "canonry.walkthrough.hidden";

/** Remember that this browser fixed or disputed an issue (step 2 of the walkthrough). */
export function markIssueHandled() {
  try {
    window.localStorage.setItem(FIXED_KEY, "1");
  } catch {
    // storage can be blocked; the step then ticks once the draft moves on
  }
}

const DONE_STATUSES = ["Signed", "Approved", "Exempt-approved"];

type Step = { title: string; body: string; done: boolean; action?: React.ReactNode };

/**
 * "Start here": the whole product in four steps a first-time visitor can follow
 * without reading anything else. Each step ticks itself off as it happens.
 */
export function StartHere({ subs, mine }: { subs: Submission[] | null; mine: Submission[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fixed, setFixed] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    try {
      setFixed(window.localStorage.getItem(FIXED_KEY) === "1");
      setHidden(window.localStorage.getItem(HIDDEN_KEY) === "1");
    } catch {
      // defaults are fine
    }
  }, []);

  async function checkSample() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ submission_id: string }>("/submissions", {
        method: "POST",
        json: { title: "My first check", channel: "social", source_type: "ai-assisted", content: SAMPLE_DRAFT },
      });
      router.push(`/submissions/${r.submission_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }

  function toggle(hide: boolean) {
    setHidden(hide);
    try {
      window.localStorage.setItem(HIDDEN_KEY, hide ? "1" : "0");
    } catch {
      // ignore
    }
  }

  const latest = mine[0];
  const inReviewOrLater = mine.some((s) => s.status === "In review" || DONE_STATUSES.includes(s.status));
  const approved = mine.find((s) => DONE_STATUSES.includes(s.status));
  const steps: Step[] = [
    {
      title: "Check a draft",
      body: "Canonry reads it against Quillmark's brand rules and facts. The sample has a few planted mistakes.",
      done: mine.length > 0,
      action: (
        <>
          <button type="button" onClick={() => void checkSample()} disabled={busy} className="btn btn-primary btn-sm">
            {busy ? "Checking…" : <>Check the sample <span aria-hidden className="btn-arrow">→</span></>}
          </button>
          <Link href="/new" className="btn btn-ghost btn-sm">
            Write or upload your own
          </Link>
        </>
      ),
    },
    {
      title: "Fix what it found",
      body: "Each issue says why, with a one-click fix. Accept it, write your own, or dispute it.",
      done: fixed || inReviewOrLater,
      action: latest ? (
        <Link href={`/submissions/${latest.id}`} className="btn btn-primary btn-sm">
          Open my draft <span aria-hidden className="btn-arrow">→</span>
        </Link>
      ) : undefined,
    },
    {
      title: "Send it for review",
      body: "A person always makes the final call. The draft is locked while it is reviewed.",
      done: inReviewOrLater,
      action: latest ? (
        <Link href={`/submissions/${latest.id}`} className="btn btn-primary btn-sm">
          Open my draft <span aria-hidden className="btn-arrow">→</span>
        </Link>
      ) : undefined,
    },
    {
      title: "Approve it as a reviewer",
      body:
        "Open the menu at the top right, switch to Reviewer, and approve it. Canonry signs the approval so anyone can verify it later.",
      done: Boolean(approved),
      action: approved ? (
        <Link href={`/submissions/${approved.id}`} className="btn btn-secondary btn-sm">
          See the signed approval
        </Link>
      ) : undefined,
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const current = steps.findIndex((s) => !s.done);
  const allDone = current === -1;

  if (subs === null) return <div className="surface h-48 animate-pulse" aria-busy="true" />;

  if (hidden) {
    return (
      <button type="button" onClick={() => toggle(false)} className="link text-sm">
        Show “Start here” ({doneCount} of {steps.length} done)
      </button>
    );
  }

  return (
    <section aria-labelledby="start-here" className="surface overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4 sm:px-6">
        <Sparkles className="size-5 text-brand" aria-hidden />
        <div className="mr-auto">
          <h2 id="start-here" className="text-lg font-bold tracking-tight">
            {allDone ? "You have seen the whole flow" : "Start here: try Canonry in 4 steps"}
          </h2>
          <p className="text-xs text-muted-foreground">
            {allDone ? "Check your own content any time." : "About two minutes. Each step ticks itself off."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div
            role="progressbar"
            aria-label="Steps done"
            aria-valuemin={0}
            aria-valuemax={steps.length}
            aria-valuenow={doneCount}
            className="h-1.5 w-24 overflow-hidden rounded-full bg-border"
          >
            <div className="h-full rounded-full bg-success-fg transition-[width] duration-500"
                 style={{ width: `${(doneCount / steps.length) * 100}%` }} />
          </div>
          <span className="text-xs font-medium text-foreground-secondary">{doneCount}/{steps.length}</span>
          <button type="button" onClick={() => toggle(true)} className="btn btn-ghost btn-sm" aria-label="Hide Start here">
            Hide <ChevronDown className="size-3.5" aria-hidden />
          </button>
        </div>
      </div>
      <ol className="divide-y divide-border">
        {steps.map((st, i) => {
          const isNow = i === current;
          return (
            <li key={st.title} className={`flex gap-4 px-5 py-4 sm:px-6 ${isNow ? "bg-brand/[0.05]" : ""}`}
                aria-current={isNow ? "step" : undefined}>
              <span
                className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold ${
                  st.done ? "bg-success-fg text-background" : isNow ? "bg-foreground text-background" : "border border-border-strong text-muted-foreground"
                }`}
              >
                {st.done ? <Check className="size-4" strokeWidth={3} aria-label="Done" /> : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className={`font-semibold ${st.done ? "text-foreground-secondary line-through decoration-1" : "text-foreground"}`}>
                  {st.title}
                </p>
                {(isNow || !st.done) && <p className="mt-0.5 text-sm text-foreground-secondary">{st.body}</p>}
                {isNow && st.action && <div className="mt-3 flex flex-wrap items-center gap-2">{st.action}</div>}
              </div>
            </li>
          );
        })}
      </ol>
      {error && (
        <p role="alert" className="border-t border-border bg-warning-bg px-5 py-3 text-sm text-warning-fg sm:px-6">
          {error}
        </p>
      )}
    </section>
  );
}
