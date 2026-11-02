
"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  FileText,
  FileUp,
  Home,
  Image as ImageIcon,
  Inbox,
  KeyRound,
  LayoutDashboard,
  MousePointer2,
  PenLine,
  X,
  type LucideIcon,
} from "lucide-react";
import { BrandMark } from "@/components/brand";
import { ROLE_LABEL, type Role } from "@/lib/roles";

type Step = {
  eyebrow: string;
  title: string;
  body: string;
  icon: LucideIcon;
  points?: string[];
  demo?: "write" | "check";
  /** open the window this step describes */
  cta?: { href: string; label: string };
  /** the element this step points at (a window in the nav bar) */
  target?: string;
  /** the window this page is about, so the tour can take you there without ending */
  href?: string;
};

/** The write window with both ways in. Only authoring profiles get this page. */
const WRITE_STEP: Step = {
  eyebrow: "Start here",
  title: "Write it, or upload it",
  body: "Type a draft, or drop the PDF, Word file or image you already have.",
  icon: FileText,
  demo: "write",
  target: '[data-nav="/new"]',
  href: "/new",
};

/** The four check pages, on one page. */
const PIPELINE_STEP: Step = {
  eyebrow: "How a check works",
  title: "Rules first, AI second, you decide",
  body: "Rules always run and are free. AI adds judgement when it can. Every finding cites its source and is pinned in the document.",
  icon: Check,
  points: [
    "Rule findings arrive even when the AI is off or out of quota.",
    "AI findings are suggestions: accept, edit or dispute them.",
  ],
  demo: "check",
};

