"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type DocumentInfo, METRICS, type MetricsResult, type MetricValue } from "@/lib/api";

const DEFAULT = ["revenue", "net_income", "operating_cash_flow", "capex", "eps_diluted"];

function parseYears(text: string): number[] | null {
  const out = new Set<number>();
  for (const part of text.split(",").map((p) => p.trim()).filter(Boolean)) {
    const m = part.match(/^(\d{4})\s*[-–]\s*(\d{4})$/);
    if (m) for (let y = Number(m[1]); y <= Number(m[2]) && out.size < 20; y++) out.add(y);
    else if (/^\d{4}$/.test(part)) out.add(Number(part));
  }
  return out.size ? [...out].sort((a, b) => b - a) : null;
}

function fmt(v: MetricValue) {
  const n = v.value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (v.unit === "per share") return `$${n}`;
  if (v.unit === "%") return `${n}%`;
  return v.unit ? `${n} ${v.unit === "millions" ? "M" : v.unit === "billions" ? "B" : "K"}` : n;
}

export default function Metrics() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [metrics, setMetrics] = useState<string[]>(DEFAULT);
  const [custom, setCustom] = useState("");
  const [years, setYears] = useState("");
  const [result, setResult] = useState<MetricsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .documents()
      .then((r) => {
        const ok = r.documents.filter((d) => d.status === "ok");
        setDocs(ok);
        setPicked(new Set(ok.map((d) => d.id)));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const label = (m: string) => METRICS.find(([id]) => id === m)?.[1] ?? m;
  const args = (): [string[], number[] | null, string[]] => [metrics, parseYears(years), [...picked]];

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.metrics(...args()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    const blob = await api.metricsCsv(...args());
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "pdfctx-metrics.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // rows: document × metric; columns: years
  const table = useMemo(() => {
    if (!result) return null;
    const years = [
      ...new Set([...result.values.map((v) => v.year), ...result.missing.map((m) => m.year)]),
    ].sort((a, b) => b - a);
    const cell = new Map(result.values.map((v) => [`${v.doc_id}|${v.metric}|${v.year}`, v]));
    const docsIn = docs.filter((d) => picked.has(d.id));
    return { years, cell, docsIn };
  }, [result, docs, picked]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
        <p className="text-sm text-zinc-500">
          Values read from the filings&apos; tables. Click a value to see its row on the page; empty cells were not
          found and are never estimated.
        </p>
      </div>

      <div className="grid gap-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900 lg:grid-cols-3">
        <div>
          <p className="mb-2 text-xs font-medium uppercase text-zinc-500">Documents</p>
          <div className="max-h-48 space-y-1 overflow-y-auto text-sm">
            {docs.length === 0 && <p className="text-zinc-500">No indexed documents yet.</p>}
            {docs.map((d) => (
              <label key={d.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={picked.has(d.id)}
                  onChange={(e) => {
                    const next = new Set(picked);
                    if (e.target.checked) next.add(d.id);
                    else next.delete(d.id);
                    setPicked(next);
                  }}
                />
                <span className="truncate" title={d.title}>
                  {d.title}
                </span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium uppercase text-zinc-500">Metrics</p>
          <div className="flex flex-wrap gap-1.5">
            {METRICS.map(([id, name]) => {
              const on = metrics.includes(id);
              return (
                <button
                  key={id}
                  onClick={() => setMetrics(on ? metrics.filter((m) => m !== id) : [...metrics, id])}
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${
                    on
                      ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border-zinc-300 dark:border-zinc-700"
                  }`}
                >
                  {name}
                </button>
              );
            })}
            {metrics
              .filter((m) => !METRICS.some(([id]) => id === m))
              .map((m) => (
                <button
                  key={m}
                  onClick={() => setMetrics(metrics.filter((x) => x !== m))}
                  className="rounded-full border border-amber-500 px-2.5 py-0.5 text-xs"
                  title="custom row label, click to remove"
                >
                  {m} ×
                </button>
              ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (custom.trim() && !metrics.includes(custom.trim())) setMetrics([...metrics, custom.trim()]);
              setCustom("");
            }}
          >
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="Add a row label, e.g. Total current assets"
              className="mt-2 w-full rounded-lg border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
            />
          </form>
        </div>
        <div className="flex flex-col gap-3">
          <div>
            <p className="mb-2 text-xs font-medium uppercase text-zinc-500">Years</p>
            <input
              value={years}
              onChange={(e) => setYears(e.target.value)}
              placeholder="e.g. 2021-2023 (empty: latest three)"
              className="w-full rounded-lg border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
            />
          </div>
          <div className="mt-auto flex gap-2">
            <button
              onClick={run}
              disabled={busy || !picked.size || !metrics.length}
              className="flex-1 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {busy ? "Reading tables…" : "Build table"}
            </button>
            {result && (
              <button onClick={download} className="rounded-lg border px-3 py-2 text-sm dark:border-zinc-700">
                CSV
              </button>
            )}
          </div>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}

      {table && (
        <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-200 text-left text-xs uppercase text-zinc-500 dark:border-zinc-800">
              <tr>
                <th className="px-4 py-2">Document</th>
                <th className="px-4 py-2">Metric</th>
                {table.years.map((y) => (
                  <th key={y} className="px-4 py-2 text-right">
                    {y}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {table.docsIn.flatMap((d) =>
                result!.metrics.map((m, i) => (
                  <tr key={`${d.id}|${m}`}>
                    <td className="max-w-56 truncate px-4 py-2 text-zinc-500" title={d.title}>
                      {i === 0 ? d.title : ""}
                    </td>
                    <td className="px-4 py-2">{label(m)}</td>
                    {table.years.map((y) => {
                      const v = table.cell.get(`${d.id}|${m}|${y}`);
                      return (
                        <td key={y} className="px-4 py-2 text-right tabular-nums">
                          {v ? (
                            <Link
                              href={`/app/d/${v.doc_id}?page=${v.page}&box=${v.bbox.join(",")}`}
                              className="hover:underline"
                              title={`p.${v.page} · ${v.label} · as printed: ${v.raw}`}
                            >
                              {fmt(v)}
                            </Link>
                          ) : (
                            <span className="text-zinc-300 dark:text-zinc-600">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
