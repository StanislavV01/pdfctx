"use client";

import { useEffect, useState } from "react";
import { api, type AuditEntry } from "@/lib/api";

export default function Audit() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .audit()
      .then((r) => setEntries(r.entries))
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="text-sm text-zinc-500">Every tool call an agent made, and exactly which blocks it was given.</p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-zinc-200 text-xs uppercase text-zinc-500 dark:border-zinc-800">
            <tr>
              <th className="px-4 py-2">Time</th>
              <th className="px-4 py-2">Client</th>
              <th className="px-4 py-2">Tool</th>
              <th className="px-4 py-2">Arguments</th>
              <th className="px-4 py-2 text-right">Blocks read</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {entries?.map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-zinc-500">{e.ts.replace("T", " ").slice(0, 19)}</td>
                <td className="px-4 py-2">{e.client}</td>
                <td className="px-4 py-2 font-mono">{e.tool}</td>
                <td className="max-w-md truncate px-4 py-2 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                  {JSON.stringify(e.args)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{e.block_ids.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
