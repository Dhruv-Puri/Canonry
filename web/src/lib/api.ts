// Typed client for the Canonry engine (same-origin /engine proxy).
// Guest mode: a 401 signs in as the demo creator once and retries; the UI
// also offers one-click demo personas so judges never need credentials.

export type Citation = {
  type: "fact" | "rule" | "term" | "pack";
  id: string;
  /** version of the rule/fact/term this finding was checked against */
  version?: number;
  /** its version today; greater than `version` means it changed since */
  current_version?: number | null;
  excerpt?: string;
  owner?: string;
  valid_to?: string | null;
  confidential?: number;
};

export type Suggestion = { replace?: string; operation?: "replace" | "remove" };

// ---- knowledge base (versioned: every change is a new version with a reason) ----

export type KBKind = "rules" | "facts" | "terms";

export type Rule = {
  id: string; category: string; statement: string; do_example: string | null; dont_example: string | null;
  severity: string; status: string; vague_flag: string | null; version: number;
};
export type Fact = {
  id: string; text: string; category: string; owner: string | null; source: string | null;
  valid_from: string | null; valid_to: string | null; confidential: number; superseded: number;
  active?: boolean; version: number;
};
export type Term = {
  id: number; preferred: string | null; banned_or_check: string | null; note: string | null;
  severity: string; status: string; version: number;
};
export type KBEntity = Rule | Fact | Term;

export type HistoryEntry = {
  version: number; action: "seed" | "create" | "update" | "retire" | "restore";
  snapshot: Record<string, unknown>; reason: string | null; by_user: string | null; by_name?: string | null; at: string;
  knowledge_version: number;
};

export type ImpactItem = { submission_id: string; title: string; status: string; because: string };

export type RulePreview = {
  rule: string;
  new_examples_would_be_tests: boolean;
  impacted_approved_content: ImpactItem[];
  impacted_count: number;
  new_breakages: ImpactItem[];
  resolved: ImpactItem[];
  impacted: { before: number; after: number; new_breakages: number; resolved: number };
};

export type KBWriteResult = { entity: KBEntity; knowledge_version: number; impact?: ImpactItem[] };

export function isRetired(kind: KBKind, e: KBEntity): boolean {
  if (kind === "facts") return Boolean((e as Fact).superseded);
  return (e as Rule | Term).status === "retired";
}

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
  by_name?: string | null;
  at: string;
};

export type Approval = {
  id: string;
  submission_id: string;
  action: string;
  reason?: string | null;
  reviewer: string;
  reviewer_name?: string | null;
  at: string;
};

export type User = { id: string; email: string; name: string; role: string };
export type AuthMode = { demo_mode: boolean; registration: "demo" | "invitation-only" };
export type InvitationInfo = { email: string; role: string; expires_at: string };
export type ImportedRule = { category: string; statement: string; do_example?: string | null; dont_example?: string | null; severity: string; status: "draft" };
export type RuleImportPreview = { proposals: ImportedRule[]; ignored: number; source: string; message: string };

export type SubmissionDetail = {
  submission: Submission;
  revisions: Revision[];
  latest_revision: Revision | null;
  findings: Finding[];
  decisions: Decision[];
  approvals: Approval[];
  poc: { id: string; created_at: string } | null;
  /** Latest check run on the latest revision; status "ai_pending" means only rule-based checks ran. */
  check: { status: string; started_at: string; finished_at: string | null; ai_calls: number; discarded: number } | null;
  me: User;
  /** which lifecycle actions the current status allows (engine workflow rules) */
  allowed: { edit: boolean; submit: boolean; approve: boolean; request_changes: boolean; override: boolean };
};

export const BASE = "/engine";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Fired when the engine says nobody is signed in; <IdentityGate> shows the welcome screen. */
export const SIGNED_OUT_EVENT = "canonry:signed-out";

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  try {
    return await request<T>(path, init);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    }
    throw e;
  }
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
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
  missing_disclaimer: "Missing disclaimer",
  missing_cta: "No call to action",
  confidential_leak: "Confidential information",
  banned_term: "Banned word",
  tone: "Tone",
  readability: "Readability",
};

export const TIER_LABEL: Record<string, string> = {
  definite: "Definite",
  likely: "Likely",
  consider: "Consider",
};
