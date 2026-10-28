"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { BrandMark } from "@/components/brand";

const MESSAGES = [
  "Running the rule checks and asking the AI model…",
  "Comparing implied claims with your approved facts…",
  "Checking tone against your voice rules…",
  "Tracing every finding back to its source…",
  "Nothing is published without a person deciding.",
];

/**
 * The synchronous check request can take a minute while the AI models answer.
 * Keep the wait in the product's own voice: a warm paper card, the seal, and a
 * scanning line, rather than a generic full-page spinner.
 */
export function AiLoadingScreen({
  open,
  title = "Checking your work",
}: {
  open: boolean;
  title?: string;
}) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      setVisible(false);
      return;
    }

    // Don't flash the overlay for checks that finish immediately.
    const show = window.setTimeout(() => setVisible(true), 220);
    setStep(0);
    const tick = window.setInterval(() => {
      setStep((i) => (i + 1) % MESSAGES.length);
    }, 4200);

    return () => {
      window.clearTimeout(show);
      window.clearInterval(tick);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const bodyOverflow = document.body.style.overflow;
    const htmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = htmlOverflow;
    };
  }, [open]);

  if (!open || !visible || !mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] grid place-items-center overflow-y-auto bg-background/85 px-4 py-4 backdrop-blur-sm"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="surface animate-fade-up max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto border-border-strong shadow-float">
        <div className="border-b border-border bg-muted/60 px-5 py-5 sm:px-6">
          <div className="flex flex-wrap items-center gap-3">
            <BrandMark className="size-8" />
            <div>
              <p className="eyebrow">Review in progress</p>
              <h2 className="mt-0.5 text-xl font-bold tracking-tight text-foreground">{title}</h2>
            </div>
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-card px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-brand" />
              Working
            </span>
          </div>
        </div>

        <div className="space-y-4 p-5 sm:p-6">
          <div className="paper relative overflow-hidden px-4 py-4">
            <span aria-hidden className="demo-scan pointer-events-none absolute inset-x-0 h-px bg-brand/50" />
            <div aria-hidden className="space-y-2.5">
              <div className="h-2 w-10/12 rounded-full bg-border-strong/70" />
              <div className="h-2 w-8/12 rounded-full bg-border-strong/55" />
              <div className="h-2 w-11/12 rounded-full bg-border-strong/70" />
              <div className="h-2 w-6/12 rounded-full bg-border-strong/55" />
            </div>
            <div aria-hidden className="mt-4 flex items-center gap-2">
              <span className="marker font-serif text-sm text-foreground">Checking every claim</span>
              <span className="h-1.5 w-12 rounded-full bg-highlight" />
            </div>
          </div>

          <p key={step} className="animate-fade-up min-h-12 text-sm text-foreground-secondary">
            {MESSAGES[step]}
          </p>

          <div className="flex items-start gap-2.5 rounded-xl border border-border bg-muted/50 px-3.5 py-3">
            <span aria-hidden className="mt-1.5 size-2 shrink-0 animate-pulse rounded-full bg-brand" />
            <p className="text-xs leading-relaxed text-muted-foreground">
              Rule checks run first. The AI review comes next and can take a minute or two on a
              free tier. Keep this tab open — the findings appear here when it finishes.
            </p>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
