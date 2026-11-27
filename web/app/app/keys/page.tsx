"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, type ApiKey } from "@/lib/api";

export default function Keys() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("claude");
  const [fresh, setFresh] = useState<ApiKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const origin = typeof window === "undefined" ? "https://your-pdfctx-host" : window.location.origin;

  const load = useCallback(() => {
    api
      .keys()
      .then((r) => setKeys(r.keys))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      setFresh(await api.createKey(name));
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const key = fresh?.key ?? "pk_live_…";
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">API keys</h1>
        <p className="text-sm text-zinc-500">
          Keys let an agent read this workspace over MCP or REST. A key is shown once; revoke it if it leaks.
        </p>
      </div>

      <form onSubmit={create} className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
          placeholder="key name"
        />
        <button className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900">
          Create key
        </button>
      </form>

      {fresh?.key && (
        <div className="rounded-xl border border-amber-400 bg-amber-50 p-4 text-sm dark:bg-amber-950/30">
          <p className="font-medium">Copy this key now. It will not be shown again.</p>
          <code className="mt-2 block break-all rounded bg-white p-2 font-mono text-xs dark:bg-zinc-900">{fresh.key}</code>
        </div>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}

      <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {keys.length === 0 && <li className="px-4 py-3 text-sm text-zinc-500">No keys yet.</li>}
        {keys.map((k) => (
          <li key={k.id} className="flex items-center gap-4 px-4 py-3 text-sm">
            <span className="font-medium">{k.name}</span>
            <code className="font-mono text-xs text-zinc-500">{k.hint}</code>
            <span className="text-xs text-zinc-400">{k.created_at.slice(0, 10)}</span>
            <button
              onClick={async () => {
                await api.revokeKey(k.id);
                load();
              }}
              className="ml-auto text-xs text-zinc-500 hover:text-red-600"
            >
              Revoke
            </button>
          </li>
        ))}
      </ul>

      <div className="space-y-2 text-sm">
        <p className="font-medium">Connect an agent</p>
        <p className="text-zinc-500">Claude Code:</p>
        <pre className="overflow-x-auto rounded-lg bg-zinc-100 p-3 text-xs dark:bg-zinc-900">
          {`claude mcp add --transport http pdfctx ${origin}/api/mcp \\\n  --header "Authorization: Bearer ${key}"`}
        </pre>
        <p className="text-zinc-500">REST:</p>
        <pre className="overflow-x-auto rounded-lg bg-zinc-100 p-3 text-xs dark:bg-zinc-900">
          {`curl -H "Authorization: Bearer ${key}" \\\n  -H "content-type: application/json" \\\n  -d '{"metrics":["revenue","capex"],"years":[2023]}' \\\n  ${origin}/api/v1/metrics`}
        </pre>
      </div>
    </div>
  );
}
