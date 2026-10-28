"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { History, RotateCcw } from "lucide-react";
import {
  api,
  ApiError,
  type HistoryEntry,
  type ImpactItem,
  type KBEntity,
  type KBKind,
  type KBWriteResult,
  type RulePreview,
} from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Field = {
  key: string;
  label: string;
  type: "text" | "textarea" | "select" | "date" | "checkbox";
  options?: string[];
  required?: boolean;
  createOnly?: boolean;
  placeholder?: string;
};

// The editable fields per kind, mirroring the engine's validation (knowledge.py).
export const FIELDS: Record<KBKind, Field[]> = {
  rules: [
    { key: "id", label: "Rule id", type: "text", createOnly: true, placeholder: "Leave empty to number it automatically" },
    { key: "category", label: "Category", type: "text", required: true, placeholder: "e.g. Brand, Claims, Voice" },
    { key: "statement", label: "Rule", type: "textarea", required: true, placeholder: "One checkable requirement" },
    { key: "do_example", label: "Do example", type: "text" },
    { key: "dont_example", label: "Don’t example", type: "text" },
    { key: "severity", label: "Severity", type: "select", options: ["low", "medium", "high"] },
    { key: "status", label: "Status", type: "select", options: ["approved", "draft"] },
  ],
  facts: [
    { key: "text", label: "Fact", type: "textarea", required: true, placeholder: "e.g. 2,300+ active customer teams" },
    { key: "category", label: "Category", type: "text", required: true, placeholder: "e.g. product, pricing" },
    { key: "owner", label: "Owner", type: "text", required: true, placeholder: "Who keeps it true" },
    { key: "source", label: "Source", type: "text", required: true, placeholder: "Where it comes from" },
    { key: "valid_from", label: "Valid from", type: "date" },
    { key: "valid_to", label: "Expires on", type: "date" },
    { key: "confidential", label: "Confidential (never published, cited as an excerpt only)", type: "checkbox" },
  ],
  terms: [
    { key: "preferred", label: "Use this", type: "text", placeholder: "e.g. team members" },
    { key: "banned_or_check", label: "Instead of (comma-separated)", type: "text", placeholder: "e.g. employees, staff" },
    { key: "note", label: "Why", type: "text" },
    { key: "severity", label: "Severity", type: "select", options: ["low", "medium", "high"] },
  ],
};

const NOUN: Record<KBKind, string> = { rules: "rule", facts: "fact", terms: "term" };

