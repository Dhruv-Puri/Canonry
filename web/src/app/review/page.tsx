"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, BookMarked, LineChart, ShieldCheck } from "lucide-react";
import { api, type Submission } from "@/lib/api";
import { EmptyIllustration } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { Reveal } from "@/components/motion";
import { SubmissionCard } from "@/components/submission-card";
import { canReview } from "@/lib/roles";

type Filter = "queue" | "changes" | "signed" | "all";

const FILTERS: { id: Filter; label: string; match: string | null }[] = [
  { id: "queue", label: "Waiting on you", match: "In review" },
  { id: "changes", label: "Changes requested", match: "Changes requested" },
  { id: "signed", label: "Signed", match: "Signed" },
  { id: "all", label: "All", match: null },
];

export default function ReviewQueuePage() {
  const { me } = useIdentity();
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("queue");

  const load = useCallback(async () => {
    try {
      setSubs((await api<{ submissions: Submission[] }>("/submissions")).submissions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (canReview(me?.role)) void load();
  }, [load, me?.role]);

  const counts = useMemo(() => {
    const all = subs ?? [];
    return {
      queue: all.filter((s) => s.status === "In review").length,
      high: all.filter((s) => s.status === "In review" && s.risk === "high").length,
      changes: all.filter((s) => s.status === "Changes requested").length,
      signed: all.filter((s) => s.status === "Signed").length,
    };
  }, [subs]);

  const visible = useMemo(() => {
    if (!subs) return [];
    const match = FILTERS.find((f) => f.id === filter)?.match;
    return match ? subs.filter((s) => s.status === match) : subs;
  }, [filter, subs]);

  if (!canReview(me?.role)) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
          <ShieldCheck className="size-6" aria-hidden />
        </span>
        <p className="eyebrow mt-5">Reviewer workspace</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">Reviews stay with reviewers</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          The review queue is for reviewers and brand admins. Your workspace is where you check and submit drafts.
        </p>
        <Link href="/" className="btn btn-primary mt-6">
          Go to your workspace <ArrowRight className="size-4" aria-hidden />
        </Link>
      </section>
    );
  }

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Review workspace</p>
          <h1 className="page-title mt-1.5">Review queue</h1>
          <p className="page-lede max-w-2xl">
            Submissions waiting on a person. Open one to read the cited findings, override with a reason, approve and
            sign, or send it back with changes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/kb" className="btn btn-secondary">
            <BookMarked className="size-4" aria-hidden /> Knowledge base
          </Link>
          <Link href="/insights" className="btn btn-secondary">
            <LineChart className="size-4" aria-hidden /> Insights
          </Link>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}

      <div className="surface grid grid-cols-2 divide-x divide-y divide-border overflow-hidden sm:grid-cols-4 sm:divide-y-0">
        <Stat label="Waiting on you" value={counts.queue} />
        <Stat label="High risk" value={counts.high} tone={counts.high > 0 ? "danger" : "normal"} />
        <Stat label="Changes requested" value={counts.changes} />
        <Stat label="Signed" value={counts.signed} />
      </div>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter the review queue">
        {FILTERS.map((f) => {
          const active = filter === f.id;
          const count = f.id === "all" ? subs?.length ?? 0 : counts[f.id];
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              aria-pressed={active}
              className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
            >
              {f.label} <span className="tabular-nums opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {!subs && !error && <p className="text-sm text-muted-foreground">Loading the queue…</p>}

      {subs && visible.length === 0 && (
        <div className="surface flex flex-col items-center gap-3 px-6 py-14 text-center">
          <EmptyIllustration />
          <p className="text-xl font-bold text-foreground">
            {filter === "queue" ? "The queue is clear" : "Nothing in this view"}
          </p>
          <p className="max-w-sm text-sm text-muted-foreground">
            {filter === "queue"
              ? "No submission is waiting for a reviewer decision right now."
              : "Try another filter, or check the knowledge base for anything that needs updating."}
          </p>
        </div>
      )}

      {subs && visible.length > 0 && (
        <ul className="grid gap-4 md:grid-cols-2">
          {visible.map((s, i) => (
            <Reveal as="li" key={s.id} delay={(i % 2) * 80}>
              <SubmissionCard submission={s} action="Open review" />
            </Reveal>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "normal" }: { label: string; value: number; tone?: "normal" | "danger" }) {
  return (
    <div className="p-5">
      <p className={`text-3xl font-bold tabular-nums ${tone === "danger" && value > 0 ? "text-danger-fg" : "text-foreground"}`}>
        {value}
      </p>
      <p className="mt-1 text-xs font-medium text-muted-foreground">{label}</p>
    </div>
  );
}
