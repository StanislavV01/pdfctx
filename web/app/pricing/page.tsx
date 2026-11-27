"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { api, type Me, PLANS } from "@/lib/api";

export default function Pricing() {
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  async function buy(plan: string) {
    setBusy(plan);
    setError(null);
    try {
      window.location.href = (await api.checkout(plan)).url;
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-5xl px-6 py-14">
        <h1 className="text-center text-3xl font-semibold tracking-tight">Pricing</h1>
        <p className="mt-2 text-center text-zinc-500">
          Priced by pages processed. Searching, metrics and agent calls on indexed pages are unlimited.
        </p>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {PLANS.map((p) => {
            const current = me?.workspace.plan === p.id;
            return (
              <div
                key={p.id}
                className={`flex flex-col rounded-xl border p-6 ${
                  p.id === "pro" ? "border-zinc-900 dark:border-zinc-100" : "border-zinc-200 dark:border-zinc-800"
                }`}
              >
                <h2 className="text-lg font-semibold">{p.name}</h2>
                <p className="mt-1 text-sm text-zinc-500">{p.blurb}</p>
                <p className="mt-4 text-3xl font-semibold">
                  ${p.price}
                  {p.price > 0 && <span className="text-base font-normal text-zinc-500">/month</span>}
                </p>
                <p className="mt-2 text-sm">
                  {p.pages.toLocaleString()} pages {p.period === "month" ? "per month" : "in total"}
                </p>
                <ul className="mt-4 flex-1 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                  <li>✓ Metrics table with source rows, CSV export</li>
                  <li>✓ MCP and REST for your agents</li>
                  <li>✓ OCR for scanned pages</li>
                  <li>✓ Audit log of every read</li>
                </ul>
                <div className="mt-6">
                  {current ? (
                    <span className="block rounded-lg border px-4 py-2 text-center text-sm dark:border-zinc-700">
                      Your plan
                    </span>
                  ) : p.id === "free" || !me ? (
                    <Link
                      href="/signin"
                      className="block rounded-lg bg-zinc-900 px-4 py-2 text-center text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
                    >
                      {p.id === "free" ? "Start free" : `Sign in to get ${p.name}`}
                    </Link>
                  ) : (
                    <button
                      onClick={() => buy(p.id)}
                      disabled={busy !== null}
                      className="w-full rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
                    >
                      {busy === p.id ? "Opening checkout…" : `Upgrade to ${p.name}`}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {error && <p className="mt-6 text-center text-sm text-red-600">{error}</p>}
      </main>
    </>
  );
}
