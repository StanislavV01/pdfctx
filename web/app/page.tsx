"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { API, api, type DocumentInfo } from "@/lib/api";

const STATUS: Record<DocumentInfo["status"], string> = {
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  no_text: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  encrypted: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export default function Documents() {
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(() => {
    api
      .documents()
      .then((r) => setDocs(r.documents))
      .catch((e: Error) => setError(`${e.message} — is \`pdfctx serve-http\` running at ${API}?`));
  }, []);

  useEffect(load, [load]);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const doc = await api.upload(file);
      if (doc.status !== "ok") setError(`${file.name}: indexed with status "${doc.status}" (no searchable text)`);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-zinc-500">Pick a document to browse its outline, search it and see cited boxes on the page.</p>
        </div>
        <label className="cursor-pointer rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900">
          {uploading ? "Indexing…" : "Upload PDF"}
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            disabled={uploading}
            onChange={(e) => onUpload(e.target.files?.[0])}
          />
        </label>
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}
      {docs === null && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {docs?.length === 0 && <p className="text-sm text-zinc-500">No documents yet. Upload one or start the server with a folder.</p>}
      <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
        {docs?.map((d) => (
          <li key={d.id} className="flex items-center gap-4 px-4 py-3">
            <div className="min-w-0 flex-1">
              {d.status === "ok" ? (
                <Link href={`/d/${d.id}`} className="font-medium hover:underline">
                  {d.title}
                </Link>
              ) : (
                <span className="font-medium text-zinc-500">{d.title}</span>
              )}
              <p className="truncate text-xs text-zinc-500">{d.file}</p>
            </div>
            <span className="text-xs text-zinc-500">{d.pages} pages</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS[d.status]}`}>{d.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
