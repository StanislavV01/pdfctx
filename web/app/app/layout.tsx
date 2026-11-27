"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Me, MODE } from "@/lib/api";

const NAV = [
  ["/app", "Documents"],
  ["/app/metrics", "Metrics"],
  ["/app/keys", "API keys"],
  ["/app/audit", "Audit log"],
] as const;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (MODE !== "cloud") return;
    api
      .me()
      .then(setMe)
      .catch(() => {
        window.location.href = "/signin";
      });
  }, []);

  const nav = MODE === "cloud" ? NAV : NAV.filter(([href]) => href !== "/app/keys");
  const ws = me?.workspace;
  const pct = ws ? Math.min(100, Math.round((ws.pages_used / ws.pages_limit) * 100)) : 0;

  return (
    <>
      <header className="border-b border-zinc-200 dark:border-zinc-800">
        <nav className="mx-auto flex max-w-7xl items-center gap-5 px-6 py-3 text-sm">
          <Link href="/" className="font-semibold tracking-tight">
            📑 pdfctx
          </Link>
          {nav.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={
                (href === "/app" ? path === "/app" || path.startsWith("/app/d/") : path.startsWith(href))
                  ? "font-medium text-zinc-900 dark:text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
              }
            >
              {label}
            </Link>
          ))}
          {ws && (
            <span className="ml-auto flex items-center gap-3">
              <span className="hidden items-center gap-2 text-xs text-zinc-500 sm:flex" title="pages processed">
                <span className="h-1.5 w-24 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
                  <span
                    className={`block h-full ${pct > 90 ? "bg-red-500" : "bg-emerald-500"}`}
                    style={{ width: `${pct}%` }}
                  />
                </span>
                {ws.pages_used.toLocaleString()} / {ws.pages_limit.toLocaleString()} pages
                {ws.period === "month" ? " this month" : ""}
              </span>
              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">{ws.plan_name}</span>
              {ws.plan === "free" ? (
                <Link href="/pricing" className="text-amber-600 hover:underline">
                  Upgrade
                </Link>
              ) : (
                ws.billing && (
                  <button
                    onClick={async () => (window.location.href = (await api.portal()).url)}
                    className="text-zinc-500 hover:underline"
                  >
                    Billing
                  </button>
                )
              )}
              <button
                onClick={async () => {
                  await api.logout();
                  window.location.href = "/";
                }}
                className="text-zinc-500 hover:underline"
                title={me?.email}
              >
                Sign out
              </button>
            </span>
          )}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
    </>
  );
}
