"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { useIdentity } from "@/components/identity";
import { GuideCharacter } from "@/components/tour-figures";
import { api, type Submission, type SubmissionDetail } from "@/lib/api";

/**
 * The guide: a short, friendly tutorial for first-time visitors that sits beside
 * the app (never over it). It always says the ONE next thing to do and points at
 * the button with a glowing ring. It follows what the person actually does, so it
 * moves on by itself. Experienced visitors never see it; "?" brings it back.
 */

const FIRST_KEY = "canonry.firstTime"; // "yes" | "no"
const GUIDE_KEY = "canonry.guide"; // "on" | "off" | "done"

type GuideCtx = { on: boolean; start: () => void; stop: (done?: boolean) => void; firstTime: boolean | null };
const Ctx = createContext<GuideCtx>({ on: false, start: () => {}, stop: () => {}, firstTime: null });
export const useGuide = () => useContext(Ctx);

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // storage blocked: the guide still works for this visit
  }
}

const SENT_KEY = "canonry.guide.sent";
/** The draft this visitor sent for review, so the guide can point the reviewer at it. */
export function rememberSent(sid: string) {
  write(SENT_KEY, sid);
}

/** True once this browser has been through the welcome screen before. */
export function hasVisited(): boolean {
  return read(FIRST_KEY) !== null;
}

/** True when this visitor asked, on the welcome screen, to be shown around. */
export function wantsGuide(): boolean {
  return read(FIRST_KEY) === "yes";
}

/** Called by the welcome screen with the visitor's answer. */
export function rememberFirstTime(first: boolean) {
  write(FIRST_KEY, first ? "yes" : "no");
  write(GUIDE_KEY, first ? "on" : "off");
  // ticking "Show me around" is an explicit request: every role's tour plays again
  if (first) {
    try {
      window.localStorage.removeItem("canonry.tour.seen");
    } catch {
      // storage blocked: nothing was remembered anyway
    }
  }
}

/**
 * Signing out forgets this visit's progress (the guide, the draft it was following). The welcome
 * answer and the tours already seen stay with the browser, so they are not shown twice.
 */
export function forgetVisit() {
  // This browser has still seen the intro and each role's tour: switching profile by signing out
  // and back in must not show them again (it did, every time). Only this visit's progress goes.
  for (const key of [GUIDE_KEY, SENT_KEY, "canonry.tour.v1", "canonry.tour.role"]) {
    try {
      window.localStorage.removeItem(key);
      window.sessionStorage.removeItem(key);
    } catch {
      // storage blocked: nothing was persisted anyway
    }
  }
}

export function GuideProvider({ children }: { children: React.ReactNode }) {
  const [on, setOn] = useState(false);
  const [firstTime, setFirstTime] = useState<boolean | null>(null);
  useEffect(() => {
    setOn(read(GUIDE_KEY) === "on");
    const f = read(FIRST_KEY);
    setFirstTime(f === null ? null : f === "yes");
  }, []);
  const start = useCallback(() => {
    write(GUIDE_KEY, "on");
    setOn(true);
  }, []);
  const stop = useCallback((done = false) => {
    write(GUIDE_KEY, done ? "done" : "off");
    setOn(false);
  }, []);
  return <Ctx.Provider value={{ on, start, stop, firstTime }}>{children}</Ctx.Provider>;
}

type Step = { n: number; title: string; body: React.ReactNode; target?: string; link?: { href: string; label: string }; total?: number };
const TOTAL = 6;
const DONE = ["Signed", "Approved", "Exempt-approved"];

