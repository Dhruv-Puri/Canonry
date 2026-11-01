"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, GitCompare, TriangleAlert } from "lucide-react";
import {
  api,
  ApiError,
  CATEGORY_LABEL,
  TIER_LABEL,
  type AiAllowance,
  type AiReason,
  type Finding,
  type FindingLocator,
  type Revision,
  type SubmissionDetail,
  uploadFile,
} from "@/lib/api";
import { diffSummary, diffWords, type DiffToken } from "@/lib/diff";
import { CategoryBadge, LevelBadge, RiskBadge, StatusBadge } from "@/components/fx";
import { AiLoadingScreen } from "@/components/ai-loading";
import { ROLE_LABEL } from "@/lib/roles";

export function SubmissionDetailClient({ sid }: { sid: string }) {
  const [d, setD] = useState<SubmissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [revIdx, setRevIdx] = useState(-1); // -1 => latest
  const [diffMode, setDiffMode] = useState(false);
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
  // the revision before the one on screen, for the diff view
  const revListIndex = d && revIdx === -1 ? d.revisions.length - 1 : revIdx;
  const prevRev: Revision | null =
    d && revListIndex > 0 ? (d.revisions[revListIndex - 1] ?? null) : null;

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

  async function uploadVersion(file: File) {
    setChecking(true);
    try {
      await act(() => uploadFile(`/submissions/${sid}/upload?filename=${encodeURIComponent(file.name)}`, file));
    } finally {
      setChecking(false);
    }
  }

  async function recheck() {
    setChecking(true);
    try {
      await act(() => api(`/submissions/${sid}/recheck`, { method: "POST" }));
    } finally {
      setChecking(false);
    }
  }

  async function review(action: "approve" | "request_changes" | "override", reason: string, findingId?: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ status?: string; poc_id?: string }>(`/submissions/${sid}/review`, {
        method: "POST",
        json: { action, reason: reason || undefined, comment: reason || undefined, finding_id: findingId },
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
    return <p className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>;
  }
  if (!d) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const s = d.submission;
  const canReview = ["reviewer", "admin"].includes(d.me.role);
  const canResolve = ["creator", "admin", "agency"].includes(d.me.role);
  const backHref = canReview ? "/review" : d.me.role === "agency" ? "/agency" : "/";
  const backLabel = canReview ? "Review queue" : d.me.role === "agency" ? "My work" : "All submissions";
  const inReview = s.status === "In review";
  // the engine says what this status allows; content changes only while with the creator
  const editable = d.allowed.edit;

  return (
    <div className="space-y-5">
      <Link
        href={backHref}
        className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        ← {backLabel}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="page-title mr-1">{s.title}</h1>
        <StatusBadge status={s.status} />
        <RiskBadge risk={s.risk} />
        <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] capitalize text-foreground-secondary">
          {s.channel} · {s.source_type}
        </span>
      </div>

      {s.router_note && <p className="text-sm text-foreground-secondary">Routing: {s.router_note}</p>}

      {d.check?.status === "ai_pending" && (
        <div role="status" className="flex gap-3 rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-fg">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            <AiSkipped reason={d.check.ai_reason} allowance={d.ai_allowance} />{" "}
            <Link href="/insights" className="font-medium underline underline-offset-2">
              See AI status
            </Link>
          </p>
        </div>
      )}

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg">
          {error}
        </p>
      )}
      {pocId && (
        <p className="rounded-md border border-success-border bg-success-bg px-3 py-2 text-sm text-success-fg">
          Proof of Compliance signed.{" "}
          <Link className="font-medium underline underline-offset-2" href={`/verify/${pocId}`}>
            Open public verification page
          </Link>
        </p>
      )}

      {d.poc && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-success-border bg-success-bg px-4 py-3 text-sm text-success-fg">
          <span>
            This revision was approved and signed.
            {d.poc.content_kind === "file" && " The approved file carries the seal in its metadata."}
          </span>
          <Link className="font-medium underline underline-offset-2" href={`/verify/${d.poc.id}`}>
            Verify its Proof of Compliance <span aria-hidden className="btn-arrow">→</span>
          </Link>
          {d.poc.content_kind === "file" && (
            <a
              className="btn btn-sm btn-secondary"
              href={`/engine/submissions/${sid}/proof-file`}
              download
            >
              Download stamped file
            </a>
          )}
        </div>
      )}

      {d.asset && (
        <AssetPreview
          asset={d.asset}
          findings={d.findings}
          canUpload={canResolve && editable}
          busy={busy || checking}
          onUpload={uploadVersion}
        />
      )}

      {canReview && inReview && (
        <ReviewBar busy={busy} onReview={review} openHigh={openFindings.some((f) => f.severity === "high")} />
      )}

      {!editable && (
        <p className="rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground-secondary">
          {inReview
            ? "Content is locked while in review. The reviewer approves it or requests changes."
            : "This content is approved and locked. To change it, start a new submission."}
        </p>
      )}

      {(canResolve || canReview) && showActionsForRev && editable && (
        <ActionsBar
          busy={busy}
          onRecheck={() => void recheck()}
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
          canSubmit={d.allowed.submit}
          allowance={d.check?.ai_reason === "no_provider" ? null : d.ai_allowance}
        />
      )}

      {/* ---- content with span highlighting ---- */}
      <section className="paper pb-5 pl-14 pr-6 pt-4">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="eyebrow">Content under review</h2>
          <button
            type="button"
            onClick={() => setDiffMode((v) => !v)}
            disabled={!prevRev}
            aria-pressed={diffMode}
            title={prevRev ? `Show what changed from rev ${prevRev.revision_no} to rev ${rev?.revision_no}` : "The first revision has nothing before it"}
            className={`btn btn-sm ml-auto ${diffMode ? "btn-primary" : "btn-secondary"}`}
          >
            <GitCompare className="size-3.5" aria-hidden />
            {diffMode ? "Viewing changes" : "Compare with previous"}
          </button>
          <select
            aria-label="Revision"
            className="field h-8 w-auto px-2 text-xs"
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
        {diffMode && prevRev ? (
          <RevisionDiff before={prevRev.content} after={rev?.content ?? ""}
                        fromNo={prevRev.revision_no} toNo={rev?.revision_no} />
        ) : d.asset && ["png", "jpeg"].includes(d.asset.kind) ? (
          <p className="text-sm text-muted-foreground">
            This is an image. The visual findings are drawn on the preview above; its alt text is “{d.asset.alt_text || "—"}”.
          </p>
        ) : (
          <ContentWithSpans content={rev?.content ?? ""} findings={rev?.id === d.latest_revision?.id ? d.findings : []} />
        )}
      </section>

      {/* ---- findings ---- */}
      <section className="space-y-2.5">
        <h2 className="section-title">
          Findings {showActionsForRev ? `(${openFindings.length} open)` : "(historical)"}
        </h2>
        {d.findings.length === 0 && (
          <p className="rounded-xl border border-dashed border-border-strong p-8 text-center text-sm text-muted-foreground">
            No findings on this revision — all checks passed or every issue was resolved.
          </p>
        )}
        {d.findings.map((f) => (
          <FindingCard
            key={f.id}
            f={f}
            disabled={busy}
            active={showActionsForRev}
            assetKind={d.asset?.kind ?? null}
            canResolve={canResolve && editable}
            onOverride={canReview && inReview ? (reason) => review("override", reason, f.id) : undefined}
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
              {dec.by_name ?? dec.by_user}
              {dec.reason ? ` — “${dec.reason}”` : dec.replacement ? ` — “${dec.replacement}”` : ""}
            </li>
          ))}
        </TrailCard>
        <TrailCard title="Approvals">
          {d.approvals.length === 0 && (
            <Empty text={s.status === "In review" ? "Waiting for a reviewer’s decision." : "Not submitted for review yet."} />
          )}
          {d.approvals.map((a) => (
            <li key={a.id}>
              <span className="font-medium capitalize">{a.action.replace("_", " ")}</span> by{" "}
              {a.reviewer.startsWith("exemption-policy:") ? "exemption policy" : a.reviewer_name ?? a.reviewer}
              {a.reason?.startsWith("[self-approved]") ? (
                <>
                  {" "}
                  <span
                    className="rounded-full bg-warning-bg px-2 py-0.5 text-[11px] font-semibold text-warning-fg"
                    title="The same person drafted and approved this. Allowed in the demo, recorded in the signed Proof of Compliance."
                  >
                    Self-approved
                  </span>
                  {a.reason.slice("[self-approved]".length).trim() ? ` — “${a.reason.slice("[self-approved]".length).trim()}”` : ""}
                </>
              ) : a.reason ? (
                ` — “${a.reason}”`
              ) : (
                ""
              )}
            </li>
          ))}
        </TrailCard>
      </section>

      <AiLoadingScreen open={checking} title="Re-checking this revision" />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function describeLocator(loc?: FindingLocator | null): string {
  if (!loc) return "";
  if (loc.kind === "image") {
    return loc.region ? `image · ${loc.region.replace(/_/g, " ")}` : "image region";
  }
  if (loc.kind === "pdf") {
    return `page ${loc.page ?? "?"}${loc.line ? ` · line ${loc.line}` : ""}`;
  }
  if (loc.kind === "docx") {
    const bits = [];
    if (loc.section) bits.push(loc.section.slice(0, 34));
    bits.push(`paragraph ${loc.paragraph ?? "?"}`);
    if (loc.page) bits.push(`page ${loc.page}`);
    return bits.join(" · ");
  }
  return "";
}

