"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, CATEGORY_LABEL, TIER_LABEL } from "@/lib/api";
import { formatDay, plural } from "@/lib/format";
import { canReview } from "@/lib/roles";
import { useIdentity } from "@/components/identity";

type Insights = {
  by_checker: Record<string, { checker: string; c: number; definite: number }>;
  decisions: Record<string, number>;
  dispute_overrides: { title: string; reason: string; at: string }[];
  categories: { category: string; c: number }[];
  unsupported_claims: number;
  statuses: { status: string; c: number }[];
  possibly_unclear_rules: { id: string; statement: string; vague_flag: string }[];
  ai_calls: { task: string; provider: string; model: string; c: number; ok: number }[];
  missing_facts?: { span_text: string; occurrences: number; sample_title: string; sample_id: string }[];
  tier_calibration?: { tier: string; total: number; disputed: number; accepted: number; open: number; dispute_rate: number; needs_recalibration: boolean }[];
};

type ExpiryAlert = {
  fact: { id: string; text: string; owner: string; valid_to: string | null };
  active: boolean;
  affected_approved_content: { id: string; title: string; status: string }[];
  action: string;
};

type StaleApproval = { submission_id: string; title: string; status: string; cites: string; current_version: number };

type AiStatus = { providers: { provider: string; available: boolean; model: string }[] };

/** Why a rule was flagged as unclear, in words. */
const UNCLEAR_REASON: Record<string, string> = {
  vague_no_examples: "No examples of what to do or avoid",
  vague_contradictory: "Asks for two things that pull against each other",
  vague_duplicate: "Says the same as another rule",
};

