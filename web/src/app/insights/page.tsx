"use client";

import Link from "next/link";
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

type StaleApproval = { submission_id: string; title: string; status: string; cites: string; current_version: number };

export default function InsightsPage() {
  const [ins, setIns] = useState<Insights | null>(null);
  const [alerts, setAlerts] = useState<ExpiryAlert[] | null>(null);
  const [ai, setAi] = useState<{ providers: { provider: string; available: boolean; model: string }[]; ai_pending_note?: string } | null>(null);
  const [stale, setStale] = useState<StaleApproval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [i, e, a, s] = await Promise.all([
        api<Insights>("/insights"),
        api<{ alerts: ExpiryAlert[] }>("/alerts/expiry"),
        api<{ providers: { provider: string; available: boolean; model: string }[]; note: string }>("/ai-status"),
        api<{ items: StaleApproval[] }>("/kb/stale-approvals"),
      ]);
      setIns(i);
      setAlerts(e.alerts);
      setAi(a);
      setStale(s.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <div>
        <p className="eyebrow">Governance health</p>
        <h1 className="page-title mt-1.5">Insights</h1>
        <p className="page-lede">
          Where friction lives: ambiguous rules, contested decisions, and what the AI spends.
        </p>
      </div>
      {error && <p className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>}

      {ai && (
        <div className="flex flex-wrap gap-2 text-sm">
          {ai.providers?.map((p) => (
            <span
              key={p.provider}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                p.available
                  ? "bg-success-bg text-success-fg"
                  : "border border-border-strong bg-card text-muted-foreground"
              }`}
            >
              AI gateway · {p.provider} {p.available ? `(${p.model})` : "(no key)"}
            </span>
          ))}
        </div>
      )}

      {ins && (
        <>
          <div className="surface grid grid-cols-1 divide-y divide-border overflow-hidden sm:grid-cols-4 sm:divide-x sm:divide-y-0">
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

          {stale && (
            <Card title="Approved content to re-review">
              {stale.map((s) => (
                <div key={s.submission_id + s.cites} className="border-b border-border py-2.5 last:border-0 text-sm">
                  <Link href={`/submissions/${s.submission_id}`} className="link">
                    {s.title}
                  </Link>{" "}
                  <span className="text-xs text-muted-foreground">
                    ({s.status}) · approved against {s.cites}, now v{s.current_version}
                  </span>
                </div>
              ))}
              {stale.length === 0 && <Muted text="Every approved item cites current knowledge." />}
            </Card>
          )}

          {ins.possibly_unclear_rules.length > 0 && (
            <Card title="Rules a human should re-word">
              {ins.possibly_unclear_rules.map((r) => (
                <div key={r.id} className="border-b border-border py-2.5 last:border-0">
                  <code className="font-mono text-xs font-semibold text-brand">{r.id}</code>{" "}
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
            <div key={a.fact.id} className="border-b border-border py-2.5 last:border-0 text-sm">
              <p>
                <code className="font-mono text-xs font-semibold text-brand">{a.fact.id}</code> {a.fact.text}
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
    <div className="surface p-5">
      <h2 className="eyebrow mb-3">{title}</h2>
      {children}
    </div>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-2 last:border-0 text-sm">
      <span>{left}</span>
      <span className="shrink-0 font-mono text-xs text-muted-foreground tabular-nums">{right}</span>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="p-5">
      <div className="text-xs font-medium text-foreground-secondary">{label}</div>
      <div className="mt-1 font-mono text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}

function Muted({ text }: { text: string }) {
  return <p className="text-sm text-muted-foreground">{text}</p>;
}
