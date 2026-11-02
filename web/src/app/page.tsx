"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, PenSquare, Wrench } from "lucide-react";
import { api, ApiError, type Submission } from "@/lib/api";
import { StatusBadge } from "@/components/fx";
import { AiLoadingScreen } from "@/components/ai-loading";
import { useIdentity } from "@/components/identity";
import { SAMPLE_DRAFT } from "@/components/start-here";
import { roleHome } from "@/lib/roles";

const DONE = ["Signed", "Approved", "Exempt-approved"];

/** The next thing to do with a draft, in words. */
function nextAction(s: Submission): { label: string; tone: "act" | "wait" | "done" } {
  if (DONE.includes(s.status)) return { label: "Approved", tone: "done" };
  if (s.status === "In review") return { label: "Waiting for a reviewer", tone: "wait" };
  const open = s.open_findings ?? 0;
  if (s.status === "Changes requested") return { label: "Reviewer asked for changes", tone: "act" };
  return open > 0 ? { label: `Fix ${open} issue${open === 1 ? "" : "s"}`, tone: "act" } : { label: "Send for review", tone: "act" };
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** A creator's home: their own drafts and the one next step on each. Nothing else. */
export default function HomePage() {
  const router = useRouter();
  const { me } = useIdentity();
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSubs((await api<{ submissions: Submission[] }>("/submissions")).submissions);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (me && me.role !== "creator") {
      router.replace(roleHome(me.role)); // every other role has its own home
      return;
    }
    void load();
  }, [load, me, router]);

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

  if (me && me.role !== "creator") {
    return <p className="text-sm text-muted-foreground" role="status">Opening your workspace…</p>;
  }

  const mine = (subs ?? []).filter((s) => !me || !s.created_by || s.created_by === me.email);
  const toFix = mine.filter((s) => nextAction(s).tone === "act");
  const waiting = mine.filter((s) => s.status === "In review");
  const approved = mine.filter((s) => DONE.includes(s.status));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">My work</h1>
          <p className="mt-1 text-foreground-secondary">Content you&apos;ve checked, and what each one needs next.</p>
        </div>
        <Link href="/new" className="btn btn-primary">
          <PenSquare className="size-4" aria-hidden /> New check
        </Link>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">
          {error}
        </p>
      )}

      {subs === null ? (
        <div className="grid gap-3 sm:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => <div key={i} className="surface h-24 animate-pulse" />)}
        </div>
      ) : mine.length === 0 ? (
        <section className="surface flex flex-col items-center px-6 py-14 text-center">
          <span className="grid size-14 place-items-center rounded-2xl bg-brand/10 text-brand">
            <PenSquare className="size-7" aria-hidden />
          </span>
          <h2 className="mt-5 text-xl font-bold tracking-tight">Nothing checked yet</h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-foreground-secondary">
            Canonry reads marketing content against Quillmark&apos;s brand rules and approved facts, and tells you what to
            fix. Try it on a sample post with a few planted mistakes.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            <button type="button" data-guide="check-sample" disabled={busy} onClick={() => void checkSample()} className="btn btn-primary">
              {busy ? "Checking…" : <>Check the sample <ArrowRight className="btn-arrow size-4" aria-hidden /></>}
            </button>
            <Link href="/new" className="btn btn-secondary">Write your own</Link>
          </div>
        </section>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Tile icon={<Wrench className="size-5" aria-hidden />} label="To fix" value={toFix.length} tone="act" />
            <Tile icon={<Clock3 className="size-5" aria-hidden />} label="Waiting for review" value={waiting.length} tone="wait" />
            <Tile icon={<CheckCircle2 className="size-5" aria-hidden />} label="Approved" value={approved.length} tone="done" />
          </div>

          <section aria-labelledby="drafts" className="surface overflow-hidden">
            <h2 id="drafts" className="sr-only">Your content</h2>
            <ul className="divide-y divide-border">
              {mine.map((s, i) => {
                const next = nextAction(s);
                return (
                  <li key={s.id}>
                    <Link
                      href={`/submissions/${s.id}`}
                      data-guide={i === 0 && next.tone === "act" ? "open-draft" : undefined}
                      className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 transition-colors hover:bg-muted/50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-foreground [overflow-wrap:anywhere]">{s.title}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          <span className="capitalize">{s.channel}</span> · {when(s.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={s.status} />
                      <span
                        className={`inline-flex items-center gap-1 text-sm font-semibold ${
                          next.tone === "act" ? "text-brand" : next.tone === "done" ? "text-success-fg" : "text-muted-foreground"
                        }`}
                      >
                        {next.label}
                        {next.tone === "act" && <ArrowRight className="size-4" aria-hidden />}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}

      <AiLoadingScreen open={busy} title="Checking the sample" />
    </div>
  );
}

function Tile({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: "act" | "wait" | "done" }) {
  const color = tone === "act" ? "text-brand bg-brand/10" : tone === "done" ? "text-success-fg bg-success-bg" : "text-foreground-secondary bg-muted";
  return (
    <div className="surface flex items-center gap-4 p-4">
      <span className={`grid size-10 place-items-center rounded-xl ${color}`}>{icon}</span>
      <div>
        <p className="text-2xl font-bold tabular-nums text-foreground">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}
