"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  CATEGORY_LABEL,
  TIER_LABEL,
  type Finding,
  type Revision,
  type SubmissionDetail,
} from "@/lib/api";
import { CategoryBadge, LevelBadge, RiskBadge, StatusBadge } from "@/components/fx";
import { personaName, ROLE_LABEL } from "@/lib/personas";

export function SubmissionDetailClient({ sid }: { sid: string }) {
  const [d, setD] = useState<SubmissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revIdx, setRevIdx] = useState(-1); // -1 => latest
  const [pocId, setPocId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api<SubmissionDetail>(`/submissions/${sid}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [sid]);

  useEffect(() => {
    void load();
  }, [load]);

  const rev: Revision | null = useMemo(() => {
    if (!d) return null;
    if (revIdx === -1) return d.latest_revision;
    return d.revisions[revIdx] ?? null;
  }, [d, revIdx]);

  const openFindings = d?.findings.filter((f) => f.status === "open") ?? [];
  const showActionsForRev = rev?.id === d?.latest_revision?.id;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function review(action: "approve" | "request_changes" | "override", reason: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ status?: string; poc_id?: string }>(`/submissions/${sid}/review`, {
        method: "POST",
        json: { action, reason: reason || undefined, comment: reason || undefined },
      });
      if (r.poc_id) setPocId(r.poc_id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !d) {
    return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40">{error}</p>;
  }
  if (!d) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const s = d.submission;
  const canReview = ["reviewer", "admin"].includes(d.me.role);
  const canResolve = ["creator", "admin", "agency"].includes(d.me.role);
  const inReview = s.status === "In review";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight">{s.title}</h1>
        <StatusBadge status={s.status} />
        <RiskBadge risk={s.risk} />
        <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] capitalize text-muted-foreground">
          {s.channel} · {s.source_type}
        </span>
      </div>

      {s.router_note && <p className="text-sm text-muted-foreground">Routing: {s.router_note}</p>}

      {error && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40">
          {error}
        </p>
      )}
      {pocId && (
        <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40">
          Proof of Compliance signed.{" "}
          <Link className="underline" href={`/verify/${pocId}`}>
            Open public verification page
          </Link>
        </p>
      )}

      {d.poc && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 text-sm dark:border-emerald-900 dark:bg-emerald-950/30">
          This revision was approved and signed.{" "}
          <Link className="font-medium underline" href={`/verify/${d.poc.id}`}>
            Verify its Proof of Compliance →
          </Link>
        </div>
      )}

      {canReview && inReview && (
        <ReviewBar busy={busy} onReview={review} openHigh={openFindings.some((f) => f.severity === "high")} />
      )}

      {(canResolve || canReview) && showActionsForRev && openFindings.length > 0 && (
        <ActionsBar
          busy={busy}
          onRecheck={() => act(() => api(`/submissions/${sid}/recheck`, { method: "POST" }))}
          onSubmitReview={
            canResolve || canReview
              ? () =>
                  act(() =>
                    api(`/submissions/${sid}/submit-review`, { method: "POST" }).catch((e) => {
                      throw e;
                    })
                  )
              : null
          }
          canSubmit={s.status === "Checked" || s.status === "Draft"}
        />
      )}

      {/* ---- content with span highlighting ---- */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold">Content</h2>
          <select
            className="ml-auto h-8 rounded-md border border-input bg-transparent px-2 text-xs"
            value={revIdx}
            onChange={(e) => setRevIdx(Number(e.target.value))}
          >
            <option value={-1}>Latest (rev {d.latest_revision?.revision_no})</option>
            {d.revisions
              .slice()
              .reverse()
              .map((r) => (
                <option key={r.id} value={d.revisions.indexOf(r)}>
                  rev {r.revision_no}
                </option>
              ))}
          </select>
        </div>
        <ContentWithSpans content={rev?.content ?? ""} findings={rev?.id === d.latest_revision?.id ? d.findings : []} />
      </section>

      {/* ---- findings ---- */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold">
          Findings {showActionsForRev ? `(${openFindings.length} open)` : "(historical)"}
        </h2>
        {d.findings.length === 0 && (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            No findings on this revision — all checks passed or every issue was resolved.
          </p>
        )}
        {d.findings.map((f) => (
          <FindingCard
            key={f.id}
            f={f}
            disabled={busy}
            active={showActionsForRev}
            onAccept={() =>
              act(() =>
                api(`/submissions/${sid}/resolve`, {
                  method: "POST",
                  json: { revision_id: rev?.id, finding_id: f.id, action: "accept" },
                })
              )
            }
            onEdit={(replacement) =>
              act(() =>
                api(`/submissions/${sid}/resolve`, {
                  method: "POST",
                  json: { revision_id: rev?.id, finding_id: f.id, action: "edit", replacement },
                })
              )
            }
            onDispute={(reason) =>
              act(() =>
                api(`/submissions/${sid}/resolve`, {
                  method: "POST",
                  json: { revision_id: rev?.id, finding_id: f.id, action: "dispute", reason },
                })
              )
            }
          />
        ))}
      </section>

      {/* ---- trail ---- */}
      <section className="grid gap-3 md:grid-cols-2">
        <TrailCard title="Decisions by creators">
          {d.decisions.length === 0 && <Empty text="No resolves yet." />}
          {d.decisions.map((dec) => (
            <li key={dec.id}>
              <span className="font-medium capitalize">{dec.action}</span> on {dec.finding_id.slice(-6)} by{" "}
              {personaName(dec.by_user)}
              {dec.reason ? ` — “${dec.reason}”` : dec.replacement ? ` — “${dec.replacement}”` : ""}
            </li>
          ))}
        </TrailCard>
        <TrailCard title="Approvals">
          {d.approvals.length === 0 && <Empty text="Not submitted for review yet." />}
          {d.approvals.map((a) => (
            <li key={a.id}>
              <span className="font-medium capitalize">{a.action.replace("_", " ")}</span> by{" "}
              {a.reviewer.startsWith("exemption-policy:") ? "exemption policy" : personaName(a.reviewer)}
              {a.reason ? ` — “${a.reason}”` : ""}
            </li>
          ))}
        </TrailCard>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ReviewBar({
  busy,
  onReview,
  openHigh,
}: {
  busy: boolean;
  onReview: (a: "approve" | "request_changes" | "override", reason: string) => Promise<void>;
  openHigh: boolean;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="grow space-y-1">
          <span className="text-xs font-medium text-muted-foreground">
            Reviewer comment / reason (required for overrides)
          </span>
          <input
            className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Approved — claims verified against the Fact Library."
          />
        </label>
        <div className="flex gap-2">
          <button
            disabled={busy || (openHigh && true)}
            title={openHigh ? "High-severity findings must be resolved or explicitly overridden first" : ""}
            onClick={() => void onReview("approve", reason)}
            className="rounded-md bg-foreground px-3.5 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-40"
          >
            Approve
          </button>
          <button
            disabled={busy || !reason.trim()}
            onClick={() => void onReview("request_changes", reason)}
            className="rounded-md border border-input px-3.5 py-2 text-sm hover:bg-muted"
          >
            Request changes
          </button>
          <button
            disabled={busy || !reason.trim()}
            title="Explicit human override — always logged with a reason"
            onClick={() => void onReview("override", reason)}
            className="rounded-md border border-amber-300 px-3.5 py-2 text-sm text-amber-700 hover:bg-amber-50 disabled:opacity-40 dark:text-amber-300"
          >
            Override finding…
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Approval signs a Proof of Compliance for this exact revision.
      </p>
    </div>
  );
}

function ActionsBar({
  busy,
  onRecheck,
  onSubmitReview,
  canSubmit,
}: {
  busy: boolean;
  onRecheck: () => void;
  onSubmitReview: (() => void) | null;
  canSubmit: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        disabled={busy}
        onClick={onRecheck}
        className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
      >
        Re-check
      </button>
      {onSubmitReview && canSubmit && (
        <button
          disabled={busy}
          onClick={onSubmitReview}
          className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background hover:opacity-90"
        >
          Submit for review
        </button>
      )}
    </div>
  );
}

function ContentWithSpans({ content, findings }: { content: string; findings: Finding[] }) {
  const spans = findings
    .filter((f) => f.status === "open" && f.span_text && content.includes(f.span_text))
    .map((f) => ({ text: f.span_text, f }));
  type Piece = { text: string; f?: Finding };
  const pieces: Piece[] = [];
  let cursor = 0;
  const sorted = [...spans].sort((a, b) => content.indexOf(a.text) - content.indexOf(b.text));
  for (const s of sorted) {
    const i = content.indexOf(s.text, cursor);
    if (i < 0) continue;
    pieces.push({ text: content.slice(cursor, i) });
    pieces.push({ text: s.text, f: s.f });
    cursor = i + s.text.length;
  }
  pieces.push({ text: content.slice(cursor) });
  return (
    <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
      {pieces.map((p, i) =>
        p.f ? (
          <mark
            key={i}
            id={`span-${p.f.id}`}
            className="rounded-sm bg-amber-100/70 px-0.5 dark:bg-amber-900/40"
            title={`${CATEGORY_LABEL[p.f.category] ?? p.f.category} · ${TIER_LABEL[p.f.tier]}`}
          >
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        )
      )}
    </p>
  );
}

function FindingCard({
  f,
  disabled,
  active,
  onAccept,
  onEdit,
  onDispute,
}: {
  f: Finding;
  disabled: boolean;
  active: boolean;
  onAccept: () => Promise<unknown>;
  onEdit: (replacement: string) => Promise<unknown>;
  onDispute: (reason: string) => Promise<unknown>;
}) {
  const [editText, setEditText] = useState(f.suggestion?.replace ?? "");
  const [reason, setReason] = useState("");
  const open = f.status === "open";

  return (
    <div
      className={`rounded-lg border bg-card p-3.5 ${
        open && f.severity === "high"
          ? "border-red-300 dark:border-red-900"
          : open
            ? "border-border"
            : "border-border/50 opacity-70"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <CategoryBadge category={f.category} />
        <LevelBadge tier={f.tier} severity={f.severity} />
        <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {f.checker}
        </span>
        {!open && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize text-muted-foreground">
            {f.status}
          </span>
        )}
      </div>

      {f.span_text && (
        <p className="mt-2 border-l-2 border-amber-400 pl-2 text-sm italic text-foreground/90">
          “{f.span_text}”
        </p>
      )}

      <p className="mt-2 text-sm">{f.explanation}</p>

      {f.citations?.length > 0 && (
        <div className="mt-2 space-y-1">
          {f.citations.map((c, i) => (
            <p key={i} className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground/70">
                {({ fact: "Fact ", rule: "Rule ", term: "Term " }[c.type] ?? "") + c.id}:
              </span>{" "}
              {c.excerpt}
              {c.valid_to ? ` (valid until ${c.valid_to})` : ""}
              {c.confidential ? " · confidential" : ""}
            </p>
          ))}
        </div>
      )}

      <p className="mt-2 text-[11px] text-muted-foreground">
        {f.provenance.model
          ? `checked by ${f.provenance.model}`
          : "deterministic rule check"} · contract {f.provenance.prompt_version}
      </p>

      {active && open && (
        <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
          {f.suggestion?.replace && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Suggested fix:</span>
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{f.suggestion.replace}</code>
              <button
                disabled={disabled}
                onClick={() => void onAccept()}
                className="rounded-md bg-foreground px-2.5 py-1 text-xs font-medium text-background hover:opacity-90"
              >
                Accept fix
              </button>
            </div>
          )}
          {f.suggestion?.operation === "remove" && (
            <button
              disabled={disabled}
              onClick={() => void onAccept()}
              className="rounded-md bg-foreground px-2.5 py-1 text-xs font-medium text-background hover:opacity-90"
            >
              Remove the flagged phrase
            </button>
          )}
          {(f.suggestion?.replace || f.suggestion?.operation === "remove") && (
            <p className="text-[11px] text-muted-foreground">You can also fix it in your own words below.</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="h-8 grow rounded-md border border-input bg-transparent px-2 text-xs"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              placeholder="Replace the flagged phrase in your own words (optional)"
            />
            <button
              disabled={disabled || !editText.trim()}
              onClick={() => void onEdit(editText)}
              className="rounded-md border border-input px-2.5 py-1 text-xs hover:bg-muted"
            >
              Apply my edit
            </button>
            <input
              className="h-8 grow rounded-md border border-input bg-transparent px-2 text-xs"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Dispute reason: rule doesn't apply / unclear rule / fact outdated / AI misread"
            />
            <button
              disabled={disabled || !reason.trim()}
              onClick={() => void onDispute(reason)}
              className="rounded-md border border-input px-2.5 py-1 text-xs hover:bg-muted"
            >
              Dispute
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TrailCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3.5">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <ul className="list-disc space-y-1 pl-4 text-xs">{children}</ul>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <li className="list-none text-muted-foreground">{text}</li>;
}