const BOX_COLOR: Record<string, string> = {
  high: "border-danger-fg bg-danger-bg/15",
  medium: "border-warning-fg bg-warning-bg/15",
  low: "border-brand bg-brand/10",
};

function AssetPreview({
  asset,
  findings,
  canUpload,
  busy,
  onUpload,
}: {
  asset: NonNullable<SubmissionDetail["asset"]>;
  findings: Finding[];
  canUpload: boolean;
  busy: boolean;
  onUpload: (file: File) => Promise<void>;
}) {
  // whole-image findings (palette, a missing logo) would only frame the picture
  const boxes = findings.filter((f) => {
    const b = f.locator?.bbox;
    if (f.status !== "open" || !b) return false;
    return !(b[0] === 0 && b[1] === 0 && b[2] >= (asset.width || 0) && b[3] >= (asset.height || 0));
  });
  return (
    <section className="surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="eyebrow">The file under review</h2>
        <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] uppercase tracking-wide text-foreground-secondary">
          {asset.kind}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {asset.filename} · {(asset.size_bytes / 1024).toFixed(0)} KB
          {asset.page_count ? ` · ${asset.page_count} page${asset.page_count === 1 ? "" : "s"}` : ""}
          {asset.width && asset.height ? ` · ${asset.width}×${asset.height}` : ""}
        </span>
      </div>

      {["png", "jpeg"].includes(asset.kind) ? (
        <div
          className="relative mx-auto mt-4 max-h-[460px] w-fit max-w-full overflow-hidden rounded-xl border border-border bg-muted"
          style={{ aspectRatio: asset.width && asset.height ? `${asset.width} / ${asset.height}` : undefined }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`/engine/assets/${asset.id}`}
            alt={asset.alt_text || `Uploaded image ${asset.filename}`}
            className="max-h-[460px] w-auto max-w-full object-contain"
          />
          {boxes.map((f) => {
            const [x, y, w, h] = f.locator!.bbox!;
            return (
              <span
                key={f.id}
                title={`${CATEGORY_LABEL[f.category] ?? f.category} · ${TIER_LABEL[f.tier]}`}
                className={`pointer-events-none absolute rounded-sm border-2 ${BOX_COLOR[f.severity] ?? BOX_COLOR.low}`}
                style={{
                  left: `${(x / (asset.width || 1)) * 100}%`,
                  top: `${(y / (asset.height || 1)) * 100}%`,
                  width: `${(w / (asset.width || 1)) * 100}%`,
                  height: `${(h / (asset.height || 1)) * 100}%`,
                }}
              />
            );
          })}
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-border-strong bg-muted/30 p-4">
          <div>
            <p className="text-sm font-medium text-foreground">{asset.filename}</p>
            <p className="text-xs text-muted-foreground">
              Findings point to {asset.kind === "pdf" ? "a page and line" : "a section and paragraph"} in the extracted text below.
            </p>
          </div>
          <a className="btn btn-sm btn-secondary ml-auto" href={`/engine/assets/${asset.id}`} target="_blank" rel="noreferrer">
            {asset.kind === "docx" ? "Download this version" : "Open the file"}
          </a>
        </div>
      )}
      {["png", "jpeg"].includes(asset.kind) && (
        <p className="mt-3 text-xs text-muted-foreground">
          Alt text: {asset.alt_text ? `“${asset.alt_text}”` : "missing"} · boxes mark where the visual findings sit.
        </p>
      )}
      {canUpload && (
        <label className={`btn btn-sm btn-secondary mt-3 w-fit ${busy ? "pointer-events-none opacity-60" : "cursor-pointer"}`}>
          Upload new version
          <input
            type="file"
            className="sr-only"
            accept=".pdf,.docx,.png,.jpg,.jpeg"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void onUpload(file);
            }}
          />
        </label>
      )}
    </section>
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
    <div className="surface p-5">
      <p className="eyebrow mb-2">Reviewer decision</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grow space-y-1">
          <span className="text-xs font-medium text-foreground-secondary">
            Reviewer comment (required to request changes; override single findings below)
          </span>
          <input
            className="field h-[38px] px-3"
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
            className="btn btn-primary"
          >
            Approve &amp; sign
          </button>
          <button
            disabled={busy || !reason.trim()}
            onClick={() => void onReview("request_changes", reason)}
            className="btn btn-secondary"
          >
            Request changes
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
  allowance,
}: {
  busy: boolean;
  onRecheck: () => void;
  onSubmitReview: (() => void) | null;
  canSubmit: boolean;
  allowance: AiAllowance | null;
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        disabled={busy}
        onClick={onRecheck}
        className="btn btn-secondary"
      >
        Re-check
      </button>
      {onSubmitReview && canSubmit && (
        <button
          disabled={busy}
          onClick={onSubmitReview}
          className="btn btn-primary"
        >
          Submit for review <span aria-hidden className="btn-arrow">→</span>
        </button>
      )}
      {allowance && (
        <span className="ml-auto text-xs text-muted-foreground" title="AI-assisted checks reset at 00:00 UTC">
          AI checks today: {allowance.used} of {allowance.limit} used
        </span>
      )}
    </div>
  );
}

