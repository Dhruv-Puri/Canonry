
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  ClipboardCheck,
  FileText,
  FileUp,
  Home,
  Image as ImageIcon,
  Inbox,
  KeyRound,
  LayoutDashboard,
  MousePointer2,
  PenLine,
  Search,
  Sparkles,
  Stamp,
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
  compare?: { rule: string[]; ai: string[] };
  demo?: "write";
  tip?: string;
  /** open the window this step describes */
  cta?: { href: string; label: string };
};

const CORE_STEPS: Step[] = [
  {
    eyebrow: "Start here",
    title: "Write it here, or upload the file you already have",
    body:
      "Canonry checks marketing copy the way you already work: type it in, or bring the PDF, Word file or image you were about to publish. Both land in the same check.",
    icon: PenLine,
    demo: "write",
  },
  {
    eyebrow: "Two kinds of checks",
    title: "Rules always run. AI adds judgement.",
    body:
      "Canonry doesn't only ask an AI. Most findings come from deterministic rules that always run; AI adds judgement where rules can't.",
    icon: Search,
    compare: {
      rule: ["Terminology and banned words", "Readability, channel limits, CTA", "Tone heuristics and confidential leaks"],
      ai: ["Implied claims", "Fact verification", "Tone judgement"],
    },
    tip: "The same report shows both: rule findings always arrive; AI findings appear when the model answers, or that section is marked pending.",
  },
  {
    eyebrow: "Always on",
    title: "The rule checks run first",
    body:
      "They are deterministic, fast, and free. They still run when the AI is off, out of quota, or every provider is busy.",
    icon: Check,
    points: [
      "Terminology, banned words, readability, channel limits and calls to action.",
      "Tone heuristics and confidential-leak checks.",
      "Every finding cites the rule, term or fact it was checked against.",
      "A check can come back with findings even when AI is marked pending.",
    ],
  },
  {
    eyebrow: "Extra coverage",
    title: "AI suggests; people decide",
    body:
      "When a provider answers, AI looks for implied claims, verifies them against your Fact Library, and judges tone against your voice rules.",
    icon: Sparkles,
    points: [
      "AI findings are suggestions: accept, edit, or dispute them.",
      "If the provider is unavailable, AI is marked pending — rule findings still arrive.",
      "Confidential facts are held back from free AI providers.",
    ],
  },
  {
    eyebrow: "The finish line",
    title: "Every issue is pinned where it happens",
    body:
      "A document opens in a page preview that keeps its layout. Each issue is highlighted in place and numbered to match its card, so you see the problem where a reader would meet it.",
    icon: Stamp,
    points: [
      "PDF findings point to a page and line; Word findings to a section and paragraph.",
      "Accept, edit or dispute each one — the preview updates as you go.",
      "Once a reviewer approves, the approval is signed and anyone can verify it.",
    ],
  },
];