/** Work out the one next step from where the person is and what they have done. */
function nextStep(path: string, role: string, mine: Submission[], detail: SubmissionDetail | null): Step {
  const sentId = typeof window === "undefined" ? null : read(SENT_KEY);
  const draft = mine.find((s) => !DONE.includes(s.status) && s.status !== "In review");
  const inReview = mine.find((s) => s.status === "In review");
  const signed = mine.find((s) => DONE.includes(s.status));

  if (path.startsWith("/verify")) {
    return {
      n: 6,
      title: "That's the whole journey",
      body: (
        <>
          This public page proves exactly what was approved, by whom and against which rules. Anyone can check a
          published copy here. You can now check your own content from <strong>New check</strong>.
        </>
      ),
    };
  }

  if (detail) {
    const st = detail.submission.status;
    const open = detail.findings.filter((f) => f.status === "open");
    const must = open.filter((f) => f.severity === "high").length;
    if (DONE.includes(st)) {
      return {
        n: 6,
        title: "Approved and signed",
        body: (
          <>
            Canonry signed the approval. Press <strong>Verify the approval</strong> to see the proof anyone can check.
          </>
        ),
        target: '[data-guide="verify"]',
      };
    }
    if (st === "In review") {
      if (role === "reviewer" || role === "admin") {
        return must > 0
          ? {
              n: 5,
              title: "Decide as the reviewer",
              body: (
                <>
                  Some issues marked <strong>Must fix</strong> are still open, so it can&apos;t be approved yet. Press{" "}
                  <strong>Send back to the writer</strong>, or switch back to Creator and fix them.
                </>
              ),
              target: '[data-guide="send-back"]',
            }
          : {
              n: 5,
              title: "Approve it",
              body: (
                <>
                  You&apos;re the reviewer now. Glance over the content, then press <strong>Approve &amp; sign</strong>.
                </>
              ),
              target: '[data-guide="approve"]',
            };
      }
      return {
        n: 4,
        title: "Now play the reviewer",
        body: (
          <>
            A person always makes the final call. Open the menu at the top right (on a phone, the menu
            button) and choose <strong>Reviewer</strong>.
          </>
        ),
        target: '[data-guide="account"], [aria-label="Open menu"]',
      };
    }
    const blocking = open.filter(
      (f) => f.severity === "high" ||
        (f.suggestion?.operation !== "rewrite" && (f.suggestion?.replace || f.suggestion?.operation === "remove")),
    );
    if (blocking.length > 0) {
      return {
        n: 2,
        title: `Canonry found ${open.length} issue${open.length === 1 ? "" : "s"}`,
        body: (
          <>
            Each card says what&apos;s wrong and how to fix it. The numbers in your text match the cards. Press{" "}
            <strong>Accept all suggested fixes</strong>, or fix them one by one.
          </>
        ),
        target: '[data-guide="accept-all"], [data-guide="accept"]',
      };
    }
    return {
      n: 3,
      title: "Send it for review",
      body: (
        <>
          {open.length > 0
            ? "What's left is only a suggestion you can leave. "
            : "Nothing left to fix. "}
          Press <strong>Send for review</strong> so a reviewer can approve it.
        </>
      ),
      target: '[data-guide="send-review"]',
    };
  }

  // the brand admin's own journey: what only an admin does
  if (role === "admin" && !path.startsWith("/review")) {
    const total = 5;
    if (path.startsWith("/kb")) {
      return {
        n: 2, total,
        title: "Keep the rulebook right",
        body: (
          <>
            Every check reads from here. Press <strong>New rule</strong> to add one; editing a rule first shows which
            approved posts it would change. Then open <strong>Insights</strong>.
          </>
        ),
        target: '[data-guide="kb-new"]',
        link: { href: "/insights", label: "Open Insights" },
      };
    }
    if (path.startsWith("/insights")) {
      return {
        n: 3, total,
        title: "Turn repeated claims into facts",
        body: (
          <>
            Under <strong>Claims with no fact behind them</strong>, press <strong>Add as approved fact</strong>: once
            approved, the same claim is backed instead of flagged.
          </>
        ),
        target: 'main a[href^="/kb?fact="]',
        link: { href: "/admin/api", label: "Next: the publishing gate" },
      };
    }
    if (path.startsWith("/admin/api")) {
      return {
        n: 4, total,
        title: "Put Canonry in front of your website",
        body: (
          <>
            Press <strong>Open the demo publisher</strong>: a post there goes live only after Canonry&apos;s signed
            approval arrives.
          </>
        ),
        target: '[data-guide="open-publisher"]',
        link: { href: "/admin", label: "Back to the overview" },
      };
    }
    if (path.startsWith("/admin") && read("canonry.guide.admin") === "done") {
      return {
        n: 5, total,
        title: "That's the admin's job",
        body: <>Rules, facts and the publishing gate are yours; reviewers decide on drafts in the review queue.</>,
        link: { href: "/review", label: "Open the review queue" },
      };
    }
    return {
      n: 1, total,
      title: "Your control room",
      body: <>The numbers show what is waiting and what needs attention. Start with the rulebook every check reads.</>,
      target: 'nav a[data-nav="/kb"]',
      link: { href: "/kb", label: "Open the knowledge base" },
    };
  }

  if (role === "reviewer" || role === "admin") {
    if (path.startsWith("/review")) {
      return {
        n: 5,
        title: "The review queue",
        body: <>Everything waiting for a decision is here. Open the draft you sent; it&apos;s highlighted.</>,
        target: sentId ? `main a[href="/submissions/${sentId}"]` : 'main a[href^="/submissions/"]',
      };
    }
    return {
      n: 5,
      title: "Open the review queue",
      body: <>Your draft is waiting there.</>,
      link: sentId ? { href: `/submissions/${sentId}`, label: "Open my draft" } : { href: "/review", label: "Go to the review queue" },
    };
  }

  if (path === "/new") {
    return {
      n: 1,
      title: "Check some content",
      body: (
        <>
          Paste your own text, or switch to <strong>PDF, Word or image</strong> and drop a document in. The sample has a
          few planted mistakes, so you can press <strong>Check it</strong> straight away.
        </>
      ),
      target: '[data-guide="new-primary"], [data-guide="check-it"]',
    };
  }
  if (signed && !draft && !inReview && role === "agency") {
    return {
      n: 6,
      title: "Approved: check your scorecard",
      body: <>Your client signed it off. The scorecard on My work shows how often your work is approved first time.</>,
      link: { href: "/agency", label: "Open my scorecard" },
    };
  }
  if (signed && !draft && !inReview) {
    return {
      n: 6,
      title: "You've done it all",
      body: <>Your content is approved and signed. Open it to see the proof, or check something new.</>,
      link: { href: `/submissions/${signed.id}`, label: "Open the approved content" },
    };
  }
  if (inReview) {
    return {
      n: 4,
      title: "Now play the reviewer",
      body: (
        <>
          Your draft is waiting for a reviewer. Open the menu at the top right (on a phone, the menu button) and choose{" "}
          <strong>Reviewer</strong>.
        </>
      ),
      target: '[data-guide="account"], [aria-label="Open menu"]',
    };
  }
  if (draft) {
    return {
      n: 2,
      title: "Fix what Canonry found",
      body: <>Open your draft to see the issues and fix them.</>,
      target: '[data-guide="open-draft"]',
      link: { href: `/submissions/${draft.id}`, label: "Open my draft" },
    };
  }
  if (role === "agency") {
    return {
      n: 1,
      title: "Submit work for your client",
      body: (
        <>
          You see only your agency&apos;s work. Press <strong>Submit client work</strong>: Canonry checks it against the
          client&apos;s rules before their reviewer sees it.
        </>
      ),
      target: '[data-guide="agency-new"]',
      link: path.startsWith("/agency") ? undefined : { href: "/agency", label: "Open my work" },
    };
  }
  return {
    n: 1,
    title: "Let's check your first post",
    body: (
      <>
        Canonry reads marketing content against the brand&apos;s rules and facts. Pick a sample under the box (
        <strong>Launch post with issues</strong> has a few planted mistakes), then press <strong>Check draft</strong>.
      </>
    ),
    target: '[data-guide="check-sample"]:not(:disabled), [data-guide="starter"]',
  };
}

