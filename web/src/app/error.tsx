"use client";

import Link from "next/link";
import { useEffect } from "react";
import { RefreshCw } from "lucide-react";

/** A screen that failed to render: say what happened, offer a retry, never show a stack trace. */
export default function ErrorPage({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <section role="alert" className="surface mx-auto mt-6 max-w-xl px-8 py-12 text-center">
      <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-danger-bg text-danger-fg">
        <RefreshCw className="size-7" aria-hidden />
      </span>
      <p className="eyebrow mt-5">Something went wrong</p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight">This screen couldn&apos;t load</h1>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
        Nothing you saved is lost. Try again; if the engine was asleep on the free server, the second try usually works.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <button type="button" className="btn btn-primary" onClick={() => retry()}>
          Try again
        </button>
        <Link href="/" className="btn btn-secondary">
          Go to your home
        </Link>
      </div>
    </section>
  );
}