/** One step per window the signed-in profile actually has. */
const ROLE_WINDOWS: Record<Role, Step[]> = {
  creator: [
    {
      eyebrow: "Your windows",
      title: "Home is your desk",
      body: "Everything starts here: a quick draft box, what is waiting, and every submission you have already checked.",
      icon: Home,
      points: [
        "Paste a draft and check it without leaving the page.",
        "At a glance: approved rules, facts on file and open drafts.",
        "Your submissions, newest first, with their open-finding counts.",
      ],
    },
    {
      eyebrow: "Your windows",
      title: "A draft page is the whole story",
      body: "Open a submission and the content sits beside its issues, with the same numbers in both places.",
      icon: ClipboardCheck,
      points: [
        "Accept a suggested fix, write your own, or dispute one with a reason.",
        "Compare revisions and read the decision and approval history.",
        "Send it for review when nothing is left to fix.",
      ],
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base: what it checks against",
      body: "Rules, approved facts and preferred terms live here, each with a version and a reason for every change. Creators read it; reviewers and admins edit it.",
      icon: BookOpen,
      points: [
        "Search across rules, facts and terms before you write.",
        "See when a fact expired or a rule was replaced.",
        "Every finding cites the version it was checked against.",
      ],
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "Reports: how the brand is doing",
      body: "The numbers behind the review: what gets caught most, approval health and how much AI checking was used.",
      icon: BarChart3,
      points: [
        "What is caught most often, by category.",
        "How many drafts are waiting, approved or signed.",
        "Useful when a rule keeps firing on the same thing.",
      ],
      cta: { href: "/insights", label: "Open reports" },
    },
  ],
  reviewer: [
    {
      eyebrow: "Your windows",
      title: "The review queue",
      body: "Everything waiting for a decision is here. Reviewers get a queue, never a draft box.",
      icon: Inbox,
      points: [
        "Oldest waiting first, so nothing stalls.",
        "Risk and open-finding counts before you open a draft.",
        "Your own sent drafts are highlighted for you.",
      ],
      cta: { href: "/review", label: "Open the review queue" },
    },
    {
      eyebrow: "Your windows",
      title: "Deciding on a draft",
      body: "Open a draft and the content, the issues and the decision bar are on one page.",
      icon: ClipboardCheck,
      points: [
        "Approve and sign, or send back with a comment.",
        "Must-fix issues block approval unless you override each with a reason.",
        "Every decision is recorded for the signed proof.",
      ],
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base: the source of truth",
      body: "Reviewers can edit rules, facts and terms. Every change is a new version with a reason, and approved content is re-checked against it.",
      icon: BookOpen,
      points: [
        "Search and filter across all three kinds of knowledge.",
        "See which approved content a change would affect before you save.",
        "Retire an old fact without losing its history.",
      ],
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "Reports: what the checks add up to",
      body: "Approval health, common findings and AI usage for reviewers and admins, in one place.",
      icon: BarChart3,
      points: [
        "Which categories fire most, and on what.",
        "How long drafts wait before a decision.",
        "How many AI checks are left today.",
      ],
      cta: { href: "/insights", label: "Open reports" },
    },
  ],
  agency: [
    {
      eyebrow: "Your windows",
      title: "My work",
      body: "Only your agency's submissions appear here, never the client's other work.",
      icon: Building2,
      points: [
        "Fix these before they can move on, at the top.",
        "Everything your agency sent, with its stage.",
        "Confidential brand facts stay hidden from agency accounts.",
      ],
      cta: { href: "/agency", label: "Open my work" },
    },
    {
      eyebrow: "Your windows",
      title: "A draft page and client review",
      body: "Your upload opens as pages with every issue marked, then goes to the client's review queue.",
      icon: ClipboardCheck,
      points: [
        "PDF findings point to a page and line; Word to a section and paragraph.",
        "Fix a PDF or image in its source, then upload a new version.",
        "The client's reviewer approves or sends it back.",
      ],
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base",
      body: "Read the client's rules, preferred terms and approved facts, so you can get it right before uploading.",
      icon: BookOpen,
      points: [
        "The same rules the checks use, with their versions.",
        "Facts that are public are shown; confidential ones are not.",
        "Every finding cites the exact rule, term or fact.",
      ],
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
  ],
  admin: [
    {
      eyebrow: "Your windows",
      title: "Workspace overview",
      body: "The admin home: the whole workspace at a glance, with shortcuts into every admin window.",
      icon: LayoutDashboard,
      points: [
        "Approved rules, facts and terms in one summary.",
        "Review load: what is waiting on a person.",
        "Governance signals for rules that keep firing.",
      ],
      cta: { href: "/admin", label: "Open the overview" },
    },
    {
      eyebrow: "Your windows",
      title: "Review queue",
      body: "Admins can decide on any draft, exactly like a reviewer. Open one to approve, sign or send it back.",
      icon: Inbox,
      points: [
        "Everything waiting for a decision.",
        "Override a single finding with a reason.",
        "Approvals are signed and publicly verifiable.",
      ],
      cta: { href: "/review", label: "Open the review queue" },
    },
    {
      eyebrow: "Your windows",
      title: "Knowledge base: rules, facts and terms",
      body: "The source of truth every check runs against. Each change is a version with a reason, and you can preview its impact first.",
      icon: BookOpen,
      points: [
        "Add, edit, retire or restore any entry.",
        "Preview which approved content a change would break.",
        "Import a rulebook as drafts instead of in one shot.",
      ],
      cta: { href: "/kb", label: "Open the knowledge base" },
    },
    {
      eyebrow: "Your windows",
      title: "Reports",
      body: "Approval health, what gets caught most and how the AI quota is being used, across the workspace.",
      icon: BarChart3,
      points: [
        "Findings by category and by rule.",
        "How long drafts wait before a decision.",
        "AI checks used today, per person and for the workspace.",
      ],
      cta: { href: "/insights", label: "Open reports" },
    },
    {
      eyebrow: "Your windows",
      title: "API & webhooks",
      body: "Run checks from your own pipeline and hear about approvals automatically. Keys are shown once and can be revoked.",
      icon: KeyRound,
      points: [
        "Create an API key and send a draft for checking.",
        "Webhook endpoints with a delivery log and retries.",
        "Compliance packs for the rules a check used.",
      ],
      cta: { href: "/admin/api", label: "Open API & webhooks" },
    },
  ],
};

/** The write window is only offered to people who can actually author content. */
function stepsFor(role: Role): Step[] {
  const rest = CORE_STEPS.slice(1);
  const windows = ROLE_WINDOWS[role] ?? [];
  return role === "creator" || role === "agency"
    ? [CORE_STEPS[0], ...windows, ...rest]
    : [...windows, ...rest];
}

/**
 * A first-run tour of the review pipeline. It deliberately separates the
 * always-on rule checks from the AI-assisted ones, because a pending AI review
 * never means the draft went unchecked. The first step is interactive: it shows
 * the write window, including the file option, with a pointer on what to press.
 */
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
  const [mounted, setMounted] = useState(false);
  const [step, setStep] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const STEPS = stepsFor(role);

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

  if (!mounted || !open) return null;

  const current = STEPS[step];
  const Icon = current.icon;
  const last = step === STEPS.length - 1;

  return createPortal(
    <div
      className="fixed inset-0 z-[90] grid place-items-center overflow-y-auto bg-foreground/35 px-3 py-4 backdrop-blur-md sm:px-4"
      role="presentation"
    >
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        className="surface animate-fade-up my-auto max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto border-border-strong shadow-float outline-none"
      >
        <div className="flex items-start gap-3 border-b border-border bg-muted/60 px-5 py-4 sm:px-6">
          <BrandMark className="mt-0.5 size-9" />
          <div className="min-w-0">
            <p className="eyebrow">Quick tour · {ROLE_LABEL[role] ?? role}</p>
            <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
              Step {step + 1} of {STEPS.length}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost btn-sm ml-auto" aria-label="Skip tour">
            <X className="size-3.5" aria-hidden /> Skip tour
          </button>
        </div>

        {/* progress rail: also the step picker, so a returning visitor can jump */}
        <div className="flex gap-1 px-5 pt-4 sm:px-6" role="tablist" aria-label="Tour steps">
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

        <div className="p-5 sm:p-7">
          <div className="flex items-start gap-4">
            <span className="relative grid size-12 shrink-0 place-items-center rounded-2xl border border-border-strong bg-card text-brand shadow-sm">
              <span aria-hidden className="tour-halo absolute inset-0 rounded-2xl" />
              <Icon className="relative size-5" strokeWidth={1.8} aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="eyebrow">{current.eyebrow}</p>
              <h2 id="tour-title" className="mt-1 text-2xl font-bold tracking-tight text-foreground">
                {current.title}
              </h2>
            </div>
          </div>

          <p className="mt-4 text-sm leading-relaxed text-foreground-secondary">{current.body}</p>

          {current.demo === "write" && (
            <>
              <WriteWindowDemo />
              <div className="mt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Choose how to start
                </p>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <button
                    type="button"
                    onClick={onFinish}
                    className="flex flex-col items-start gap-1 rounded-xl border border-border-strong bg-card p-3 text-left transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
                  >
                    <PenLine className="size-4 text-brand" aria-hidden />
                    <span className="text-xs font-semibold text-foreground">Make a draft here</span>
                    <span className="text-[11px] leading-snug text-muted-foreground">
                      Use the paste box on this page.
                    </span>
                  </button>
                  <Link
                    href="/new"
                    onClick={onClose}
                    className="flex flex-col items-start gap-1 rounded-xl border border-border-strong bg-card p-3 text-left transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
                  >
                    <FileText className="size-4 text-brand" aria-hidden />
                    <span className="text-xs font-semibold text-foreground">Write window</span>
                    <span className="text-[11px] leading-snug text-muted-foreground">
                      Title, channel and a full text box.
                    </span>
                  </Link>
                  <Link
                    href="/new?mode=file"
                    onClick={onClose}
                    className="flex flex-col items-start gap-1 rounded-xl border border-brand/60 bg-brand/[0.05] p-3 text-left transition-all hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
                  >
                    <FileUp className="size-4 text-brand" aria-hidden />
                    <span className="text-xs font-semibold text-foreground">Upload a file</span>
                    <span className="text-[11px] leading-snug text-muted-foreground">
                      PDF, Word or image — the drop zone opens lit.
                    </span>
                  </Link>
                </div>
              </div>
            </>
          )}

          {current.compare ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-border-strong bg-card p-4">
                <div className="flex items-center gap-2">
                  <Search className="size-4 text-brand" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">Rule-based</span>
                </div>
                <p className="mt-2 text-sm font-semibold text-foreground">Always runs</p>
                <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-foreground-secondary">
                  {current.compare.rule.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-brand" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-border-strong bg-muted/50 p-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="size-4 text-brand" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">AI-assisted</span>
                </div>
                <p className="mt-2 text-sm font-semibold text-foreground">When available</p>
                <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-foreground-secondary">
                  {current.compare.ai.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-brand" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            current.points && (
              <ul className="mt-5 space-y-2.5 text-sm leading-relaxed text-foreground-secondary">
                {current.points.map((point) => (
                  <li key={point} className="flex gap-2.5">
                    <Check className="mt-0.5 size-4 shrink-0 text-brand" strokeWidth={2.2} aria-hidden />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            )
          )}

          {current.tip && (
            <p className="mt-4 rounded-xl border border-border bg-muted/50 px-3.5 py-3 text-xs leading-relaxed text-muted-foreground">
              {current.tip}
            </p>
          )}

          {current.cta && (
            <Link href={current.cta.href} onClick={onClose} className="btn btn-sm btn-secondary mt-4 w-fit">
              {current.cta.label} <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          )}
        </div>

        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 border-t border-border bg-card px-5 py-4 sm:px-6">
          <p className="text-xs tabular-nums text-muted-foreground">
            {step + 1} / {STEPS.length}
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
      className="mt-5 overflow-hidden rounded-2xl border border-border-strong bg-card shadow-card"
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

        <div className="relative mt-3 min-h-[156px]">
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
