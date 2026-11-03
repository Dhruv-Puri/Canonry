/**
 * Pictures for the product tour: a friendly guide who explains each window in one plain sentence,
 * and a small drawing of the window itself, so no tour page is just a line of text.
 * Everything is drawn in code (no images to load) and is decorative: the words carry the meaning.
 */
import { ArrowRight, BadgeCheck, Building2, Lock, Send, ShieldCheck } from "lucide-react";

export type FigureKind = "home" | "kb" | "work" | "queue" | "insights" | "overview" | "api" | "agency";

/** The tour's guide: an original, kindly "uncle" character in Canonry's colours. */
export function GuideCharacter({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 72" className={className} aria-hidden>
      {/* top hat */}
      <rect x="18" y="2" width="28" height="18" rx="3" fill="#3b2618" />
      <rect x="18" y="13" width="28" height="4" fill="#c49a74" />
      <rect x="11" y="19" width="42" height="5" rx="2.5" fill="#3b2618" />
      {/* face */}
      <circle cx="32" cy="36" r="13" fill="#f3d9bd" stroke="#8b5e3c" strokeWidth="1.2" />
      {/* spectacles */}
      <circle cx="26.5" cy="34" r="3.6" fill="#fffefb" stroke="#3b2618" strokeWidth="1.3" />
      <circle cx="37.5" cy="34" r="3.6" fill="#fffefb" stroke="#3b2618" strokeWidth="1.3" />
      <line x1="30.1" y1="34" x2="33.9" y2="34" stroke="#3b2618" strokeWidth="1.3" />
      <circle cx="26.8" cy="34.4" r="1.2" fill="#3b2618" />
      <circle cx="37.8" cy="34.4" r="1.2" fill="#3b2618" />
      {/* moustache and smile */}
      <path d="M24 41.5c3-2.6 6.2-2.6 8 0 1.8-2.6 5-2.6 8 0-2.8 1.2-5.6 1-8-.4-2.4 1.4-5.2 1.6-8 .4z" fill="#fffefb" stroke="#8b5e3c" strokeWidth=".8" />
      <path d="M28.5 45.2c2.2 1.4 4.8 1.4 7 0" stroke="#8b5e3c" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      {/* coat and bow tie */}
      <path d="M14 72c1-12 8-18 18-18s17 6 18 18z" fill="#8b5e3c" />
      <path d="M27 56l5 4 5-4-1.5 6H28.5z" fill="#fffefb" />
      <path d="M28 59l4 2-4 2zM36 59l-4 2 4 2z" fill="#3b2618" />
      {/* pointer stick */}
      <line x1="50" y1="64" x2="62" y2="44" stroke="#3b2618" strokeWidth="2" strokeLinecap="round" />
      <circle cx="62" cy="44" r="1.8" fill="#c49a74" />
    </svg>
  );
}

/** The guide and a speech bubble with the one-sentence, plain-language explanation. */
export function GuideSays({ text }: { text: string }) {
  return (
    <div className="mt-3 flex items-end gap-2.5">
      <GuideCharacter className="h-16 w-14 shrink-0" />
      <p className="relative rounded-2xl rounded-bl-sm border border-border-strong bg-warning-bg/60 px-3.5 py-2.5 text-[13px] leading-relaxed text-foreground">
        {text}
      </p>
    </div>
  );
}

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div aria-hidden className="mt-3 overflow-hidden rounded-xl border border-border-strong bg-card shadow-card">
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
