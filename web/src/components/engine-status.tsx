"use client";

// What a visitor sees while the checking engine is asleep or unreachable.
// <IdentityGate> decides when; these components only say it.

import { LoaderCircle } from "lucide-react";
import { ApiError, ENGINE_UNREACHABLE } from "@/lib/api";
import { BrandMark } from "@/components/brand";

/** After this long without an answer, say the engine is waking up instead of showing a blank page. */
export const WAKE_NOTICE_MS = 3_000;
/** After this long, stop waiting and offer "Try again". */
export const GIVE_UP_MS = 45_000;
/** Pause between attempts while the engine starts (the proxy answers 5xx until it is up). */
export const RETRY_MS = 2_500;

/** The engine is not up yet (connection refused, proxy 5xx): worth asking again. */
export function isWaking(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 0 || e.status >= 500);
}

/** Blank for the first 3 s (most loads finish by then), then the waking card with a counter. */
export function EngineLoading({ elapsedMs }: { elapsedMs: number }) {
  if (elapsedMs < WAKE_NOTICE_MS) return <div className="min-h-dvh" aria-busy="true" />;
  return <EngineWaking seconds={Math.floor(elapsedMs / 1000)} />;
}

/** Shown after 3 s without an answer: the engine sleeps after a quiet spell and takes a moment to wake. */
export function EngineWaking({ seconds }: { seconds: number }) {
  // fills over the usual 30 s, then waits near the end instead of pretending to finish
  const pct = Math.min(92, Math.round((seconds / 30) * 100));
  return (
    <main className="grid min-h-dvh place-items-center px-5" aria-busy="true">
      <div className="surface w-full max-w-md p-8 text-center">
        <BrandMark className="mx-auto size-9" />
        <h1 className="mt-4 text-xl font-bold tracking-tight text-foreground">Waking up the checking engine…</h1>
        <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">
          This happens after a quiet spell and usually takes 20–30 seconds. Canonry opens by itself when it&apos;s ready.
        </p>
        <div className="mt-6 flex items-center gap-3">
          <LoaderCircle className="size-4 shrink-0 animate-spin text-brand motion-reduce:animate-none" aria-hidden />
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full rounded-full bg-brand transition-[width] duration-1000 ease-linear" style={{ width: `${pct}%` }} />
          </div>
          <span className="w-10 text-right text-sm tabular-nums text-muted-foreground">
            <span className="sr-only">Waiting for </span>{seconds}s
          </span>
        </div>
        <p className="sr-only" role="status">Waking up the checking engine. This usually takes 20 to 30 seconds.</p>
      </div>
    </main>
  );
}

/** Shown when the engine does not answer at all; one button tries again. */
export function EngineDown({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="grid min-h-dvh place-items-center px-5">
      <div role="alert" className="surface max-w-md p-8 text-center">
        <BrandMark className="mx-auto size-9" />
        <h1 className="mt-4 text-xl font-bold tracking-tight text-foreground">Canonry is not answering</h1>
        <p className="mt-2 text-sm leading-relaxed text-foreground-secondary">{ENGINE_UNREACHABLE}</p>
        <button type="button" onClick={onRetry} className="btn btn-primary mt-6">
          Try again
        </button>
      </div>
    </main>
  );
}