/** Why the AI checks did not run on this revision, in plain words. Rule-based checks always ran. */
function AiSkipped({ reason, allowance }: { reason: AiReason | null; allowance: AiAllowance }) {
  const resets = new Date(allowance.resets_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const ran = "Rule-based checks still ran on this revision; tone and implied claims were not reviewed.";
  switch (reason) {
    case "user_quota":
      if (allowance.limit === 0)
        return (
          <>
            <b className="font-semibold">AI checks are turned off for individual users in this workspace.</b> {ran}
          </>
        );
      return (
        <>
          <b className="font-semibold">You&apos;ve used all {allowance.limit} of your AI checks for today.</b> {ran} Your AI
          checks reset at {resets} (00:00 UTC).
        </>
      );
    case "workspace_quota":
      return (
        <>
          <b className="font-semibold">The workspace&apos;s AI checks for today ({allowance.workspace_limit}) are used up.</b>{" "}
          {ran} AI checks resume at {resets} (00:00 UTC).
        </>
      );
    case "provider_unavailable":
      return (
        <>
          <b className="font-semibold">The AI provider didn&apos;t answer.</b> It may be busy or rate-limited. {ran} Press
          Re-check in a few minutes; this did not use one of your AI checks.
        </>
      );
    case "time_budget":
      return (
        <>
          <b className="font-semibold">The AI checks ran out of time before they finished.</b> Rule-based checks still
          ran on this revision. Press Re-check to try the AI part again.
        </>
      );
    case "budget":
      return (
        <>
          <b className="font-semibold">This check reached its AI budget</b> (3 calls per 1,000 words). {ran}
        </>
      );
    case "no_provider":
      return (
        <>
          <b className="font-semibold">AI checks are off.</b> No AI provider is configured for this workspace. {ran}
        </>
      );
    default:
      return (
        <>
          <b className="font-semibold">AI checks are pending.</b> {ran} Press Re-check to run them.
        </>
      );
  }
}

const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

/** Where a finding sits in this text: the engine's offsets when they still match, else the first occurrence. */
function locate(content: string, f: Finding): [number, number] | null {
  if (!f.span_text) return null;
  if (content.slice(f.span_start, f.span_end) === f.span_text) return [f.span_start, f.span_end];
  const i = content.indexOf(f.span_text);
  return i < 0 ? null : [i, i + f.span_text.length];
}

/**
 * The copy with every open finding marked. Overlapping findings are split at
 * their boundaries instead of dropped: each piece knows all findings covering
 * it, overlaps get a deeper marker, and a click jumps to the most severe card.
 */
function ContentWithSpans({ content, findings }: { content: string; findings: Finding[] }) {
  const located = findings
    .filter((f) => f.status === "open")
    .map((f) => ({ f, at: locate(content, f) }))
    .filter((x): x is { f: Finding; at: [number, number] } => x.at !== null);

  const cuts = Array.from(new Set([0, content.length, ...located.flatMap((x) => x.at)])).sort((a, b) => a - b);
  const pieces = cuts.slice(0, -1).map((start, i) => {
    const end = cuts[i + 1];
    const covering = located
      .filter((x) => x.at[0] <= start && x.at[1] >= end)
      .map((x) => x.f)
      .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 1) - (SEVERITY_RANK[b.severity] ?? 1));
    return { text: content.slice(start, end), covering };
  });

  return (
    <p className="whitespace-pre-wrap font-serif text-[17px] leading-[28px]">
      {pieces.map((p, i) =>
        p.covering.length ? (
          <mark key={i} className={`${p.covering.length > 1 ? "marker-strong" : "marker"} bg-transparent text-foreground`}>
            <a
              href={`#finding-${p.covering[0].id}`}
              className="rounded-sm no-underline"
              title={p.covering.map((f) => `${CATEGORY_LABEL[f.category] ?? f.category} · ${TIER_LABEL[f.tier]}`).join("\n")}
            >
              {p.text}
            </a>
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        )
      )}
    </p>
  );
}

