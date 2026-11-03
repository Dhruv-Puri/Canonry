"use client";

import Link from "next/link";
import { Check } from "lucide-react";
import type { ReactNode } from "react";

/** The four stages every piece of content goes through, in plain words. */
const STAGES = ["Checked", "Fix issues", "In review", "Approved"] as const;

export function stageOf(status: string): number {
  if (["Signed", "Approved", "Exempt-approved"].includes(status)) return 3;
  if (status === "In review") return 2;
  return 1; // with the creator: checked, now fixing
}

/** A compact stepper so a newcomer always knows where this draft is. */
export function JourneySteps({ status }: { status: string }) {
  const current = stageOf(status);
  const done = (i: number) => i < current || (i === 3 && current === 3);
  return (
    <ol aria-label="Progress" className="flex flex-wrap items-center gap-x-1 gap-y-2 text-xs">
      {STAGES.map((label, i) => {
        const isDone = done(i);
        const isNow = i === current && !isDone;
        return (
          <li key={label} className="flex items-center gap-1" aria-current={isNow ? "step" : undefined}>
            <span
              className={`grid size-5 place-items-center rounded-full text-[10px] font-bold ${
                isDone
                  ? "bg-success-fg text-background"
                  : isNow
                    ? "bg-foreground text-background"
                    : "border border-border-strong text-muted-foreground"
              }`}
            >
              {isDone ? <Check className="size-3" strokeWidth={3} aria-hidden /> : i + 1}
            </span>
            <span className={isNow ? "font-semibold text-foreground" : isDone ? "text-foreground-secondary" : "text-muted-foreground"}>
              {label}
            </span>
            {i < STAGES.length - 1 && <span aria-hidden className="mx-1.5 h-px w-5 bg-border-strong sm:w-8" />}
          </li>
        );
      })}
    </ol>
  );
}

/** One clear "what now" for the person looking at this draft. */
export function NextStep({
  tone = "brand",
  title,
  children,
  actions,
  progress,
}: {
  tone?: "brand" | "success" | "muted";
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  progress?: { done: number; total: number };
}) {
  const box =
    tone === "success"
      ? "border-success-border bg-success-bg"
      : tone === "muted"
        ? "border-border bg-muted/60"
        : "border-brand/30 bg-brand/[0.06]";
  return (
    <section aria-label="Next step" className={`rounded-2xl border ${box} p-4 sm:p-5`}>
      <p className="eyebrow">Next step</p>
      <h2 className="mt-1 text-lg font-bold tracking-tight text-foreground">{title}</h2>
      {children && <div className="mt-1 text-sm leading-relaxed text-foreground-secondary">{children}</div>}
      {progress && progress.total > 0 && (
        <div className="mt-3 flex items-center gap-3">
          <div
            role="progressbar"
            aria-label="Issues handled"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-border"
          >
            <div
              className="h-full rounded-full bg-success-fg transition-[width] duration-500"
              style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
            />
          </div>
          <span className="shrink-0 text-xs font-medium text-foreground-secondary">
            {progress.done} of {progress.total} handled
          </span>
        </div>
      )}
      {actions && <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>}
    </section>
  );
}

export function VerifyLink({ pocId }: { pocId: string }) {
  return (
    <Link href={`/verify/${pocId}`} data-guide="verify" className="btn btn-primary">
      Verify the approval <span aria-hidden className="btn-arrow">→</span>
    </Link>
  );
}
