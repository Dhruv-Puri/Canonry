"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { FileText, Image as ImageIcon } from "lucide-react";
import { CATEGORY_LABEL, TIER_LABEL, type Finding, type LocatorBlock } from "@/lib/api";

/**
 * A document shown the way it was laid out: PDF pages stay pages, Word keeps
 * its sections and paragraphs. Findings are marked where they sit and carry
 * the same number as their card, so the preview and the report agree.
 */

type Block = { start: number; end: number; heading: boolean };
type Sheet = { page: number | null; start: number; end: number; blocks: Block[] };

/** Where a finding sits in this text: the engine's offsets when they still match, else the first occurrence. */
function locateRange(content: string, f: Finding): [number, number] | null {
  if (!f.span_text) return null;
  if (content.slice(f.span_start, f.span_end) === f.span_text) return [f.span_start, f.span_end];
  const i = content.indexOf(f.span_text);
  return i < 0 ? null : [i, i + f.span_text.length];
}

function isAllCaps(text: string): boolean {
  const letters = text.replace(/[^A-Za-z]/g, "");
  return letters.length >= 4 && text === text.toUpperCase();
}

/** Group a PDF page's visual lines into headings and paragraphs, keeping line breaks. */
function pdfBlocks(content: string, lines: { start: number; end: number }[]): Block[] {
  const rows = lines.map((l) => {
    const raw = content.slice(l.start, l.end);
    const text = raw.trim();
    return { start: l.start, end: l.end, raw, text, blank: text === "" };
  });
  const blocks: Block[] = [];
  let current: Block | null = null;
  const flush = () => {
    if (current) {
      blocks.push(current);
      current = null;
    }
  };

  rows.forEach((row, i) => {
    if (row.blank) {
      flush();
      return;
    }
    const before = i === 0 || rows[i - 1].blank;
    const noEndPunctuation = !/[.!?,;:]$/.test(row.text);
    // A label-like line: short, no figures or colons, and opening a block.
    // That keeps centred titles as headings without promoting body lines.
    const label = row.text.length <= 60 && !/[0-9:]/.test(row.text);
    const heading = noEndPunctuation && (isAllCaps(row.text) || (label && before));

    if (heading) {
      flush();
      blocks.push({ start: row.start, end: row.end, heading: true });
      return;
    }
    const indent = row.raw.length - row.raw.trimStart().length;
    if (!current) current = { start: row.start + indent, end: row.end, heading: false };
    else current.end = row.end;
  });
  flush();
  return blocks;
}

/** Word: one block per paragraph; a paragraph that repeats its section heading is a heading. */
function docxBlocks(content: string, map: LocatorBlock[]): Block[] {
  return map
    .filter((b) => content.slice(b.start, b.end).trim() !== "")
    .map((b) => {
      const text = content.slice(b.start, b.end).trim();
      return { start: b.start, end: b.end, heading: Boolean(b.section) && text === (b.section ?? "").trim() };
    });
}

function buildSheets(content: string, map: LocatorBlock[] | null, kind: "pdf" | "docx"): Sheet[] {
  if (map?.length) {
    if (kind === "pdf") {
      const pages = map
        .filter((p) => content.slice(p.start, p.end).trim() !== "")
        .map((p) => ({
          page: p.page ?? null,
          start: p.start,
          end: p.end,
          blocks: p.lines?.length
            ? pdfBlocks(content, p.lines)
            : [{ start: p.start, end: p.end, heading: false }],
        }));
      if (pages.length) return pages;
    } else if (map.some((b) => b.page != null)) {
      const numbers = Array.from(new Set(map.map((b) => b.page ?? null)));
      const sheets = numbers.map((n) => {
        const blocks = map.filter((b) => (b.page ?? null) === n);
        return {
          page: n,
          start: blocks[0]?.start ?? 0,
          end: blocks[blocks.length - 1]?.end ?? 0,
          blocks: docxBlocks(content, blocks),
        };
      });
      if (sheets.some((s) => s.blocks.length)) return sheets;
    } else {
      return [{ page: null, start: map[0].start, end: map[map.length - 1].end, blocks: docxBlocks(content, map) }];
    }
  }
  return content.trim()
    ? [{ page: null, start: 0, end: content.length, blocks: [{ start: 0, end: content.length, heading: false }] }]
    : [{ page: null, start: 0, end: 0, blocks: [] }];
}

type Mark = { f: Finding; start: number; end: number; number: number | undefined };

const TIER_ORDER: Record<string, number> = { definite: 0, likely: 1, consider: 2 };
function worstTier(marks: Mark[]): string {
  return marks.map((m) => m.f.tier).sort((a, b) => (TIER_ORDER[a] ?? 3) - (TIER_ORDER[b] ?? 3))[0] ?? "consider";
}

