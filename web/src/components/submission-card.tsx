import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { Submission } from "@/lib/api";
import { RiskBadge, StatusBadge } from "@/components/fx";
import { plural } from "@/lib/format";

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

/**
 * What happens next, in words, for the person looking at the card.
 * `act` is true when the next step is theirs (shown as the call to action).
 */
export function nextStep(s: Submission, viewer: "reviewer" | "writer"): { text: string; act: boolean } {
  const open = s.open_findings ?? 0;
  const signed = s.status === "Signed" || s.status === "Approved" || s.status === "Exempt-approved";
  if (signed) return { text: "Signed. View the approval", act: false };
  if (viewer === "reviewer") {
    if (s.status === "In review") return { text: "Review", act: true };
    return { text: "Waiting for writer", act: false };
  }
  if (s.status === "In review") return { text: "Waiting for reviewer", act: false };
  if (s.status === "Changes requested") return { text: "Make the requested changes", act: true };
  if (open > 0) return { text: `Fix ${plural(open, "issue")}`, act: true };
  if (s.status === "Checked") return { text: "Send for review", act: true };
  return { text: "Open", act: true };
}

/** One submission, presented the same way wherever a role needs to act on it. */
export function SubmissionCard({
  submission,
  viewer = "writer",
}: {
  submission: Submission;
  viewer?: "reviewer" | "writer";
}) {
  const open = submission.open_findings ?? 0;
  const step = nextStep(submission, viewer);

  return (
    <Link
      href={`/submissions/${submission.id}`}
      className="surface surface-interactive group flex h-full flex-col p-6"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={submission.status} />
        <RiskBadge risk={submission.risk} />
        <span className="ml-auto text-xs text-muted-foreground">
          {/* capitalise the channel only: on the whole line it turned "pm" into "Pm" */}
          <span className="capitalize">{submission.channel}</span> · {when(submission.created_at)}
        </span>
      </div>
      <p className="mt-4 text-lg font-bold tracking-tight text-foreground [overflow-wrap:anywhere]">{submission.title}</p>
      <Verdict submission={submission} />
      {submission.router_note && !submission.last_review && (
        <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-foreground-secondary">
          {submission.router_note}
        </p>
      )}
      <div className="mt-auto flex items-end justify-between gap-3 pt-6">
        <p className="text-sm text-muted-foreground">
          <span className="text-2xl font-bold tabular-nums text-foreground">{open}</span> open issue
          {open === 1 ? "" : "s"}
        </p>
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold ${
            step.act ? "text-brand" : "text-muted-foreground"
          }`}
        >
          {step.text} {step.act && <ArrowRight className="size-4" aria-hidden />}
        </span>
      </div>
    </Link>
  );
}

/** What the reviewer decided, in words the writer can act on. Nothing until there is a verdict. */
function Verdict({ submission }: { submission: Submission }) {
  const r = submission.last_review;
  if (!r) return null;
  const who = (r.by_name ?? "").replace(/\s*\(.*\)$/, "") || "The reviewer";
  if (r.action === "request_changes" && submission.status === "Changes requested") {
    return (
      <p className="mt-2 line-clamp-3 rounded-lg border border-warning-border bg-warning-bg px-3 py-2 text-sm leading-relaxed text-foreground">
        <span className="font-semibold text-warning-fg">Sent back by {who}:</span>{" "}
        {r.reason ? `“${r.reason}”` : "changes requested."}
      </p>
    );
  }
  if (r.action === "approve" || r.action === "exempt_approve") {
    return (
      <p className="mt-2 text-sm text-success-fg">
        {r.action === "exempt_approve" ? "Approved automatically under an exemption policy." : `Approved by ${who}.`}
      </p>
    );
  }
  return null;
}
