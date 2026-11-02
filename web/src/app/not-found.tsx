import type { Metadata } from "next";
import Link from "next/link";
import { Compass } from "lucide-react";

export const metadata: Metadata = { title: "Page not found" };

/** Any address the app does not have: say so plainly and offer the way back. */
export default function NotFound() {
  return (
    <section className="surface mx-auto mt-6 max-w-xl px-8 py-12 text-center">
      <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-muted text-brand">
        <Compass className="size-7" aria-hidden />
      </span>
      <p className="eyebrow mt-5">Error 404</p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight">This page doesn&apos;t exist</h1>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-foreground-secondary">
        The link may be mistyped or out of date. Approval links stay valid: if you were checking a published piece,
        open the verify link you were given.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Link href="/" className="btn btn-primary">
          Go to your home <span aria-hidden className="btn-arrow">→</span>
        </Link>
        <Link href="/new" className="btn btn-secondary">
          Check a draft
        </Link>
      </div>
    </section>
  );
}