/** Document type sizes, set inline so a stale stylesheet can never blow them up. */
const TYPE_BODY = { fontSize: "12.5px", lineHeight: 1.7 } as const;
const TYPE_HEADING = { fontSize: "12px", lineHeight: 1.45 } as const;
const TYPE_PIN = { minWidth: 12, height: 12, fontSize: 8, padding: 0 } as const;

/** Severity is shown by colour AND line style, never colour alone. */
const HIGHLIGHT: Record<string, string> = {
  definite: "rounded-sm bg-danger-bg/80 underline decoration-danger-fg decoration-2 underline-offset-4",
  likely: "rounded-sm bg-warning-bg/80 underline decoration-warning-fg decoration-dashed decoration-2 underline-offset-4",
  consider: "rounded-sm bg-muted underline decoration-muted-foreground decoration-dotted decoration-2 underline-offset-4",
};

/** A slice of the document with every finding that covers it marked, split at their boundaries. */
function MarkedRange({ text, base, marks }: { text: string; base: number; marks: Mark[] }) {
  const end = base + text.length;
  const local = marks.filter((m) => m.end > base && m.start < end);
  if (local.length === 0) return <>{text}</>;

  const cuts = Array.from(
    new Set([base, end, ...local.flatMap((m) => [Math.max(base, m.start), Math.min(end, m.end)])]),
  ).sort((a, b) => a - b);

  return (
    <>
      {cuts.slice(0, -1).map((start, i) => {
        const stop = cuts[i + 1];
        const covering = local
          .filter((m) => m.start <= start && m.end >= stop)
          .sort((a, b) => (TIER_ORDER[a.f.tier] ?? 3) - (TIER_ORDER[b.f.tier] ?? 3));
        const slice = text.slice(start - base, stop - base);
        if (covering.length === 0) return <span key={i}>{slice}</span>;
        return (
          <mark key={i} className={`${HIGHLIGHT[worstTier(covering)]} text-foreground`}>
            {covering
              .filter((m) => m.start === start && m.number !== undefined)
              .map((m) => (
                <a
                  key={m.f.id}
                  href={`#finding-${m.f.id}`}
                  className="doc-pin"
                  style={TYPE_PIN}
                  aria-label={`Issue ${m.number}`}
                  title={`${CATEGORY_LABEL[m.f.category] ?? m.f.category} · ${TIER_LABEL[m.f.tier]}`}
                >
                  {m.number}
                </a>
              ))}
            <a
              href={`#finding-${covering[0].f.id}`}
              className="rounded-sm no-underline"
              title={covering
                .map((m) => `${CATEGORY_LABEL[m.f.category] ?? m.f.category} · ${TIER_LABEL[m.f.tier]}`)
                .join("\n")}
            >
              {slice}
            </a>
          </mark>
        );
      })}
    </>
  );
}

