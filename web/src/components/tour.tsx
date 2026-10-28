"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Search,
  Sparkles,
  Stamp,
  X,
  type LucideIcon,
} from "lucide-react";
import { BrandMark } from "@/components/brand";

type Step = {
  eyebrow: string;
  title: string;
  body: string;
  icon: LucideIcon;
  points?: string[];
  compare?: { rule: string[]; ai: string[] };
};

const STEPS: Step[] = [
  {
    eyebrow: "Start here",
    title: "Two kinds of checks, one report",
    body:
      "Canonry doesn't only ask an AI. Most findings come from deterministic rules that always run; AI adds judgement where rules can't.",
    icon: Search,
    compare: {
      rule: ["Terminology and banned words", "Readability, channel limits, CTA", "Tone heuristics and confidential leaks"],
      ai: ["Implied claims", "Fact verification", "Tone judgement"],
    },
  },
  {
    eyebrow: "Always on",
    title: "The rule checks run first",
    body:
      "They are deterministic, fast, and free. They still run when the AI is off, out of quota, or every provider is busy.",
    icon: Check,
    points: [
      "Terminology, banned words, readability, channel limits and calls to action.",
      "Tone heuristics and confidential-leak checks.",
      "Every finding cites the rule, term or fact it was checked against.",
      "A check can come back with findings even when AI is marked pending.",
    ],
  },
  {
    eyebrow: "Extra coverage",
    title: "AI suggests; people decide",
    body:
      "When a provider answers, AI looks for implied claims, verifies them against your Fact Library, and judges tone against your voice rules.",
    icon: Sparkles,
    points: [
      "AI findings are suggestions: accept, edit, or dispute them.",
      "If the provider is unavailable, AI is marked pending — rule findings still arrive.",
      "Confidential facts are held back from free AI providers.",
    ],
  },
  {
    eyebrow: "The finish line",
    title: "Approve, sign, verify",
    body:
      "Resolve the findings, send the draft for review, and approve it. The approval becomes a signed Proof of Compliance anyone can verify.",
    icon: Stamp,
    points: [
      "A reviewer approves or requests changes.",
      "In production, a different reviewer must approve.",
      "The seal is public and can be checked later.",
    ],
  },
];

/**
 * A first-run tour of the review pipeline. It deliberately separates the
 * always-on rule checks from the AI-assisted ones, because a pending AI review
 * never means the draft went unchecked.
 */
export function ProductTour({
  open,
  onClose,
  onFinish,
}: {
  open: boolean;
  onClose: () => void;
  onFinish: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [step, setStep] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open || !mounted) return;
    setStep(0);
    const frame = window.requestAnimationFrame(() => cardRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, mounted]);

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

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setStep((current) => Math.min(STEPS.length - 1, current + 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setStep((current) => Math.max(0, current - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!mounted || !open) return null;

  const current = STEPS[step];
  const Icon = current.icon;
  const last = step === STEPS.length - 1;

  return createPortal(
    <div
      className="fixed inset-0 z-[90] grid place-items-center overflow-y-auto bg-background/85 px-4 py-4 backdrop-blur-sm"
      role="presentation"
    >
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        className="surface animate-fade-up max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto border-border-strong shadow-float outline-none"
      >
        <div className="flex items-start gap-3 border-b border-border bg-muted/60 px-5 py-4 sm:px-6">
          <BrandMark className="mt-0.5 size-9" />
          <div>
            <p className="eyebrow">Quick tour</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Step {step + 1} of {STEPS.length}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost btn-sm ml-auto" aria-label="Skip tour">
            <X className="size-3.5" aria-hidden /> Skip tour
          </button>
        </div>

        <div className="p-5 sm:p-7">
          <div className="flex items-start gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl border border-border-strong bg-card text-brand shadow-sm">
              <Icon className="size-5" strokeWidth={1.8} aria-hidden />
            </span>
            <div>
              <p className="eyebrow">{current.eyebrow}</p>
              <h2 id="tour-title" className="mt-1 text-2xl font-bold tracking-tight text-foreground">
                {current.title}
              </h2>
            </div>
          </div>

          <p className="mt-4 text-sm leading-relaxed text-foreground-secondary">{current.body}</p>

          {current.compare ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-border-strong bg-card p-4">
                <div className="flex items-center gap-2">
                  <Search className="size-4 text-brand" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">Rule-based</span>
                </div>
                <p className="mt-2 text-sm font-semibold text-foreground">Always runs</p>
                <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-foreground-secondary">
                  {current.compare.rule.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-brand" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-border-strong bg-muted/50 p-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="size-4 text-brand" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-brand">AI-assisted</span>
                </div>
                <p className="mt-2 text-sm font-semibold text-foreground">When available</p>
                <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-foreground-secondary">
                  {current.compare.ai.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-brand" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <ul className="mt-5 space-y-2.5 text-sm leading-relaxed text-foreground-secondary">
              {current.points?.map((point) => (
                <li key={point} className="flex gap-2.5">
                  <Check className="mt-0.5 size-4 shrink-0 text-brand" strokeWidth={2.2} aria-hidden />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          )}

          {step === 0 && (
            <p className="mt-4 rounded-xl border border-border bg-muted/50 px-3.5 py-3 text-xs leading-relaxed text-muted-foreground">
              The same report shows both: rule findings always arrive; AI findings appear when the model answers, or
              the AI section is marked pending.
            </p>
          )}
        </div>

        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 border-t border-border bg-card px-5 py-4 sm:px-6">
          <div className="flex items-center gap-1.5" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            {STEPS.map((s, i) => (
              <span
                key={s.title}
                aria-hidden
                className={`h-1.5 rounded-full transition-all ${
                  i === step ? "w-6 bg-brand" : "w-1.5 bg-border-strong"
                }`}
              />
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setStep((current) => Math.max(0, current - 1))}
              disabled={step === 0}
              className="btn btn-secondary btn-sm"
            >
              <ArrowLeft className="size-3.5" aria-hidden /> Back
            </button>
            {last ? (
              <button type="button" onClick={onFinish} className="btn btn-primary btn-sm">
                Try a sample <ArrowRight className="size-3.5" aria-hidden />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStep((current) => Math.min(STEPS.length - 1, current + 1))}
                className="btn btn-primary btn-sm"
              >
                Next <ArrowRight className="size-3.5" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