export default function InsightsPage() {
  const { me } = useIdentity();
  // AI gateway internals (providers, keys, the call ledger) are for the people who run the workspace
  const staff = canReview(me?.role);
  const [ins, setIns] = useState<Insights | null>(null);
  const [alerts, setAlerts] = useState<ExpiryAlert[] | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [stale, setStale] = useState<StaleApproval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [i, e, s, a] = await Promise.all([
        api<Insights>("/insights"),
        api<{ alerts: ExpiryAlert[] }>("/alerts/expiry"),
        api<{ items: StaleApproval[] }>("/kb/stale-approvals"),
        staff ? api<AiStatus>("/ai-status") : Promise.resolve(null),
      ]);
      setIns(i);
      setAlerts(e.alerts);
      setStale(s.items);
      setAi(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [staff]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalSubmissions = ins?.statuses.reduce((n, s) => n + s.c, 0) ?? 0;
  const missing = mergeMissing(ins?.missing_facts ?? []);
  const tiers = [...(ins?.tier_calibration ?? [])].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));

  return (
    <div className="space-y-5">
      <div>
        <p className="eyebrow">How the brand is doing</p>
        <h1 className="page-title mt-1.5">Reports</h1>
        <p className="page-lede">
          What Canonry catches most, which rules confuse people, and which facts need attention.
        </p>
      </div>
      {error && <p className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>}

      {ins && (
        <>
          <div className="surface grid grid-cols-1 divide-y divide-border overflow-hidden sm:grid-cols-4 sm:divide-x sm:divide-y-0">
            <Stat
              label="Submissions"
              value={String(totalSubmissions)}
              hint={ins.statuses.map((s) => `${s.c} ${s.status.toLowerCase()}`).join(" · ") || "None yet"}
            />
            <Stat label="Claims with no fact" value={String(ins.unsupported_claims)} hint="need an approved fact behind them" />
            <Stat label="Disputed issues" value={String(ins.dispute_overrides.length)} hint="someone disagreed with a check" />
            <Stat label="Rules to re-word" value={String(ins.possibly_unclear_rules.length)} hint="flagged for the brand owner" />
          </div>

          <Card title="What gets caught most">
            {ins.categories.slice(0, 8).map((c) => (
              <Row key={c.category} left={CATEGORY_LABEL[c.category] ?? sentence(c.category)} right={plural(c.c, "issue")} />
            ))}
            {ins.categories.length === 0 && <Muted text="Nothing caught yet. Run a check to see results here." />}
          </Card>

          {missing.length > 0 && (
            <Card title="Claims with no fact behind them">
              <p className="mb-2 text-xs text-muted-foreground">
                These phrases keep coming up without an approved fact to support them. One well-written fact can clear
                every occurrence. Canonry suggests; the brand owner decides.
              </p>
              {missing.map((m) => (
                <div key={m.span_text + m.sample_id} className="border-b border-border py-2.5 last:border-0 text-sm">
                  <p className="font-serif italic">“{m.span_text}”</p>
                  <p className="text-xs text-muted-foreground">
                    {plural(m.occurrences, "submission")} · e.g.{" "}
                    <Link href={`/submissions/${m.sample_id}`} className="link">{m.sample_title}</Link>
                    {staff && (
                      <>
                        {" "}· <Link href="/kb" className="link">add or link a fact</Link>
                      </>
                    )}
                  </p>
                </div>
              ))}
            </Card>
          )}

          {ins.possibly_unclear_rules.length > 0 && (
            <Card title="Rules that need clearer wording">
              {ins.possibly_unclear_rules.map((r) => (
                <div key={r.id} className="border-b border-border py-2.5 last:border-0">
                  <code className="font-mono text-xs font-semibold text-brand">{r.id}</code>{" "}
                  <span className="text-sm">{r.statement}</span>
                  <p className="text-xs text-muted-foreground">{UNCLEAR_REASON[r.vague_flag] ?? sentence(r.vague_flag.replace("vague_", ""))}</p>
                </div>
              ))}
            </Card>
          )}
        </>
      )}

      {alerts && (
        <Card title="Facts that have expired">
          {alerts.map((a) => {
            const cited = a.affected_approved_content;
            return (
              <div key={a.fact.id} className="border-b border-border py-2.5 last:border-0 text-sm">
                <p>
                  <code className="font-mono text-xs font-semibold text-brand">{a.fact.id}</code> {a.fact.text}
                </p>
                <p className="text-xs text-muted-foreground">
                  Expired {formatDay(a.fact.valid_to)} ·{" "}
                  {cited.length === 0
                    ? "no approved content cites it"
                    : `cited by ${plural(cited.length, "approved item")}: ${cited.map((c) => c.title).join(", ")}`}
                </p>
              </div>
            );
          })}
          {alerts.length === 0 && <Muted text="Every fact on file is still in date." />}
        </Card>
      )}

      {stale && (
        <Card title="Approved content to re-check">
          {stale.map((s) => (
            <div key={s.submission_id + s.cites} className="border-b border-border py-2.5 last:border-0 text-sm">
              <Link href={`/submissions/${s.submission_id}`} className="link">
                {s.title}
              </Link>{" "}
              <span className="text-xs text-muted-foreground">
                ({s.status}) · approved against {s.cites}, now version {s.current_version}
              </span>
            </div>
          ))}
          {stale.length === 0 && <Muted text="Every approved item was checked against the current rules and facts." />}
        </Card>
      )}

      {ins && (
        <>
          <Card title="Disputed and overridden issues (latest 20)">
            {ins.dispute_overrides.map((o, i) => (
              <Row key={i} left={`“${o.reason}” — ${o.title}`} right={formatDay(o.at)} />
            ))}
            {ins.dispute_overrides.length === 0 && <Muted text="No disputes yet." />}
          </Card>

          {staff && tiers.length > 0 && (
            <Card title="How often each level is disputed">
              <p className="mb-2 text-xs text-muted-foreground">
                If more than 10% of “Must fix” issues are disputed, that level needs re-calibrating before people trust it.
              </p>
              {tiers.map((t) => (
                <div key={t.tier} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border py-2 last:border-0 text-sm">
                  <span className="font-medium">{TIER_LABEL[t.tier] ?? sentence(t.tier)}</span>
                  <span className="text-xs text-muted-foreground">
                    {plural(t.total, "issue")} · {t.disputed} disputed · {(t.dispute_rate * 100).toFixed(1)}% dispute rate
                  </span>
                  {t.needs_recalibration && (
                    <span className="rounded-full bg-warning-bg px-2 py-0.5 text-[11px] font-semibold text-warning-fg">
                      Needs re-calibrating
                    </span>
                  )}
                </div>
              ))}
            </Card>
          )}

          {staff && (
            <section aria-labelledby="ai-usage" className="space-y-5">
              <h2 id="ai-usage" className="eyebrow pt-2">For reviewers and admins: how the checks run</h2>
              {ai && ai.providers.length > 0 && (
                <div className="flex flex-wrap gap-2 text-sm">
                  {ai.providers.map((p) => (
                    <span
                      key={p.provider}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                        p.available ? "bg-success-bg text-success-fg" : "border border-border-strong bg-card text-muted-foreground"
                      }`}
                    >
                      AI provider · {p.provider} {p.available ? `(${p.model})` : "(no key)"}
                    </span>
                  ))}
                </div>
              )}
              <Card title="Issues by checker">
                {Object.values(ins.by_checker).map((b) => (
                  <Row key={b.checker} left={b.checker} right={`${plural(b.c, "issue")} · ${b.definite} must fix`} />
                ))}
                {Object.keys(ins.by_checker).length === 0 && <Muted text="No checks have run yet." />}
              </Card>
              <Card title="AI usage">
                {ins.ai_calls.map((a, i) => (
                  <Row key={i} left={`${a.task} · ${a.provider}/${a.model}`} right={`${plural(a.c, "call")} (${a.ok ?? 0} ok)`} />
                ))}
                {ins.ai_calls.length === 0 && <Muted text="No AI calls yet. Rule checks carry the load." />}
              </Card>
            </section>
          )}
        </>
      )}
    </div>
  );
}

/** "no_examples" -> "No examples" */
function sentence(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const TIER_ORDER = ["definite", "likely", "consider"];

type MissingFact = NonNullable<Insights["missing_facts"]>[number];

/** "India's #1" and "India’s #1" are the same claim: merge phrases that differ only in quotes, dashes, case or spacing. */
function mergeMissing(items: MissingFact[]): MissingFact[] {
  const key = (s: string) =>
    s.normalize("NFKC").replace(/[‘’ʼ`´]/g, "'").replace(/[“”]/g, '"').replace(/[‐-―]/g, "-")
      .replace(/\s+/g, " ").trim().toLowerCase();
  const merged = new Map<string, MissingFact>();
  for (const m of items) {
    const k = key(m.span_text);
    const seen = merged.get(k);
    if (seen) merged.set(k, { ...seen, occurrences: seen.occurrences + m.occurrences });
    else merged.set(k, { ...m });
  }
  return [...merged.values()].sort((a, b) => b.occurrences - a.occurrences);
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="surface p-5">
      <h2 className="mb-3 text-base font-bold tracking-tight text-foreground">{title}</h2>
      {children}
    </div>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-2 last:border-0 text-sm">
      <span>{left}</span>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{right}</span>
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
