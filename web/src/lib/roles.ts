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

export function initials(name: string): string {
  // first letter of the first and last word, skipping punctuation: "Guest (Reviewer)" -> "GR"
  const parts = name.trim().split(/\s+/).map((w) => w.match(/[\p{L}\p{N}]/u)?.[0] ?? "").filter(Boolean);
  return ((parts[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1] : "")).toUpperCase() || "?";
}
