"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Check, Copy, KeyRound, RefreshCw, Send, ShieldCheck, Webhook } from "lucide-react";
import { api } from "@/lib/api";
import { useIdentity } from "@/components/identity";

type ApiKey = {
  id: string; name: string; prefix: string; scopes: string[];
  created_at: string; last_used_at: string | null; revoked_at: string | null;
};

type Endpoint = {
  id: string; url: string; events: string[]; active: number; description: string | null;
  created_at: string;
  last_delivery: { status: string; last_status: number | null; attempts: number; delivered_at: string | null; created_at: string } | null;
};

type Delivery = {
  id: string; endpoint_id: string; url: string; event: string; status: string;
  attempts: number; last_status: number | null; last_error: string | null;
  created_at: string; delivered_at: string | null; next_attempt_at: string | null;
};

type Packs = {
  packs: { id: string; name: string; version: string; source: string; clauses: number; workspace_active: number | null }[];
  retrieval: { model: string; dimensions: number; clauses: number; cached_embeddings: number; provider: string };
};

const EVENTS = ["checked", "approved", "signed"] as const;
/** What each event means, in plain words, next to its technical name. */
const EVENT_MEANING: Record<(typeof EVENTS)[number], string> = {
  checked: "a check finished",
  approved: "a reviewer approved it",
  signed: "the approval was signed: safe to publish",
};

/** The publishing gate in three plain steps, for an admin who has never set up an integration. */
const GATE_STEPS = [
  { title: "Your site sends a draft", body: "Your website or CMS sends the draft to Canonry with an API key, instead of publishing it straight away." },
  { title: "Canonry checks it, people decide", body: "The same checks as here run; writers fix, a reviewer approves and Canonry signs the approval." },
  { title: "Your site is told it may publish", body: "A webhook (a signed message) tells your site the draft was approved. The site publishes only if its text matches what was approved." },
];

function when(iso: string | null) {
  return iso ? `${iso.slice(0, 16).replace("T", " ")} UTC` : "never";
}

