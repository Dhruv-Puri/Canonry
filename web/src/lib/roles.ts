// The four roles a person can choose (no login). The engine enforces what each
// may see and do (engine/access.py, knowledge.py); these lines just explain it.
import { Building2, Crown, PenLine, ShieldCheck, type LucideIcon } from "lucide-react";

export type Role = "creator" | "reviewer" | "agency" | "admin";

// `short` is the one-line version for the guest entry page; `does` is the full one.
export const ROLES: { id: Role; label: string; short: string; does: string; icon: LucideIcon }[] = [
  { id: "creator", label: "Creator", short: "Write drafts and fix what Canonry flags",
    does: "Write drafts, fix findings and send them for review.", icon: PenLine },
  { id: "reviewer", label: "Reviewer", short: "Approve drafts or send them back",
    does: "Approve and sign content, override findings, edit the knowledge base.", icon: ShieldCheck },
  { id: "agency", label: "Agency partner", short: "Submit work for a client brand",
    does: "Submit work from outside. Sees only its own drafts, never confidential facts.", icon: Building2 },
  { id: "admin", label: "Brand admin", short: "Manage the brand's rules and facts",
    does: "Everything a reviewer can do, for the whole workspace.", icon: Crown },
];

export const ROLE_LABEL: Record<string, string> = Object.fromEntries(ROLES.map((r) => [r.id, r.label]));

/** Roles whose job is deciding on submissions, not authoring them. */
export function canReview(role: string | null | undefined): boolean {
  return role === "reviewer" || role === "admin";
}

/** Where a role starts and where its logo goes. */
export function roleHome(role: string | null | undefined): string {
  if (role === "admin") return "/admin";
  if (role === "reviewer") return "/review";
  if (role === "agency") return "/agency";
  return "/";
}

/** Navigation is deliberately different per role: a reviewer should never land on a draft box. */
export function navLinksFor(role: string | null | undefined): { href: string; label: string }[] {
  if (role === "admin") {
    return [
      { href: "/admin", label: "Overview" },
      { href: "/review", label: "Review queue" },
      { href: "/kb", label: "Knowledge base" },
      { href: "/insights", label: "Insights" },
    ];
  }
  if (role === "reviewer") {
    return [
      { href: "/review", label: "Review queue" },
      { href: "/kb", label: "Knowledge base" },
      { href: "/insights", label: "Insights" },
    ];
  }
  if (role === "agency") {
    return [
      { href: "/agency", label: "My work" },
      { href: "/new", label: "Submit" },
      { href: "/kb", label: "Knowledge base" },
    ];
  }
  return [
    { href: "/", label: "Home" },
    { href: "/new", label: "Write" },
    { href: "/kb", label: "Knowledge base" },
    { href: "/insights", label: "Insights" },
  ];
}

export function initials(name: string): string {
  // first letter of the first and last word, skipping punctuation: "Guest (Reviewer)" -> "GR"
  const parts = name.trim().split(/\s+/).map((w) => w.match(/[\p{L}\p{N}]/u)?.[0] ?? "").filter(Boolean);
  return ((parts[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1] : "")).toUpperCase() || "?";
}
