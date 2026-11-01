"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SealGraphic } from "@/components/brand";

type VerifyResult = {
  status: "verified" | "modified" | "unknown" | "signature_invalid";
  content_checked: boolean;
  content_kind?: "text" | "file";
  record?: Record<string, unknown>;
  reason?: string;
  stamped?: boolean;
  file_sha256?: string;
  signature_valid?: boolean;
};

const HEADLINE: Record<string, { title: string; cls: string }> = {
  genuine: {
    title: "Genuine seal: this approval is on record",
    cls: "bg-success-bg border-success-border text-success-fg",
  },
  verified: {
    title: "Verified: this is the approved content",
    cls: "bg-success-bg border-success-border text-success-fg",
  },
  modified: {
    title: "Modified: this content is not what was approved",
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
  const [text, setText] = useState("");
  const [checking, setChecking] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileResult, setFileResult] = useState<VerifyResult | null>(null);
  const [fileChecking, setFileChecking] = useState(false);

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

  async function checkText() {
    setChecking(true);
    setErr(null);
    try {
      const res = await fetch(`/engine/verify/${pocId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      if (!res.ok) throw new Error(res.status === 422 ? "That text is too long to check." : `Check failed (${res.status}).`);
      setR((await res.json()) as VerifyResult);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }

  async function checkFile() {
    if (!file) return;
    setFileChecking(true);
    setErr(null);
    try {
      const res = await fetch(`/engine/verify/${pocId}/file`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      const data = (await res.json()) as VerifyResult & { detail?: string };
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Check failed (${res.status}).`);
      setFileResult(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setFileChecking(false);
    }
  }

  const shown = fileResult ?? r;
  const head = shown ? HEADLINE[shown.status === "verified" && !shown.content_checked ? "genuine" : shown.status] : null;

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
            <SealGraphic ok={shown?.status === "verified"} className="mb-3 size-16" />
            <p className="font-serif text-xl font-medium">{head.title}</p>
            {shown?.reason && <p className="mt-1 text-sm opacity-90">{shown.reason}</p>}
            <p className="mt-1.5 font-mono text-xs opacity-80">POC {pocId}</p>
          </div>

          {r.content_kind === "file" ? (
            <div className="surface space-y-3 p-6">
              <h2 className="section-title">Check the published file</h2>
              <p className="text-sm text-muted-foreground">
                Upload the original or the stamped copy. Canonry checks the SHA-256 against the signed record and,
                when the file carries a stamp, verifies the embedded proof signature too.
              </p>
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                aria-label="Published file"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setFileResult(null); }}
                className="field p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-2 file:py-1 file:text-xs file:font-medium"
              />
              <button
                type="button"
                onClick={() => void checkFile()}
                disabled={!file || fileChecking}
                className="btn btn-primary"
              >
                {fileChecking ? "Checking…" : "Check this file"}
              </button>
              {fileResult && (
                <div className={`rounded-lg border px-3 py-2 text-sm ${fileResult.status === "verified" ? "border-success-border bg-success-bg text-success-fg" : "border-danger-border bg-danger-bg text-danger-fg"}`}>
                  <strong>{fileResult.status === "verified" ? "Matches the signed record" : "Does not verify"}</strong>
                  {fileResult.reason ? ` — ${fileResult.reason}` : ""}
                  {fileResult.stamped ? " · carries an embedded seal" : ""}
                </div>
              )}
            </div>
          ) : (
            <div className="surface space-y-3 p-6">
              <h2 className="section-title">Check the published text</h2>
              <p className="text-sm text-muted-foreground">
                Paste the text exactly as it was published. Canonry compares its fingerprint with the approved
                version; the approved text itself is never shown here.
              </p>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={5}
                aria-label="Published text"
                className="field p-3 text-sm"
                placeholder="Paste the published copy…"
              />
              <button
                type="button"
                onClick={() => void checkText()}
                disabled={!text.trim() || checking}
                className="btn btn-primary"
              >
                {checking ? "Checking…" : "Check this text"}
              </button>
            </div>
          )}

          {shown?.record && (
          <div className="surface p-6">
            <h2 className="section-title mb-4">Signed record</h2>
            <dl className="divide-y divide-border rounded-lg border border-border bg-background font-mono text-[13px]">
              {Object.entries(shown.record).map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:gap-3">
                  <dt className="shrink-0 text-muted-foreground sm:w-40">{k}</dt>
                  <dd className="break-all">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
          )}

          <p className="text-center text-xs text-muted-foreground">
            The seal covers the SHA-256 fingerprint of the approved text, the approver&apos;s role and the
            knowledge version at decision time. Back to{" "}
            <Link href="/" className="link">
              Canonry
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
