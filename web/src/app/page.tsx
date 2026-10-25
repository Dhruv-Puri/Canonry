"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Submission, type User } from "@/lib/api";
import { RiskBadge, StatusBadge } from "@/components/fx";

type Workspace = {
  workspace: string;
  rules: number;
  facts: number;
  terms: number;
  vague_rules: { id: string; statement: string; vague_flag: string }[];
};

export default function DashboardPage() {
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Submissions</h1>
          <p className="text-sm text-muted-foreground">
            Content in, checks explained, humans decide — the full review trail is kept.
          </p>
        </div>
        <Link
          href="/new"
          className="rounded-md bg-foreground px-3.5 py-2 text-sm font-medium text-background hover:opacity-90"
        >
          Submit content
        </Link>
      </div>

      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40">{error}</p>}

      {ws && (
        <div className="grid grid-cols-3 gap-3 text-sm">
          <StatCard label="Approved rules" value={ws.rules} hint="Quillmark checkable rules" />
          <StatCard label="Facts on file" value={ws.facts} hint="Every claim must trace to one" />
          <StatCard label="Terms" value={ws.terms} hint="Approved brand vocabulary" />
        </div>
      )}
      {ws && ws.vague_rules.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {ws.vague_rules.length} rule(s) are flagged as possibly unclear — see Insights.
        </p>
      )}

      {subs === null && !error && <p className="text-sm text-muted-foreground">Loading submissions…</p>}

      {subs && subs.length === 0 && (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nothing submitted yet. Try the demo: submit the Quillmark launch post and watch the findings come back with citations.
        </div>
      )}

      <div className="space-y-2">
        {subs?.map((s) => (
          <Link
            key={s.id}
            href={`/submissions/${s.id}`}
            className="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-foreground/25"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{s.title}</span>
              <StatusBadge status={s.status} />
              <RiskBadge risk={s.risk} />
              <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] capitalize text-muted-foreground">
                {s.channel} · {s.source_type}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {s.open_findings ?? 0} open finding{(s.open_findings ?? 0) === 1 ? "" : "s"}
              </span>
            </div>
            <p className="mt-1.5 line-clamp-1 text-sm text-muted-foreground">{s.content}</p>
            {(s as unknown as { router_note?: string }).router_note && (
              <p className="mt-1 text-xs text-muted-foreground">{assertNote(s)}</p>
            )}
          </Link>
        ))}
      </div>

      {me && me.role === "reviewer" && (
        <p className="text-xs text-muted-foreground">
          You are signed in as a reviewer — approvals on your screen show the full decision trail.
        </p>
      )}
    </div>
  );
}

function assertNote(s: Submission): string {
  return (s as unknown as { router_note?: string }).router_note ?? "";
}

function StatCard({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-sm font-medium">{label}</div>
      <div className="text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}