/** One short page per window the profile actually has. */
const ROLE_WINDOWS: Record<Role, Step[]> = {
  creator: [
    {
      eyebrow: "Your windows",
      title: "Home is your desk",
      body: "Paste a draft, see what is waiting, and reopen your submissions.",
      icon: Home,
      target: '[data-nav="/"]',
      href: "/",
      cta: { href: "/", label: "Open home" },
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base",
      body: "The rules, facts and terms every check runs against.",
      icon: BookOpen,
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "My work",
      body: "Everything you wrote: what a reviewer sent back and why, what is with them, and what was approved.",
      icon: Inbox,
      cta: { href: "/work", label: "Open my work" },
    },
  ],
  reviewer: [
    {
      eyebrow: "Your windows",
      title: "Review queue",
      body: "Everything waiting on a decision, oldest first.",
      icon: Inbox,
      cta: { href: "/review", label: "Open the review queue" },
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base",
      body: "Edit the rules and facts, with a reason for every change.",
      icon: BookOpen,
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "Insights",
      body: "Approval health and the findings that fire most.",
      icon: BarChart3,
      cta: { href: "/insights", label: "Open insights" },
    },
  ],
  agency: [
    {
      eyebrow: "Your windows",
      title: "My work",
      body: "Only your agency's submissions, and what needs fixing.",
      icon: Building2,
      cta: { href: "/agency", label: "Open my work" },
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base",
      body: "The client's rules, so you can get it right first time.",
      icon: BookOpen,
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
  ],
  admin: [
    {
      eyebrow: "Your windows",
      title: "Overview",
      body: "The workspace at a glance, and every admin door.",
      icon: LayoutDashboard,
      cta: { href: "/admin", label: "Open the overview" },
    },
    {
      eyebrow: "Your windows",
      title: "Review queue",
      body: "Any draft waiting on a person.",
      icon: Inbox,
      cta: { href: "/review", label: "Open the review queue" },
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base",
      body: "Rules, facts and terms; every change is a version.",
      icon: BookOpen,
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "Insights",
      body: "Approval health, top findings and AI usage.",
      icon: BarChart3,
      cta: { href: "/insights", label: "Open insights" },
    },
    {
      eyebrow: "Your windows",
      title: "API & webhooks",
      body: "Run checks from your own pipeline, and hear about approvals.",
      icon: KeyRound,
      cta: { href: "/admin/api", label: "Open API & webhooks" },
    },
  ],
};

/** The write window first for authors; every profile ends on the checks. */
function stepsFor(role: Role): Step[] {
  const windows = (ROLE_WINDOWS[role] ?? []).map((s) => {
    const href = s.cta?.href ?? s.href;
    if (!href) return s;
    return { ...s, href, target: s.target ?? '[data-nav="' + href + '"]' };
  });
  return role === "creator" || role === "agency"
    ? [WRITE_STEP, ...windows, PIPELINE_STEP]
    : [...windows, PIPELINE_STEP];
}

export function ProductTour({
  open,
  role,
  onClose,
  onFinish,
}: {
  open: boolean;
  role: Role;
  onClose: () => void;
  onFinish: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [step, setStep] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const openedNav = useRef(false);
  const STEPS = stepsFor(role);
  const [spot, setSpot] = useState<{ top: number; left: number; width: number; height: number } | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open || !mounted) return;
    setStep(0);
    const frame = window.requestAnimationFrame(() => cardRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, mounted]);

  useEffect(() => {
    if (!open) return;
    const bodyOverflow = document.body.style.overflow;
    const htmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = htmlOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setStep((current) => Math.min(STEPS.length - 1, current + 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setStep((current) => Math.max(0, current - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const targetSelector = STEPS[step]?.target;

  // Walk the windows: measure the nav item this step points at and keep the
  // highlight on it through scrolls and layout shifts.
  useEffect(() => {
    if (!open || !targetSelector) {
      setSpot(null);
      return;
    }
    const measure = () => {
      // Pick the visible one: the desktop row and the phone menu hold the same link.
      const el = Array.from(document.querySelectorAll<HTMLElement>(targetSelector)).find(
        (node) => node.getClientRects().length > 0 && node.getBoundingClientRect().width > 8,
      );
      if (!el) {
        // On a phone the windows live in the menu: open it so the tour can point.
        if (!openedNav.current) {
          openedNav.current = true;
          window.dispatchEvent(new Event("canonry:open-nav"));
        }
        setSpot(null);
        return;
      }
      const r = el.getBoundingClientRect();
      setSpot((prev) =>
        prev &&
        Math.abs(prev.top - r.top) < 1 &&
        Math.abs(prev.left - r.left) < 1 &&
        Math.abs(prev.width - r.width) < 1 &&
        Math.abs(prev.height - r.height) < 1
          ? prev
          : { top: r.top, left: r.left, width: r.width, height: r.height },
      );
    };
    measure();
    const timer = window.setInterval(measure, 300);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, { passive: true });
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure);
    };
  }, [open, targetSelector]);

  // If the tour had to open the phone menu, close it again when the tour ends.
  useEffect(() => {
    if (open || !openedNav.current) return;
    openedNav.current = false;
    window.dispatchEvent(new Event("canonry:close-nav"));
  }, [open]);

  if (!mounted || !open) return null;

  const current = STEPS[step];
  const Icon = current.icon;
  const last = step === STEPS.length - 1;
  const spotLabel = current.cta?.label?.replace(/^Open /, "") ?? current.title;

  return createPortal(
    <div
      className="fixed inset-0 z-[90] grid place-items-center overflow-y-auto px-3 pb-4 pt-24 sm:px-4"
      role="presentation"
    >
      {!spot && <div aria-hidden className="fixed inset-0 bg-foreground/35 backdrop-blur-md" />}
      {spot && (
        <>
          <button
            type="button"
            tabIndex={-1}
            aria-label={current.href ? `Open ${spotLabel}` : undefined}
            onClick={() => {
              const href = current.href;
              if (href) router.push(href);
            }}
            className="tour-hole"
            style={{ top: spot.top, left: spot.left, width: spot.width, height: spot.height }}
          />
          <span
            aria-hidden
            className="tour-spot-label"
            style={{ top: spot.top + spot.height + 10, left: spot.left + spot.width / 2 }}
          >
            <MousePointer2 className="size-3.5" fill="currentColor" strokeWidth={1.4} />
            {spotLabel}
            <span className="font-normal opacity-70">· click to open</span>
          </span>
        </>
      )}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        style={{ height: "min(80dvh, 35rem)" }}
        className="surface relative z-10 my-auto flex w-full max-w-xl flex-col overflow-hidden border-border-strong shadow-float outline-none"
      >
        <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-muted/60 px-5 py-3">
          <BrandMark className="size-7" />
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand">
            Quick tour · {ROLE_LABEL[role] ?? role}
          </p>
          <button type="button" onClick={onClose} className="btn btn-ghost btn-sm ml-auto" aria-label="Skip tour">
            <X className="size-3.5" aria-hidden /> Skip
          </button>
        </div>

        {/* progress rail: also the step picker, so a returning visitor can jump */}
        <div className="flex shrink-0 gap-1 px-5 pt-3" role="tablist" aria-label="Tour steps">
          {STEPS.map((s, i) => (
            <button
              key={s.title}
              type="button"
              role="tab"
              aria-selected={i === step}
              aria-label={`Step ${i + 1}: ${s.title}`}
              onClick={() => setStep(i)}
              className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
                i === step ? "bg-brand" : i < step ? "bg-brand/45" : "bg-border-strong hover:bg-brand/30"
              }`}
            />
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="flex items-start gap-4">
            <span className="relative grid size-10 shrink-0 place-items-center rounded-xl border border-border-strong bg-card text-brand shadow-sm">
              <span aria-hidden className="tour-halo absolute inset-0 rounded-2xl" />
              <Icon className="relative size-4" strokeWidth={1.8} aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="eyebrow">{current.eyebrow}</p>
              <h2 id="tour-title" className="mt-0.5 text-xl font-bold tracking-tight text-foreground">
                {current.title}
              </h2>
            </div>
          </div>

          <p className="mt-3 text-sm leading-relaxed text-foreground-secondary">{current.body}</p>

          {current.demo === "write" && (
            <>
              <WriteWindowDemo />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => router.push("/new")} className="btn btn-sm btn-primary">
                  Open the write window <ArrowRight className="size-3.5" aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => router.push("/new?mode=file")}
                  className="btn btn-sm btn-secondary"
                >
                  Upload a file
                </button>
                <span className="text-[11px] text-muted-foreground">The tour stays with you.</span>
              </div>
            </>
          )}

          {current.demo === "check" && <CheckDemo />}

          {current.points && (
            <ul className="mt-3 space-y-2 text-[13px] leading-relaxed text-foreground-secondary">
              {current.points.map((point) => (
                <li key={point} className="flex gap-2.5">
                  <Check className="mt-0.5 size-4 shrink-0 text-brand" strokeWidth={2.2} aria-hidden />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          )}

          {current.cta && current.href && (
            <button
              type="button"
              onClick={() => {
                const href = current.href;
                if (href) router.push(href);
              }}
              className="btn btn-sm btn-secondary mt-3 w-fit"
            >
              {pathname === current.href ? "You are in this window" : current.cta.label}
              <ArrowRight className="size-3.5" aria-hidden />
            </button>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3 border-t border-border bg-card px-5 py-3">
          <p className="text-xs tabular-nums text-muted-foreground">
            Step {step + 1} of {STEPS.length}
          </p>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setStep((current) => Math.max(0, current - 1))}
              disabled={step === 0}
              className="btn btn-secondary btn-sm"
            >
              <ArrowLeft className="size-3.5" aria-hidden /> Back
            </button>
            {last ? (
              <button type="button" onClick={onFinish} className="btn btn-primary btn-sm">
                Try a sample <ArrowRight className="size-3.5" aria-hidden />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep((current) => Math.min(STEPS.length - 1, current + 1))}
                className="btn btn-primary btn-sm"
              >
                Next <ArrowRight className="size-3.5" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * The two halves of a check, as something to press: rules always run; AI rows
 * appear only when the model answers. It teaches the split by doing it.
 */
function CheckDemo() {
  const [ai, setAi] = useState(false);
  const rows = [
    { tag: "Rule", text: "“India’s #1” is a banned superlative.", verdict: "Must fix" },
    { tag: "Rule", text: "“₹999/month!” breaks the price format.", verdict: "Should fix" },
    { tag: "AI", text: "“5,000+ teams” is not supported by the fact library.", verdict: "Check" },
    { tag: "AI", text: "The tone reads as over-promising for this channel.", verdict: "Consider" },
  ];
  return (
    <div className="mt-3 rounded-xl border border-border-strong bg-card p-3 shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="What the check includes" className="flex rounded-full bg-muted p-0.5">
          <button
            type="button"
            aria-pressed={!ai}
            onClick={() => setAi(false)}
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors ${
              !ai ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Rules only
          </button>
          <button
            type="button"
            aria-pressed={ai}
            onClick={() => setAi(true)}
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors ${
              ai ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Rules + AI
          </button>
        </div>
        <p className="ml-auto text-[11px] text-muted-foreground">
          {ai ? "4 findings" : "2 findings, even offline"}
        </p>
      </div>
      <ul className="mt-2 space-y-1.5">
        {rows
          .filter((row) => ai || row.tag === "Rule")
          .map((row) => (
            <li key={row.text} className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-2.5 py-1.5">
              <span
                className={`mt-0.5 rounded px-1 text-[9px] font-bold uppercase ${
                  row.tag === "AI" ? "bg-brand/10 text-brand" : "bg-danger-bg text-danger-fg"
                }`}
              >
                {row.tag}
              </span>
              <span className="flex-1 text-[11.5px] leading-snug text-foreground-secondary">{row.text}</span>
              <span className="shrink-0 text-[10px] font-medium text-muted-foreground">{row.verdict}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}

/** A pointing cursor with a tap ripple: the one obvious thing to try. */
function Pointer({ label, className }: { label: string; className?: string }) {
  return (
    <span aria-hidden className={`tour-pointer ${className ?? ""}`}>
      <span className="tour-pointer-ring" />
      <MousePointer2 className="tour-pointer-icon" fill="currentColor" strokeWidth={1.4} />
      <span className="tour-pointer-label">{label}</span>
    </span>
  );
}

/**
 * The write window, shrunk to a card. It alternates between writing and
 * uploading on its own until someone touches it, so the file option cannot be
 * missed; the pointer always sits on the choice it wants you to notice.
 */
function WriteWindowDemo() {
  const [tab, setTab] = useState<"text" | "file">("text");
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto) return;
    const t = window.setInterval(() => setTab((v) => (v === "text" ? "file" : "text")), 3600);
    return () => window.clearInterval(t);
  }, [auto]);

  function pick(next: "text" | "file") {
    setAuto(false);
    setTab(next);
  }

  return (
    <div
      className="mt-3 overflow-hidden rounded-xl border border-border-strong bg-card shadow-card"
      aria-label="Preview of the write window"
    >
      <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-3.5 py-2">
        <span className="flex gap-1" aria-hidden>
          <span className="size-1.5 rounded-full bg-border-strong" />
          <span className="size-1.5 rounded-full bg-border-strong" />
          <span className="size-1.5 rounded-full bg-border-strong" />
        </span>
        <p className="truncate text-[11px] font-medium text-muted-foreground">New check · your draft box</p>
        <span className="ml-auto rounded-full bg-card px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand ring-1 ring-border">
          tour
        </span>
      </div>

      <div className="p-3.5 sm:p-4">
        <div
          role="group"
          aria-label="Write text or upload a file"
          className="relative flex w-fit max-w-full flex-wrap gap-1 rounded-full border border-border bg-muted/60 p-1"
        >
          <button
            type="button"
            aria-pressed={tab === "text"}
            onClick={() => pick("text")}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
              tab === "text" ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <PenLine className="size-3.5" aria-hidden /> Write text
          </button>
          <button
            type="button"
            aria-pressed={tab === "file"}
            onClick={() => pick("file")}
            className={`relative inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
              tab === "file" ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <FileUp className="size-3.5" aria-hidden /> PDF, Word or image
            {tab === "text" && <Pointer label="upload here" className="pointer-tab" />}
          </button>
        </div>

        <div className="relative mt-2 min-h-[132px]">
          {tab === "text" ? (
            <div className="animate-fade-up space-y-2">
              <div className="rounded-xl border border-border bg-card px-3 py-2.5">
                <p className="font-serif text-[13px] leading-relaxed text-foreground">
                  Meet Quillmark Insights 2.0 — India&apos;s #1 analytics platform, trusted by 5,000+ teams. Plans start
                  at just ₹999/month!
                </p>
              </div>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">18 words · 1 exclamation mark</p>
                <span className="btn btn-primary btn-sm pointer-events-none">Check it</span>
              </div>
            </div>
          ) : (
            <div className="animate-fade-up">
              <div className="relative flex flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-brand-highlight bg-muted/40 px-4 py-7 text-center">
                <FileUp className="size-6 text-brand" aria-hidden />
                <p className="text-xs font-semibold text-foreground">Drop a file here, or choose one</p>
                <p className="text-[11px] text-muted-foreground">PDF, DOCX, PNG or JPEG · up to 4 MB</p>
                <div className="mt-1 flex gap-1">
                  {[FileText, ImageIcon, FileUp].map((Ico, i) => (
                    <span key={i} className="grid size-6 place-items-center rounded-md bg-card text-muted-foreground ring-1 ring-border">
                      <Ico className="size-3" aria-hidden />
                    </span>
                  ))}
                </div>
                <Pointer label="or drop it here" className="pointer-drop" />
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">Issues appear on a page preview, numbered.</p>
                <span className="btn btn-primary btn-sm pointer-events-none">Upload and check</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
