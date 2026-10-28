"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, FileText, History, Pencil, Plus, RotateCcw, Search, Upload, X } from "lucide-react";
import {
  api,
  isRetired,
  type Fact,
  type ImpactItem,
  type ImportedRule,
  type RuleImportPreview,
  type KBEntity,
  type KBKind,
  type KBWriteResult,
  type Rule,
  type Term,
  type User,
} from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EntityDialog, HistoryDialog, ImpactNotice, ReasonDialog } from "./editor";

const NOUN: Record<KBKind, string> = { rules: "rule", facts: "fact", terms: "term" };

type Lists = { rules: Rule[]; facts: Fact[]; terms: Term[] };

function searchable(kind: KBKind, e: KBEntity): string {
  const v = Object.values(e).filter((x) => typeof x === "string" || typeof x === "number");
  return (kind + " " + v.join(" ")).toLowerCase();
}

export default function KBPage() {
  const [lists, setLists] = useState<Lists | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<KBKind>("rules");
  const [query, setQuery] = useState("");
  const [showRetired, setShowRetired] = useState(false);

  // dialogs
  const [editing, setEditing] = useState<{ kind: KBKind; entity: KBEntity | null } | null>(null);
  const [historyOf, setHistoryOf] = useState<{ kind: KBKind; entity: KBEntity } | null>(null);
  const [retiring, setRetiring] = useState<{ kind: KBKind; entity: KBEntity } | null>(null);
  const [impact, setImpact] = useState<{ factId: string; items: ImpactItem[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, f, t, m] = await Promise.all([
        api<{ rules: Rule[] }>("/rules"),
        api<{ facts: Fact[] }>("/facts"),
        api<{ terms: Term[] }>("/terms"),
        api<User>("/me"),
      ]);
      setLists({ rules: r.rules, facts: f.facts, terms: t.terms });
      setMe(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canEdit = me?.role === "reviewer" || me?.role === "admin";

  function afterWrite(kind: KBKind, r: KBWriteResult, verb: string) {
    setNotice(`${NOUN[kind][0].toUpperCase() + NOUN[kind].slice(1)} ${r.entity.id} ${verb} (now v${r.entity.version}).`);
    if (kind === "facts" && r.impact && r.impact.length > 0) setImpact({ factId: String(r.entity.id), items: r.impact });
    void load();
  }

  const visible = useMemo(() => {
    if (!lists) return null;
    const q = query.trim().toLowerCase();
    const pick = <T extends KBEntity>(kind: KBKind, items: T[]) =>
      items.filter((e) => (showRetired || !isRetired(kind, e)) && (!q || searchable(kind, e).includes(q)));
    return { rules: pick("rules", lists.rules), facts: pick("facts", lists.facts), terms: pick("terms", lists.terms) };
  }, [lists, query, showRetired]);

  const retiredCount = lists ? (["rules", "facts", "terms"] as KBKind[]).reduce(
    (n, k) => n + (lists[k] as KBEntity[]).filter((e) => isRetired(k, e)).length, 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Source of truth</p>
          <h1 className="page-title mt-1.5">Knowledge base</h1>
          <p className="page-lede max-w-2xl">
            Every check cites an entry from here. Changes are versioned: earlier findings and signed approvals keep
            showing the version they were checked against.
          </p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            {tab === "rules" && <button className="btn btn-secondary" onClick={() => setImportOpen((open) => !open)}><Upload className="size-4" aria-hidden /> Import rulebook</button>}
            <button className="btn btn-primary" onClick={() => setEditing({ kind: tab, entity: null })}>
              <Plus className="size-4" aria-hidden /> New {NOUN[tab]}
            </button>
          </div>
        )}
      </div>

      {error && <p className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>}
      {notice && (
        <p role="status" className="rounded-xl border border-success-border bg-success-bg px-3 py-2 text-sm text-success-fg">
          {notice}
        </p>
      )}
      {impact && <ImpactNotice factId={impact.factId} items={impact.items} onClose={() => setImpact(null)} />}
      {importOpen && canEdit && tab === "rules" && <RuleDocumentImporter onImported={(count) => { setImportOpen(false); setNotice(`${count} reviewed rule draft${count === 1 ? "" : "s"} added. Edit each draft and approve it before it is used in checks.`); void load(); }} onCancel={() => setImportOpen(false)} />}
      {me && !canEdit && (
        <p className="text-sm text-muted-foreground">You can read the knowledge base. Reviewers and admins change it.</p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[220px] flex-1">
          <span className="sr-only">Search the knowledge base</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            className="field h-10 pl-9 pr-3"
            placeholder="Search ids, wording, owners…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <label className="inline-flex items-center gap-2 text-sm text-foreground-secondary">
          <input type="checkbox" className="size-4 accent-[var(--brand)]" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
          Show retired ({retiredCount})
        </label>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as KBKind)}>
        <TabsList>
          <TabsTrigger value="rules">Rules {visible ? `(${visible.rules.length})` : ""}</TabsTrigger>
          <TabsTrigger value="facts">Facts {visible ? `(${visible.facts.length})` : ""}</TabsTrigger>
          <TabsTrigger value="terms">Terms {visible ? `(${visible.terms.length})` : ""}</TabsTrigger>
        </TabsList>

        {(["rules", "facts", "terms"] as KBKind[]).map((kind) => (
          <TabsContent key={kind} value={kind} className="space-y-2 pt-3">
            {visible && visible[kind].length === 0 && (
              <p className="rounded-xl border border-dashed border-border-strong p-8 text-center text-sm text-muted-foreground">
                Nothing matches. {query ? "Try a different search." : ""}
              </p>
            )}
            {(visible?.[kind] as KBEntity[] | undefined)?.map((e) => {
              const retired = isRetired(kind, e);
              return (
                <div key={String(e.id)} className={`surface p-4 text-sm ${retired ? "opacity-60" : "surface-interactive"}`}>
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      {kind === "rules" && <RuleBody r={e as Rule} />}
                      {kind === "facts" && <FactBody f={e as Fact} />}
                      {kind === "terms" && <TermBody t={e as Term} />}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {retired && <span className="mr-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">Retired</span>}
                      <span className="mr-1 font-mono text-[11px] text-muted-foreground">v{e.version}</span>
                      <IconButton label="History" onClick={() => setHistoryOf({ kind, entity: e })}>
                        <History className="size-4" />
                      </IconButton>
                      {canEdit && !retired && (
                        <>
                          <IconButton label={`Edit ${NOUN[kind]}`} onClick={() => setEditing({ kind, entity: e })}>
                            <Pencil className="size-4" />
                          </IconButton>
                          <IconButton label={`Retire ${NOUN[kind]}`} onClick={() => setRetiring({ kind, entity: e })}>
                            <Archive className="size-4" />
                          </IconButton>
                        </>
                      )}
                      {canEdit && retired && (
                        <IconButton label={`Restore ${NOUN[kind]} from history`} onClick={() => setHistoryOf({ kind, entity: e })}>
                          <RotateCcw className="size-4" />
                        </IconButton>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </TabsContent>
        ))}
      </Tabs>

      {editing && (
        <EntityDialog
          kind={editing.kind}
          entity={editing.entity}
          open
          onOpenChange={(o) => !o && setEditing(null)}
          onSaved={(r) => afterWrite(editing.kind, r, editing.entity ? "saved" : "added")}
          onReload={() => void load()}
        />
      )}
      {historyOf && (
        <HistoryDialog
          kind={historyOf.kind}
          entity={historyOf.entity}
          open
          onOpenChange={(o) => !o && setHistoryOf(null)}
          canEdit={canEdit}
          onRestored={(r) => afterWrite(historyOf.kind, r, "restored")}
        />
      )}
      {retiring && (
        <ReasonDialog
          open
          onOpenChange={(o) => !o && setRetiring(null)}
          title={`Retire ${NOUN[retiring.kind]} ${retiring.entity.id}?`}
          description="It stops being used in checks. Past findings and approvals keep citing it, and you can restore it from History."
          confirmLabel="Retire"
          onConfirm={async (reason) => {
            const r = await api<KBWriteResult>(`/kb/${retiring.kind}/${retiring.entity.id}/retire`, {
              method: "POST",
              json: { expected_version: retiring.entity.version, reason },
            });
            afterWrite(retiring.kind, r, "retired");
          }}
        />
      )}
    </div>
  );
}

function RuleDocumentImporter({ onImported, onCancel }: { onImported: (count: number) => void; onCancel: () => void }) {
  const [preview, setPreview] = useState<RuleImportPreview | null>(null);
  const [rules, setRules] = useState<ImportedRule[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function inspect(file?: File) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const result = await api<RuleImportPreview>(`/rules/import-document?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      setPreview(result);
      setRules(result.proposals);
      if (!result.proposals.length) setError("No rule-sized paragraphs were found. Try a Markdown or DOCX document with one guideline per paragraph.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveDrafts() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ count: number }>("/rules/import-drafts", { method: "POST", json: { proposals: rules } });
      onImported(result.count);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <section className="surface space-y-4 p-5" aria-label="Import a guideline document">
      <div className="flex items-start gap-3">
        <FileText className="mt-1 size-5 shrink-0 text-brand" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-foreground">Import a rulebook as drafts</h2>
          <p className="mt-1 text-sm text-muted-foreground">Choose a Markdown, text, or Word (.docx) file up to 5 MB. Canonry groups paragraphs into editable suggestions; nothing is made active until a reviewer approves each rule.</p>
        </div>
        <button className="btn btn-ghost btn-sm size-8 px-0" onClick={onCancel} aria-label="Close import"><X className="size-4" /></button>
      </div>
      <label className="flex cursor-pointer flex-wrap items-center gap-3 rounded-xl border border-dashed border-border-strong p-4 text-sm">
        <Upload className="size-4 text-brand" aria-hidden />
        <span className="font-medium">{busy ? "Reading document…" : preview ? `Selected: ${preview.source}` : "Choose a .md, .txt, or .docx file"}</span>
        <input type="file" accept=".md,.markdown,.txt,.docx" className="sr-only" disabled={busy} onChange={(event) => void inspect(event.target.files?.[0])} />
      </label>
      {preview && rules.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">Review each extracted paragraph, change its category or wording, and remove anything that is not a rule. {preview.ignored > 0 ? `${preview.ignored} short or excess paragraphs were skipped.` : ""}</p>
          {rules.map((rule, index) => (
            <article key={index} className="rounded-xl border border-border bg-background p-3">
              <div className="flex items-center justify-between gap-3"><span className="text-xs font-semibold text-warning-fg">Draft suggestion {index + 1}</span><button className="text-xs text-muted-foreground underline" onClick={() => setRules((current) => current.filter((_, i) => i !== index))}>Remove</button></div>
              <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
                <input className="field h-9 px-3" aria-label={`Category for draft ${index + 1}`} value={rule.category} onChange={(e) => setRules((current) => current.map((item, i) => i === index ? { ...item, category: e.target.value } : item))} />
                <select className="field h-9 px-3 capitalize" aria-label={`Severity for draft ${index + 1}`} value={rule.severity} onChange={(e) => setRules((current) => current.map((item, i) => i === index ? { ...item, severity: e.target.value } : item))}><option>low</option><option>medium</option><option>high</option></select>
              </div>
              <textarea className="field mt-2 w-full px-3 py-2 text-sm" aria-label={`Rule statement for draft ${index + 1}`} rows={2} value={rule.statement} onChange={(e) => setRules((current) => current.map((item, i) => i === index ? { ...item, statement: e.target.value } : item))} />
            </article>
          ))}
          <div className="flex justify-end gap-2"><button className="btn btn-secondary" onClick={onCancel}>Cancel</button><button className="btn btn-primary" disabled={busy || !rules.length || rules.some((rule) => !rule.category.trim() || rule.statement.trim().length < 10)} onClick={() => void saveDrafts()}>{busy ? "Saving drafts…" : `Save ${rules.length} as drafts`}</button></div>
        </div>
      )}
      {error && <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>}
    </section>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" title={label} aria-label={label} onClick={onClick} className="btn btn-ghost btn-sm size-8 px-0">
      {children}
    </button>
  );
}

function RuleBody({ r }: { r: Rule }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-xs font-semibold text-brand">{r.id}</code>
        <span className="text-xs text-muted-foreground">{r.category}</span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize text-foreground-secondary">{r.severity}</span>
        {r.status === "draft" && <span className="rounded-full bg-warning-bg px-1.5 py-0.5 text-[11px] text-warning-fg">draft</span>}
        {r.vague_flag && (
          <span className="rounded-full border border-dashed border-warning-border px-1.5 py-0.5 text-[11px] text-warning-fg">
            possibly unclear: {r.vague_flag.replace("vague_", "").replace("_", " ")}
          </span>
        )}
      </div>
      <p className="mt-2 text-foreground">{r.statement}</p>
      {(r.do_example || r.dont_example) && (
        <p className="mt-1 text-xs text-muted-foreground">
          {r.do_example && <>Do: “{r.do_example}” </>}
          {r.dont_example && <>· Don’t: “{r.dont_example}”</>}
        </p>
      )}
    </>
  );
}

function FactBody({ f }: { f: Fact }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <code className="font-mono font-semibold text-brand">{f.id}</code>
        <span>owner: {f.owner ?? "—"}</span>
        {f.source && <span>· {f.source}</span>}
        {(f.valid_from || f.valid_to) && (
          <span>
            · valid {f.valid_from ?? "…"} → {f.valid_to ?? "open"}
          </span>
        )}
        {!f.valid_to && !f.superseded && (
          <span className="rounded-full bg-warning-bg px-1.5 py-0.5 text-warning-fg">No expiry set</span>
        )}
        {f.active === false && !f.superseded && (
          <span className="rounded-full bg-danger-bg px-1.5 py-0.5 text-danger-fg">expired</span>
        )}
        {f.confidential ? <span className="rounded-full bg-info-bg px-1.5 py-0.5 text-info-fg">confidential</span> : null}
      </div>
      <p className="mt-2 text-foreground">{f.text}</p>
    </>
  );
}

function TermBody({ t }: { t: Term }) {
  // banned_or_check may hold several comma-separated variants ("Quill Mark,Quillmark Ltd").
  const avoid = (t.banned_or_check ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {t.preferred ? (
          <span className="rounded-full bg-success-bg px-2.5 py-0.5 font-medium text-success-fg">Use “{t.preferred}”</span>
        ) : (
          <span className="rounded-full bg-warning-bg px-2.5 py-0.5 font-medium text-warning-fg">Check before use</span>
        )}
        {avoid.map((a) => (
          <span
            key={a}
            className={`rounded-full border px-2.5 py-0.5 ${
              t.preferred ? "border-danger-border text-danger-fg line-through decoration-1" : "border-warning-border text-warning-fg"
            }`}
          >
            {t.preferred ? <span className="sr-only">instead of </span> : null}“{a}”
          </span>
        ))}
        <span className="text-xs capitalize text-muted-foreground">{t.severity}</span>
      </div>
      {t.note && <p className="mt-2 text-xs text-muted-foreground">{t.note}</p>}
    </>
  );
}