export function DocumentPreview({
  kind,
  filename,
  src,
  content,
  locatorMap,
  findings,
  numbers,
}: {
  kind: "pdf" | "docx";
  filename: string;
  /** the uploaded file itself, so its real pages (and images) can be shown */
  src: string;
  content: string;
  locatorMap: LocatorBlock[] | null;
  findings: Finding[];
  numbers: Map<string, number>;
}) {
  const sheets = useMemo(() => buildSheets(content, locatorMap, kind), [content, locatorMap, kind]);
  const marks = useMemo<Mark[]>(
    () =>
      findings
        .filter((f) => f.status === "open")
        .map((f) => {
          const at = locateRange(content, f);
          return at ? { f, start: at[0], end: at[1], number: numbers.get(f.id) } : null;
        })
        .filter((m): m is Mark => m !== null),
    [findings, content, numbers],
  );

  const [view, setView] = useState<"text" | "original">("text");
  const [full, setFull] = useState(false);

  // The original file opens in its own full-screen layer: the browser's PDF
  // viewer is not designed to live inside a clipped, scrolling card, where it
  // flickers. One surface, one size, no reflow around it.
  useEffect(() => {
    if (!full) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [full]);
  const pageCount = kind === "pdf" ? sheets.length : null;
  const total = marks.length;

  return (
    <div id="doc-viewer" className="doc-desk mt-4 scroll-mt-24 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2.5">
        <div role="tablist" aria-label="How to show the file" className="flex items-center gap-0.5 rounded-full bg-white/10 p-0.5">
          <button
            type="button"
            role="tab"
            aria-selected={view === "text"}
            onClick={() => setView("text")}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
              view === "text" ? "bg-white/90 text-[#221a13]" : "text-[#e8d8c4] hover:bg-white/10"
            }`}
          >
            <FileText className="size-3.5" aria-hidden /> Marked text
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "original"}
            onClick={() => setView("original")}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
              view === "original" ? "bg-white/90 text-[#221a13]" : "text-[#e8d8c4] hover:bg-white/10"
            }`}
          >
            <ImageIcon className="size-3.5" aria-hidden /> Original pages
          </button>
        </div>
        {view === "text" && sheets.length > 1 && (
          <nav aria-label="Jump to a page" className="flex flex-wrap gap-1">
            {sheets.map((sheet, i) => (
              <a
                key={i}
                href={`#doc-page-${i + 1}`}
                className="rounded-full px-2 py-1 text-[11px] font-medium text-[#d9c8b3] transition-colors hover:bg-white/10 hover:text-white"
              >
                {sheet.page ? `Page ${sheet.page}` : `Sheet ${i + 1}`}
              </a>
            ))}
          </nav>
        )}
        <span className="ml-auto text-[11px] text-[#cbb79f]">
          {total > 0 ? `${total} issue${total === 1 ? "" : "s"} pinned` : "No open issues on this version"}
        </span>
      </div>

      {view === "text" ? (
      <div className="max-h-[70vh] overflow-y-auto px-2 pb-5 pt-3 sm:px-5">
        {sheets.map((sheet, index) => {
          const pins = marks.filter((m) => m.start >= sheet.start && m.start < sheet.end).length;
          return (
            <article
              key={index}
              id={`doc-page-${index + 1}`}
              className="doc-sheet relative mx-auto mb-5 w-full max-w-[640px] scroll-mt-4 px-6 py-7 text-[#2b1d14] sm:px-10 sm:py-9"
            >
              <header className="mb-5 flex items-baseline justify-between gap-3 border-b border-[#e7dccb] pb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[#8b745c]">
                <span className="truncate">{filename}</span>
                <span className="shrink-0">
                  {sheet.page
                    ? `Page ${sheet.page}${pageCount ? ` of ${pageCount}` : ""}`
                    : kind === "docx"
                      ? "Word document"
                      : "Document"}
                  {pins > 0 ? ` · ${pins} issue${pins === 1 ? "" : "s"}` : ""}
                </span>
              </header>

              {sheet.blocks.length === 0 && (
                <p className="text-sm italic text-[#8b745c]">No readable text on this page.</p>
              )}
              {sheet.blocks.map((block, i) => (
                <p
                  key={i}
                  className={block.heading ? "doc-heading" : "doc-body"}
                  style={block.heading ? TYPE_HEADING : TYPE_BODY}
                >
                  <MarkedRange text={content.slice(block.start, block.end)} base={block.start} marks={marks} />
                </p>
              ))}

              <footer className="mt-8 border-t border-[#e7dccb] pt-2 text-center text-[10px] text-[#8b745c]">
                {sheet.page ?? "Canonry"}
              </footer>
            </article>
          );
        })}
      </div>

      ) : (
        <div className="bg-[#2a221b] px-4 py-8 text-center">
          {kind === "pdf" ? (
            <>
              <p className="text-[12px] leading-relaxed text-[#e8d8c4]">
                See the pages exactly as they were made: images, fonts and the real layout.
              </p>
              <button type="button" onClick={() => setFull(true)} className="btn btn-sm btn-secondary mt-3">
                Open the original pages
              </button>
              <p className="mt-2 text-[11px] text-[#a8927a]">
                Opens full screen, so the PDF viewer is never squeezed into this card.
              </p>
            </>
          ) : (
            <>
              <p className="text-[12px] leading-relaxed text-[#e8d8c4]">
                A Word file keeps its images and layout in Word, not in the browser.
              </p>
              <a className="btn btn-sm btn-secondary mt-3" href={src} target="_blank" rel="noreferrer">
                Open the original .docx
              </a>
            </>
          )}
        </div>
      )}

      <p className="border-t border-white/10 px-4 py-2 text-[11px] leading-relaxed text-[#cbb79f]">
        Highlights sit exactly where the finding was found. The number on a highlight matches its issue card.
      </p>

      {full &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label={`${filename} — original pages`}
            className="fixed inset-0 z-[95] flex flex-col bg-[#161009] p-3 sm:p-4"
          >
            <div className="mb-2 flex shrink-0 items-center gap-2">
              <p className="min-w-0 truncate text-[12px] font-medium text-[#e8d8c4]">{filename}</p>
              <a
                href={src}
                target="_blank"
                rel="noreferrer"
                className="ml-auto rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-[#e8d8c4] hover:bg-white/20"
              >
                Open in a new tab
              </a>
              <button
                type="button"
                onClick={() => setFull(false)}
                aria-label="Close the original pages"
                className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-[#e8d8c4] hover:bg-white/20"
              >
                Close
              </button>
            </div>
            <iframe
              src={`${src}#toolbar=1&navpanes=0&view=FitH`}
              title={`${filename} — original pages`}
              className="min-h-0 w-full flex-1 rounded-md border-0 bg-white"
            />
          </div>,
          document.body,
        )}
    </div>
  );
}
