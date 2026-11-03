"use client";

/**
 * Pictures for the product tour: a friendly guide who explains each window in one plain sentence,
 * and a small drawing of the window itself, so no tour page is just a line of text.
 * Everything is drawn in code (no images to load) and is decorative: the words carry the meaning.
 */
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BadgeCheck, Building2, Lock, Send, ShieldCheck } from "lucide-react";

export type FigureKind = "home" | "kb" | "work" | "queue" | "insights" | "overview" | "api" | "agency";

const TIPS = [
  "Tip: the arrow keys move through the tour, and Esc closes it.",
  "Tip: every finding names the rule or fact behind it, so you can check my work.",
  "Tip: you can reopen this tour any time from the home page.",
  "Tip: you decide. I only point things out.",
];

/**
 * The tour's guide: an original, kindly "uncle" character in Canonry's colours. He breathes,
 * blinks and waves his pointer; hovering makes him tip his hat, and clicking makes him wave.
 * All motion stops when the visitor prefers reduced motion.
 */
export function GuideCharacter({ className = "", waving = false }: { className?: string; waving?: boolean }) {
  return (
    <svg viewBox="0 0 80 96" className={`guide-char ${waving ? "is-waving" : ""} ${className}`} aria-hidden>
      <defs>
        <radialGradient id="gc-face" cx="45%" cy="40%" r="65%">
          <stop offset="0%" stopColor="#fbe6cf" />
          <stop offset="100%" stopColor="#ecc9a4" />
        </radialGradient>
        <linearGradient id="gc-coat" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#9a6a45" />
          <stop offset="100%" stopColor="#6b4428" />
        </linearGradient>
        <linearGradient id="gc-hat" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#2b1d14" />
          <stop offset="55%" stopColor="#4a3020" />
          <stop offset="100%" stopColor="#2b1d14" />
        </linearGradient>
      </defs>
      <ellipse cx="40" cy="93" rx="22" ry="2.6" fill="#3b2618" opacity=".12" className="gc-shadow" />
      <g className="gc-body">
        <path d="M17 94c1.5-15 10-23 23-23s21.5 8 23 23z" fill="url(#gc-coat)" />
        <path d="M33 72l7 10 7-10-3 22h-8z" fill="#fffaf2" />
        <path d="M33 72l7 10-5 2-4-11z M47 72l-7 10 5 2 4-11z" fill="#7a5034" />
        <circle cx="40" cy="87" r="1" fill="#3b2618" />
        <circle cx="40" cy="91" r="1" fill="#3b2618" />
        <path d="M35.5 77.5l4.5 2.3-4.5 2.3zM44.5 77.5L40 79.8l4.5 2.3z" fill="#b5651d" />
        <rect x="35" y="64" width="10" height="8" rx="3" fill="#ecc9a4" />
        <g className="gc-head">
          <circle cx="23.5" cy="49" r="3.4" fill="#ecc9a4" />
          <circle cx="56.5" cy="49" r="3.4" fill="#ecc9a4" />
          <ellipse cx="40" cy="48" rx="16" ry="17" fill="url(#gc-face)" />
          <path d="M25 52c1 11 7 17 15 17s14-6 15-17c-3 4-6 5-8 4-2 3-5 3-7 3s-5 0-7-3c-2 1-5 0-8-4z" fill="#fbf8f2" stroke="#e2d6c4" strokeWidth=".6" />
          <circle cx="29" cy="52" r="2.6" fill="#e8a38a" opacity=".45" />
          <circle cx="51" cy="52" r="2.6" fill="#e8a38a" opacity=".45" />
          <path d="M28 40.5q4-2.4 8 0M44 40.5q4-2.4 8 0" stroke="#d9cbb7" strokeWidth="1.6" fill="none" strokeLinecap="round" className="gc-brows" />
          <g className="gc-eyes">
            <circle cx="33" cy="46" r="1.6" fill="#2b1d14" />
            <circle cx="47" cy="46" r="1.6" fill="#2b1d14" />
            <circle cx="33.5" cy="45.4" r=".5" fill="#fff" />
            <circle cx="47.5" cy="45.4" r=".5" fill="#fff" />
          </g>
          <circle cx="33" cy="46" r="4.6" fill="#ffffff" fillOpacity=".25" stroke="#3b2618" strokeWidth="1.2" />
          <circle cx="47" cy="46" r="4.6" fill="#ffffff" fillOpacity=".25" stroke="#3b2618" strokeWidth="1.2" />
          <path d="M37.6 46h4.8" stroke="#3b2618" strokeWidth="1.2" />
          <path d="M31 54.5c3.5-3 7-3 9 0 2-3 5.5-3 9 0-3 1.6-6.4 1.3-9-.4-2.6 1.7-6 2-9 .4z" fill="#fbf8f2" stroke="#d9cbb7" strokeWidth=".6" />
          <path d="M36 58.2q4 2.6 8 0" stroke="#8b5e3c" strokeWidth="1.2" fill="none" strokeLinecap="round" />
          <g className="gc-hat">
            <rect x="26" y="12" width="28" height="22" rx="3" fill="url(#gc-hat)" />
            <rect x="26" y="27" width="28" height="4.5" fill="#b5651d" />
            <rect x="19" y="32" width="42" height="5" rx="2.5" fill="#2b1d14" />
          </g>
        </g>
        <g className="gc-arm">
          <path d="M58 78c5-2 9-6 11-11" stroke="url(#gc-coat)" strokeWidth="7" strokeLinecap="round" fill="none" />
          <circle cx="69.5" cy="66" r="3.4" fill="#ecc9a4" />
          <line x1="70" y1="66" x2="78" y2="44" stroke="#3b2618" strokeWidth="2" strokeLinecap="round" />
          <circle cx="78" cy="44" r="2" fill="#b5651d" />
        </g>
      </g>
    </svg>
  );
}

