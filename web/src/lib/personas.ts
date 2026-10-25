// The four personas from the Quillmark demo (doc Section 6.2). One click
// signs you in — no credentials, so a judge can act as any role immediately.
export const PERSONAS = [
  { email: "arjun@quillmark", name: "Arjun (Product Marketer)", role: "creator" },
  { email: "maya@quillmark", name: "Maya (Brand & Content Manager)", role: "reviewer" },
  { email: "riya@agency", name: "Riya (Agency Copywriter)", role: "agency" },
  { email: "karan@quillmark", name: "Karan (Head of Marketing)", role: "admin" },
] as const;

export const ROLE_LABEL: Record<string, string> = {
  creator: "Creator",
  reviewer: "Reviewer",
  agency: "Agency",
  admin: "Admin",
};

export function personaName(email: string): string {
  const p = PERSONAS.find((p) => p.email === email);
  if (p) return p.name;
  return email.split("@")[0].replace(/\b\w/g, (c) => c.toUpperCase());
}
