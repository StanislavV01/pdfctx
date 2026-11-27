/** "local": the open-source server on your machine (no accounts). "cloud": pdfctx Cloud behind the /api proxy. */
export const MODE: "local" | "cloud" = process.env.NEXT_PUBLIC_PDFCTX_MODE === "cloud" ? "cloud" : "local";
export const API =
  MODE === "cloud" ? "/api" : (process.env.NEXT_PUBLIC_PDFCTX_API ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export type BBox = [number, number, number, number];

export interface DocumentInfo {
  id: string;
  title: string;
  file: string;
  pages: number;
  status: "ok" | "no_text" | "encrypted" | "failed";
  error?: string;
}

export interface SectionNode {
  id: string;
  title: string;
  level: number;
  page: number;
  children: SectionNode[];
}

export interface SearchResult {
  block_id: string;
  unit_id: string;
  doc_id: string;
  kind: "heading" | "paragraph" | "table";
  match: "block" | "table" | "row";
  page: number;
  bbox: BBox;
  section_path: string[];
  text: string;
  score: number;
}

export interface PackBlock {
  block_id: string;
  unit_id?: string;
  kind: string;
  page: number;
  text: string;
}

export interface ContextPack {
  sections: { doc_id: string; path: string[]; blocks: PackBlock[] }[];
  used_tokens: number;
  budget_tokens: number;
  dropped: number;
}

export interface AuditEntry {
  id: number;
  ts: string;
  client: string;
  tool: string;
  args: Record<string, unknown>;
  block_ids: string[];
  doc_ids: string[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: MODE === "cloud" ? "include" : "omit",
    // Required by the cloud for writes made with the session cookie (CSRF defence); harmless locally.
    headers: { ...(init?.headers ?? {}), "x-pdfctx": "1" },
  });
  if (res.status === 401 && MODE === "cloud" && typeof window !== "undefined" && !path.startsWith("/me")) {
    window.location.href = "/signin";
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((body as { error?: string }).error ?? `HTTP ${res.status}`, res.status);
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export interface MetricValue {
  doc_id: string;
  doc_title: string;
  metric: string;
  year: number;
  value: number;
  raw: string;
  unit: string | null;
  label: string;
  page: number;
  bbox: BBox;
  block_id: string;
  table: string;
}

export interface MetricsResult {
  metrics: string[];
  years: number[] | null;
  values: MetricValue[];
  missing: { doc_id: string; doc_title: string; metric: string; year: number }[];
}

export interface Me {
  email: string;
  workspace: {
    id: string;
    plan: "free" | "pro" | "team";
    plan_name: string;
    pages_used: number;
    pages_limit: number;
    period: "month" | "total";
    billing: boolean;
  };
}

export interface ApiKey {
  id: string;
  name: string;
  hint: string;
  created_at: string;
  key?: string;
}

export const api = {
  documents: () => call<{ documents: DocumentInfo[] }>("/v1/documents"),
  outline: (id: string) =>
    call<{ doc_id: string; title: string; pages: number; sections: SectionNode[] }>(
      `/v1/documents/${encodeURIComponent(id)}/outline?max_depth=4`,
    ),
  search: (q: string, docId: string, k = 8) =>
    call<{ results: SearchResult[] }>(
      `/v1/search?q=${encodeURIComponent(q)}&k=${k}&doc_id=${encodeURIComponent(docId)}`,
    ),
  context: (query: string, docId: string, budget: number) =>
    call<ContextPack>("/v1/context", json({ query, budget_tokens: budget, doc_ids: [docId] })),
  metrics: (metrics: string[], years: number[] | null, docIds: string[] | null) =>
    call<MetricsResult>("/v1/metrics", json({ metrics, years, doc_ids: docIds })),
  metricsCsv: async (metrics: string[], years: number[] | null, docIds: string[] | null) => {
    const res = await fetch(`${API}/v1/metrics?format=csv`, {
      ...json({ metrics, years, doc_ids: docIds }),
      credentials: MODE === "cloud" ? "include" : "omit",
      headers: { "content-type": "application/json", "x-pdfctx": "1" },
    });
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
    return res.blob();
  },
  audit: (limit = 200) => call<{ entries: AuditEntry[] }>(`/v1/audit?limit=${limit}`),
  upload: (file: File) =>
    call<{ id: string; title: string; pages: number; status: string }>("/v1/documents", {
      method: "POST",
      headers: { "content-type": "application/pdf", "x-filename": encodeURIComponent(file.name) },
      body: file,
    }),
  remove: (id: string) => call<{ deleted: string }>(`/v1/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  pageUrl: (id: string, page: number, scale: number) =>
    `${API}/v1/documents/${encodeURIComponent(id)}/pages/${page}.png?scale=${scale}`,

  // cloud only
  me: () => call<Me>("/me"),
  requestLink: (email: string) => call<{ sent: boolean }>("/auth/request", json({ email })),
  verify: (token: string) => call<{ ok: boolean }>("/auth/verify", json({ token })),
  logout: () => call<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  keys: () => call<{ keys: ApiKey[] }>("/keys"),
  createKey: (name: string) => call<ApiKey>("/keys", json({ name })),
  revokeKey: (id: string) => call<{ revoked: string }>(`/keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  checkout: (plan: string) => call<{ url: string }>("/billing/checkout", json({ plan })),
  portal: () => call<{ url: string }>("/billing/portal", { method: "POST" }),
};

export const METRICS = [
  ["revenue", "Revenue"],
  ["gross_profit", "Gross profit"],
  ["operating_income", "Operating income"],
  ["net_income", "Net income"],
  ["eps_diluted", "Diluted EPS"],
  ["operating_cash_flow", "Operating cash flow"],
  ["capex", "Capex"],
  ["free_cash_flow", "Free cash flow"],
  ["rnd", "R&D"],
  ["sga", "SG&A"],
  ["depreciation_amortization", "D&A"],
  ["cash", "Cash"],
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["long_term_debt", "Long-term debt"],
  ["dividends_paid", "Dividends paid"],
] as const;

export const PLANS = [
  { id: "free", name: "Free", price: 0, pages: 50, period: "total", blurb: "Try it on a few filings." },
  { id: "pro", name: "Pro", price: 29, pages: 2000, period: "month", blurb: "For an analyst covering a sector." },
  { id: "team", name: "Team", price: 99, pages: 10000, period: "month", blurb: "For a desk or a small fund." },
] as const;
