"use client";

import { type FormEvent, Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";
import { api } from "@/lib/api";

function SignInForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(
    params.get("error") === "expired" ? "That sign-in link has expired or was already used. Request a new one." : null,
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.requestLink(email);
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return sent ? (
    <div className="rounded-xl border border-zinc-200 p-6 text-center dark:border-zinc-800">
      <p className="font-semibold">Check your email</p>
      <p className="mt-1 text-sm text-zinc-500">
        We sent a sign-in link to {email}. Open it in this browser; it works once and expires in 15 minutes.
      </p>
    </div>
  ) : (
    <form onSubmit={submit} className="space-y-3">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@fund.com"
        className="w-full rounded-lg border border-zinc-300 bg-transparent px-3 py-2 outline-none focus:border-zinc-500 dark:border-zinc-700"
      />
      <button className="w-full rounded-lg bg-zinc-900 px-4 py-2 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900">
        Email me a sign-in link
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <p className="text-xs text-zinc-500">No password. New here? The same link creates your free workspace.</p>
    </form>
  );
}

export default function SignIn() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-sm px-6 py-20">
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Sign in to pdfctx</h1>
        <Suspense>
          <SignInForm />
        </Suspense>
      </main>
    </>
  );
}
