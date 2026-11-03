"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, BookMarked, LineChart, ShieldCheck } from "lucide-react";
import { api, type Submission } from "@/lib/api";
import { EmptyIllustration } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { SubmissionRow } from "@/components/submission-card";
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
            Open a draft, read what Canonry flagged, then approve or send it back.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/kb" className="btn btn-secondary">
            <BookMarked className="size-4" aria-hidden /> Brand rules
          </Link>
          <Link href="/insights" className="btn btn-secondary">
            <LineChart className="size-4" aria-hidden /> Reports
          </Link>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}

      {/* the counts live in the filter itself: one control, no repeated number tiles */}
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-border" role="group" aria-label="Filter the review queue">
        {FILTERS.map((f) => {
          const active = filter === f.id;
          const count = f.id === "all" ? subs?.length ?? 0 : counts[f.id];
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              aria-pressed={active}
              className={`queue-tab ${active ? "is-active" : ""}`}
            >
              <span className="text-2xl font-bold tabular-nums">{count}</span>
              <span className="text-sm font-medium">{f.label}</span>
            </button>
          );
        })}
        {counts.high > 0 && (
          <p className="mb-2 ml-auto inline-flex items-center gap-1.5 rounded-full bg-danger-bg px-3 py-1 text-sm font-semibold text-danger-fg">
            <span className="size-2 rounded-full bg-danger-fg" aria-hidden />
            {counts.high} high risk: a senior look first
          </p>
        )}
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
              ? "No submission is waiting for a reviewer decision right now. New ones appear here when a writer sends them for review."
              : "No submissions have this status yet."}
          </p>
          {filter === "queue" && counts.signed > 0 ? (
            <button type="button" className="btn btn-secondary mt-2" onClick={() => setFilter("signed")}>
              See signed work
            </button>
          ) : filter !== "queue" && filter !== "all" ? (
            <button type="button" className="btn btn-secondary mt-2" onClick={() => setFilter("all")}>
              Show all submissions
            </button>
          ) : (
            <Link href="/kb" className="btn btn-secondary mt-2">
              Look over the brand rules
            </Link>
          )}
        </div>
      )}

      {subs && visible.length > 0 && (
        <div className="surface overflow-hidden p-0">
          <div
            aria-hidden
            className="hidden border-b border-border bg-muted/40 px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground md:grid md:grid-cols-[minmax(0,1fr)_8.5rem_6.5rem_8rem] md:gap-x-6"
          >
            <span>Submission</span>
            <span>Channel · age</span>
            <span>Issues</span>
            <span className="text-right">Next</span>
          </div>
          <ul className="divide-y divide-border">
            {visible.map((s) => (
              <li key={s.id}>
                <SubmissionRow submission={s} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