function initialValues(kind: KBKind, entity: KBEntity | null): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const f of FIELDS[kind]) {
    const v = entity ? (entity as Record<string, unknown>)[f.key] : undefined;
    if (f.type === "checkbox") out[f.key] = Boolean(v);
    else if (f.type === "select") out[f.key] = (v as string) ?? f.options?.[f.key === "status" ? 0 : 1] ?? "";
    else out[f.key] = v == null ? "" : String(v);
  }
  return out;
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Create or edit a rule, fact or term. Editing always asks why. */
export function EntityDialog({
  kind,
  entity,
  open,
  onOpenChange,
  onSaved,
  onReload,
}: {
  kind: KBKind;
  entity: KBEntity | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (result: KBWriteResult) => void;
  onReload: () => void;
}) {
  const [values, setValues] = useState(() => initialValues(kind, entity));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const editing = entity !== null;

  useEffect(() => {
    if (open) {
      setValues(initialValues(kind, entity));
      setReason("");
      setError(null);
      setConflict(false);
      setPreview(null);
    }
  }, [open, kind, entity]);

  const missing = FIELDS[kind].some((f) => f.required && !String(values[f.key] ?? "").trim());
  const needsWord = kind === "terms" && !String(values.preferred).trim() && !String(values.banned_or_check).trim();
  const canSave = !busy && !missing && !needsWord && (!editing || reason.trim().length >= 3);

  async function previewImpact() {
    if (!entity) return;
    setPreviewBusy(true);
    setError(null);
    try {
      setPreview(
        await api<RulePreview>(`/rules/${entity.id}/preview-change`, {
          method: "POST",
          json: {
            statement: values.statement,
            do_example: values.do_example,
            dont_example: values.dont_example,
          },
        })
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPreviewBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { ...values, reason: reason.trim() || undefined };
      if (editing) delete body.id;
      const result = editing
        ? await api<KBWriteResult>(`/kb/${kind}/${entity.id}`, {
            method: "PUT",
            json: { ...body, expected_version: entity.version },
          })
        : await api<KBWriteResult>(`/kb/${kind}`, { method: "POST", json: body });
      onSaved(result);
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
      setConflict(e instanceof ApiError && e.status === 409);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto bg-card sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold tracking-tight">
            {editing ? `Edit ${NOUN[kind]} ${entity.id}` : `New ${NOUN[kind]}`}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? `Saving creates version ${entity.version + 1}. Version ${entity.version} stays in the history, and findings that cited it keep showing it.`
              : "It takes effect on the next check."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSave) void save();
          }}
        >
          {FIELDS[kind]
            .filter((f) => !(editing && f.createOnly))
            .map((f) => (
              <FieldInput key={f.key} field={f} value={values[f.key]} onChange={(v) => setValues((s) => ({ ...s, [f.key]: v }))} />
            ))}

          {editing && (
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-foreground">Why are you changing it? (required)</span>
              <input
                className="field h-10 px-3"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Price changed on 1 Oct 2026"
              />
            </label>
          )}

          {kind === "rules" && editing && (
            <div className="rounded-xl border border-border bg-muted/40 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-foreground">Rule test</span>
                <span className="text-xs text-muted-foreground">
                  Which shipped content this change would affect, before you save it.
                </span>
                <button
                  type="button"
                  onClick={() => void previewImpact()}
                  disabled={previewBusy}
                  className="btn btn-sm btn-secondary ml-auto"
                >
                  {previewBusy ? "Checking…" : "Preview impact"}
                </button>
              </div>
              {preview && (
                <div className="mt-2 space-y-1.5 text-xs">
                  <p>
                    {preview.impacted.new_breakages > 0 ? (
                      <b className="text-warning-fg">
                        {preview.impacted.new_breakages} approved item
                        {preview.impacted.new_breakages === 1 ? "" : "s"} would newly break.
                      </b>
                    ) : (
                      <span className="text-muted-foreground">No approved content would newly break.</span>
                    )}{" "}
                    {preview.impacted.resolved > 0 && (
                      <span className="text-success-fg">
                        {preview.impacted.resolved} would stop being flagged.
                      </span>
                    )}
                  </p>
                  {preview.impacted_approved_content.length > 0 ? (
                    <ul className="space-y-1">
                      {preview.impacted_approved_content.slice(0, 6).map((i) => (
                        <li key={i.submission_id} className="text-muted-foreground">
                          <Link href={`/submissions/${i.submission_id}`} className="link font-medium">
                            {i.title}
                          </Link>{" "}
                          — {i.because}{" "}
                          {preview.new_breakages.some((n) => n.submission_id === i.submission_id) && (
                            <span className="ml-1 rounded-full bg-warning-bg px-1.5 py-0.5 text-[10px] font-semibold text-warning-fg">
                              newly affected
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground">
                      Nothing approved contains the words in the current don’t-example.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {error && (
            <div role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
              {error}
              {conflict && (
                <button
                  type="button"
                  onClick={() => {
                    onReload();
                    onOpenChange(false);
                  }}
                  className="ml-2 font-semibold underline underline-offset-2"
                >
                  Reload
                </button>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn btn-secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!canSave}>
              {busy ? "Saving…" : editing ? `Save as v${entity.version + 1}` : `Add ${NOUN[kind]}`}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function FieldInput({ field, value, onChange }: { field: Field; value: string | boolean; onChange: (v: string | boolean) => void }) {
  const label = (
    <span className="text-xs font-semibold text-foreground">
      {field.label}
      {field.required ? " *" : ""}
    </span>
  );
  if (field.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-[var(--brand)]" />
        {field.label}
      </label>
    );
  }
  return (
    <label className="block space-y-1">
      {label}
      {field.type === "textarea" ? (
        <textarea
          rows={3}
          className="field px-3 py-2 font-serif text-[15px] leading-relaxed"
          value={String(value)}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : field.type === "select" ? (
        <select className="field h-10 px-3 capitalize" value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {field.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === "date" ? "date" : "text"}
          className="field h-10 px-3"
          value={String(value)}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}

/** Ask for a reason before retiring or restoring. */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setReason("");
      setError(null);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold tracking-tight">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              await onConfirm(reason.trim());
              onOpenChange(false);
            } catch (err) {
              setError(errorText(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-foreground">Why? (required)</span>
            <input className="field h-10 px-3" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
          </label>
          {error && (
            <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy || reason.trim().length < 3}>
              {busy ? "Working…" : confirmLabel}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const ACTION_LABEL: Record<HistoryEntry["action"], string> = {
  seed: "Initial version",
  create: "Created",
  update: "Edited",
  retire: "Retired",
  restore: "Restored",
};

function retiredSnapshot(kind: KBKind, s: Record<string, unknown>): boolean {
  return kind === "facts" ? Boolean(s.superseded) : s.status === "retired";
}

/** Every version of one entry, newest first, with what changed and a restore button. */
export function HistoryDialog({
  kind,
  entity,
  open,
  onOpenChange,
  canEdit,
  onRestored,
}: {
  kind: KBKind;
  entity: KBEntity | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  onRestored: (result: KBWriteResult) => void;
}) {
  const [versions, setVersions] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);

  useEffect(() => {
    if (!open || !entity) return;
    setVersions(null);
    setError(null);
    api<{ versions: HistoryEntry[] }>(`/kb/${kind}/${entity.id}/history`)
      .then((r) => setVersions(r.versions))
      .catch((e) => setError(errorText(e)));
  }, [open, kind, entity]);

  const keys = [...FIELDS[kind].filter((f) => !f.createOnly).map((f) => f.key), kind === "facts" ? "superseded" : "status"];

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto bg-card sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-xl font-bold tracking-tight">
              <History className="size-5 text-brand" aria-hidden /> History of {NOUN[kind]} {entity?.id}
            </DialogTitle>
            <DialogDescription>Every version is kept. Findings and approvals point at the version they used.</DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-danger-fg">{error}</p>}
          {!versions && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
          <ol className="space-y-3">
            {versions?.map((v, i) => {
              const prev = versions[i + 1]?.snapshot;
              const changed = prev ? keys.filter((k) => String(prev[k] ?? "") !== String(v.snapshot[k] ?? "")) : [];
              const restorable = canEdit && i > 0 && !retiredSnapshot(kind, v.snapshot);
              return (
                <li key={v.version} className="rounded-xl border border-border bg-background p-4">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">v{v.version}</span>
                    <span className="font-semibold text-foreground">{ACTION_LABEL[v.action]}</span>
                    <span className="text-muted-foreground">
                      {v.by_user && v.by_user !== "system" ? `by ${v.by_name ?? v.by_user} · ` : ""}
                      {v.at.slice(0, 10)}
                    </span>
                    {i === 0 && <span className="text-xs font-semibold text-success-fg">Current</span>}
                    {restorable && (
                      <button className="btn btn-sm btn-secondary ml-auto" onClick={() => setRestoring(v.version)}>
                        <RotateCcw className="size-3.5" aria-hidden /> Restore this version
                      </button>
                    )}
                  </div>
                  {v.reason && <p className="mt-1.5 text-sm text-foreground-secondary">“{v.reason}”</p>}
                  {changed.length > 0 && (
                    <dl className="mt-2 space-y-1 text-xs">
                      {changed.map((k) => (
                        <div key={k} className="flex flex-wrap gap-x-2">
                          <dt className="font-semibold text-muted-foreground">{FIELDS[kind].find((f) => f.key === k)?.label ?? k}:</dt>
                          <dd>
                            <span className="text-danger-fg line-through">{String(prev?.[k] ?? "—") || "—"}</span>{" "}
                            <span className="text-success-fg">{String(v.snapshot[k] ?? "—") || "—"}</span>
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </li>
              );
            })}
          </ol>
        </DialogContent>
      </Dialog>

      <ReasonDialog
        open={restoring !== null}
        onOpenChange={(o) => !o && setRestoring(null)}
        title={`Restore version ${restoring}?`}
        description={`This saves version ${restoring}'s content as a new version ${(entity?.version ?? 0) + 1}. Nothing is lost.`}
        confirmLabel="Restore"
        onConfirm={async (reason) => {
          if (!entity || restoring === null) return;
          const r = await api<KBWriteResult>(`/kb/${kind}/${entity.id}/restore`, {
            method: "POST",
            json: { version: restoring, expected_version: entity.version, reason },
          });
          onRestored(r);
          onOpenChange(false);
        }}
      />
    </>
  );
}

/** After a fact changes: the approved content that relied on the old value. */
export function ImpactNotice({ factId, items, onClose }: { factId: string; items: ImpactItem[]; onClose: () => void }) {
  return (
    <div role="status" className="rounded-2xl border border-warning-border bg-warning-bg p-4 text-sm text-warning-fg">
      <div className="flex items-start gap-3">
        <p className="flex-1">
          <b className="font-semibold">
            {items.length} approved item{items.length === 1 ? "" : "s"} relied on the old value of {factId}.
          </b>{" "}
          Re-review {items.length === 1 ? "it" : "them"} so nothing published goes out of date.
        </p>
        <button className="text-xs font-semibold underline underline-offset-2" onClick={onClose}>
          Dismiss
        </button>
      </div>
      <ul className="mt-2 space-y-1">
        {items.map((i) => (
          <li key={i.submission_id}>
            <Link href={`/submissions/${i.submission_id}`} className="font-semibold underline underline-offset-2">
              {i.title}
            </Link>{" "}
            <span className="opacity-90">
              ({i.status}) · {i.because}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
