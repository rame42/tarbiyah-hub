// Thin fetch wrapper for the Tarbiyah Hub REST API. Errors carry the backend's {"detail": ...} text.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, type}]
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? `${(d as { loc?: unknown[] }).loc?.join(".") ?? ""}: ${(d as { msg: string }).msg}` : JSON.stringify(d)))
      .join("; ");
  }
  return JSON.stringify(detail);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, `Network error: ${(e as Error).message}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      if (ct.includes("json")) {
        const j = await res.json();
        if (j && j.detail !== undefined) msg = `${res.status}: ${detailText(j.detail)}`;
      } else {
        const tx = await res.text();
        if (tx) msg = `${res.status}: ${tx.slice(0, 300)}`;
      }
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, msg);
  }
  if (ct.includes("json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ---------------------------------------------------------------- shared types

export interface PillarScore { pillar: string; score: number; method?: string }

export interface ResourceBrief {
  id: number;
  title: string;
  title_translations: Record<string, unknown>;
  authors: string | null;
  type: string;
  language: string | null;
  year: number | null;
  url: string | null;
  source_key: string | null;
  access_status: string;
  acquisition_status: string;
  processing_status: string;
  pillars: PillarScore[];
  discovered_at: string | null;
  has_file: boolean;
  labels?: string[];
  relevance?: number | null;
  archived?: boolean;
  role?: string;
}

export interface Question {
  id: number;
  text: string;
  text_alt: string | null;
  lang: string;
  kind: string;
  pillars: string[];
  priority: number;
  scores: Record<string, number> | null;
  status: string;
  depth: number;
  rationale: string | null;
  search_queries: unknown;
  next_steps: unknown;
  answer_summary: string | null;
  created_by: string;
  attempts: number;
  parent_id: number | null;
  objective_id: number | null;
  related_count: number;
  created_at: string;
  investigated_at: string | null;
}

export interface Status {
  worker: { alive: boolean; state?: string; heartbeat_at?: string; [k: string]: unknown };
  automation: { enabled: boolean; paused: boolean; within_operating_hours: boolean; operating_hours: { start: string; end: string }; paused_collectors: string[] };
  ai: { configured: boolean; enabled: boolean; model: string; calls_today: number; cost_today_usd: number; daily_call_limit: number; daily_budget_usd: number };
  ocr: { tesseract: boolean; languages: string[]; provider_setting: string; claude_ocr_available: boolean };
  jobs: Record<string, number>;
  counts: Record<string, number>;
  storage: { used_gb: number; limit_gb: number; disk_free_gb: number; data_dir: string };
  usage_today: Record<string, number>;
  limits: Record<string, number>;
  credentials: Record<string, boolean>;
}

export interface Meta {
  pillars: Record<string, { en: string; ar: string }>;
  topics: { id: number; slug: string; name_en: string; name_ar: string; pillar: string | null }[];
  resource_types: string[];
  source_keys: string[];
}

let metaCache: Promise<Meta> | null = null;
export function getMeta(): Promise<Meta> {
  if (!metaCache) {
    metaCache = api.get<Meta>("/api/meta").catch((e) => {
      metaCache = null;
      throw e;
    });
  }
  return metaCache;
}