/** The guide's line fades in word by word (smoothly); click the bubble to show it at once, click him for a tip. */
export function GuideSays({ text }: { text: string }) {
  const [instant, setInstant] = useState(false);
  const [waving, setWaving] = useState(false);
  const [tip, setTip] = useState<string | null>(null);
  const words = useMemo(() => text.split(" "), [text]);

  useEffect(() => {
    setTip(null);
    setInstant(false);
  }, [text]);

  function poke() {
    setWaving(true);
    setInstant(true);
    setTip((cur) => TIPS[(TIPS.indexOf(cur ?? "") + 1) % TIPS.length]);
    window.setTimeout(() => setWaving(false), 1200);
  }

  return (
    <div className="mt-4 flex items-end gap-3">
      <button
        type="button"
        onClick={poke}
        className="guide-char-btn shrink-0 rounded-2xl"
        aria-label="Ask the guide for a tip"
        title="Click me for a tip"
      >
        <GuideCharacter className="h-[88px] w-[74px]" waving={waving} />
      </button>
      <div className="min-w-0 flex-1">
        <p
          onClick={() => setInstant(true)}
          className="tutorial-text relative rounded-2xl rounded-bl-sm border border-border-strong bg-card px-4 py-3 text-foreground shadow-sm"
        >
          <span className="sr-only">{text}</span>
          <span aria-hidden key={text} className={instant ? "guide-words is-instant" : "guide-words"}>
            {words.map((w, i) => (
              <span key={i} className="guide-word" style={{ animationDelay: `${i * 70}ms` }}>
                {w}{" "}
              </span>
            ))}
          </span>
        </p>
        {tip && (
          <p role="status" className="animate-fade-up mt-1.5 text-xs text-muted-foreground">
            {tip}
          </p>
        )}
      </div>
    </div>
  );
}

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div aria-hidden className="mt-4 overflow-hidden rounded-xl border border-border-strong bg-card shadow-card">
      <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-3 py-1.5">
        <span className="flex gap-1">
          <span className="size-1.5 rounded-full bg-border-strong" />
          <span className="size-1.5 rounded-full bg-border-strong" />
          <span className="size-1.5 rounded-full bg-border-strong" />
        </span>
        <p className="truncate text-[10.5px] font-medium text-muted-foreground">{title}</p>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

