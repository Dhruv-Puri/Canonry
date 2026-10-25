import { Suspense } from "react";
import { SubmissionDetailClient } from "./detail";

async function SubmissionInner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SubmissionDetailClient sid={id} />;
}

// Next 16 (cacheComponents): awaiting `params` at the route's top level is
// runtime data — it blocks prerendering. Wrapping the await in Suspense lets
// the shell render instantly and the dynamic content stream in.
export default function SubmissionPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="mx-auto max-w-4xl p-10 text-sm text-muted-foreground">Loading submission…</div>}>
      <SubmissionInner params={params} />
    </Suspense>
  );
}