/** What changed between the previous revision and the one on screen (plan Must: revision diff). */
function RevisionDiff({ before, after, fromNo, toNo }: {
  before: string;
  after: string;
  fromNo?: number;
  toNo?: number;
}) {
  const tokens = useMemo(() => diffWords(before, after), [before, after]);
  const { added, removed } = diffSummary(tokens);
  const show = (t: DiffToken, i: number) => {
    if (t.op === "same") return <span key={i}>{t.text}</span>;
    return (
      <mark
        key={i}
        className={
          t.op === "add"
            ? "rounded-sm bg-success-bg px-0.5 font-medium text-success-fg"
            : "rounded-sm bg-danger-bg px-0.5 text-danger-fg line-through decoration-danger-fg/60"
        }
        title={t.op === "add" ? "added in this revision" : "removed in this revision"}
      >
        {t.text}
      </mark>
    );
  };
  return (
    <div>
      <p className="mb-3 text-xs text-muted-foreground">
        Changes from <span className="font-medium text-foreground">rev {fromNo}</span> to{" "}
        <span className="font-medium text-foreground">rev {toNo}</span> ·{" "}
        <span className="font-medium text-success-fg">+{added} word{added === 1 ? "" : "s"}</span> ·{" "}
        <span className="font-medium text-danger-fg">−{removed} word{removed === 1 ? "" : "s"}</span>
      </p>
      <p className="whitespace-pre-wrap font-serif text-[15px] leading-relaxed text-foreground">
        {tokens.map(show)}
      </p>
    </div>
  );
}

