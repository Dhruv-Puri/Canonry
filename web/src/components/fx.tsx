import { CircleAlert, CircleCheck, CircleDot, Clock, Info, PenLine, TriangleAlert } from "lucide-react";
import { CATEGORY_LABEL } from "@/lib/api";

// Tone classes come from the semantic tokens in globals.css (light/dark handled there).
const TONE = {
  danger: "bg-danger-bg text-danger-fg",
  warning: "bg-warning-bg text-warning-fg",
  neutral: "bg-neutral-bg text-neutral-fg",
  success: "bg-success-bg text-success-fg",
  info: "bg-info-bg text-info-fg",
} as const;

type Tone = keyof typeof TONE;

const PILL = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium";

function statusTone(status: string): Tone {
  if (status === "Signed" || status === "Approved" || status === "Exempt-approved") return "success";
  if (status === "In review") return "info";
  if (status === "Checked") return "warning";
  if (status === "Changes requested") return "danger";
  return "neutral";
}

const STATUS_ICON: Record<Tone, typeof CircleCheck> = {
  success: CircleCheck,
  info: Clock,
  warning: CircleDot,
  danger: CircleAlert,
  neutral: PenLine,
};

const DOT: Record<Tone, string> = {
  success: "bg-success-fg",
  info: "bg-brand",
  warning: "bg-warning-fg",
  danger: "bg-danger-fg",
  neutral: "bg-muted-foreground",
};

export function LevelBadge({ tier, severity }: { tier?: string; severity?: string }) {
  const tone: Tone = tier === "definite" ? "danger" : tier === "likely" ? "warning" : "neutral";
  const Icon = tier === "definite" ? CircleAlert : tier === "likely" ? TriangleAlert : Info;
  return (
    <span className={`${PILL} ${TONE[tone]}`}>
      <Icon className="size-3" strokeWidth={2.25} aria-hidden />
      {tier === "definite" ? "Definite" : tier === "likely" ? "Likely" : "Consider"}
      {severity && severity !== "medium" ? ` · ${severity}` : ""}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border-strong px-2 py-0.5 text-[11px] font-medium text-foreground">
      {CATEGORY_LABEL[category] ?? category.replace(/_/g, " ")}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = statusTone(status);
  const Icon = STATUS_ICON[tone];
  return (
    <span className={`${PILL} ${TONE[tone]}`}>
      <Icon className="size-3" strokeWidth={2.25} aria-hidden />
      {status}
    </span>
  );
}

/** Small coloured dot for dense lists (sidebar recents); the status is in the title attribute. */
export function StatusDot({ status }: { status: string }) {
  return <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${DOT[statusTone(status)]}`} />;
}

export function RiskBadge({ risk }: { risk?: string | null }) {
  if (!risk) return null;
  const tone: Tone = risk === "low" ? "success" : risk === "high" ? "danger" : risk === "exempt" ? "info" : "warning";
  return (
    <span className={`${PILL} border border-current/25 bg-transparent ${TONE[tone].split(" ")[1]}`}>
      {risk[0].toUpperCase() + risk.slice(1)} risk
    </span>
  );
}