function firstVisible(selector: string): HTMLElement | null {
  const all = Array.from(document.querySelectorAll<HTMLElement>(selector));
  return all.find((el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden") ?? null;
}

/** The panel itself: floating bottom-right beside the page; a bottom sheet on phones. */
export function GuidePanel() {
  const { on, stop } = useGuide();
  const { me } = useIdentity();
  const path = usePathname();
  const [mine, setMine] = useState<Submission[]>([]);
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [tick, setTick] = useState(0);

  const sid = path.startsWith("/submissions/") ? path.split("/")[2] : null;

  // follow what the person does: refresh on navigation and every few seconds
  useEffect(() => {
    if (!on || !me) return;
    const t = window.setInterval(() => setTick((x) => x + 1), 3500);
    return () => window.clearInterval(t);
  }, [on, me]);
  useEffect(() => {
    if (!on || !me) return;
    let alive = true;
    void (async () => {
      try {
        const [list, d] = await Promise.all([
          api<{ submissions: Submission[] }>("/submissions").catch(() => ({ submissions: [] as Submission[] })),
          sid ? api<SubmissionDetail>(`/submissions/${sid}`).catch(() => null) : Promise.resolve(null),
        ]);
        if (!alive) return;
        setMine(list.submissions.filter((s) => !s.created_by || s.created_by === me.email || me.role !== "creator"));
        setDetail(d);
      } catch {
        // the guide is help, never an error source
      }
    })();
    return () => {
      alive = false;
    };
  }, [on, me, sid, path, tick]);

  useEffect(() => {
    if (on && me?.role === "admin" && path.startsWith("/admin/api")) write("canonry.guide.admin", "done");
  }, [on, me, path]);

  const step = useMemo(
    () => (me ? nextStep(path, me.role, me.role === "creator" || me.role === "agency" ? mine : [], detail) : null),
    [path, me, mine, detail],
  );

  // the glowing ring on the one thing to press
  useEffect(() => {
    if (!on || !step?.target) return;
    const target = step.target;
    let marked: HTMLElement | null = null;
    const mark = () => {
      const el = firstVisible(target);
      if (el === marked) return;
      marked?.classList.remove("guide-pulse");
      el?.classList.add("guide-pulse");
      marked = el;
    };
    mark();
    const t = window.setInterval(mark, 400); // buttons appear after data loads
    return () => {
      window.clearInterval(t);
      marked?.classList.remove("guide-pulse");
    };
  }, [on, step?.target]);

  if (!on || !me || !step) return null;
  const finished = path.startsWith("/verify");

  function showMe() {
    const el = step?.target ? firstVisible(step.target) : null;
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.focus({ preventScroll: true });
  }

  return (
    <aside
      aria-label="Guide"
      aria-live="polite"
      className="guide-panel fixed inset-x-3 bottom-3 z-50 mx-auto max-w-[460px] rounded-2xl border border-brand/30 bg-card p-4 shadow-float md:bottom-6"
    >
      <div className="flex items-start gap-3">
        {/* the same guide who leads the Quick Tour walks you through the steps */}
        <GuideCharacter className="-mb-1 -ml-1 -mt-2 h-[68px] w-[58px] shrink-0" waving={finished} />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand">
            Guide · step {step.n} of {step.total ?? TOTAL}
          </p>
          <p className="mt-0.5 font-semibold text-foreground">{step.title}</p>
        </div>
        <button
          type="button"
          onClick={() => stop(finished)}
          aria-label="Close the guide"
          className="-mr-1 -mt-1 grid size-8 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <p className="tutorial-text mt-2 text-foreground">{step.body}</p>
      <div aria-hidden className="mt-3 flex gap-1">
        {Array.from({ length: step.total ?? TOTAL }, (_, i) => (
          <span key={i} className={`h-1 flex-1 rounded-full ${i < step.n ? "bg-brand" : "bg-border"}`} />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {step.target && !finished && (
          <button type="button" onClick={showMe} className="btn btn-sm btn-secondary">
            Show me
          </button>
        )}
        {step.link && (
          <Link href={step.link.href} className="btn btn-sm btn-primary">
            {step.link.label}
          </Link>
        )}
        {finished && (
          <button type="button" onClick={() => stop(true)} className="btn btn-sm btn-primary">
            Finish the guide
          </button>
        )}
        <button type="button" onClick={() => stop()} className="ml-auto text-xs text-muted-foreground hover:text-foreground">
          I&apos;ll explore on my own
        </button>
      </div>
    </aside>
  );
}
