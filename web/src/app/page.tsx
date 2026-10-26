"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  BadgeCheck,
  BookMarked,
  CalendarClock,
  Check,
  FileWarning,
  Gavel,
  Hash,
  Library,
  Megaphone,
  MessageSquareWarning,
  PenLine,
  ScrollText,
  Search,
  Stamp,
  Tag,
  Type,
} from "lucide-react";
import { api, CATEGORY_LABEL, type Submission, type User } from "@/lib/api";
import { RiskBadge, StatusBadge } from "@/components/fx";
import { EmptyIllustration } from "@/components/brand";
import { HeroDemo } from "@/components/hero-demo";
import { CountUp, Reveal } from "@/components/motion";
import { Tilt } from "@/components/effects";

type Workspace = {
  workspace: string;
  rules: number;
  facts: number;
  terms: number;
  vague_rules: { id: string; statement: string; vague_flag: string }[];
};

type Category = { category: string; c: number };

const STARTERS = [
  {
    icon: Megaphone,
    label: "Launch post with issues",
    channel: "social",
    text:
      "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by 5,000+ teams and " +
      "fully ISO 27001 certified. Plans start at just ₹999/month!",
  },
  {
    icon: ScrollText,
    label: "Clean pricing copy",
    channel: "web",
    text:
      "Quillmark Pulse 2.0 is an analytics platform trusted by 2,300+ teams. Plans start at " +
      "₹1,299/month. Start your free trial at quillmark.co/pulse.",
  },
] as const;

const STEPS = [
  { icon: PenLine, title: "Draft", text: "Write or paste the copy, from any team or agency." },
  { icon: Search, title: "Check", text: "Every claim, term and rule is matched to an approved source." },
  { icon: Gavel, title: "Decide", text: "A person accepts the fix, edits it, or disputes it." },
  { icon: Stamp, title: "Seal", text: "Approval is signed, so anyone can verify it later." },
] as const;

// What the checks catch, for the moving strip under the hero.
const CATCHES = [
  { icon: Tag, text: "Outdated product names" },
  { icon: BadgeCheck, text: "Unsupported “#1” claims" },
  { icon: Hash, text: "Numbers that contradict the facts" },
  { icon: CalendarClock, text: "Expired certifications" },
  { icon: FileWarning, text: "Missing disclaimers" },
  { icon: Tag, text: "Old pricing" },
  { icon: MessageSquareWarning, text: "Off-brand tone" },
  { icon: Type, text: "Banned words" },
  { icon: Megaphone, text: "No call to action" },
] as const;

const FLOW = ["Draft", "Checked", "In review", "Signed"] as const;

function flowIndex(status: string): number {
  if (status === "Signed" || status === "Approved" || status === "Exempt-approved") return 3;
  if (status === "In review") return 2;
  if (status === "Checked" || status === "Changes requested") return 1;
  return 0;
}

const CHANNELS = ["social", "web", "blog", "email", "sales"];
const HEADLINE = ["Every", "word,"];
const HEADLINE_INK = ["on", "brand."];

