"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { FileText, FileUp, Image as ImageIcon, PenLine, ShieldCheck, X } from "lucide-react";
import { api, MAX_UPLOAD_BYTES, uploadFile } from "@/lib/api";
import { AiLoadingScreen } from "@/components/ai-loading";
import { useIdentity } from "@/components/identity";
import { canReview } from "@/lib/roles";

const SAMPLE_POST =
  "Meet Quillmark Pulse — India's most trusted analytics platform. " +
  "Plans start from ₹1,299/month. Sign up at quillmark.co/pulse.";

const MISTAKES_POST =
  "Meet Quillmark Insights 2.0 — India's #1 analytics platform, trusted by " +
  "5,000+ teams and fully ISO 27001 certified. Plans start at just ₹999/month!";

const ACCEPT =
  ".pdf,.docx,.png,.jpg,.jpeg,application/pdf," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg";

function words(text: string): number {
  const t = text.trim();
  return t ? t.split(/\s+/).length : 0;
}
function exclamations(text: string): number {
  return (text.match(/!/g) ?? []).length;
}

function fileKindLabel(file: File): string {
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return "PDF document";
  if (ext === "docx") return "Word document";
  if (ext === "png" || ext === "jpg" || ext === "jpeg") return "Image";
  return "File";
}

function isImageFile(file: File): boolean {
  return fileKindLabel(file) === "Image";
}

/** Why this file cannot be checked, in plain words; null when it can. */
function fileProblem(file: File): string | null {
  if (fileKindLabel(file) === "File") {
    return "Choose a PDF, a Word .docx, or a PNG or JPEG image.";
  }
  if (file.size === 0) return "This file is empty. Choose it again, or export it again from its source.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB; uploads can be up to 4 MB. Compress it or export a smaller copy.`;
  }
  return null;
}

/** A local thumbnail for an uploaded image. Other files get no preview URL. */
function useFilePreview(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file || !isImageFile(file)) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}

