"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { api, type Submission } from "@/lib/api";
import { EmptyIllustration } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { Reveal } from "@/components/motion";
import { SubmissionCard } from "@/components/submission-card";

const SIGNED = new Set(["Signed", "Approved", "Exempt-approved"]);

/** A writer's own drafts, grouped by whose move it is: what a reviewer decided, and what to do next. */
export default function MyWorkPage() {
  const { me } = useIdentity();
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    let active = true;
    api<{ submissions: Submission[] }>("/submissions")
      .then((s) => {
        if (active) setSubs(s.submissions.filter((x) => x.created_by === me.email));
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      active = false;
    };
  }, [me]);

  const list = subs ?? [];
  const sentBack = list.filter((s) => s.status === "Changes requested");
  const toFinish = list.filter((s) => s.status === "Checked" || s.status === "Draft");
  const withReviewer = list.filter((s) => s.status === "In review");
  const approved = list.filter((s) => SIGNED.has(s.status));

  return (
    <div className="space-y-9">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Your drafts</p>
          <h1 className="page-title mt-1.5">My work</h1>
          <p className="page-lede max-w-2xl">
            Everything you wrote, and where it stands: what a reviewer sent back and why, what is still with them, and
            what was approved.
          </p>
        </div>
        <Link href="/new" className="btn btn-primary btn-lg shadow-card">
          Write a draft <span aria-hidden className="btn-arrow">→</span>
        </Link>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}

      <div className="surface grid grid-cols-2 divide-x divide-y divide-border overflow-hidden sm:grid-cols-4 sm:divide-y-0">
        <Stat label="Sent back to you" value={sentBack.length} tone="warning" />
        <Stat label="To finish and send" value={toFinish.length} tone="warning" />
        <Stat label="With a reviewer" value={withReviewer.length} />
        <Stat label="Approved" value={approved.length} tone="success" />
      </div>

      {subs === null && !error && <p className="text-sm text-muted-foreground">Loading your work…</p>}

      {subs && subs.length === 0 && (
        <div className="surface flex flex-col items-center gap-3 px-6 py-14 text-center">
          <EmptyIllustration />
          <p className="text-xl font-bold text-foreground">Nothing written yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Write or upload a draft. Once a reviewer decides on it, their answer shows up here.
          </p>
          <Link href="/new" className="btn btn-primary mt-2">
            Write your first draft <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      )}

      <Group
        title="Sent back to you"
        lede="A reviewer asked for changes. Open one, make them (Edit text, or Upload new version for a file), then send it again."
        items={sentBack}
      />
      <Group title="To finish and send" lede="Fix what Canonry flagged, then send it for review." items={toFinish} />
      <Group title="With a reviewer" lede="Locked while a reviewer reads it. Their answer will appear here." items={withReviewer} />
      <Group title="Approved" lede="Signed: anyone can verify the published copy against the approved one." items={approved} />
    </div>
  );
}

function Group({ title, lede, items }: { title: string; lede: string; items: Submission[] }) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-4">
      <Reveal>
        <h2 className="text-2xl font-bold tracking-tight">
          {title} <span className="text-base font-medium text-muted-foreground tabular-nums">({items.length})</span>
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{lede}</p>
      </Reveal>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">
        {items.map((s, i) => (
          <Reveal as="li" key={s.id} delay={(i % 2) * 80}>
            <SubmissionCard submission={s} />
          </Reveal>
        ))}
      </ul>
    </section>
  );
}

function Stat({ label, value, tone = "normal" }: { label: string; value: number; tone?: "normal" | "warning" | "success" }) {
  const color =
    tone === "warning" && value > 0 ? "text-warning-fg" : tone === "success" && value > 0 ? "text-success-fg" : "text-foreground";
  return (
    <div className="p-5">
      <p className={`text-3xl font-bold tabular-nums ${color}`}>{value}</p>
      <p className="mt-1 text-xs font-medium text-muted-foreground">{label}</p>
    </div>
  );
}
