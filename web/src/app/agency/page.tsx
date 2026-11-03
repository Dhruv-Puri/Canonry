"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Building2, ShieldCheck } from "lucide-react";
import { api, type Submission } from "@/lib/api";
import { EmptyIllustration } from "@/components/brand";
import { useIdentity } from "@/components/identity";
import { Reveal } from "@/components/motion";
import { SubmissionCard } from "@/components/submission-card";
import { roleHome } from "@/lib/roles";
import { AgencyScorecard } from "./scorecard";

export default function AgencyWorkspacePage() {
  const { me } = useIdentity();
  const isAgency = me?.role === "agency";
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAgency) return;
    let active = true;
    api<{ submissions: Submission[] }>("/submissions")
      .then((s) => {
        if (active) setSubs(s.submissions);
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      active = false;
    };
  }, [isAgency]);

  if (!isAgency) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
          <Building2 className="size-6" aria-hidden />
        </span>
        <p className="eyebrow mt-5">Agency workspace</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">This space is for agency partners</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          Agency partners submit client work and follow it through review. Your own workspace is the right place to
          work from.
        </p>
        <Link href={roleHome(me?.role)} className="btn btn-primary mt-6">
          Go to your workspace <ArrowRight className="size-4" aria-hidden />
        </Link>
      </section>
    );
  }

  const list = subs ?? [];
  const needsWork = list.filter(
    (s) => s.status === "Changes requested" || (s.status === "Checked" && (s.open_findings ?? 0) > 0)
  );

  return (
    <div className="space-y-9">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Agency workspace</p>
          <h1 className="page-title mt-1.5">My work</h1>
          <p className="page-lede max-w-2xl">
            Your agency’s work for the client, and how it is doing.
          </p>
        </div>
        <Link href="/new" data-guide="agency-new" className="btn btn-primary btn-lg shadow-card">
          Submit client work <span aria-hidden className="btn-arrow">→</span>
        </Link>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}

      <AgencyScorecard />

      {/* with no work yet, the empty state below is the one thing to do */}
      {list.length > 0 && (
      <section className="space-y-4">
        <Reveal>
          <p className="eyebrow">Needs your attention</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">Fix these before they can move on</h2>
        </Reveal>
        {subs && needsWork.length === 0 ? (
          <p className="rounded-xl border border-success-border bg-success-bg px-4 py-3 text-sm text-success-fg">
            Nothing needs a change from you right now.
          </p>
        ) : (
          <ul className="grid gap-4 md:grid-cols-2">
            {needsWork.map((s, i) => (
              <Reveal as="li" key={s.id} delay={(i % 2) * 80}>
                <SubmissionCard submission={s} />
              </Reveal>
            ))}
          </ul>
        )}
      </section>
      )}

      <section className="space-y-4">
        <Reveal className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">Your submissions</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight">Everything your agency sent</h2>
          </div>
          {list.length > 0 && (
            <Link href="/new" className="btn btn-secondary">
              New submission <span aria-hidden className="btn-arrow">→</span>
            </Link>
          )}
        </Reveal>

        {subs === null && !error && <p className="text-sm text-muted-foreground">Loading your work…</p>}

        {subs && subs.length === 0 && (
          <div className="surface flex flex-col items-center gap-3 px-6 py-14 text-center">
            <EmptyIllustration />
            <p className="text-xl font-bold text-foreground">No client work yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Submit a draft and Canonry will check it before it reaches the brand’s review queue.
            </p>
            <Link href="/new" className="btn btn-primary mt-2">
              Submit your first draft <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
        )}

        {subs && subs.length > 0 && (
          <ul className="grid gap-4 md:grid-cols-2">
            {subs.map((s, i) => (
              <Reveal as="li" key={s.id} delay={(i % 2) * 80}>
                <SubmissionCard submission={s} />
              </Reveal>
            ))}
          </ul>
        )}
      </section>

      <div className="flex items-start gap-3 rounded-xl border border-border bg-muted/50 px-4 py-3">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <p className="text-xs leading-relaxed text-muted-foreground">
          Agency access is scoped: this workspace shows only work your agency submitted. Confidential brand facts stay
          redacted, and brand rules are read-only.
        </p>
      </div>
    </div>
  );
}
