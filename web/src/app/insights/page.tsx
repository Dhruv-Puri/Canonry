"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Insights = {
  by_checker: Record<string, { checker: string; c: number; definite: number }>;
  decisions: Record<string, number>;
  dispute_overrides: { title: string; reason: string; at: string }[];
  categories: { category: string; c: number }[];
  unsupported_claims: number;
  statuses: { status: string; c: number }[];
  possibly_unclear_rules: { id: string; statement: string; vague_flag: string }[];
  ai_calls: { task: string; provider: string; model: string; c: number; ok: number }[];
};

type ExpiryAlert = {
  fact: { id: string; text: string; owner: string; valid_to: string | null };
  active: boolean;
  affected_approved_content: { id: string; title: string; status: string }[];
  action: string;
};

export default function InsightsPage() {
  const [ins, setIns] = useState<Insights | null>(null);
  const [alerts, setAlerts] = useState<ExpiryAlert[] | null>(null);
  const [ai, setAi] = useState<{ providers: { provider: string; available: boolean; model: string }[]; ai_pending_note?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [i, e, a] = await Promise.all([
        api<Insights>("/insights"),
        api<{ alerts: ExpiryAlert[] }>("/alerts/expiry"),
        api<{ providers: { provider: string; available: boolean; model: string }[]; note: string }>("/ai-status"),
      ]);
      setIns(i);
      setAlerts(e.alerts);
      setAi(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Insights</h1>
        <p className="text-sm text-muted-foreground">
          Where friction lives: ambiguous rules, contested decisions, and what the AI spends.
        </p>
      </div>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40">{error}</p>}

      {ai && (
        <div className="flex flex-wrap gap-2 text-sm">
          {ai.providers?.map((p) => (
            <span
              key={p.provider}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                p.available
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              AI gateway · {p.provider} {p.available ? `(${p.model})` : "(no key)"}
            </span>
          ))}
        </div>
      )}

      {ins && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Submissions by status" value={ins.statuses.map((s) => `${s.c}`).join(" / ")} hint={ins.statuses.map((s) => s.status).join(" / ") || "—"} />
            <Stat label="Unsupported claims" value={String(ins.unsupported_claims)} hint="needing a fact on file" />
            <Stat label="Disputes / overrides" value={String(ins.dispute_overrides.length)} hint="contested findings" />
            <Stat label="Unclear rules" value={String(ins.possibly_unclear_rules.length)} hint="flagged for the brand owner" />
          </div>

          <Card title="Findings by checker">
            {Object.values(ins.by_checker).map((b) => (
              <Row key={b.checker} left={b.checker} right={`${b.c} findings · ${b.definite} definite`} />
            ))}
            {Object.keys(ins.by_checker).length === 0 && <Muted text="No checks have run yet." />}
          </Card>

          <Card title="Most frequent categories">
            {ins.categories.slice(0, 8).map((c) => (
              <Row key={c.category} left={c.category.replace(/_/g, " ")} right={String(c.c)} />
            ))}
          </Card>

          <Card title="Disputes & overrides (latest 20)">
            {ins.dispute_overrides.map((o, i) => (
              <Row key={i} left={`“${o.reason}” — ${o.title}`} right={o.at.slice(0, 16)} />
            ))}
            {ins.dispute_overrides.length === 0 && <Muted text="No disputes yet." />}
          </Card>

          <Card title="AI usage (the honest ledger)">
            {ins.ai_calls.map((a, i) => (
              <Row key={i} left={`${a.task} · ${a.provider}/${a.model}`} right={`${a.c} calls (${a.ok ?? 0} ok)`} />
            ))}
            {ins.ai_calls.length === 0 && <Muted text="No AI calls yet — deterministic checks carry the load." />}
          </Card>

          {ins.possibly_unclear_rules.length > 0 && (
            <Card title="Rules a human should re-word">
              {ins.possibly_unclear_rules.map((r) => (
                <div key={r.id} className="border-b border-border/50 py-2 last:border-0">
                  <code className="text-xs font-semibold">{r.id}</code>{" "}
                  <span className="text-sm">{r.statement}</span>
                  <p className="text-xs text-muted-foreground">flag: {r.vague_flag.replace("vague_", "")}</p>
                </div>
              ))}
            </Card>
          )}
        </>
      )}

      {alerts && (
        <Card title="Fact expiry alerts">
          {alerts.map((a) => (
            <div key={a.fact.id} className="border-b border-border/50 py-2 last:border-0 text-sm">
              <p>
                <code className="text-xs font-semibold">{a.fact.id}</code> {a.fact.text}
              </p>
              <p className="text-xs text-muted-foreground">
                valid to {a.fact.valid_to} · {a.affected_approved_content.length} approved item(s) cite it
                {a.affected_approved_content.length > 0 &&
                  `: ${a.affected_approved_content.map((c) => c.title).join(", ")}`}
              </p>
            </div>
          ))}
          {alerts.length === 0 && <Muted text="No facts are past their valid_to date." />}
        </Card>
      )}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {children}
    </div>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/50 py-1.5 last:border-0 text-sm">
      <span>{left}</span>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{right}</span>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs font-medium">{label}</div>
      <div className="text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}

function Muted({ text }: { text: string }) {
  return <p className="text-sm text-muted-foreground">{text}</p>;
}