function Tile({ n, label, tone = "" }: { n: string; label: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-background px-2.5 py-1.5">
      <p className={`text-base font-bold tabular-nums ${tone || "text-foreground"}`}>{n}</p>
      <p className="text-[10px] text-muted-foreground">{label}</p>
    </div>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "danger" | "warning" | "success" | "neutral" }) {
  const cls = {
    danger: "bg-danger-bg text-danger-fg",
    warning: "bg-warning-bg text-warning-fg",
    success: "bg-success-bg text-success-fg",
    neutral: "bg-muted text-foreground-secondary",
  }[tone];
  return <span className={`rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold ${cls}`}>{children}</span>;
}

function Row({ title, badges, right }: { title: string; badges: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5">
      <span className="flex shrink-0 gap-1">{badges}</span>
      <span className="min-w-0 flex-1 truncate text-[11.5px] font-semibold text-foreground">{title}</span>
      {right}
    </div>
  );
}

/** A small drawing of the window a tour page is about. */
export function WindowFigure({ kind }: { kind: FigureKind }) {
  switch (kind) {
    case "home":
      return (
        <Frame title="Home · your desk">
          <div className="grid grid-cols-3 gap-1.5">
            <Tile n="2" label="Need your fix" tone="text-danger-fg" />
            <Tile n="1" label="With a reviewer" />
            <Tile n="3" label="Approved" tone="text-success-fg" />
          </div>
          <div className="mt-2 space-y-1.5">
            <Row title="Launch post — Pulse 2.0" badges={<Badge tone="warning">4 to fix</Badge>} right={<span className="text-[10px] font-semibold text-brand">Fix →</span>} />
            <Row title="Webinar invite" badges={<Badge tone="success">Approved</Badge>} />
          </div>
        </Frame>
      );
    case "kb":
      return (
        <Frame title="Knowledge base · the brand's rulebook">
          <div className="grid gap-1.5 sm:grid-cols-3">
            <div className="rounded-lg border border-border bg-background p-2">
              <p className="text-[9.5px] font-semibold uppercase text-brand">Rule</p>
              <p className="mt-0.5 text-[11px] leading-snug text-foreground">No “#1” without a source.</p>
            </div>
            <div className="rounded-lg border border-border bg-background p-2">
              <p className="text-[9.5px] font-semibold uppercase text-brand">Fact</p>
              <p className="mt-0.5 text-[11px] leading-snug text-foreground">Trusted by 2,300+ teams</p>
              <p className="text-[9.5px] text-muted-foreground">approved until Mar 2027</p>
            </div>
            <div className="rounded-lg border border-border bg-background p-2">
              <p className="text-[9.5px] font-semibold uppercase text-brand">Term</p>
              <p className="mt-0.5 text-[11px] leading-snug text-foreground">
                <s className="text-danger-fg">Insights</s> → <b>Pulse</b>
              </p>
            </div>
          </div>
          <p className="mt-2 text-[10.5px] text-muted-foreground">Every check reads from here; every change is saved as a version.</p>
        </Frame>
      );
    case "work":
      return (
        <Frame title="My work · where each draft stands">
          <div className="grid grid-cols-3 gap-1.5 text-[10px]">
            {[
              { h: "Sent back", t: "Launch post", tone: "warning" as const, note: "“Add the trial link.”" },
              { h: "With a reviewer", t: "Webinar invite", tone: "neutral" as const },
              { h: "Approved", t: "Partner email", tone: "success" as const },
            ].map((c) => (
              <div key={c.h} className="rounded-lg border border-border bg-background p-1.5">
                <p className="font-semibold text-muted-foreground">{c.h}</p>
                <div className="mt-1 rounded-md border border-border bg-card p-1.5">
                  <Badge tone={c.tone}>{c.h === "Approved" ? "Signed" : c.h === "Sent back" ? "Changes" : "In review"}</Badge>
                  <p className="mt-1 truncate text-[11px] font-semibold text-foreground">{c.t}</p>
                  {c.note && <p className="mt-0.5 rounded bg-warning-bg px-1 text-[10px] text-warning-fg">{c.note}</p>}
                </div>
              </div>
            ))}
          </div>
        </Frame>
      );
    case "queue":
      return (
        <Frame title="Review queue · waiting on a person">
          <div className="space-y-1.5">
            <Row title="Diwali offer" badges={<Badge tone="danger">High risk</Badge>} right={<span className="text-[10px] font-semibold text-brand">Review →</span>} />
            <Row title="Launch post — Pulse 2.0" badges={<Badge tone="warning">Medium</Badge>} right={<span className="text-[10px] font-semibold text-brand">Review →</span>} />
            <Row title="Partner newsletter" badges={<Badge tone="success">Low risk</Badge>} right={<span className="text-[10px] font-semibold text-brand">Review →</span>} />
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
            <BadgeCheck className="size-3.5 text-success-fg" /> Approve &amp; sign, or send back with a note.
          </div>
        </Frame>
      );
    case "insights":
      return (
        <Frame title="Insights · the brand's report card">
          <div className="space-y-1.5">
            {[
              ["Unsupported claim", 92],
              ["Outdated claim", 70],
              ["Tone", 48],
              ["Banned word", 26],
            ].map(([label, w]) => (
              <div key={label as string} className="flex items-center gap-2 text-[10.5px]">
                <span className="w-28 shrink-0 text-foreground-secondary">{label}</span>
                <span className="h-2 rounded-full bg-brand/70" style={{ width: `${w}%` }} />
              </div>
            ))}
          </div>
          <p className="mt-2 text-[10.5px] text-muted-foreground">Plus: rules people dispute most, and claims with no fact behind them.</p>
        </Frame>
      );
    case "overview":
      return (
        <Frame title="Overview · the control room">
          <div className="grid grid-cols-4 gap-1.5">
            <Tile n="4" label="Waiting" />
            <Tile n="1" label="High risk" tone="text-danger-fg" />
            <Tile n="48" label="Rules" />
            <Tile n="36" label="Facts" />
          </div>
          <div className="mt-2 space-y-1">
            <p className="flex justify-between rounded-md bg-background px-2 py-1 text-[10.5px] text-foreground-secondary">Rules flagged unclear <b className="text-foreground">4</b></p>
            <p className="flex justify-between rounded-md bg-background px-2 py-1 text-[10.5px] text-foreground-secondary">Facts past expiry <b className="text-foreground">5</b></p>
          </div>
        </Frame>
      );
    case "api":
      return (
        <Frame title="API & webhooks · the publishing gate">
          <div className="flex items-center justify-between gap-1 text-center text-[10px]">
            {[
              { icon: Send, t: "Your website sends the post" },
              { icon: ShieldCheck, t: "Canonry checks; a person approves" },
              { icon: BadgeCheck, t: "A signed “approved” note comes back" },
            ].map(({ icon: Ico, t }, i) => (
              <div key={t} className="flex flex-1 items-center gap-1">
                <div className="flex-1 rounded-lg border border-border bg-background px-1.5 py-2">
                  <Ico className="mx-auto size-4 text-brand" />
                  <p className="mt-1 leading-tight text-foreground-secondary">{t}</p>
                </div>
                {i < 2 && <ArrowRight className="size-3.5 shrink-0 text-brand" />}
              </div>
            ))}
          </div>
          <p className="mt-2 text-center text-[10.5px] font-semibold text-success-fg">Only then is it published.</p>
        </Frame>
      );
    case "agency":
      return (
        <Frame title="My work · your agency only">
          <div className="space-y-1.5">
            <Row title="Festive banner (your agency)" badges={<Badge tone="warning">2 to fix</Badge>} />
            <Row title="Product video script (your agency)" badges={<Badge tone="success">Approved</Badge>} />
            <div className="flex items-center gap-2 rounded-lg border border-dashed border-border-strong px-2.5 py-1.5 text-[10.5px] text-muted-foreground">
              <Lock className="size-3.5" /> Other teams’ drafts and confidential facts stay hidden
            </div>
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
            <Building2 className="size-3.5" /> You see only what your agency sent.
          </div>
        </Frame>
      );
  }
}
