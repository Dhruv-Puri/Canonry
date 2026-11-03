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

/** How long it has been waiting, the way a queue reads it ("12 min", "3 h", "2 d"). */
function waiting(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min`;
  const h = Math.round(min / 60);
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} d`;
}

/**
 * One queue item as a scannable row (Linear / Stripe style): on a desktop the columns line up
 * under the list header; on a phone the same element stacks like a compact card.
 */
export function SubmissionRow({ submission }: { submission: Submission }) {
  const open = submission.open_findings ?? 0;
  const step = nextStep(submission, "reviewer");
  const age = waiting(submission.created_at) || when(submission.created_at);
  return (
    <Link
      href={`/submissions/${submission.id}`}
      className="group grid gap-x-6 gap-y-2 px-5 py-4 transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 md:grid-cols-[minmax(0,1fr)_8.5rem_6.5rem_8rem] md:items-center"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={submission.status} />
          <RiskBadge risk={submission.risk} />
        </div>
        <p className="mt-1.5 truncate text-[15px] font-semibold text-foreground group-hover:underline group-hover:underline-offset-2">
          {submission.title}
        </p>
        {submission.router_note && (
          <p className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground" title={submission.router_note}>
            {submission.router_note}
          </p>
        )}
      </div>
      <div className="flex items-center gap-4 md:contents">
      <p className="text-xs text-muted-foreground">
        <span className="capitalize">{submission.channel}</span>
        <span className="md:block">
          <span className="md:hidden"> · </span>
          {age === "just now" ? age : submission.status === "In review" ? `waiting ${age}` : `${age} ago`}
        </span>
      </p>
      <p className="text-sm text-muted-foreground">
        <span className={`font-bold tabular-nums ${open ? "text-foreground" : ""}`}>{open}</span> open
      </p>
      <span
        className={`ml-auto inline-flex items-center gap-1.5 text-sm font-semibold md:ml-0 md:justify-end ${
          step.act ? "text-brand" : "text-muted-foreground"
        }`}
      >
        {step.text} {step.act && <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />}
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