/** A key or secret shown once: copy it (with feedback), then hide it for good. */
function ShownOnce({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  return (
    <div className="mt-3 rounded-xl border border-warning-border bg-warning-bg p-3" role="status">
      <p className="text-xs font-semibold text-warning-fg">{label}</p>
      <code className="mt-2 block break-all rounded-md bg-card px-2 py-1.5 font-mono text-xs">{value}</code>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={() =>
            navigator.clipboard.writeText(value).then(() => setCopied("yes"), () => setCopied("no"))
          }
        >
          {copied === "yes" ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          {copied === "yes" ? "Copied" : "Copy"}
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onDone}>I have saved it — hide</button>
        {copied === "no" && <span className="text-xs text-warning-fg">Copy did not work here; select the text and copy it by hand.</span>}
      </div>
    </div>
  );
}

export default function ApiSettingsPage() {
  const { me } = useIdentity();
  const isAdmin = me?.role === "admin";
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [packs, setPacks] = useState<Packs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [keyScopes, setKeyScopes] = useState<string[]>(["check", "read"]);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [hookUrl, setHookUrl] = useState("");
  const [hookEvents, setHookEvents] = useState<string[]>([...EVENTS]);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const [k, e, d, p] = await Promise.all([
        api<{ keys: ApiKey[] }>("/api-keys"),
        api<{ endpoints: Endpoint[] }>("/webhook-endpoints"),
        api<{ deliveries: Delivery[] }>("/webhook-deliveries?limit=25"),
        api<Packs>("/compliance/packs"),
      ]);
      setKeys(k.keys);
      setEndpoints(e.endpoints);
      setDeliveries(d.deliveries);
      setPacks(p);
    } catch (err) {
      setError(`Could not load the API settings: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [isAdmin]);

  useEffect(() => { void load(); }, [load]);

  // the demo publisher is mounted only in demo mode
  const [publisherUp, setPublisherUp] = useState(false);
  useEffect(() => {
    if (!isAdmin) return;
    api<{ ok: boolean }>("/cms/healthz").then((r) => setPublisherUp(Boolean(r.ok)), () => setPublisherUp(false));
  }, [isAdmin]);

  async function run(fn: () => Promise<void>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
          <ShieldCheck className="size-6" aria-hidden />
        </span>
        <p className="eyebrow mt-5">Brand admin</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">API settings are for brand admins</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          Keys and webhook secrets can publish content and read the workspace. Only an administrator can issue or revoke them.
        </p>
        <Link href="/admin" className="btn btn-primary mt-6">Back to overview</Link>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <Link href="/admin" className="-ml-1 inline-flex min-h-8 items-center gap-1 rounded-md px-1 text-sm font-medium text-muted-foreground hover:text-foreground pointer-coarse:min-h-11">
        <ArrowLeft className="size-3.5" aria-hidden /> Workspace overview
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Integration surface</p>
          <h1 className="page-title mt-1.5">API &amp; webhooks</h1>
          <p className="page-lede max-w-2xl">
            Connect the systems that publish (a website, a CMS, a script) so nothing goes live before it passes Canonry.
            You only need this if someone on your team publishes through one of those systems.
          </p>
        </div>
        <button onClick={() => void run(async () => {
            const r = await api<{ attempted: number; delivered: number }>("/webhooks/flush", { method: "POST" });
            setNotice(r.attempted ? `Sent ${r.attempted} waiting deliver${r.attempted === 1 ? "y" : "ies"}; ${r.delivered} delivered.` : "Nothing was waiting to be sent.");
          })}
          disabled={busy} className="btn btn-secondary">
          <RefreshCw className={`size-4 ${busy ? "animate-spin" : ""}`} aria-hidden /> Send waiting webhooks now
        </button>
      </div>

      <section aria-label="How the publishing gate works" className="surface p-5">
        <p className="eyebrow">How it works</p>
        <ol className="mt-3 grid gap-3 sm:grid-cols-3">
          {GATE_STEPS.map((g, i) => (
            <li key={g.title} className="rounded-xl border border-border bg-muted/60 p-4">
              <p className="flex items-center gap-2 text-sm font-semibold">
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-primary text-xs text-primary-foreground">{i + 1}</span>
                {g.title}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">{g.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {publisherUp && <section className="surface flex flex-wrap items-center gap-3 p-5">
        <div className="min-w-0 flex-1 basis-72">
          <p className="font-medium">Try the publishing gate</p>
          <p className="mt-1 text-sm text-muted-foreground">
            The demo publisher sends a post to Canonry through this API and publishes it only after the signed webhook
            for its approval arrives. Its key and endpoint below are named <em>Demo publisher</em>.
          </p>
        </div>
        <a href="/engine/cms" target="_blank" rel="noreferrer" className="btn btn-primary">Open the demo publisher</a>
      </section>}

      {error && <p role="alert" className="rounded-xl border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{error}</p>}
      {notice && <p role="status" className="rounded-xl border border-success-border bg-success-bg px-3 py-2 text-sm text-success-fg">{notice}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="surface p-6">
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-brand" aria-hidden />
            <h2 className="section-title">API keys</h2>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">
            A key is a password for another system: it lets your website or a script send drafts to Canonry and read the
            results. Give each system its own key, so you can switch one off without breaking the others.
          </p>
          <details className="mt-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium hover:text-foreground">For developers</summary>
            <p className="mt-1.5 leading-relaxed">
              Scope <code>check</code> can create and check submissions; <code>read</code> can read them;{" "}
              <code>admin</code> includes both. Send <code>Authorization: Bearer ck_live_…</code>. Keys are shown once;
              only a hash is stored.
            </p>
          </details>
          <form
            className="mt-4 flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const r = await api<{ key: string }>("/api-keys", { method: "POST", json: { name: keyName, scopes: keyScopes } });
                setCreatedKey(r.key);
                setKeyName("");
              });
            }}
          >
            <label className="min-w-40 flex-1 text-xs font-medium text-foreground-secondary">
              Key name
              <input className="field mt-1 h-9 px-3" value={keyName} maxLength={80} placeholder="e.g. Website CMS"
                onChange={(e) => setKeyName(e.target.value)} required />
            </label>
            <div className="flex flex-wrap gap-2 pb-1">
              {["check", "read", "admin"].map((scope) => (
                <label key={scope} className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 text-xs pointer-coarse:min-h-11">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--brand)]"
                    checked={keyScopes.includes(scope)}
                    onChange={(e) => setKeyScopes((s) => e.target.checked ? [...new Set([...s, scope])] : s.filter((x) => x !== scope))}
                  />
                  {scope}
                </label>
              ))}
            </div>
            <button className="btn btn-primary btn-sm" disabled={busy || !keyName.trim() || keyScopes.length === 0}>Create key</button>
          </form>
          {keyScopes.length === 0 && <p className="mt-2 text-xs text-warning-fg">Choose at least one scope.</p>}

          {createdKey && (
            <ShownOnce label="Copy this key now. Canonry keeps only its hash, so it cannot show it again."
              value={createdKey} onDone={() => setCreatedKey(null)} />
          )}

          <ul className="mt-4 divide-y divide-border text-sm">
            {keys.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2.5">
                <span className="font-medium">{k.name}</span>
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{k.prefix}…</code>
                <span className="text-xs text-muted-foreground">{k.scopes.join(" · ")}</span>
                {k.revoked_at ? (
                  <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[11px]">revoked</span>
                ) : (
                  <button
                    className="btn btn-ghost btn-sm ml-auto"
                    onClick={() => void run(async () => {
                      await api(`/api-keys/${k.id}/revoke`, { method: "POST" });
                      setNotice(`Key “${k.name}” is revoked. Requests with it now get 401.`);
                    }, `Revoke “${k.name}”? Anything using this key stops working at once. This cannot be undone.`)}
                    disabled={busy}
                  >
                    Revoke
                  </button>
                )}
                <span className="basis-full text-[11px] text-muted-foreground">
                  created {when(k.created_at)} · last used {when(k.last_used_at)}
                </span>
              </li>
            ))}
            {keys.length === 0 && (
              <li className="py-3 text-sm text-muted-foreground">
                No keys yet. Create one to let a CMS or script send content to Canonry.
              </li>
            )}
          </ul>
        </section>

        <section className="surface p-6">
          <div className="flex items-center gap-2">
            <Webhook className="size-4 text-brand" aria-hidden />
            <h2 className="section-title">Webhook endpoints</h2>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">
            A webhook is a message Canonry sends to your system the moment something happens, such as a draft being
            approved, so it can publish without anyone copying and pasting. If your system is down, Canonry keeps trying.
          </p>
          <details className="mt-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer font-medium hover:text-foreground">For developers</summary>
            <p className="mt-1.5 leading-relaxed">
              Each delivery is signed:{" "}
              <code className="break-all">X-Canonry-Signature: sha256=HMAC(secret, timestamp + &quot;.&quot; + body)</code>.
              A failed delivery is retried after 30 s, 2 min, 10 min, 30 min, 1 h, 2 h and 6 h, then marked failed.
            </p>
          </details>
          <form
            className="mt-4 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const r = await api<{ secret: string }>("/webhook-endpoints", {
                  method: "POST",
                  json: { url: hookUrl, events: hookEvents },
                });
                setCreatedSecret(r.secret);
                setHookUrl("");
              });
            }}
          >
            <label className="block text-xs font-medium text-foreground-secondary">
              HTTPS endpoint
              <input className="field mt-1 h-9 px-3" type="url" value={hookUrl} placeholder="https://cms.example.com/webhooks/canonry"
                onChange={(e) => setHookUrl(e.target.value)} required />
              <span className="mt-1 block font-normal text-muted-foreground">
                Public HTTPS only: addresses inside a private network are refused.
              </span>
            </label>
            <div className="flex flex-wrap gap-3 pt-1">
              {EVENTS.map((event) => (
                <label key={event} className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 text-xs pointer-coarse:min-h-11">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--brand)]"
                    checked={hookEvents.includes(event)}
                    onChange={(e) => setHookEvents((s) => e.target.checked ? [...new Set([...s, event])] : s.filter((x) => x !== event))}
                  />
                  <span><code>{event}</code> <span className="text-muted-foreground">({EVENT_MEANING[event]})</span></span>
                </label>
              ))}
            </div>
            <button className="btn btn-primary btn-sm" disabled={busy || hookEvents.length === 0 || !hookUrl.trim()}>Add endpoint</button>
          </form>

          {createdSecret && (
            <ShownOnce label="Signing secret: copy it now and set it on the receiver. It is not shown again."
              value={createdSecret} onDone={() => setCreatedSecret(null)} />
          )}

          <ul className="mt-4 divide-y divide-border text-sm">
            {endpoints.map((e) => (
              <li key={e.id} className="py-3">
                {e.description && <p className="text-xs font-medium">{e.description}</p>}
                <div className="flex flex-wrap items-center gap-2">
                  <code className="min-w-0 flex-1 break-all text-xs">{e.url}</code>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${e.active ? "bg-success-bg text-success-fg" : "bg-muted text-muted-foreground"}`}>
                    {e.active ? "active" : "disabled"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {e.events.join(" · ")} · {e.last_delivery ? `${e.last_delivery.status} (${e.last_delivery.attempts} attempt${e.last_delivery.attempts === 1 ? "" : "s"})` : "no deliveries yet"}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void run(async () => {
                      const r = await api<{ secret: string }>(`/webhook-endpoints/${e.id}/rotate`, { method: "POST" });
                      setCreatedSecret(r.secret);
                    }, "Rotate the signing secret? The old secret stops working at once, so update the receiver straight away.")}
                  >
                    Rotate secret
                  </button>
                  {Boolean(e.active) && (
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      onClick={() => void run(async () => {
                        await api(`/webhook-endpoints/${e.id}/disable`, { method: "POST" });
                        setNotice("Endpoint disabled. It receives no further events.");
                      }, "Disable this endpoint? It stops receiving events and cannot be turned back on (add it again instead).")}
                    >
                      Disable
                    </button>
                  )}
                </div>
              </li>
            ))}
            {endpoints.length === 0 && (
              <li className="py-3 text-sm text-muted-foreground">
                No endpoints yet. Add one to be told when content is checked, approved and signed.
              </li>
            )}
          </ul>
        </section>
      </div>

      <section className="surface p-6">
        <div className="flex items-center gap-2">
          <Send className="size-4 text-brand" aria-hidden />
          <h2 className="section-title">Delivery log</h2>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">Every message Canonry sent to your systems, newest first. Retry sends the exact same signed message again.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-muted-foreground">
              <tr><th className="py-2 pr-3">Event</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Attempts</th><th className="py-2 pr-3">Endpoint</th><th className="py-2 pr-3">When</th><th className="py-2" /></tr>
            </thead>
            <tbody>
              {deliveries.map((d) => (
                <tr key={d.id} className="border-t border-border align-top">
                  <td className="py-2 pr-3 font-mono text-xs">{d.event}</td>
                  <td className="py-2 pr-3">
                    <span className={`rounded-full px-2 py-0.5 text-[11px] ${d.status === "delivered" ? "bg-success-bg text-success-fg" : d.status === "failed" ? "bg-danger-bg text-danger-fg" : "bg-warning-bg text-warning-fg"}`}>{d.status}</span>
                    {d.last_error && <p className="mt-1 max-w-xs break-words text-[11px] text-danger-fg">{d.last_error}</p>}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{d.attempts}</td>
                  <td className="max-w-xs break-all py-2 pr-3 text-xs text-muted-foreground">{d.url}</td>
                  <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted-foreground">{d.created_at.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-2">
                    {d.status !== "delivered" && (
                      <button className="btn btn-ghost btn-sm" disabled={busy}
                        onClick={() => void run(async () => { await api(`/webhook-deliveries/${d.id}/retry`, { method: "POST" }); })}>
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {deliveries.length === 0 && <tr><td colSpan={6} className="py-3 text-sm text-muted-foreground">Nothing sent yet. Once an endpoint is added, every check, approval and signature it listens for shows up here, with failed ones retried automatically.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {packs && (
        <section className="surface p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Compliance packs</p>
              <h2 className="mt-1 text-xl font-bold tracking-tight">Retrieved law, cited clause by clause</h2>
            </div>
            <span className="rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs">
              {packs.retrieval.provider} embeddings · {packs.retrieval.dimensions}d · {packs.retrieval.clauses} clauses
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {packs.packs.map((p) => (
              <div key={p.id} className="rounded-xl border border-border p-4">
                <div className="flex items-center gap-2">
                  <span className={`grid size-6 place-items-center rounded-full ${p.workspace_active ? "bg-success-bg text-success-fg" : "bg-muted text-muted-foreground"}`}>
                    <Check className="size-3.5" aria-hidden />
                  </span>
                  <p className="font-medium">{p.name}</p>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">v{p.version}</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{p.source}</p>
                <p className="mt-2 text-xs text-foreground-secondary">{p.clauses} active clauses · retrieval {packs.retrieval.model}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs">{p.workspace_active ? "On: every check cites these clauses." : "Off: these clauses are not checked."}</span>
                  <button
                    className="btn btn-secondary btn-sm ml-auto"
                    disabled={busy}
                    onClick={() => void run(async () => {
                      const next = await api<Packs>(`/compliance/packs/${p.id}`, { method: "POST", json: { active: !p.workspace_active } });
                      setPacks(next);
                      setNotice(p.workspace_active ? `${p.name} is off for new checks.` : `${p.name} is on for new checks.`);
                    })}
                  >
                    {p.workspace_active ? "Switch off" : "Switch on"}
                  </button>
                </div>
              </div>
            ))}
            {packs.packs.length === 0 && <p className="text-sm text-muted-foreground">No packs installed.</p>}
          </div>
        </section>
      )}
    </div>
  );
}
