import { CATEGORY_LABEL } from "@/lib/api";

export function LevelBadge({ tier, severity }: { tier?: string; severity?: string }) {
  const tierCls =
    tier === "definite"
      ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200"
      : tier === "likely"
        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
        : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tierCls}`}>
      {tier === "definite" ? "Definite" : tier === "likely" ? "Likely" : "Consider"}
      {severity && severity !== "medium" ? ` · ${severity}` : ""}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[11px] font-medium">
      {CATEGORY_LABEL[category] ?? category.replace(/_/g, " ")}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "Signed" || status === "Approved"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
      : status === "In review"
        ? "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200"
        : status === "Checked"
          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200"
          : "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {status}
    </span>
  );
}

export function RiskBadge({ risk }: { risk?: string | null }) {
  if (!risk) return null;
  const cls =
    risk === "low"
      ? "border-emerald-300 text-emerald-700"
      : risk === "high"
        ? "border-red-300 text-red-700"
        : risk === "exempt"
          ? "border-violet-300 text-violet-700"
          : "border-amber-300 text-amber-700";
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase ${cls}`}>
      risk: {risk}
    </span>
  );
}
