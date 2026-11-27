export const API = (process.env.NEXT_PUBLIC_PDFCTX_API ?? "http://127.0.0.1:8000").replace(/\/$/, "");

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

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`);
  return body as T;
}

export const api = {
  documents: () => call<{ documents: DocumentInfo[] }>("/v1/documents"),
  outline: (id: string) => call<{ doc_id: string; title: string; pages: number; sections: SectionNode[] }>(
    `/v1/documents/${encodeURIComponent(id)}/outline?max_depth=4`,
  ),
  search: (q: string, docId: string, k = 8) =>
    call<{ results: SearchResult[] }>(
      `/v1/search?q=${encodeURIComponent(q)}&k=${k}&doc_id=${encodeURIComponent(docId)}`,
    ),
  context: (query: string, docId: string, budget: number) =>
    call<ContextPack>("/v1/context", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query, budget_tokens: budget, doc_ids: [docId] }),
    }),
  audit: (limit = 200) => call<{ entries: AuditEntry[] }>(`/v1/audit?limit=${limit}`),
  upload: (file: File) =>
    call<{ id: string; title: string; pages: number; status: string }>("/v1/documents", {
      method: "POST",
      headers: { "content-type": "application/pdf", "x-filename": encodeURIComponent(file.name) },
      body: file,
    }),
  pageUrl: (id: string, page: number, scale: number) =>
    `${API}/v1/documents/${encodeURIComponent(id)}/pages/${page}.png?scale=${scale}`,
};
