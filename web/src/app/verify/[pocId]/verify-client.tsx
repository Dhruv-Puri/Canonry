"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type VerifyResult = {
  status: "verified" | "modified" | "unknown" | "signature_invalid";
  record: Record<string, unknown>;
  reason?: string;
};

const HEADLINE: Record<string, { title: string; cls: string }> = {
  verified: {
    title: "✓ Verified — this approval is intact",
    cls: "bg-emerald-50 border-emerald-300 text-emerald-900 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-200",
  },
  modified: {
    title: "⚠ Modified — the content changed after approval",
    cls: "bg-red-50 border-red-300 text-red-900 dark:bg-red-950/40 dark:border-red-800 dark:text-red-200",
  },
  signature_invalid: {
    title: "✗ Signature check failed",
    cls: "bg-red-50 border-red-300 text-red-900 dark:bg-red-950/40 dark:border-red-800 dark:text-red-200",
  },
  unknown: {
    title: "？ Unknown Proof of Compliance id",
    cls: "bg-muted border-border",
  },
};

export function VerifyClient({ pocId }: { pocId: string }) {
  const [r, setR] = useState<VerifyResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`/engine/verify/${pocId}`, { cache: "no-store" });
        setR((await res.json()) as VerifyResult);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [pocId]);

  const head = r ? HEADLINE[r.status] : null;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Proof of Compliance</h1>
        <p className="text-sm text-muted-foreground">
          Anyone with the link can verify an approval — no sign-in, no account.
        </p>
      </div>

      {err && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40">{err}</p>}

      {!r && !err && <p className="text-sm text-muted-foreground">Checking…</p>}

      {r && head && (
        <>
          <div className={`rounded-lg border p-6 text-center ${head.cls}`}>
            <p className="text-lg font-semibold">{head.title}</p>
            {r.reason && <p className="mt-1 text-sm opacity-80">{r.reason}</p>}
            <p className="mt-1 text-xs opacity-70">POC {pocId}</p>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Signed record
            </h2>
            <dl className="space-y-1 text-sm">
              {Object.entries(r.record).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="w-40 shrink-0 font-medium text-muted-foreground">{k}</dt>
                  <dd className="break-all">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>

          <p className="text-center text-xs text-muted-foreground">
            The seal covers the exact content SHA-256 of the approved revision, the approver and the
            rules version at decision time. Back to{" "}
            <Link href="/" className="underline">
              Canonry
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
