// Typed client for the Canonry engine (same-origin /engine proxy).
// Guest mode: every 401 is surfaced; the UI always offers one-click demo
// personas so judges never need credentials.

export type Citation = {
  type: "fact" | "rule" | "term";
  id: string;
  excerpt?: string;
  owner?: string;
  valid_to?: string | null;
  confidential?: number;
};

export type Suggestion = { replace?: string; operation?: "replace" | "remove" };

export type Provenance = { model: string | null; prompt_version: string; knowledge_version: string };

export type Finding = {
  id: string;
  checker: string;
  category: string;
  span_start: number;
  span_end: number;
  span_text: string;
  tier: "definite" | "likely" | "consider";
  severity: "high" | "medium" | "low";
  citations: Citation[];
  explanation: string;
  suggestion: Suggestion | null;
  provenance: Provenance;
  status: "open" | "accepted" | "edited" | "disputed" | "discarded";
  title?: string | null;
};

export type Revision = { id: string; revision_no: number; content: string; created_at: string };

export type Submission = {
  id: string;
  title: string;
  channel: string;
  source_type: string;
  status: string;
  risk?: string | null;
  router_note?: string | null;
  content?: string;
  open_findings?: number;
  poc_sig?: string | null;
  created_at: string;
};

export type Decision = {
  id: string;
  revision_id: string;
  finding_id: string;
  action: string;
  replacement?: string | null;
  reason?: string | null;
  by_user: string;
  at: string;
};

export type Approval = {
  id: string;
  submission_id: string;
  action: string;
  reason?: string | null;
  reviewer: string;
  at: string;
};

export type User = { id: string; email: string; name: string; role: string };

export type SubmissionDetail = {
  submission: Submission;
  revisions: Revision[];
  latest_revision: Revision | null;
  findings: Finding[];
  decisions: Decision[];
  approvals: Approval[];
  poc: { id: string; created_at: string } | null;
  me: User;
};

export const BASE = "/engine";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    credentials: "same-origin",
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(rest.headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const d = (data ?? {}) as { detail?: unknown; message?: unknown };
    const msg =
      typeof d.detail === "string" ? d.detail :
      typeof d.message === "string" ? d.message :
      `Engine error ${res.status}`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

export const CATEGORY_LABEL: Record<string, string> = {
  outdated_term: "Outdated term",
  contradicted_claim: "Contradicted claim",
  outdated_claim: "Outdated claim",
  unsupported_claim: "Unsupported claim",
  missing_disclaimer: "Missing CTA/disclaimer",
  banned_term: "Banned word",
  tone: "Tone",
  readability: "Readability",
};

export const TIER_LABEL: Record<string, string> = {
  definite: "Definite",
  likely: "Likely",
  consider: "Consider",
};
