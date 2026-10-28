import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { Submission } from "@/lib/api";
import { RiskBadge, StatusBadge } from "@/components/fx";

function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** One submission, presented the same way wherever a role needs to act on it. */
export function SubmissionCard({
  submission,
  action = "Open",
}: {
  submission: Submission;
  action?: string;
}) {
  const open = submission.open_findings ?? 0;

  return (
    <Link
      href={`/submissions/${submission.id}`}
      className="surface surface-interactive group flex h-full flex-col p-6"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={submission.status} />
        <RiskBadge risk={submission.risk} />
        <span className="ml-auto text-xs capitalize text-muted-foreground">
          {submission.channel} · {when(submission.created_at)}
        </span>
      </div>
      <p className="mt-4 text-lg font-bold tracking-tight text-foreground">{submission.title}</p>
      {submission.router_note && (
        <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-foreground-secondary">
          {submission.router_note}
        </p>
      )}
      <div className="mt-auto flex items-end justify-between gap-3 pt-6">
        <p className="text-sm text-muted-foreground">
          <span className="text-2xl font-bold tabular-nums text-foreground">{open}</span> open finding
          {open === 1 ? "" : "s"}
        </p>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-brand">
          {action} <ArrowRight className="size-4" aria-hidden />
        </span>
      </div>
    </Link>
  );
}