export default function NewSubmissionPage() {
  const router = useRouter();
  const { me } = useIdentity();
  const isAgency = me?.role === "agency";
  const [title, setTitle] = useState("Launch post — Pulse 2.0");
  const [channel, setChannel] = useState("social");
  const [source, setSource] = useState("ai-assisted");
  const [content, setContent] = useState(MISTAKES_POST);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"text" | "file">("text");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [altText, setAltText] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const preview = useFilePreview(file);

  // The tour and the guide deep-link here with ?mode=file, so the upload side
  // opens directly. Read it from the URL after mount instead of useSearchParams
  // so this page keeps rendering without a Suspense boundary.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("mode");
    if (wanted === "file" || wanted === "text") setMode(wanted);
  }, []);

  function chooseFile(next: File | null) {
    if (!next) {
      setFile(null);
      setFileError(null);
      return;
    }
    const problem = fileProblem(next);
    setFileError(problem);
    setFile(problem ? null : next);
    setAltText("");
  }

  async function upload() {
    if (!file) return;
    const problem = fileProblem(file);
    if (problem) {
      setFileError(problem);
      return;
    }
    setUploading(true);
    setError(null);
    setFileError(null);
    try {
      const qs = new URLSearchParams({
        title: title.trim() || file.name,
        channel,
        source_type: isAgency ? "agency" : source,
        filename: file.name,
        alt_text: isImageFile(file) ? altText : "",
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
        <p className="eyebrow">{isAgency ? "Agency submission" : "New check"}</p>
        <h1 className="page-title mt-1.5">{isAgency ? "Submit client work" : "Check your content"}</h1>
        <p className="page-lede">
          Write it here or upload a file. Canonry checks it against Quillmark&apos;s brand rules and approved facts as
          soon as you submit, and tells you what to fix.
          {isAgency ? " It then goes to the client’s review queue under your agency source." : ""}
        </p>
      </div>

      <div className="surface space-y-4 p-6">
        <div
          data-guide={mode === "text" ? "new-primary" : undefined}
          tabIndex={-1}
          className="flex w-fit flex-wrap gap-1 rounded-full border border-border bg-muted/50 p-1"
          role="tablist"
          aria-label="What are you submitting?"
        >
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
              className="field h-[38px] px-2"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              {[["social", "Social post"], ["web", "Web page"], ["blog", "Blog"], ["email", "Email"], ["sales", "Sales material"]].map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
          <Field label="Written by">
            {isAgency ? (
              <p className="field flex h-[38px] items-center px-3 text-sm text-muted-foreground">
                Agency
              </p>
            ) : (
              <select
                className="field h-[38px] px-2"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                {[["in-house", "Our team"], ["ai-assisted", "With AI help"]].map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            )}
          </Field>
        </div>

        {mode === "text" ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Start from">
              <span className="mr-1 text-xs text-muted-foreground">Start from:</span>
              {([
                ["mistakes", "Sample with mistakes", MISTAKES_POST],
                ["clean", "Clean sample", SAMPLE_POST],
                ["blank", "Blank", ""],
              ] as const).map(([id, label, text]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={content === text}
                  onClick={() => setContent(text)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    content === text ? "border-foreground bg-foreground text-background" : "border-border text-foreground-secondary hover:border-border-strong"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <Field label="Content">
              <textarea
                rows={7}
                className="field p-3 font-serif text-base leading-relaxed"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                onKeyDown={(e) => {
                  // Ctrl/⌘ + Enter checks it, as in most writing tools
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !busy && content.trim() && title.trim()) {
                    e.preventDefault();
                    void submit();
                  }
                }}
                aria-keyshortcuts="Control+Enter Meta+Enter"
                placeholder="Paste or write your post, email or page copy here."
              />
            </Field>
            <p className="-mt-2 text-xs text-muted-foreground" aria-live="polite">
              {words(content)} word{words(content) === 1 ? "" : "s"}
              {exclamations(content) > 0 && ` · ${exclamations(content)} exclamation mark${exclamations(content) === 1 ? "" : "s"}`}
              {content === MISTAKES_POST && " · this sample has a few planted mistakes for you to find and fix"}
            </p>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="hidden text-xs text-muted-foreground sm:block">
                Press <kbd className="kbd">Ctrl</kbd> or <kbd className="kbd">⌘</kbd> + <kbd className="kbd">Enter</kbd> to check
              </p>
              <button
                data-guide="check-it"
                onClick={() => void submit()}
                disabled={busy || !content.trim() || !title.trim()}
                className="btn btn-primary"
              >
                {busy ? "Checking…" : <>Check it <span aria-hidden className="btn-arrow">→</span></>}
              </button>
            </div>
          </>
        ) : (
          <>
            <div
              data-guide={mode === "file" ? "new-primary" : undefined}
              tabIndex={-1}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                chooseFile(e.dataTransfer.files?.[0] ?? null);
              }}
              className={`animate-fade-up rounded-2xl border-2 border-dashed px-5 py-6 text-center transition-all ${
                dragOver
                  ? "border-brand bg-brand/10 shadow-[0_0_0_6px_var(--ring-glow)]"
                  : "border-brand/60 bg-brand/[0.04] shadow-[0_0_0_4px_var(--ring-glow)]"
              }`}
            >
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                onChange={(e) => {
                  chooseFile(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
              />
              {!file ? (
                <>
                  <span className="mx-auto grid size-11 place-items-center rounded-2xl bg-card text-brand ring-1 ring-border">
                    <FileUp className="size-5" aria-hidden />
                  </span>
                  <p className="mt-3 text-sm font-semibold text-foreground">Drop your document or image here</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    PDF, Word, PNG or JPEG · up to 4 MB · PDFs up to 20 pages
                  </p>
                  <button
                    type="button"
                    data-guide="upload"
                    onClick={() => fileInput.current?.click()}
                    className="btn btn-secondary btn-sm mt-3"
                  >
                    Choose a file
                  </button>
                </>
              ) : (
                <div className="flex items-center gap-3 text-left">
                  {preview ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={preview} alt="" className="size-12 shrink-0 rounded-lg object-cover ring-1 ring-border" />
                  ) : (
                    <span className="grid size-12 shrink-0 place-items-center rounded-lg bg-card text-brand ring-1 ring-border">
                      {isImageFile(file) ? <ImageIcon className="size-5" aria-hidden /> : <FileText className="size-5" aria-hidden />}
                    </span>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-foreground">{file.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {fileKindLabel(file)} · {(file.size / 1024).toFixed(0)} KB · ready to check
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => chooseFile(null)}
                    className="btn btn-ghost btn-sm"
                    aria-label="Remove this file"
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                </div>
              )}
            </div>

            {fileError && (
              <p role="alert" className="text-sm text-danger-fg">
                {fileError}
              </p>
            )}

            {file && isImageFile(file) && (
              <Field label="Alt text (findings check it too)">
                <input
                  className="field h-[38px] px-3"
                  value={altText}
                  onChange={(e) => setAltText(e.target.value)}
                  placeholder="Describe what a person who cannot see the image needs to know"
                />
              </Field>
            )}

            <p className="text-xs leading-relaxed text-muted-foreground">
              PDFs report the page and line of each finding; Word reports the section and paragraph, and opens in a page
              preview with each issue highlighted and numbered. A PDF or image is fixed in its source and uploaded as a
              new version; Word fixes are made inside the file. Scanned PDFs without a text layer are refused rather
              than guessed at.
            </p>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                {file ? "The result opens with the issue pins on the document." : "Choose a file to check it."}
              </p>
              <button
                data-guide="upload"
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
        Text and files are checked the same way: the always-on rules run first, and AI adds judgement when a provider is
        available.
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
