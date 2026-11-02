"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, GitCompare, Info, Sparkles, TriangleAlert } from "lucide-react";
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
import { LevelBadge, RiskBadge, StatusBadge } from "@/components/fx";
import { AiLoadingScreen } from "@/components/ai-loading";
import { JourneySteps, NextStep, VerifyLink } from "@/components/journey";
import { rememberSent } from "@/components/guide";
import { markIssueHandled } from "@/components/start-here";
import { ROLE_LABEL, roleHome } from "@/lib/roles";
import { useIdentity } from "@/components/identity";

export function SubmissionDetailClient({ sid }: { sid: string }) {
  const [d, setD] = useState<SubmissionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const { me } = useIdentity();
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [revIdx, setRevIdx] = useState(-1); // -1 => latest
  const [diffMode, setDiffMode] = useState(false);
  const [tierFilter, setTierFilter] = useState<"all" | "definite" | "likely" | "consider">("all");
  const [pocId, setPocId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api<SubmissionDetail>(`/submissions/${sid}`));
      setMissing(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
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
  const mustFix = openFindings.filter((f) => f.severity === "high").length;
  const acceptable = openFindings.filter(oneClickFix).length;
  // the same number on a highlight and on its card
  const issueNumber = new Map(openFindings.map((f, i) => [f.id, i + 1] as const));
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
      // someone (or another tab) changed it first: show what is true now, keep the message
      if (e instanceof ApiError && e.status === 409) await load();
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

  async function acceptAll() {
    setChecking(true);
    setBusy(true);
    setError(null);
    try {
      for (let round = 0; round < 20; round++) {
        const cur = await api<SubmissionDetail>(`/submissions/${sid}`);
        const kind = cur.asset?.kind;
        if (kind === "pdf" || kind === "png" || kind === "jpeg") break; // fixed in the source file
        const next = cur.findings.find(
          (f) => f.status === "open" && oneClickFix(f),
        );
        if (!next || !cur.latest_revision) break;
        await api(`/submissions/${sid}/resolve`, {
          method: "POST",
          json: { revision_id: cur.latest_revision.id, finding_id: next.id, action: "accept" },
        });
        markIssueHandled();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      await load();
      setBusy(false);
      setChecking(false);
    }
  }

  async function submitForReview() {
    await act(async () => {
      await api(`/submissions/${sid}/submit-review`, { method: "POST" });
      rememberSent(sid); // the guide points the reviewer at this draft
    });
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
      if (e instanceof ApiError && e.status === 409) await load();
    } finally {
      setBusy(false);
    }
  }

  if (missing && !d) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <p className="eyebrow">Not found</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">This submission isn&apos;t available</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          The link may be wrong, the demo data may have been reset, or your role can&apos;t see it (agency partners
          see only their own work).
        </p>
        <Link href={roleHome(me?.role)} className="btn btn-primary mt-6">
          Go to your work <span aria-hidden className="btn-arrow">→</span>
        </Link>
      </section>
    );
  }
  if (error && !d) {
    return (
      <div role="alert" className="mx-auto max-w-xl space-y-3 rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">
        <p>{error}</p>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => { setError(null); void load(); }}>
          Try again
        </button>
      </div>
    );
  }
  if (!d) return <p className="text-sm text-muted-foreground" aria-busy="true">Loading the submission…</p>;

  const s = d.submission;
  // the reviewer's latest "request changes", so the writer sees what to change
  const sentBack = [...d.approvals].reverse().find((a) => a.action === "request_changes") ?? null;
  // what the engine understood about this content before checking it (shown when the engine sends it)
  const profile = d.check?.profile ?? null;
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
        {canReview && <RiskBadge risk={s.risk} />}
        <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-foreground-secondary">
          {sourceLabel(s.channel)} · {sourceLabel(s.source_type)}
        </span>
      </div>
      <JourneySteps status={s.status} open={openFindings.length} />

      {error && (
        <p role="alert" className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-fg">
          {error}
        </p>
      )}

      {s.status === "Changes requested" && sentBack && (
        <section role="note" className="rounded-2xl border border-warning-border bg-warning-bg p-4 sm:p-5">
          <p className="eyebrow text-warning-fg">Sent back by the reviewer</p>
          <p className="mt-1 text-base font-semibold text-foreground">
            {sentBack.reason ? `“${sentBack.reason}”` : "The reviewer asked for changes."}
          </p>
          <p className="mt-1 text-xs text-foreground-secondary">
            {sentBack.reviewer_name ?? sentBack.reviewer}. Make the changes, then send it for review again.
          </p>
        </section>
      )}

      {d.poc || pocId ? (
        <NextStep
          tone="success"
          title="Approved and signed"
          actions={
            <>
              <VerifyLink pocId={d.poc?.id ?? pocId ?? ""} />
              {d.poc?.content_kind === "file" && (
                <a className="btn btn-secondary" href={`/engine/submissions/${sid}/proof-file`} download>
                  Download the approved file
                </a>
              )}
            </>
          }
        >
          This version is locked. Anyone can check that a published copy matches it on the public verify page
          {d.poc?.content_kind === "file" ? ", and the approved file carries its proof inside it." : "."}
        </NextStep>
      ) : inReview ? (
        canReview ? (
          <NextStep title="Approve it, or send it back">
            Read the issues below, then decide. Approving signs it with a Proof of Compliance that anyone can verify.
          </NextStep>
        ) : (
          <NextStep tone="muted" title="Waiting for a reviewer">
            It is locked while a reviewer looks at it. To finish the demo yourself, open the menu at the top right,
            switch to <strong>Reviewer</strong>, and open this draft from the review queue.
          </NextStep>
        )
      ) : editable && (canResolve || canReview) && showActionsForRev ? (
        openFindings.length > 0 ? (
          <NextStep
            title={`${openFindings.length} issue${openFindings.length === 1 ? "" : "s"} to handle`}
            progress={{ done: d.decisions.length, total: d.decisions.length + openFindings.length }}
            actions={
              <>
                <a href={`#finding-${openFindings[0].id}`} className="btn btn-primary">
                  Go to issue 1 <span aria-hidden className="btn-arrow">→</span>
                </a>
                {acceptable > 1 && (
                  <button type="button" data-guide="accept-all" disabled={busy} onClick={() => void acceptAll()} className="btn btn-secondary">
                    Accept all {acceptable} suggested fixes
                  </button>
                )}
                {d.allowed.submit && (
                  <button type="button" data-guide="send-review" disabled={busy} onClick={() => void submitForReview()} className="btn btn-ghost">
                    Send for review anyway
                  </button>
                )}
                <button type="button" disabled={busy} onClick={() => void recheck()} className="btn btn-ghost">
                  Re-check
                </button>
              </>
            }
          >
            For each one: accept the suggested fix, write your own, or dispute it if Canonry got it wrong. Then send it
            to a reviewer.
            {mustFix > 0 && (
              <>
                {" "}
                <strong className="text-foreground">
                  {mustFix} {mustFix === 1 ? "is" : "are"} marked Must fix
                </strong>
                : a reviewer can&apos;t approve while {mustFix === 1 ? "it is" : "they are"} open.
              </>
            )}
          </NextStep>
        ) : (
          <NextStep
            title="Ready for review"
            progress={d.decisions.length ? { done: d.decisions.length, total: d.decisions.length } : undefined}
            actions={
              <>
                {d.allowed.submit && (
                  <button type="button" data-guide="send-review" disabled={busy} onClick={() => void submitForReview()} className="btn btn-primary">
                    Send for review <span aria-hidden className="btn-arrow">→</span>
                  </button>
                )}
                <button type="button" disabled={busy} onClick={() => void recheck()} className="btn btn-secondary">
                  Re-check
                </button>
              </>
            }
          >
            {d.decisions.length ? "Every issue is handled." : "Canonry found nothing to fix."} A reviewer approves it and
            signs it.
          </NextStep>
        )
      ) : null}

      {profile?.summary && (
        <section aria-label="What Canonry understood" className="surface flex flex-wrap items-start gap-3 p-4">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="eyebrow">What Canonry understood</p>
            <p className="mt-1 text-sm leading-relaxed text-foreground">{profile.summary}</p>
            {(profile.kind || profile.intent || profile.format) && (
              <p className="mt-2 flex flex-wrap gap-1.5">
                {[profile.format_label, profile.kind_label, profile.intent, profile.audience && `for ${profile.audience}`]
                  .filter(Boolean)
                  .map((t) => (
                    <span key={String(t)} className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground-secondary">
                      {String(t)}
                    </span>
                  ))}
              </p>
            )}
            {profile.checks?.length ? (
              <details className="group/checks mt-2">
                <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-brand hover:underline [&::-webkit-details-marker]:hidden">
                  <ChevronRight className="size-3.5 transition-transform group-open/checks:rotate-90" aria-hidden />
                  Which checks ran, and why
                </summary>
                <ul className="mt-2 space-y-1 text-xs">
                  {profile.checks.map((c) => (
                    <li key={c.check} className={c.applies ? "text-foreground-secondary" : "text-muted-foreground"}>
                      <span className={`font-medium ${c.applies ? "text-success-fg" : ""}`}>{c.applies ? "Checked" : "Skipped"}:</span>{" "}
                      {c.why}
                    </li>
                  ))}
                </ul>
              </details>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">
                Canonry reads what the content is and who it is for before applying the brand rules, so only the rules
                that fit this kind of content are checked.
              </p>
            )}
          </div>
        </section>
      )}

      {d.check?.status === "ai_pending" && (
        <p role="status" className="flex gap-2 text-xs leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            <AiSkipped reason={d.check.ai_reason} allowance={d.ai_allowance} />{" "}
            <Link href="/insights" className="underline underline-offset-2 hover:text-foreground">
              AI status
            </Link>
          </span>
        </p>
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

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] lg:items-start">
      {/* ---- content with span highlighting ---- */}
      <section className="paper pb-5 pl-12 pr-4 pt-4 sm:pl-14 sm:pr-6 lg:sticky lg:top-24 lg:max-h-[calc(100dvh-7rem)] lg:overflow-auto">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="eyebrow mr-auto">Your content</h2>
          <button
            type="button"
            onClick={() => setDiffMode((v) => !v)}
            disabled={!prevRev}
            aria-pressed={diffMode}
            title={prevRev ? `Show what changed from rev ${prevRev.revision_no} to rev ${rev?.revision_no}` : "The first revision has nothing before it"}
            className={`btn btn-sm ${diffMode ? "btn-primary" : "btn-secondary"}`}
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
          <ContentWithSpans
            content={rev?.content ?? ""}
            findings={rev?.id === d.latest_revision?.id ? d.findings : []}
            numbers={issueNumber}
          />
        )}
      </section>

      {/* ---- findings ---- */}
      <section className="space-y-2.5">
        <h2 className="section-title">
          {showActionsForRev ? `Issues (${openFindings.length} open)` : "Issues on this earlier version"}
        </h2>
        {d.findings.length === 0 && (
          <p className="rounded-xl border border-dashed border-border-strong p-8 text-center text-sm text-muted-foreground">
            No findings on this revision — all checks passed or every issue was resolved.
          </p>
        )}
        {showActionsForRev && d.findings.length > 0 && (
          <div role="group" aria-label="Show issues" className="flex flex-wrap gap-1.5">
            {(["all", "definite", "likely", "consider"] as const).map((t) => {
              const count = t === "all" ? openFindings.length : openFindings.filter((f) => f.tier === t).length;
              if (t !== "all" && count === 0) return null;
              const on = tierFilter === t;
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setTierFilter(t)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    on ? "border-foreground bg-foreground text-background" : "border-border text-foreground-secondary hover:border-border-strong"
                  }`}
                >
                  {t === "all" ? "All" : TIER_LABEL[t]} · {count}
                </button>
              );
            })}
          </div>
        )}
        {(d.asset?.kind === "pdf" || d.asset?.kind === "png" || d.asset?.kind === "jpeg") && showActionsForRev && editable && (
          <p className="rounded-xl border border-border bg-muted/60 px-4 py-3 text-sm text-foreground-secondary">
            {d.asset.kind === "pdf"
              ? "This is a PDF, which Canonry can't edit. Fix issues in your source document, export it again and use Upload new version above."
              : "Issues in the picture itself are fixed in your design file: change it and use Upload new version above. Alt text can be fixed here."}
          </p>
        )}
        {d.findings.filter((f) => tierFilter === "all" || f.status !== "open" || f.tier === tierFilter).map((f) => (
          <FindingCard
            key={f.id}
            f={f}
            index={issueNumber.get(f.id)}
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
                }).then(markIssueHandled)
              )
            }
            onEdit={(replacement) =>
              act(() =>
                api(`/submissions/${sid}/resolve`, {
                  method: "POST",
                  json: { revision_id: rev?.id, finding_id: f.id, action: "edit", replacement },
                }).then(markIssueHandled)
              )
            }
            onDispute={(reason) =>
              act(() =>
                api(`/submissions/${sid}/resolve`, {
                  method: "POST",
                  json: { revision_id: rev?.id, finding_id: f.id, action: "dispute", reason },
                }).then(markIssueHandled)
              )
            }
          />
        ))}
      </section>

      </div>

      {/* ---- trail ---- */}
      <details className="group/hist surface p-4">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-foreground [&::-webkit-details-marker]:hidden">
          <ChevronRight className="size-4 transition-transform group-open/hist:rotate-90" aria-hidden />
          History: decisions and approvals
          <span className="ml-1 text-xs font-normal text-muted-foreground">
            ({d.decisions.length + d.approvals.length})
          </span>
        </summary>
      <section className="mt-3 grid gap-3 md:grid-cols-2">
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
      </details>

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
      {openHigh && (
        <div role="note" className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg">
          <span className="mr-auto">
            Issues marked <strong>Must fix</strong> are still open, so it can&apos;t be approved yet. Send it back to the
            writer, or override each one below with a reason.
          </span>
          <button
            type="button"
            disabled={busy}
            data-guide="send-back"
            onClick={() => void onReview("request_changes", reason.trim() || "Please fix the issues marked Must fix.")}
            className="btn btn-sm btn-secondary"
          >
            Send back to the writer
          </button>
        </div>
      )}
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
            disabled={busy || openHigh}
            title={openHigh ? "Resolve or override the Must fix issues first" : ""}
            data-guide="approve"
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
function ContentWithSpans({ content, findings, numbers }: {
  content: string;
  findings: Finding[];
  numbers?: Map<string, number>;
}) {
  const endsAt = new Map<string, number>();
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
    return { text: content.slice(start, end), covering, end };
  });
  for (const x of located) endsAt.set(x.f.id, x.at[1]);

  return (
    <p className="whitespace-pre-wrap font-serif text-[17px] leading-[28px] [overflow-wrap:anywhere]">
      {pieces.map((p, i) =>
        p.covering.length ? (
          <mark key={i} className={`${HIGHLIGHT[topTier(p.covering)]} text-foreground`}>
            <a
              href={`#finding-${p.covering[0].id}`}
              className="rounded-sm no-underline"
              title={p.covering.map((f) => `${CATEGORY_LABEL[f.category] ?? f.category} · ${TIER_LABEL[f.tier]}`).join("\n")}
            >
              {p.text}
              {p.covering
                .filter((f) => endsAt.get(f.id) === p.end && numbers?.has(f.id))
                .sort((a, b) => (numbers!.get(a.id) ?? 0) - (numbers!.get(b.id) ?? 0))
                .map((f) => (
                  <sup
                    key={f.id}
                    className="ml-0.5 rounded-full bg-foreground px-1 font-sans text-[10px] font-bold not-italic text-background"
                  >
                    {numbers!.get(f.id)}
                  </sup>
                ))}
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
      <p className="whitespace-pre-wrap font-serif text-[15px] leading-relaxed text-foreground [overflow-wrap:anywhere]">
        {tokens.map(show)}
      </p>
    </div>
  );
}

/** A fix Canonry applies by itself (a replacement or a removal). Written advice ("rewrite") is not one. */
function oneClickFix(f: Finding): boolean {
  if (f.suggestion?.operation === "rewrite") return false;
  return Boolean(f.suggestion?.replace) || f.suggestion?.operation === "remove";
}

/** A plain headline per issue type: what is wrong, in words a newcomer knows. */
const HEADLINE: Record<string, string> = {
  outdated_term: "Old product or term name",
  banned_term: "A word Quillmark doesn't use",
  contradicted_claim: "Doesn't match our approved facts",
  outdated_claim: "Out-of-date claim",
  unsupported_claim: "Claim with no approved source",
  missing_cta: "No call to action",
  missing_disclaimer: "Missing disclaimer",
  confidential_leak: "Confidential information",
  tone: "Sounds too pushy",
  readability: "Hard to read",
  logo_outdated: "Old logo",
  logo_distorted: "Logo is stretched or tilted",
  logo_recoloured: "Logo colours changed",
  logo_busy_background: "Logo on a busy background",
  logo_clear_space: "Logo needs more space",
  logo_too_small: "Logo too small",
  logo_missing: "No logo found",
  off_brand_colour: "Colour outside the brand palette",
  low_text_contrast: "Text is hard to read",
  missing_alt_text: "Missing image description",
  alt_text_quality: "Image description needs work",
  free_claim: "\u201cFree\u201d with a cost attached",
  bait_advertising: "Offer that may not be available",
  comparative_advertising: "Comparison with a rival",
  endorsement_disclosure: "Endorsement without a disclosure",
};

const TIER_ORDER: Record<string, number> = { definite: 0, likely: 1, consider: 2 };
function topTier(fs: Finding[]): string {
  return fs.map((f) => f.tier).sort((a, b) => (TIER_ORDER[a] ?? 3) - (TIER_ORDER[b] ?? 3))[0] ?? "consider";
}
/** Severity is shown by colour AND line style, never colour alone. */
const HIGHLIGHT: Record<string, string> = {
  definite: "rounded-sm bg-danger-bg/70 underline decoration-danger-fg decoration-2 underline-offset-4",
  likely: "rounded-sm bg-warning-bg/70 underline decoration-warning-fg decoration-dashed decoration-2 underline-offset-4",
  consider: "rounded-sm bg-muted underline decoration-muted-foreground decoration-dotted decoration-2 underline-offset-4",
};

const DISPUTE_REASONS = [
  "The rule doesn't apply here",
  "The rule is unclear",
  "The fact is out of date",
  "Canonry misread the text",
];

/** Dispute with a reason chosen from a short list, plus an optional note. */
function DisputeControl({ disabled, onDispute }: { disabled: boolean; onDispute: (reason: string) => Promise<unknown> }) {
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");
  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <select
        aria-label="Why do you disagree?"
        className="field h-[30px] w-auto px-2 text-xs"
        value={choice}
        onChange={(e) => setChoice(e.target.value)}
      >
        <option value="">Why do you disagree?</option>
        {DISPUTE_REASONS.map((r) => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
      <input
        className="field h-[30px] w-auto grow px-2 text-xs"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="Note for the reviewer (optional)"
        placeholder="Note for the reviewer (optional)"
      />
      <button
        type="button"
        disabled={disabled || !choice}
        onClick={() => void onDispute(note.trim() ? `${choice}: ${note.trim()}` : choice)}
        className="btn btn-sm btn-secondary"
      >
        Dispute
      </button>
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  "ai-assisted": "AI-assisted", "in-house": "In-house", agency: "Agency", social: "Social", blog: "Blog",
  email: "Email", web: "Web", ad: "Ad", print: "Print", press: "Press release",
};
function sourceLabel(v: string): string {
  return SOURCE_LABEL[v] ?? v.charAt(0).toUpperCase() + v.slice(1);
}

/** The explanation without engine reference codes such as "(rule TERM-04; fact F-001)":
 *  a newcomer reads the reason; the codes stay under "Why is this flagged?". */
function plainExplanation(text: string): string {
  return text
    .replace(/\s*\((?:rule|fact|facts|source|voice rule|term)\b[^()]*\)/gi, "")
    .replace(/\s*\((?:[A-Z]{1,6}-\d[\w.\-/]*(?:[;,]\s*)?)+\)/g, "")
    .replace(/\s+([.,;:])/g, "$1")
    .trim();
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
  index,
}: {
  index?: number;
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
  const [reason, setReason] = useState(""); // reviewer override reason
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
        {index !== undefined && open && (
          <span
            aria-label={`Issue ${index}`}
            className="grid size-6 shrink-0 place-items-center rounded-full bg-foreground text-[11px] font-bold text-background"
          >
            {index}
          </span>
        )}
        <LevelBadge tier={f.tier} severity={f.severity} />
        {!open && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize text-muted-foreground">
            {f.status}
          </span>
        )}
      </div>

      <h3 className="mt-2 text-base font-semibold leading-snug text-foreground">
        {HEADLINE[f.category] ?? f.title ?? CATEGORY_LABEL[f.category] ?? f.category.replace(/_/g, " ")}
      </h3>

      {where && (
        <p className="mt-2 inline-flex items-center rounded-full border border-border bg-muted/50 px-2.5 py-1 text-[11px] font-medium text-foreground-secondary">
          {where}
        </p>
      )}

      {f.span_text && (
        <p className="mt-3 border-l-2 border-brand-highlight pl-3 font-serif text-[15px] italic text-foreground [overflow-wrap:anywhere]">
          “{f.span_text}”
        </p>
      )}

      <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">{plainExplanation(f.explanation)}</p>

      <details className="group/why mt-2">
        <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-brand hover:underline [&::-webkit-details-marker]:hidden">
          <ChevronRight className="size-3.5 transition-transform group-open/why:rotate-90" aria-hidden />
          Why is this flagged?
        </summary>
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
        <p className="mt-1 text-[11px] text-muted-foreground">Checker: {f.checker}</p>
      </details>

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
          <p className="text-xs text-muted-foreground">
            Fix this in your source file, then use <strong className="font-medium text-foreground">Upload new version</strong>.
            Or dispute it:
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <DisputeControl disabled={disabled} onDispute={onDispute} />
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
          {f.suggestion?.operation === "rewrite" && f.suggestion.replace && (
            <p className="rounded-lg bg-muted/60 px-3 py-2 text-sm text-foreground-secondary">
              <span className="font-medium text-foreground">How to fix: </span>
              {f.suggestion.replace}
            </p>
          )}
          {f.suggestion?.replace && f.suggestion.operation !== "rewrite" && canAccept && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Suggested fix:</span>
              <code className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">{f.suggestion.replace}</code>
              <button
                disabled={disabled}
                data-guide={index === 1 ? "accept" : undefined}
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
          <details className="group" open={!oneClickFix(f)}>
            <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
              Fix it in your own words, or dispute
            </summary>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <input
              className="field h-[30px] w-auto grow px-2 text-xs"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              aria-label="Your replacement for the flagged phrase"
              placeholder="Replace the flagged phrase in your own words (optional)"
            />
            <button
              disabled={disabled || !editText.trim()}
              onClick={() => void onEdit(editText)}
              className="btn btn-sm btn-secondary"
            >
              Apply my edit
            </button>
            <DisputeControl disabled={disabled} onDispute={onDispute} />
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
