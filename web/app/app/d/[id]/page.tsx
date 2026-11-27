"use client";

import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, type BBox, type ContextPack, type SearchResult, type SectionNode } from "@/lib/api";

const SCALE = 1.5;
const BUDGETS = [500, 1000, 2000, 4000];

function Outline({ nodes, onPick, depth = 0 }: { nodes: SectionNode[]; onPick: (page: number) => void; depth?: number }) {
  return (
    <ul className={depth ? "ml-3 border-l border-zinc-200 pl-2 dark:border-zinc-800" : ""}>
      {nodes.map((n) => (
        <li key={n.id}>
          <button
            onClick={() => onPick(n.page)}
            className="w-full truncate rounded px-1 py-0.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
            title={n.title}
          >
            {n.title} <span className="text-xs text-zinc-400">p.{n.page}</span>
          </button>
          {n.children.length > 0 && <Outline nodes={n.children} onPick={onPick} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}

function Highlight({ bbox, size, strong }: { bbox: BBox; size: { w: number; h: number }; strong: boolean }) {
  const [x0, top, x1, bottom] = bbox;
  const pct = (v: number, total: number) => `${((v * SCALE) / total) * 100}%`;
  return (
    <div
      className={`pointer-events-none absolute rounded-sm ${
        strong ? "bg-amber-300/40 ring-2 ring-amber-500" : "bg-sky-300/20 ring-1 ring-sky-400/60"
      }`}
      style={{
        left: pct(x0 - 2, size.w),
        top: pct(top - 2, size.h),
        width: pct(x1 - x0 + 4, size.w),
        height: pct(bottom - top + 4, size.h),
      }}
    />
  );
}

export default function Viewer() {
  const { id } = useParams<{ id: string }>();
  const [title, setTitle] = useState("");
  const [pages, setPages] = useState(1);
  const [sections, setSections] = useState<SectionNode[]>([]);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [budget, setBudget] = useState(1000);
  const [pack, setPack] = useState<ContextPack | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Opened from the metrics table: ?page=46&box=x0,top,x1,bottom highlights the cited row's table.
  const [cited, setCited] = useState<{ page: number; box: BBox } | null>(null);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = Number(q.get("page"));
    const box = (q.get("box") ?? "").split(",").map(Number);
    if (p > 0) setPage(p);
    if (p > 0 && box.length === 4 && box.every((v) => Number.isFinite(v))) {
      setCited({ page: p, box: box as BBox });
    }
  }, []);

  useEffect(() => {
    api
      .outline(id)
      .then((o) => {
        setTitle(o.title);
        setPages(o.pages);
        setSections(o.sections);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const boxes = useMemo(() => results.filter((r) => r.page === page), [results, page]);

  function goto(p: number) {
    setSize(null);
    setPage(Math.min(Math.max(1, p), pages));
  }

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const [s, c] = await Promise.all([api.search(query, id), api.context(query, id, budget)]);
      setResults(s.results);
      setPack(c);
      if (s.results[0]) {
        setSelected(s.results[0].block_id);
        goto(s.results[0].page);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)_380px]">
      <aside className="max-h-[80vh] overflow-y-auto rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-2 truncate text-sm font-semibold" title={title}>
          {title || "…"}
        </h2>
        {sections.length ? <Outline nodes={sections} onPick={goto} /> : <p className="text-xs text-zinc-500">No outline.</p>}
      </aside>

      <section className="space-y-2">
        <div className="flex items-center gap-2 text-sm">
          <button onClick={() => goto(page - 1)} className="rounded border px-2 py-0.5 dark:border-zinc-700">
            ←
          </button>
          <span className="tabular-nums">
            page {page} / {pages}
          </span>
          <button onClick={() => goto(page + 1)} className="rounded border px-2 py-0.5 dark:border-zinc-700">
            →
          </button>
          {boxes.length > 0 && <span className="text-xs text-zinc-500">{boxes.length} match(es) on this page</span>}
        </div>
        <div className="relative w-full overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            key={page}
            src={api.pageUrl(id, page, SCALE)}
            alt={`page ${page}`}
            className="block w-full"
            onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
          />
          {size && boxes.map((r) => <Highlight key={r.block_id} bbox={r.bbox} size={size} strong={r.block_id === selected} />)}
          {size && cited && cited.page === page && <Highlight bbox={cited.box} size={size} strong />}
        </div>
      </section>

      <aside className="space-y-3">
        <form onSubmit={run} className="space-y-2 rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask the document… e.g. capital expenditure 2018"
            className="w-full rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700"
          />
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            context budget
            <select
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="rounded border bg-transparent px-1 dark:border-zinc-700"
            >
              {BUDGETS.map((b) => (
                <option key={b} value={b}>
                  {b} tokens
                </option>
              ))}
            </select>
            <button
              disabled={busy}
              className="ml-auto rounded-lg bg-zinc-900 px-3 py-1.5 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {busy ? "…" : "Search"}
            </button>
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </form>

        {results.length > 0 && (
          <div className="max-h-[42vh] space-y-2 overflow-y-auto">
            {results.map((r) => (
              <button
                key={r.block_id}
                onClick={() => {
                  setSelected(r.block_id);
                  goto(r.page);
                }}
                className={`w-full rounded-xl border p-3 text-left text-sm ${
                  r.block_id === selected
                    ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30"
                    : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
                }`}
              >
                <div className="mb-1 flex items-center gap-2 text-xs text-zinc-500">
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono dark:bg-zinc-800">{r.match}</span>
                  <span>p.{r.page}</span>
                  <span className="truncate">{r.section_path.join(" › ")}</span>
                </div>
                <p className="line-clamp-4 whitespace-pre-line">{r.text}</p>
              </button>
            ))}
          </div>
        )}

        {pack && (
          <div className="rounded-xl border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-semibold">context_pack</span>
              <span className="font-mono text-xs text-zinc-500">
                {pack.used_tokens} / {pack.budget_tokens} tokens
              </span>
            </div>
            <div className="max-h-64 space-y-2 overflow-y-auto text-xs">
              {pack.sections.map((s, i) => (
                <div key={i}>
                  <p className="font-medium text-zinc-500">{s.path.join(" › ") || "—"}</p>
                  {s.blocks.map((b) => (
                    <p key={b.block_id + (b.unit_id ?? "")} className="mt-1 whitespace-pre-line">
                      <span className="text-zinc-400">p.{b.page} </span>
                      {b.text}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
