// The four roles a person can choose (no login). The engine enforces what each
// may see and do (engine/access.py, knowledge.py); these lines just explain it.
import { Building2, Crown, PenLine, ShieldCheck, type LucideIcon } from "lucide-react";

export type Role = "creator" | "reviewer" | "agency" | "admin";

export const ROLES: { id: Role; label: string; does: string; icon: LucideIcon }[] = [
  { id: "creator", label: "Creator", does: "Write drafts, fix findings and send them for review.", icon: PenLine },
  { id: "reviewer", label: "Reviewer", does: "Approve and sign content, override findings, edit the knowledge base.", icon: ShieldCheck },
  { id: "agency", label: "Agency partner", does: "Submit work from outside. Sees only its own drafts, never confidential facts.", icon: Building2 },
  { id: "admin", label: "Brand admin", does: "Everything a reviewer can do, for the whole workspace.", icon: Crown },
];

export const ROLE_LABEL: Record<string, string> = Object.fromEntries(ROLES.map((r) => [r.id, r.label]));

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}
