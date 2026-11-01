"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { FileUp, PenLine, ShieldCheck } from "lucide-react";
import { api, uploadFile } from "@/lib/api";
import { AiLoadingScreen } from "@/components/ai-loading";
import { useIdentity } from "@/components/identity";
import { canReview } from "@/lib/roles";

const SAMPLE_POST =
  "Meet Quillmark Pulse — India's most trusted analytics platform. " +
  "Plans start from ₹1,299/month. Sign up at quillmark.co/pulse.";

export default function NewSubmissionPage() {
  const router = useRouter();
  const { me } = useIdentity();
  const isAgency = me?.role === "agency";
  const [title, setTitle] = useState("Launch post — Pulse 2.0");
  const [channel, setChannel] = useState("social");
  const [source, setSource] = useState("ai-assisted");
  const [content, setContent] = useState(
    "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by " +
      "5,000+ teams and fully ISO 27001 certified. Plans start at just ₹999/month!"
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"text" | "file">("text");
  const [file, setFile] = useState<File | null>(null);
  const [altText, setAltText] = useState("");
  const [uploading, setUploading] = useState(false);

  async function upload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        title: title.trim() || file.name,
        channel,
        source_type: isAgency ? "agency" : source,
        filename: file.name,
        alt_text: altText,
      });
      const data = await uploadFile<{ submission_id: string }>(`/submissions/upload?${qs.toString()}`, file);
      router.push(`/submissions/${data.submission_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setUploading(false);
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ submission_id: string }>("/submissions", {
        method: "POST",
        json: { title, channel, source_type: isAgency ? "agency" : source, content },
      });
      router.push(`/submissions/${r.submission_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  if (canReview(me?.role)) {
    return (
      <section className="surface mx-auto max-w-xl p-8 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
          <ShieldCheck className="size-6" aria-hidden />
        </span>
        <p className="eyebrow mt-5">Reviewer workspace</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">Drafts come from creators</h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
          Reviewers and brand admins decide on submitted work; they do not need a draft box. Open the queue to review
          what is waiting for a decision.
        </p>
        <Link href="/review" className="btn btn-primary mt-6">
          Open review queue <span aria-hidden className="btn-arrow">→</span>
        </Link>
      </section>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <p className="eyebrow">{isAgency ? "Agency submission" : "New submission"}</p>
        <h1 className="page-title mt-1.5">{isAgency ? "Submit client work" : "Submit content"}</h1>
        <p className="page-lede">
          Checks run on save — no separate “run check” step to forget.
          {isAgency ? " This goes to the client’s review queue under your agency source." : ""}
        </p>
      </div>

      <div className="surface space-y-4 p-6">
        <div className="flex flex-wrap gap-1 rounded-full border border-border bg-muted/50 p-1 w-fit" role="tablist" aria-label="What are you submitting?">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "text"}
            onClick={() => { setMode("text"); setError(null); }}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${mode === "text" ? "bg-card text-foreground shadow-card" : "text-muted-foreground"}`}
          >
            <PenLine className="size-3.5" aria-hidden /> Text
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "file"}
            onClick={() => { setMode("file"); setError(null); }}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${mode === "file" ? "bg-card text-foreground shadow-card" : "text-muted-foreground"}`}
          >
            <FileUp className="size-3.5" aria-hidden /> PDF, Word or image
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Title">
            <input
              className="field h-[38px] px-3"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label="Channel">
            <select
              className="field h-[38px] px-2 capitalize"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              {["social", "web", "blog", "email", "sales"].map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="Source">
            {isAgency ? (
              <p className="field flex h-[38px] items-center px-3 text-sm capitalize text-muted-foreground">
                agency
              </p>
            ) : (
              <select
                className="field h-[38px] px-2 capitalize"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                {["in-house", "ai-assisted"].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            )}
          </Field>
        </div>

        {mode === "text" ? (
          <>
            <Field label="Content">
              <textarea
                rows={7}
                className="field p-3 font-serif text-base leading-relaxed"
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            </Field>

            <div className="flex items-center justify-between">
              <button
                onClick={() => setContent(SAMPLE_POST)}
                className="link text-xs"
              >
                Use a clean sample post instead
              </button>
              <button
                onClick={() => void submit()}
                disabled={busy || !content.trim() || !title.trim()}
                className="btn btn-primary"
              >
                {busy ? "Checking…" : <>Submit for check <span aria-hidden className="btn-arrow">→</span></>}
              </button>
            </div>
          </>
        ) : (
          <>
            <Field label="File (PDF, DOCX, PNG or JPEG · up to 4 MB)">
              <input
                type="file"
                accept=".pdf,.docx,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
                className="field p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-2 file:py-1 file:text-xs file:font-medium"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </Field>
            <Field label="Alt text (for an image; findings check it)">
              <input
                className="field h-[38px] px-3"
                value={altText}
                onChange={(e) => setAltText(e.target.value)}
                placeholder="Describe what a person who cannot see the image needs to know"
              />
            </Field>
            <p className="text-xs leading-relaxed text-muted-foreground">
              PDFs report the page and line of each finding; Word reports the section and paragraph. Scanned PDFs
              without a text layer are refused rather than guessed at. Fixes to a Word file are made inside the file; a PDF or an
              image is fixed in its source, then uploaded as a new version.
            </p>
            <div className="flex justify-end">
              <button
                onClick={() => void upload()}
                disabled={uploading || !file || !title.trim()}
                className="btn btn-primary"
              >
                {uploading ? "Uploading…" : <>Upload and check <span aria-hidden className="btn-arrow">→</span></>}
              </button>
            </div>
          </>
        )}
        {error && <p className="text-sm text-danger-fg" role="alert">{error}</p>}
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        The prefilled text deliberately breaks a few Quillmark rules — an outdated product name,
        a contradicted count, an unsupported superlative and an old price — so you can see the
        finding → fix → review → approve loop in one pass.
      </p>

      <AiLoadingScreen open={busy || uploading} title={mode === "file" ? "Reading and checking your file" : "Checking your submission"} />
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-foreground-secondary">{label}</span>
      {children}
    </label>
  );
}
