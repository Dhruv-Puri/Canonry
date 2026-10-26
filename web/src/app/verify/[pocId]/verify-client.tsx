"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SealGraphic } from "@/components/brand";

type VerifyResult = {
  status: "verified" | "modified" | "unknown" | "signature_invalid";
  record: Record<string, unknown>;
  reason?: string;
};

const HEADLINE: Record<string, { title: string; cls: string }> = {
  verified: {
    title: "Verified: this approval is intact",
    cls: "bg-success-bg border-success-border text-success-fg",
  },
  modified: {
    title: "Modified: the content changed after approval",
    cls: "bg-danger-bg border-danger-border text-danger-fg",
  },
  signature_invalid: {
    title: "Signature check failed",
    cls: "bg-danger-bg border-danger-border text-danger-fg",
  },
  unknown: {
    title: "Unknown Proof of Compliance id",
    cls: "bg-muted border-border-strong",
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
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <p className="eyebrow">Public verification</p>
        <h1 className="page-title mt-1.5">Proof of Compliance</h1>
        <p className="page-lede">
          Anyone with the link can verify an approval — no sign-in, no account.
        </p>
      </div>

      {err && <p className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">{err}</p>}

      {!r && !err && <p className="text-sm text-muted-foreground">Checking…</p>}

      {r && head && (
        <>
          <div className={`flex flex-col items-center rounded-2xl border p-8 text-center ${head.cls}`} role="status">
            <SealGraphic ok={r.status === "verified"} className="mb-3 size-16" />
            <p className="font-serif text-xl font-medium">{head.title}</p>
            {r.reason && <p className="mt-1 text-sm opacity-90">{r.reason}</p>}
            <p className="mt-1.5 font-mono text-xs opacity-80">POC {pocId}</p>
          </div>

          <div className="surface p-6">
            <h2 className="section-title mb-4">Signed record</h2>
            <dl className="divide-y divide-border rounded-lg border border-border bg-background font-mono text-[13px]">
              {Object.entries(r.record).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:gap-3">
                  <dt className="shrink-0 text-muted-foreground sm:w-40">{k}</dt>
                  <dd className="break-all">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>

          <p className="text-center text-xs text-muted-foreground">
            The seal covers the exact content SHA-256 of the approved revision, the approver and the
            rules version at decision time. Back to{" "}
            <Link href="/" className="link">
              Canonry
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
