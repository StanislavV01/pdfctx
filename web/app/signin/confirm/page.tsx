"use client";

import { useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { api } from "@/lib/api";

// The emailed link lands here instead of signing in on GET: mail scanners that open links cannot use it up,
// and the server only accepts it in the browser that asked for it.
export default function Confirm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.verify(new URLSearchParams(window.location.search).get("token") ?? "");
      window.location.href = "/app";
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-sm px-6 py-20 text-center">
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Sign in to pdfctx</h1>
        <button
          onClick={confirm}
          disabled={busy}
          className="w-full rounded-lg bg-zinc-900 px-4 py-2 font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {busy ? "Signing in…" : "Continue"}
        </button>
        {error && (
          <p className="mt-4 text-sm text-red-600">
            {error}{" "}
            <a href="/signin" className="underline">
              Request a new link
            </a>
          </p>
        )}
      </main>
    </>
  );
}
