"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, BookMarked, LineChart, ShieldCheck, Sparkles, TriangleAlert, Users } from "lucide-react";
import { api, type Fact, type Submission } from "@/lib/api";
import { RiskBadge, StatusBadge } from "@/components/fx";
import { useIdentity } from "@/components/identity";
import { Reveal } from "@/components/motion";
import { roleHome } from "@/lib/roles";

type Workspace = {
  workspace: string;
  rules: number;
  facts: number;
  terms: number;
  vague_rules: { id: string; statement: string; vague_flag: string }[];
};

type Insights = {
  statuses: { status: string; c: number }[];
  ai_calls: { task: string; provider: string; model: string; c: number; ok: number }[];
  dispute_overrides: { title: string; reason: string; at: string }[];
  possibly_unclear_rules: { id: string; statement: string }[];
};

type AiStatus = {
  providers: { provider: string; available: boolean; model: string }[];
  note?: string;
};

type Expiry = { alerts: { fact: { id: string; text: string; valid_to: string | null } }[] };

export default function AdminOverviewPage() {
  const { me, demoMode } = useIdentity();
  const isAdmin = me?.role === "admin";
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [expiry, setExpiry] = useState<Expiry | null>(null);
  // "active facts": in date and not superseded, the same count as Brand rules and the creator home
  const [activeFacts, setActiveFacts] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    let active = true;
    Promise.all([
      api<Workspace>("/workspace"),
      api<{ submissions: Submission[] }>("/submissions"),
      api<Insights>("/insights"),
      api<AiStatus>("/ai-status"),
      api<Expiry>("/alerts/expiry"),
      api<{ facts: Fact[] }>("/facts"),
    ])
      .then(([w, s, i, a, e, f]) => {
        if (!active) return;
        setWorkspace(w);
        setSubs(s.submissions);
        setInsights(i);
        setAi(a);
        setExpiry(e);
        setActiveFacts(f.facts.filter((x) => x.active).length);
      })
      .catch((e) => {
        if (active) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      active = false;
    };
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
          <ShieldCheck className="size-6" aria-hidden />
        </span>
        <p className="eyebrow mt-5">Brand admin</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">This overview is for brand admins</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          Brand admins manage the rules, facts, and review load for the whole workspace. Your own workspace is the right
          place to work from.
        </p>
        <Link href={roleHome(me?.role)} className="btn btn-primary mt-6">
          Go to your workspace <ArrowRight className="size-4" aria-hidden />
        </Link>
      </section>
    );
  }

  const queue = (subs ?? []).filter((s) => s.status === "In review");
  const signed = (subs ?? []).filter((s) => s.status === "Signed");
  const high = queue.filter((s) => s.risk === "high").length;
  const aiCalls = insights?.ai_calls.reduce((n, c) => n + c.c, 0) ?? 0;
  const aiOk = insights?.ai_calls.reduce((n, c) => n + c.ok, 0) ?? 0;
  const unclear = workspace?.vague_rules.length ?? insights?.possibly_unclear_rules.length ?? 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Brand admin</p>
          <h1 className="page-title mt-1.5">Workspace overview</h1>
          <p className="page-lede max-w-2xl">
            The brand’s rules, its review load, and the health of the rules and facts behind every check.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/review" className="btn btn-primary">
            Review queue <ArrowRight className="size-4" aria-hidden />
          </Link>
          <Link href="/kb" className="btn btn-secondary">
            <BookMarked className="size-4" aria-hidden /> Brand rules
          </Link>
          <Link href="/admin/api" className="btn btn-secondary">
            <ShieldCheck className="size-4" aria-hidden /> API &amp; webhooks
          </Link>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}

      <div className="surface grid grid-cols-2 divide-x divide-y divide-border overflow-hidden sm:grid-cols-4 sm:divide-y-0">
        <Stat label="Awaiting review" value={queue.length} />
        <Stat label="High risk" value={high} tone={high > 0 ? "danger" : "normal"} />
        <Stat label="Approved rules" value={workspace?.rules ?? 0} />
        <Stat label="Active facts" value={activeFacts} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
        <Reveal className="surface p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Review load</p>
              <h2 className="mt-1 text-xl font-bold tracking-tight">Waiting on a person</h2>
            </div>
            <Link href="/review" className="btn btn-secondary btn-sm">
              Open queue <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {queue.length === 0
              ? "Nothing is waiting for a reviewer decision."
              : `${queue.length} submission${queue.length === 1 ? "" : "s"} in review, ${high} high risk.`}
          </p>

          {queue.length > 0 ? (
            <ul className="mt-4 divide-y divide-border">
              {queue.slice(0, 4).map((s) => (
                <li key={s.id}>
                  <Link href={`/submissions/${s.id}`} className="flex flex-wrap items-center gap-2 py-3 hover:text-brand">
                    <StatusBadge status={s.status} />
                    <RiskBadge risk={s.risk} />
                    <span className="min-w-0 flex-1 truncate font-medium text-foreground">{s.title}</span>
                    <span className="text-xs tabular-nums text-muted-foreground">{s.open_findings ?? 0} open</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 rounded-xl border border-dashed border-border-strong p-6 text-center text-sm text-muted-foreground">
              The queue is clear.
            </p>
          )}

          {signed.length > 0 && (
            <p className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
              {signed.length} signed item{signed.length === 1 ? "" : "s"} in the workspace.{" "}
              <Link href="/insights" className="link">
                See the trail
              </Link>
            </p>
          )}
        </Reveal>

        <Reveal delay={80} className="surface p-6">
          <div className="flex items-center gap-2">
            <TriangleAlert className="size-4 text-brand" aria-hidden />
            <p className="eyebrow">Governance signals</p>
          </div>
          <h2 className="mt-1 text-xl font-bold tracking-tight">What needs attention</h2>
          <ul className="mt-4 space-y-3 text-sm">
            <Signal
              label="Rules flagged unclear"
              value={unclear}
              href="/insights"
              hint="a human should re-word them"
            />
            <Signal
              label="Facts past expiry"
              value={expiry?.alerts.length ?? 0}
              href="/insights"
              hint="check content that cites them"
            />
            <Signal
              label="Disputes & overrides"
              value={insights?.dispute_overrides.length ?? 0}
              href="/insights"
              hint="issues people disagreed with"
            />
            <Signal
              label="Active facts and terms"
              value={(workspace?.terms ?? 0) + activeFacts}
              href="/kb"
              hint="what every check is matched against"
            />
          </ul>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link href="/kb" className="btn btn-secondary btn-sm">
              Manage brand rules
            </Link>
            <Link href="/insights" className="btn btn-ghost btn-sm">
              All reports <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>
        </Reveal>

        <Reveal delay={120} className="surface p-6 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 text-brand" aria-hidden />
                <p className="eyebrow">AI review</p>
              </div>
              <h2 className="mt-1 text-xl font-bold tracking-tight">What the AI adds, and what it never does</h2>
            </div>
            <Link href="/insights" className="btn btn-ghost btn-sm">
              AI ledger <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto]">
            <div>
              <div className="flex flex-wrap gap-2">
                {ai?.providers?.map((p) => (
                  <span
                    key={p.provider}
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      p.available
                        ? "bg-success-bg text-success-fg"
                        : "border border-border-strong bg-card text-muted-foreground"
                    }`}
                  >
                    {p.provider}: {p.available ? p.model : "not set up"}
                  </span>
                ))}
                {!ai && <span className="text-sm text-muted-foreground">Checking providers…</span>}
              </div>
              <ul className="mt-3 space-y-1.5 text-sm leading-relaxed text-foreground-secondary">
                <li><strong className="text-foreground">Adds:</strong> claims the rules cannot see (&ldquo;trusted by every bank&rdquo;),
                  tone, and what an image shows.</li>
                <li><strong className="text-foreground">Never:</strong> decides anything, or sees confidential facts. Its findings are at most
                  Should fix and always cite a rule; people accept or dispute them.</li>
                <li><strong className="text-foreground">Without it:</strong> every rule check still runs, and the page says AI was skipped.
                  The first available provider in the list answers, on free tiers.</li>
              </ul>
              {ai?.note && <p className="mt-2 text-xs text-muted-foreground">{ai.note}</p>}
            </div>
            <div className="rounded-xl border border-border bg-muted/50 px-4 py-3 text-sm">
              <p className="text-xs font-medium text-muted-foreground">Calls answered</p>
              <p className="mt-1 text-2xl font-bold tabular-nums">{aiCalls}</p>
              <p className="text-xs text-muted-foreground">{aiOk} successful</p>
            </div>
          </div>

          <div className="mt-5 flex items-start gap-3 border-t border-border pt-4">
            <Users className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
            <p className="text-xs leading-relaxed text-muted-foreground">
              {demoMode
                ? "Demo workspace: switch roles from the profile menu to test each side of the workflow."
                : "Team access is invitation-only. Invite a teammate from your profile menu; their role is fixed by the invitation."}
            </p>
          </div>
        </Reveal>
      </div>
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

function Signal({
  label,
  value,
  href,
  hint,
}: {
  label: string;
  value: number;
  href: string;
  hint: string;
}) {
  return (
    <li className="flex items-start justify-between gap-3 border-b border-border pb-3 last:border-0 last:pb-0">
      <span>
        <span className="block font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </span>
      <Link href={href} className="shrink-0 text-lg font-bold tabular-nums text-brand" aria-label={`${label}: ${value}`}>
        {value}
      </Link>
    </li>
  );
}
