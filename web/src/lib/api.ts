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
  /** compliance pack citation: the exact clause and where to read it */
  ref?: string;
  source?: string;
  url?: string;
};

export type Suggestion = { replace?: string; operation?: "replace" | "remove" | "rewrite" | "upload" };

export type FindingLocator = {
  kind: "text" | "pdf" | "docx" | "image";
  asset_id?: string | null;
  page?: number | null;
  line?: number | null;
  paragraph?: number | null;
  section?: string | null;
  bbox?: [number, number, number, number] | null;
  region?: string | null;
};

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
  locator?: FindingLocator | null;
  location_key?: string | null;
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
  poc: {
    id: string; created_at: string; content_kind?: "text" | "file";
    asset_id?: string | null; stamped_sha256?: string | null;
  } | null;
  asset: {
    id: string; kind: "pdf" | "docx" | "png" | "jpeg"; filename: string; mime: string;
    size_bytes: number; width: number | null; height: number | null;
    page_count: number | null; alt_text: string | null; sha256: string;
  } | null;
  /** Latest check run on the latest revision; status "ai_pending" means only rule-based checks ran. */
  check: {
    status: string; started_at: string; finished_at: string | null; ai_calls: number; discarded: number;
    /** why the AI checks were skipped on this run; null when they ran */
    ai_reason: AiReason | null;
  } | null;
  me: User;
  /** which lifecycle actions the current status allows (engine workflow rules) */
  allowed: { edit: boolean; submit: boolean; approve: boolean; request_changes: boolean; override: boolean };
  /** today's AI-assisted checks for the signed-in person and the workspace (reset 00:00 UTC) */
  ai_allowance: AiAllowance;
};

export type AiReason = "no_provider" | "user_quota" | "workspace_quota" | "provider_unavailable" | "budget" | "time_budget";
export type AiAllowance = {
  used: number; limit: number; workspace_used: number; workspace_limit: number; resets_at: string;
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

/** Shown whenever the engine does not answer, or answers with a page that is not its own JSON. */
export const ENGINE_UNREACHABLE =
  "Canonry's checking engine can't be reached right now. It may be starting up (this can take up to a minute " +
  "on the free server). Wait a moment, then reload the page.";

/** Plain words for a failed engine response; never a raw status code or proxy text. */
export function engineErrorMessage(status: number, data: unknown): string {
  const d = (data ?? {}) as { detail?: unknown; message?: unknown; __text?: unknown };
  if (typeof d.detail === "string" && d.__text === undefined) return d.detail;
  if (typeof d.message === "string") return d.message;
  if (status >= 500 || status === 0) return ENGINE_UNREACHABLE;
  if (status === 404) return "That item was not found. It may have been removed, or the link is wrong.";
  if (status === 401) return "Your session has ended. Choose a role to continue.";
  if (status === 403) return "Your role can't do that. Switch role from your name in the top bar.";
  if (status === 413) return "That is too large to send. Keep files under 4 MB.";
  if (status === 422 && Array.isArray(d.detail)) return "Some of the details sent were not valid. Check the form and try again.";
  return `Something went wrong (${status}). Try again in a moment.`;
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...rest,
      credentials: "same-origin",
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(rest.headers ?? {}),
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, ENGINE_UNREACHABLE); // offline, or the proxy dropped the connection
  }
  const text = await res.text().catch(() => "");
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, engineErrorMessage(res.status, data));
  return data as T;
}

/** JSON, or a marker that the body was not JSON (a proxy error page, "Internal Server Error"). */
export function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text, __text: true };
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
  // documents, images and the India pack
  logo_missing: "Logo missing",
  logo_outdated: "Retired logo",
  logo_too_small: "Logo too small",
  logo_clear_space: "Logo clear space",
  off_brand_colour: "Off-brand colour",
  low_text_contrast: "Text contrast",
  missing_alt_text: "Missing alt text",
  alt_text_quality: "Alt text quality",
  accessibility: "Accessibility",
  bait_advertising: "Bait advertising",
  surrogate_advertising: "Surrogate advertising",
  free_claim: "Free claim",
  children_directed: "Children-directed",
  comparative_advertising: "Comparative advertising",
  endorsement_disclosure: "Endorsement disclosure",
  misleading_claim: "Misleading claim",
  unsubstantiated_claim: "Unsubstantiated claim",
  missing_disclosure: "Missing disclosure",
};

export const TIER_LABEL: Record<string, string> = {
  definite: "Definite",
  likely: "Likely",
  consider: "Consider",
};


/** Vercel's proxy refuses request bodies above about 4.5 MB, so the web app checks first. */
export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

/** POST a raw file to the engine; a friendly error for every failure, never a JSON parse error. */
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new ApiError(413, `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB; uploads can be up to 4 MB. Compress it or export a smaller copy.`);
  }
  if (file.size === 0) {
    throw new ApiError(422, "This file is empty (0 bytes). Choose the file again, or export it again from its source.");
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      body: file,
      credentials: "same-origin",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, ENGINE_UNREACHABLE);
  }
  const text = await res.text().catch(() => "");
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    const msg =
      res.status === 413 ? "This file is too large to upload. Keep it under 4 MB." : engineErrorMessage(res.status, data);
    throw new ApiError(res.status, msg);
  }
  return data as T;
}