function FindingCard({
  f,
  disabled,
  active,
  assetKind,
  canResolve,
  onOverride,
  onAccept,
  onEdit,
  onDispute,
}: {
  f: Finding;
  disabled: boolean;
  active: boolean;
  assetKind: "pdf" | "docx" | "png" | "jpeg" | null;
  canResolve: boolean;
  onOverride?: (reason: string) => Promise<unknown>;
  onAccept: () => Promise<unknown>;
  onEdit: (replacement: string) => Promise<unknown>;
  onDispute: (reason: string) => Promise<unknown>;
}) {
  const [editText, setEditText] = useState(f.suggestion?.replace ?? "");
  const [reason, setReason] = useState("");
  const open = f.status === "open";
  const uploadedImage = assetKind === "png" || assetKind === "jpeg";
  // Where the fix can happen: Word files are edited in place; a PDF, or anything
  // in the picture itself, must be fixed in the source file (alt text lives here).
  const inAltText = uploadedImage && f.locator?.region === "alt text";
  const fixInSource = assetKind === "pdf" || (uploadedImage && !inAltText);
  const canAccept = !uploadedImage && !fixInSource;
  const where = describeLocator(f.locator);

  return (
    <div
      id={`finding-${f.id}`}
      className={`finding scroll-mt-28 rounded-xl border bg-card p-5 transition-[border-color,box-shadow] duration-150 ${
        open && f.severity === "high"
          ? "border-danger-border border-l-[3px]"
          : open
            ? "border-border hover:border-border-strong hover:shadow-card"
            : "border-border opacity-65 shadow-none"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <CategoryBadge category={f.category} />
        <LevelBadge tier={f.tier} severity={f.severity} />
        <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground-secondary">
          {f.checker}
        </span>
        {!open && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize text-muted-foreground">
            {f.status}
          </span>
        )}
      </div>

      {where && (
        <p className="mt-2 inline-flex items-center rounded-full border border-border bg-muted/50 px-2.5 py-1 text-[11px] font-medium text-foreground-secondary">
          {where}
        </p>
      )}

      {f.span_text && (
        <p className="mt-3 border-l-2 border-brand-highlight pl-3 font-serif text-[15px] italic text-foreground">
          “{f.span_text}”
        </p>
      )}

      <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">{f.explanation}</p>

      {f.citations?.length > 0 && (
        <div className="mt-2 space-y-1">
          {f.citations.map((c, i) => (
            <p key={i} className="text-xs text-muted-foreground">
              <span className="font-mono font-medium text-brand">
                {({ fact: "Fact ", rule: "Rule ", term: "Term ", pack: "Clause " }[c.type] ?? "") + c.id}
                {c.version ? ` v${c.version}` : ""}:
              </span>{" "}
              {c.type === "pack" && c.ref ? (
                <>
                  <span className="font-medium text-foreground">{c.source} {c.ref}</span>{" "}
                  {c.url && (
                    <a href={c.url} target="_blank" rel="noreferrer" className="link ml-1">
                      read the clause
                    </a>
                  )}{" "}
                </>
              ) : null}
              {c.excerpt}
              {c.valid_to ? ` (valid until ${c.valid_to})` : ""}
              {c.confidential ? " · confidential" : ""}
              {c.version && c.current_version && c.current_version > c.version ? (
                <Link
                  href="/kb"
                  className="ml-1.5 inline-flex rounded-full bg-warning-bg px-2 py-0.5 text-[11px] font-semibold text-warning-fg no-underline"
                  title="This finding shows the version it was checked against. Re-check to use the current one."
                >
                  Updated since (now v{c.current_version})
                </Link>
              ) : null}
            </p>
          ))}
        </div>
      )}

      <p className="mt-2 text-[11px] text-muted-foreground">
        {f.provenance.model
          ? `checked by ${f.provenance.model}`
          : "deterministic rule check"} · contract {f.provenance.prompt_version}
      </p>

      {active && open && onOverride && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <input
            className="field h-[30px] w-auto grow px-2 text-xs"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="Override reason"
            placeholder="Override reason: rule doesn't apply / rule unclear / fact outdated / AI misread"
          />
          <button
            disabled={disabled || !reason.trim()}
            title="Explicit human override — always logged with a reason"
            onClick={() => void onOverride(reason)}
            className="btn btn-sm btn-warning"
          >
            Override finding
          </button>
        </div>
      )}

      {active && open && canResolve && fixInSource && (
        <div className="mt-3 space-y-2.5 border-t border-border pt-3">
          <p className="rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {assetKind === "pdf"
              ? "Canonry can't edit a PDF. Fix this in the source document, export the PDF again and use Upload new version, or dispute the finding."
              : "This is part of the image. Change it in the design file and use Upload new version, or dispute the finding."}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="field h-[30px] w-auto grow px-2 text-xs"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Dispute reason: rule doesn't apply / unclear rule / fact outdated / misread"
            />
            <button
              disabled={disabled || !reason.trim()}
              onClick={() => void onDispute(reason)}
              className="btn btn-sm btn-secondary"
            >
              Dispute
            </button>
          </div>
        </div>
      )}

      {active && open && canResolve && !fixInSource && (
        <div className="mt-3 space-y-2.5 border-t border-border pt-3">
          {assetKind === "docx" && (
            <p className="text-xs text-muted-foreground">
              Fixes are made inside your Word file, keeping its formatting. Download the fixed file from the file panel.
            </p>
          )}
          {f.suggestion?.replace && canAccept && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Suggested fix:</span>
              <code className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">{f.suggestion.replace}</code>
              <button
                disabled={disabled}
                onClick={() => void onAccept()}
                className="btn btn-sm btn-primary"
              >
                Accept fix
              </button>
            </div>
          )}
          {f.suggestion?.operation === "remove" && canAccept && (
            <button
              disabled={disabled}
              onClick={() => void onAccept()}
              className="btn btn-sm btn-primary"
            >
              Remove the flagged phrase
            </button>
          )}
          {inAltText && (
            <p className="text-xs text-muted-foreground">
              Write better alt text below: say what the image shows, in one sentence.
            </p>
          )}
          {/* Secondary paths stay folded away until wanted; open by default when there is no one-click fix. */}
          <details className="group" open={!(f.suggestion?.replace || f.suggestion?.operation === "remove")}>
            <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
              Fix it in your own words, or dispute
            </summary>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <input
              className="field h-[30px] w-auto grow px-2 text-xs"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              placeholder="Replace the flagged phrase in your own words (optional)"
            />
            <button
              disabled={disabled || !editText.trim()}
              onClick={() => void onEdit(editText)}
              className="btn btn-sm btn-secondary"
            >
              Apply my edit
            </button>
            <input
              className="field h-[30px] w-auto grow px-2 text-xs"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Dispute reason: rule doesn't apply / unclear rule / fact outdated / AI misread"
            />
            <button
              disabled={disabled || !reason.trim()}
              onClick={() => void onDispute(reason)}
              className="btn btn-sm btn-secondary"
            >
              Dispute
            </button>
          </div>
          </details>
        </div>
      )}
    </div>
  );
}

function TrailCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="surface p-5">
      <h3 className="eyebrow mb-3">{title}</h3>
      <ul className="list-disc space-y-1.5 pl-4 text-xs text-foreground-secondary marker:text-border-strong">{children}</ul>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <li className="list-none text-muted-foreground">{text}</li>;
}
