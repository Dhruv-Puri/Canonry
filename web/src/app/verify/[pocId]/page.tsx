import { Suspense } from "react";
import { VerifyClient } from "./verify-client";

async function VerifyInner({ params }: { params: Promise<{ pocId: string }> }) {
  const { pocId } = await params;
  return <VerifyClient pocId={pocId} />;
}

// Next 16 (cacheComponents): stream the dynamic id instead of blocking prerender.
export default function VerifyPage({ params }: { params: Promise<{ pocId: string }> }) {
  return (
    <Suspense fallback={<div className="mx-auto max-w-2xl p-10 text-sm text-muted-foreground">Checking seal…</div>}>
      <VerifyInner params={params} />
    </Suspense>
  );
}