export default function HomePage() {
  const router = useRouter();
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [cats, setCats] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [channel, setChannel] = useState("social");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, w, m] = await Promise.all([
        api<{ submissions: Submission[] }>("/submissions"),
        api<Workspace>("/workspace"),
        api<User>("/me"),
      ]);
      setSubs(s.submissions);
      setWs(w);
      setMe(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    try {
      setCats((await api<{ categories: Category[] }>("/insights")).categories.slice(0, 5));
    } catch {
      setCats([]); // the chart is a nice-to-have; the page works without it
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function check() {
    const content = draft.trim();
    if (!content) return;
    setBusy(true);
    setError(null);
    try {
      const words = content.replace(/\s+/g, " ").split(" ");
      const title = words.slice(0, 6).join(" ") + (words.length > 6 ? "…" : "");
      const r = await api<{ submission_id: string }>("/submissions", {
        method: "POST",
        json: { title, channel, source_type: me?.role === "agency" ? "agency" : "in-house", content },
      });
      router.push(`/submissions/${r.submission_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const firstName = me ? me.name.split(" ")[0] : null;
  const awaiting = subs?.filter((s) => s.status === "In review").length ?? 0;
  const signed = subs?.filter((s) => flowIndex(s.status) === 3).length ?? 0;
  const catMax = Math.max(1, ...cats.map((c) => c.c));

  return (
    <div className="space-y-28">
      {/* ---------------- hero ---------------- */}
      <section className="relative grid items-center gap-14 pt-6 lg:grid-cols-[1.05fr_1fr]">
        <div aria-hidden className="pointer-events-none absolute -inset-x-40 -top-40 bottom-0 -z-10">
          <div className="aurora left-[2%] top-[8%] size-[420px] bg-[#f7e2b5]" />
          <div className="aurora right-[4%] top-[20%] size-[380px] bg-[#f3cfb4]" style={{ animationDelay: "-6s" }} />
          <div className="aurora left-[35%] top-[45%] size-[340px] bg-[#e9d9c0]" style={{ animationDelay: "-11s" }} />
        </div>

        <div>
          <p className="animate-rise inline-flex items-center gap-2 rounded-full border border-border-strong bg-card/80 py-1 pl-1 pr-3 text-[13px] font-medium text-foreground-secondary shadow-sm backdrop-blur">
            <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] font-semibold text-primary-foreground">New</span>
            {firstName ? `Hi ${firstName}, ` : ""}brand review for Quillmark
          </p>
          <h1 className="display mt-6" aria-label="Every word, on brand.">
            <span aria-hidden>
              {HEADLINE.map((w, i) => (
                <span key={w} className="word mr-[0.22em]" style={{ "--i": i } as React.CSSProperties}>
                  {w}
                </span>
              ))}
              <br />
              {HEADLINE_INK.map((w, i) => (
                // Reveal and shimmer are separate animations, so they live on separate spans.
                <span key={w} className="word mr-[0.22em]" style={{ "--i": i + HEADLINE.length } as React.CSSProperties}>
                  <span className="ink-gradient ink-shimmer pb-[0.08em]">{w}</span>
                </span>
              ))}
            </span>
          </h1>
          <p
            className="animate-rise mt-6 max-w-md text-lg leading-relaxed text-foreground-secondary"
            style={{ "--rise-delay": "420ms" } as React.CSSProperties}
          >
            Canonry reads your draft against Quillmark’s approved rules, terms and facts, points to the source of
            every issue, and leaves the decision with you.
          </p>
          <div className="animate-rise mt-8 flex flex-wrap gap-3" style={{ "--rise-delay": "520ms" } as React.CSSProperties}>
            <a href="#check" className="btn btn-primary btn-lg shadow-card">
              Check a draft <span aria-hidden className="btn-arrow">→</span>
            </a>
            <a href="#how" className="btn btn-secondary btn-lg">
              How it works
            </a>
          </div>
          <ul
            className="animate-rise mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm text-foreground-secondary"
            style={{ "--rise-delay": "620ms" } as React.CSSProperties}
          >
            {["Every issue cites its source", "A person makes the call", "Approvals are signed"].map((t) => (
              <li key={t} className="inline-flex items-center gap-1.5">
                <span className="grid size-4 place-items-center rounded-full bg-success-bg text-success-fg">
                  <Check className="size-2.5" strokeWidth={3.5} />
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>

        <div className="animate-rise" style={{ "--rise-delay": "300ms" } as React.CSSProperties}>
          <Tilt>
            <HeroDemo />
          </Tilt>
        </div>
      </section>

      {/* ---------------- what it catches ---------------- */}
      <section aria-label="What Canonry catches" className="-mt-10">
        <p className="mb-4 text-center text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          What it catches before you publish
        </p>
        <div className="marquee overflow-hidden">
          <ul className="marquee-track gap-3 py-1">
            {[...CATCHES, ...CATCHES].map(({ icon: Icon, text }, i) => (
              <li
                key={i}
                aria-hidden={i >= CATCHES.length}
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm font-medium text-foreground-secondary shadow-sm"
              >
                <Icon className="size-4 text-brand" strokeWidth={2} />
                {text}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ---------------- quick check ---------------- */}
      <Reveal as="section">
        <div
          id="check"
          className="relative scroll-mt-28 overflow-hidden rounded-[36px] border border-border bg-gradient-to-b from-muted via-background to-background p-6 sm:p-12"
        >
          <div aria-hidden className="dot-grid pointer-events-none absolute inset-0 opacity-50 [mask-image:radial-gradient(ellipse_at_top,#000_20%,transparent_70%)]" />
          <div className="relative mx-auto max-w-3xl">
            <h2 className="text-center text-4xl font-bold tracking-tight sm:text-5xl">
              Paste it. <span className="ink-gradient">Check it.</span>
            </h2>
            <p className="mt-3 text-center text-lg text-foreground-secondary">
              Results in a second, every issue with its source.
            </p>

            <form
              className="paper mt-10"
              onSubmit={(e) => {
                e.preventDefault();
                void check();
              }}
            >
              <label htmlFor="composer" className="sr-only">
                Draft to check
              </label>
              <textarea
                id="composer"
                rows={4}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void check();
                }}
                placeholder="Start writing, or paste a post…"
                className="block w-full resize-none bg-transparent pb-2 pl-14 pr-5 pt-[14px] font-serif text-[17px] leading-[28px] text-foreground outline-none"
              />
              <div className="flex flex-wrap items-center gap-2 rounded-b-[17px] border-t border-border bg-muted/60 py-3 pl-14 pr-3">
                <label className="sr-only" htmlFor="composer-channel">
                  Channel
                </label>
                <select
                  id="composer-channel"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                  className="h-9 cursor-pointer rounded-full border border-border-strong bg-card px-3 text-xs font-medium capitalize text-foreground-secondary"
                >
                  {CHANNELS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <span className="hidden text-xs text-muted-foreground sm:inline">Ctrl + Enter</span>
                <button type="submit" disabled={busy || !draft.trim()} className="btn btn-primary ml-auto">
                  {busy ? "Checking…" : <>Check draft <span aria-hidden className="btn-arrow">→</span></>}
                </button>
              </div>
            </form>

            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              {STARTERS.map(({ icon: Icon, label, text, channel: c }) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    setDraft(text);
                    setChannel(c);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-card px-3.5 py-1.5 text-[13px] font-medium text-foreground-secondary transition-all hover:-translate-y-0.5 hover:border-brand-highlight hover:text-foreground hover:shadow-card"
                >
                  <Icon className="size-3.5" strokeWidth={2} />
                  {label}
                </button>
              ))}
            </div>
            {error && (
              <p className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg" role="alert">
                {error}
              </p>
            )}
          </div>
        </div>
      </Reveal>

      {/* ---------------- bento: chart + numbers ---------------- */}
      {ws && (
        <section className="space-y-6">
          <Reveal>
            <p className="eyebrow">At a glance</p>
            <h2 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">The workspace, in numbers.</h2>
          </Reveal>
          <div className="grid gap-4 lg:grid-cols-4">
            <Reveal className="lg:col-span-2 lg:row-span-2">
              <div className="surface h-full p-7">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-foreground">What gets caught most</p>
                  <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">All checks</span>
                </div>
                {cats.length === 0 ? (
                  <p className="mt-10 text-sm text-muted-foreground">Run a check to see this fill in.</p>
                ) : (
                  <ul className="mt-7 space-y-5">
                    {cats.map((c, i) => (
                      <li key={c.category}>
                        <div className="flex items-baseline justify-between text-sm">
                          <span className="font-medium text-foreground">
                            {CATEGORY_LABEL[c.category] ?? c.category.replace(/_/g, " ")}
                          </span>
                          <span className="tabular-nums text-muted-foreground">{c.c}</span>
                        </div>
                        <div className="mt-2 h-3 overflow-hidden rounded-full bg-muted">
                          <div
                            className="bar h-full rounded-full bg-gradient-to-r from-brand-highlight to-brand"
                            style={{ width: `${(c.c / catMax) * 100}%`, "--i": i } as React.CSSProperties}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Reveal>
            {[
              { icon: BookMarked, value: ws.rules, label: "Approved rules" },
              { icon: Library, value: ws.facts, label: "Facts on file" },
              { icon: Gavel, value: awaiting, label: "Awaiting review" },
              { icon: Stamp, value: signed, label: "Signed & sealed" },
            ].map(({ icon: Icon, value, label }, i) => (
              <Reveal key={label} delay={i * 90}>
                <div className="surface h-full p-6">
                  <span className="grid size-11 place-items-center rounded-2xl bg-gradient-to-br from-highlight to-brand-highlight/50 text-primary">
                    <Icon className="size-5" strokeWidth={2} />
                  </span>
                  <p className="mt-5 text-5xl font-bold tracking-tight text-foreground">
                    <CountUp value={value} />
                  </p>
                  <p className="mt-1 font-semibold text-foreground">{label}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>
      )}

      {/* ---------------- submissions ---------------- */}
      <section className="space-y-6">
        <Reveal className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">Your submissions</h2>
          </div>
          <Link href="/new" className="btn btn-secondary">
            New draft <span aria-hidden className="btn-arrow">→</span>
          </Link>
        </Reveal>

        {subs === null && !error && <p className="text-sm text-muted-foreground">Loading submissions…</p>}

        {subs && subs.length === 0 && (
          <div className="surface flex flex-col items-center gap-3 px-6 py-14 text-center">
            <EmptyIllustration />
            <p className="text-xl font-bold text-foreground">Nothing submitted yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Try the launch post above. Findings come back with citations, and you decide what to change.
            </p>
          </div>
        )}

        {subs && subs.length > 0 && (
          <ul className="grid gap-4 md:grid-cols-2">
            {subs.map((s, i) => {
              const step = flowIndex(s.status);
              return (
                <Reveal as="li" key={s.id} delay={(i % 2) * 90}>
                  <Link
                    href={`/submissions/${s.id}`}
                    className="surface surface-interactive group flex h-full flex-col p-6"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={s.status} />
                      <RiskBadge risk={s.risk} />
                      <span className="ml-auto text-xs capitalize text-muted-foreground">{s.channel}</span>
                    </div>
                    <p className="mt-4 text-lg font-bold tracking-tight text-foreground">{s.title}</p>
                    <p className="mt-1.5 line-clamp-2 font-serif text-[15px] leading-relaxed text-foreground-secondary">
                      {s.content}
                    </p>

                    {/* where it is in the journey */}
                    <div className="mt-5" aria-label={`Stage: ${FLOW[step]}`}>
                      <div className="flex gap-1.5">
                        {FLOW.map((f, j) => (
                          <span
                            key={f}
                            className={`h-1.5 flex-1 rounded-full ${j <= step ? "bg-gradient-to-r from-brand-highlight to-brand" : "bg-muted"}`}
                          />
                        ))}
                      </div>
                      <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground">
                        {FLOW.map((f, j) => (
                          <span key={f} className={j === step ? "font-semibold text-foreground" : ""}>
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="mt-auto flex items-end justify-between pt-5">
                      <p className="text-sm text-muted-foreground">
                        <span className="text-2xl font-bold tabular-nums text-foreground">{s.open_findings ?? 0}</span> open
                        finding{(s.open_findings ?? 0) === 1 ? "" : "s"}
                      </p>
                      <span className="grid size-9 place-items-center rounded-full bg-muted text-foreground transition-all duration-300 group-hover:rotate-[-45deg] group-hover:bg-primary group-hover:text-primary-foreground">
                        <ArrowRight className="size-4" />
                      </span>
                    </div>
                  </Link>
                </Reveal>
              );
            })}
          </ul>
        )}

        {ws && ws.vague_rules.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {ws.vague_rules.length} rule(s) may be unclear.{" "}
            <Link href="/insights" className="link">
              See Insights
            </Link>
          </p>
        )}
      </section>

      {/* ---------------- how it works ---------------- */}
      <section id="how" className="scroll-mt-28">
        <Reveal className="text-center">
          <p className="eyebrow">How it works</p>
          <h2 className="mx-auto mt-2 max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
            From draft to <span className="ink-gradient">signed</span> in four steps.
          </h2>
        </Reveal>
        <div className="relative mt-14">
          <div aria-hidden className="absolute left-[12%] right-[12%] top-8 hidden h-px bg-gradient-to-r from-transparent via-border-strong to-transparent md:block" />
          <ol className="relative grid gap-6 md:grid-cols-4">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <Reveal as="li" key={title} delay={i * 120} className="relative text-center">
                <span className="relative mx-auto grid size-16 place-items-center rounded-full border border-border-strong bg-card text-brand shadow-card transition-transform duration-500 hover:-translate-y-1 hover:rotate-6">
                  <Icon className="size-6" strokeWidth={1.75} />
                  <span className="absolute -right-1 -top-1 grid size-6 place-items-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
                    {i + 1}
                  </span>
                </span>
                <p className="mt-5 text-lg font-bold text-foreground">{title}</p>
                <p className="mx-auto mt-1 max-w-[220px] text-sm text-muted-foreground">{text}</p>
              </Reveal>
            ))}
          </ol>
        </div>
        <Reveal className="mt-16 text-center">
          <a href="#check" className="btn btn-primary btn-lg shadow-card">
            Try it on your own copy <span aria-hidden className="btn-arrow">→</span>
          </a>
        </Reveal>
      </section>
    </div>
  );
}
